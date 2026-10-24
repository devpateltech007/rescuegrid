"""Deterministic mission engine: simulation clock, drones, sensing, reconstruction,
observations -> Bedrock -> incidents -> human decisions -> routing.

Thread model: tick() runs in a worker thread under self.lock; Bedrock/S3 work runs in a small
thread pool and re-enters under the same lock. Every state change emits a sequenced event.
"""
from __future__ import annotations

import io
import json
import logging
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import shapely
from shapely.geometry import Polygon

from app.ai import briefing as briefing_ai
from app.ai import hazard_analyzer
from app.ai.bedrock import bedrock
from app.config import RUNTIME, settings
from app.geospatial.crs import to_geo, to_local
from app.models.schemas import (AccessStatus, FlightState, HazardType, Incident, IncidentStatus, MissionState,
                                Observation, OperatorDecision, Pose, Provenance, ScanRecord, SuggestedAccess)
from app.reconstruction.tiles import CELL, Reconstruction
from app.routing.graph import RoadNetwork
from app.routing.planner import NoRouteError, plan_routes
from app.sensors.camera import NoaaCatalog, render_synthetic
from app.sensors.lidar import LidarConfig, scan
from app.services.events import EventBus
from app.simulation.coordinator import DRONES, Coordinator
from app.simulation.drones import Drone, Waypoint
from app.simulation.world import World
from app.storage.db import DB
from app.storage.s3 import s3

log = logging.getLogger("rescuegrid.engine")

ANOMALY_CELL = 10.0
ANOMALY_MIN_POINTS = 10
ANOMALY_DEV_M = 0.45
POINTS_PER_SCAN_STREAM = 360
TILE_EMIT_EVERY = 3
ROAD_CHECK_EVERY = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionEngine:
    def __init__(self, db: DB, bus: EventBus):
        t0 = time.perf_counter()
        self.db, self.bus = db, bus
        self.lock = threading.RLock()
        self.net = RoadNetwork()
        self.world = World(self.net)
        self.scenario = self.world.scenario
        self.coord = Coordinator(self.net, self.world, self.scenario)
        self.catalog = NoaaCatalog()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai")
        self.lidar_cfg = LidarConfig(rays_across=26, rays_along=26)
        area = self.world.area
        self.recon = Reconstruction(area["center_local"]["x"], area["center_local"]["y"], area["survey_half_m"])
        self.ref_lon, self.ref_lat = area["bridge"]["centroid"]["lon"], area["bridge"]["centroid"]["lat"]
        self._prep_edge_samples()
        self._prep_sector_masks()
        self.speed = 1
        self.auto_pause = False
        self.reset(initial=True)
        log.info("engine ready in %.1fs", time.perf_counter() - t0)

    # ------------------------------------------------------------------ setup
    def _prep_edge_samples(self):
        self.edge_samples: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        sb = self.coord.survey
        for e in self.net.edges.values():
            if not e.line_local.intersects(sb):
                continue
            seg = e.line_local.intersection(sb)
            if seg.is_empty or seg.length < 5:
                continue
            n = max(2, int(seg.length / 8))
            pts = [seg.interpolate(i / (n - 1), normalized=True) for i in range(n)]
            self.edge_samples[e.edge_id] = (np.array([p.x for p in pts]), np.array([p.y for p in pts]))

    def _prep_sector_masks(self):
        n = self.recon.n
        xs = self.recon.x0 + (np.arange(n) + 0.5) * CELL
        ys = self.recon.y0 + (np.arange(n) + 0.5) * CELL
        X, Y = np.meshgrid(xs, ys)
        self.sector_masks = {}
        for d in DRONES:
            poly = self.coord.lines[d.drone_id].buffer(30, cap_style=2)
            self.sector_masks[d.drone_id] = shapely.contains_xy(poly, X, Y)

    # ------------------------------------------------------------------ lifecycle
    def reset(self, initial: bool = False):
        with self.lock:
            old = getattr(self, "mission_id", None)
            if old:
                self.db.clear_mission(old)
            self.mission_id = f"M-{uuid.uuid4().hex[:6].upper()}"
            self.tick_n = 0
            self.state = MissionState.BRIEFING
            self.sim_start = datetime.fromisoformat(self.scenario["sim_start"])
            self.net.reset_status()
            self.recon = Reconstruction(self.recon.x0 + self.recon.n * CELL / 2, self.recon.y0 + self.recon.n * CELL / 2,
                                        self.recon.n * CELL / 2)
            self.rng_seed = settings.seed
            hx, hy = self.coord.home
            plans = self.coord.plans()
            self.drones: dict[str, Drone] = {}
            for i, cfg in enumerate(DRONES):
                # staggered pads 6 m apart at staging
                d = Drone(cfg=cfg, home=(hx, hy), plan=plans[cfg.drone_id], x=hx + (i - 1) * 6, y=hy)
                d.ground = self.world.ground_height(d.x, d.y)
                d.z = d.ground + 0.3
                d.heading = 0.0
                self.drones[cfg.drone_id] = d
            self.observations: dict[str, dict] = {}
            self.incidents: dict[str, dict] = {}
            self.invocations: dict[str, dict] = {}
            self.scans_meta: list[dict] = []
            self.point_batches: list[dict] = []
            self.total_points = 0
            self.anomaly_cnt: dict[tuple[int, int], int] = {}
            self.anomaly_sum: dict[tuple[int, int], list[float]] = {}
            self.claimed: list[tuple[float, float]] = []
            self.hot_done: set[tuple[int, int]] = set()
            self.capture_sites: list[tuple[float, float, str]] = []
            self.anomalous_edges: set[str] = set()
            self.inspected_edges: set[str] = set()
            self.retask_log: list[dict] = []
            self.decisions: list[dict] = []
            self.briefings: dict[str, dict] = {}
            self.routes: dict[str, dict] = {}
            self.route_history: list[dict] = []
            self.current_route_id: str | None = None
            self.approved_route_id: str | None = None
            self.metrics_extra = {"route_recalc_ms": [], "bedrock_latency_ms": []}
            self._scan_chunks: dict[str, list] = {k: [] for k in self.drones}
            self._pending_scan_rows: list[dict] = []
            self.mission_row = {"mission_id": self.mission_id, "scenario": self.scenario["scenario_id"],
                                "operator": None, "created": _now()}
            self.db.put("missions", self.mission_id, self.mission_row, self.mission_id)
            self._plan_initial_route()
            if not initial:
                self.emit("mission.reset", {"mission_id": self.mission_id})

    def emit(self, type_: str, payload: dict) -> dict:
        return self.bus.emit(self.mission_id, type_, payload, self.sim_time())

    def sim_time(self) -> str:
        return (self.sim_start + timedelta(seconds=self.tick_n)).isoformat()

    def start(self):
        with self.lock:
            if self.state != MissionState.BRIEFING:
                return
            for d in self.drones.values():
                d.state = FlightState.TAKEOFF
                d.task = "Takeoff"
            self.state = MissionState.RUNNING
            self.emit("mission.started", {"drones": list(self.drones)})

    def pause(self, reason: str = "operator"):
        with self.lock:
            if self.state == MissionState.RUNNING:
                self.state = MissionState.PAUSED
                self.emit("mission.paused", {"reason": reason})

    def resume(self):
        with self.lock:
            if self.state == MissionState.PAUSED:
                self.state = MissionState.RUNNING
                self.emit("mission.resumed", {})

    def set_speed(self, s: int):
        with self.lock:
            self.speed = s
            self.emit("mission.speed_changed", {"speed": s})

    # ------------------------------------------------------------------ tick
    def tick(self, force: bool = False):
        with self.lock:
            if self.state != MissionState.RUNNING and not force:
                return
            if self.state == MissionState.BRIEFING:
                return
            self.tick_n += 1
            dt = 1.0
            for idx, d in enumerate(self.drones.values()):
                d.step(dt, self.world.ground_height)
                for ev in d.events:
                    self.emit(ev["type"], {"drone_id": d.cfg.drone_id, **{k: v for k, v in ev.items() if k != "type"}})
                if d.state in (FlightState.SURVEYING, FlightState.INSPECTING, FlightState.RETURNING) and d.z - d.ground > 15:
                    self._do_scan(d, idx)
                if d.pending_capture is not None:
                    w = d.pending_capture
                    d.pending_capture = None
                    inc_id = getattr(w, "incident_id", None)
                    trig = ("OPERATOR_REINSPECTION" if inc_id else
                            "COORDINATOR_RETASK" if (w.task_id or "").startswith("TASK-IG") else
                            "OPERATOR_RETASK" if (w.label or "").startswith("Operator") else "PLANNED_INSPECTION")
                    self._capture(d, w.target[0], w.target[1], trigger=trig, close=w.close_inspection,
                                  incident_id=inc_id, task_label=w.label)
            for d in self.drones.values():
                self.emit("drone.telemetry", self.telemetry(d))
            if self.tick_n % TILE_EMIT_EVERY == 0:
                tiles = self.recon.pop_dirty()
                if tiles:
                    self.emit("recon.tiles_updated", {"tiles": tiles})
                self.emit("scan.coverage_updated", {**self.coverage_summary(),
                                                    **({"metrics": self.metrics()} if self.tick_n % (TILE_EMIT_EVERY * 3) == 0 else {})})
            if self.tick_n % ROAD_CHECK_EVERY == 0:
                self._update_observed_roads()
            if all(d.state == FlightState.COMPLETE for d in self.drones.values()) and self.state == MissionState.RUNNING:
                tiles = self.recon.pop_dirty()
                if tiles:
                    self.emit("recon.tiles_updated", {"tiles": tiles})
                self._update_observed_roads()
                self.state = MissionState.COMPLETE
                self.emit("mission.survey_complete", self.metrics())

    def _sector_cov(self, drone_id: str) -> float:
        key = (self.tick_n, drone_id)
        cache = getattr(self, "_cov_cache", {})
        if key not in cache:
            mask = self.sector_masks[drone_id]
            cache = {k: v for k, v in cache.items() if k[0] == self.tick_n}
            cache[key] = float((self.recon.cnt[mask] > 0).mean() * 100) if mask.any() else 0.0
            self._cov_cache = cache
        return cache[key]

    def telemetry(self, d: Drone) -> dict:
        lon, lat = to_geo(d.x, d.y)
        cov = self._sector_cov(d.cfg.drone_id)
        return {
            "drone_id": d.cfg.drone_id, "mission_id": self.mission_id, "simulated_timestamp": self.sim_time(),
            "latitude": lat, "longitude": lon, "altitude_agl_m": round(d.z - d.ground, 1),
            "altitude_msl_m": round(d.z, 2), "terrain_elevation_m": round(d.ground, 2),
            "heading_deg": round(d.heading, 1), "pitch_deg": round(d.pitch, 1), "roll_deg": round(d.roll, 1),
            "speed_mps": round(d.speed, 2), "battery_percentage": round(d.battery_pct, 1),
            "battery_consumed_wh": round(d.consumed_wh, 2), "flight_state": d.state.value,
            "current_waypoint": d.wp, "total_waypoints": len(d.plan), "scan_coverage_percentage": round(cov, 1),
            "current_sensor_mode": d.sensor_mode if d.state != FlightState.IDLE else "STANDBY",
            "communication_state": "LINK_OK", "sector_id": d.cfg.sector_id, "task": d.task,
            "scans": d.scans, "distance_m": round(d.distance_m),
            "camera_target": list(to_geo(*d.camera_target)) if d.camera_target else None,
        }

    # ------------------------------------------------------------------ sensing
    def _do_scan(self, d: Drone, idx: int):
        if (self.tick_n % max(1, int(d.cfg.scan_interval_s))) != 0:
            return
        rng = np.random.default_rng((self.rng_seed, idx, d.scans))
        pitch = -90.0 if d.state != FlightState.INSPECTING else -75.0
        res = scan(self.world, d.x, d.y, d.z, d.heading, pitch, self.lidar_cfg, rng)
        if res is None:
            return
        d.scans += 1
        d.sensor_mode = "LIDAR+EO"
        scan_id = f"SC-{d.cfg.drone_id[0]}{d.scans:04d}-{self.mission_id[-4:]}"
        self.recon.add(res.xyz, res.deviation, res.klass, self.tick_n)
        # local storage of the full-resolution scan (lon, lat, h, class, deviation)
        sdir = RUNTIME / "scans" / self.mission_id
        sdir.mkdir(parents=True, exist_ok=True)
        arr = np.column_stack([res.lonlat_h, res.klass, res.deviation]).astype(np.float64)
        fpath = sdir / f"{scan_id}.npy"
        np.save(fpath, arr)
        self._scan_chunks[d.cfg.drone_id].append(arr)
        if len(self._scan_chunks[d.cfg.drone_id]) >= 25:
            chunk = np.concatenate(self._scan_chunks[d.cfg.drone_id])
            self._scan_chunks[d.cfg.drone_id] = []
            key = f"missions/{self.mission_id}/scans/{d.cfg.drone_id}-{d.scans:04d}.npy"
            self.pool.submit(self._upload_npy, key, chunk)
        # stream a decimated batch
        n = len(arr)
        sel = np.linspace(0, n - 1, min(n, POINTS_PER_SCAN_STREAM)).astype(int)
        lon_i = np.round((res.lonlat_h[sel, 0] - self.ref_lon) * 1e6).astype(int)
        lat_i = np.round((res.lonlat_h[sel, 1] - self.ref_lat) * 1e6).astype(int)
        h_i = np.round(res.lonlat_h[sel, 2] * 100).astype(int)
        cls = res.klass[sel].astype(int)
        anom = (np.abs(res.deviation[sel]) > ANOMALY_DEV_M).astype(int)
        flat = np.column_stack([lon_i, lat_i, h_i, cls, anom]).ravel().tolist()
        self.total_points += n
        rec = ScanRecord(
            scan_id=scan_id, drone_id=d.cfg.drone_id, mission_id=self.mission_id, scan_timestamp=self.sim_time(),
            camera_or_sensor_pose=Pose(longitude=float(to_geo(d.x, d.y)[0]), latitude=float(to_geo(d.x, d.y)[1]),
                                       altitude_msl_m=d.z, heading_deg=d.heading, pitch_deg=pitch, roll_deg=d.roll),
            observed_point_count=n, surveyed_polygon=res.footprint_lonlat + [res.footprint_lonlat[0]],
            point_cloud_file=str(fpath.relative_to(RUNTIME.parent.parent)).replace("\\", "/"),
            reconstructed_tile_ids=sorted({f"T{int((y - self.recon.y0) // (CELL * 32)):02d}_{int((x - self.recon.x0) // (CELL * 32)):02d}"
                                           for x, y in res.footprint}),
            quality_metadata={"range_noise_sigma_m": self.lidar_cfg.range_noise_m, "fov_deg": self.lidar_cfg.fov_deg,
                              "rays": self.lidar_cfg.rays_across * self.lidar_cfg.rays_along, "hits": n,
                              "mean_range_m": round(res.mean_range_m, 1), "agl_m": round(d.z - d.ground, 1),
                              "seed": [self.rng_seed, idx, d.scans - 1],
                              "change_points": int((np.abs(res.deviation) > ANOMALY_DEV_M).sum())},
        )
        meta = rec.model_dump(mode="json")
        self.scans_meta.append(meta)
        self._pending_scan_rows.append(meta)
        if len(self._pending_scan_rows) >= 30:
            self._flush_scans()
        batch = {"scan_id": scan_id, "drone_id": d.cfg.drone_id, "ref": [self.ref_lon, self.ref_lat],
                 "stride": 5, "points": flat, "footprint": res.footprint_lonlat,
                 "observed_point_count": n, "simulated_timestamp": self.sim_time()}
        ev = self.emit("scan.completed", batch)
        self.point_batches.append({**batch, "seq": ev["seq"]})
        self._detect_changes(d, res)

    def _flush_scans(self):
        rows, self._pending_scan_rows = self._pending_scan_rows, []
        self.db.put_many("scans", [(m["scan_id"], m) for m in rows], self.mission_id)

    def _upload_npy(self, key: str, arr: np.ndarray):
        buf = io.BytesIO()
        np.save(buf, arr)
        s3.put_bytes(key, buf.getvalue(), "application/octet-stream")

    def _detect_changes(self, d: Drone, res):
        """Change detection: measured surface vs pre-storm baseline on road / bridge corridors."""
        r, c = self.world.idx(res.xyz[:, 0], res.xyz[:, 1])
        on_road = self.world.road_mask[r, c] | self.world.bridge_cells[r, c]
        m = (np.abs(res.deviation) > ANOMALY_DEV_M) & on_road
        if not m.any():
            return
        for x, y in res.xyz[m, :2]:
            k = (int(x // ANOMALY_CELL), int(y // ANOMALY_CELL))
            self.anomaly_cnt[k] = self.anomaly_cnt.get(k, 0) + 1
            s = self.anomaly_sum.setdefault(k, [0.0, 0.0])
            s[0] += x
            s[1] += y
        touched = {(int(x // ANOMALY_CELL), int(y // ANOMALY_CELL)) for x, y in res.xyz[m, :2]}
        hot = [k for k in touched if self.anomaly_cnt[k] >= ANOMALY_MIN_POINTS and k not in self.hot_done]
        for k in hot:
            self.hot_done.add(k)
            cx = self.anomaly_sum[k][0] / self.anomaly_cnt[k]
            cy = self.anomaly_sum[k][1] / self.anomaly_cnt[k]
            for ex, _ in self.net.edges_near(cx, cy, 15):
                self.anomalous_edges.add(ex)
            if any(math.hypot(cx - a, cy - b) < 45 for a, b in self.claimed):
                continue
            # snap to a mapped point of interest (e.g. bridge) when nearby
            tx, ty = cx, cy
            for poi in self.scenario["pois"]:
                px, py = to_local(poi["lon"], poi["lat"])
                if math.hypot(px - cx, py - cy) < 60:
                    tx, ty = px, py
            if any(math.hypot(tx - a, ty - b) < 45 for a, b in self.claimed):
                self.claimed.append((cx, cy))
                continue
            self.claimed.append((tx, ty))
            self.claimed.append((cx, cy))
            self.emit("scan.change_detected", {"drone_id": d.cfg.drone_id, "lon": to_geo(tx, ty)[0], "lat": to_geo(tx, ty)[1],
                                               "points": self.anomaly_cnt[k],
                                               "method": f"|measured - pre-storm baseline| > {ANOMALY_DEV_M} m on road corridor"})
            self._capture(d, tx, ty, trigger="LIDAR_CHANGE_DETECTION")

    # ------------------------------------------------------------------ observations
    def _capture(self, d: Drone, tx: float, ty: float, trigger: str, close: bool = False,
                 incident_id: str | None = None, task_label: str = ""):
        if not close and any(math.hypot(tx - a, ty - b) < 40 for a, b, _ in self.capture_sites):
            return None
        oid = f"OBS-{uuid.uuid4().hex[:6].upper()}"
        d.camera_target = (tx, ty)
        crop = self.catalog.find(tx, ty, prefer_close=close)
        odir = RUNTIME / "observations"
        odir.mkdir(parents=True, exist_ok=True)
        cam_lon, cam_lat = to_geo(d.x, d.y)
        tlon, tlat = to_geo(tx, ty)
        if crop:
            img = crop["path"].read_bytes()
            src = Provenance.PUBLIC_HISTORICAL_IMAGERY
            half = crop["half_size_m"]
            b = crop["bounds_wgs84"]
            footprint = [[b["west"], b["south"]], [b["east"], b["south"]], [b["east"], b["north"]], [b["west"], b["north"]]]
            acc = {"method": "NOAA georeferenced orthomosaic tile mosaic (XYZ z19)", "footprint_m": round(2 * half),
                   "approx_gsd_m": crop["approx_gsd_m"], "acquisition_date": crop["acquisition_date"],
                   "flight_id": crop["flight_id"], "publisher": crop["publisher"], "accuracy_note": crop["accuracy_note"],
                   "drone_role": "Simulated drone pose selected this archived NOAA frame; NOAA imagery was not captured by the simulated drone."}
            image_source = f"NOAA NGS Hurricane Helene imagery, flight {crop['flight_id']} ({crop['acquisition_date']})"
            site_key = crop["site"]
        else:
            half = 25.0 if close else 40.0
            img = render_synthetic(self.world, tx, ty, half, d.heading, seed=self.tick_n)
            src = Provenance.SIMULATED_SENSOR
            corners = [(tx - half, ty - half), (tx + half, ty - half), (tx + half, ty + half), (tx - half, ty + half)]
            footprint = [list(to_geo(x, y)) for x, y in corners]
            acc = {"method": "Simulated camera: pose from telemetry, footprint centred on gimbal target",
                   "footprint_m": round(2 * half), "horizontal_error_m_sim": 0.0,
                   "note": "Synthetic render of the exercise ground truth; not a photograph."}
            image_source = "Synthetic render (SIMULATED_SENSOR)"
            site_key = None
        path = odir / f"{oid}.jpg"
        path.write_bytes(img)
        # spatial matching: GIS decides which road segments the image is about
        near = self.net.edges_near(tx, ty, 25.0)
        matched: list[str] = []
        if near:
            best_d = near[0][1]
            for eid, dist in near:
                if dist <= best_d + 8:
                    for t in self.net.twin_ids(eid):
                        if t not in matched:
                            matched.append(t)
        names = sorted({self.net.edges[e].road_name for e in matched})
        is_bridge = any(self.net.edges[e].is_bridge for e in matched)
        obs = Observation(
            observation_id=oid, mission_id=self.mission_id, drone_id=d.cfg.drone_id, simulated_timestamp=self.sim_time(),
            camera_position=Pose(longitude=cam_lon, latitude=cam_lat, altitude_msl_m=d.z, heading_deg=d.heading,
                                 pitch_deg=-90.0 if not close else -80.0, roll_deg=0.0),
            camera_orientation={"heading_deg": round(d.heading, 1), "gimbal_pitch_deg": -90.0, "target_lon": tlon, "target_lat": tlat},
            sensor_field_of_view=d.cfg.fov_deg, image_source=image_source,
            image_file_location=str(path.relative_to(RUNTIME.parent.parent)).replace("\\", "/"),
            image_url=f"/api/media/observations/{oid}.jpg", source_type=src,
            nearby_road_segment_ids=matched, match_status="MATCHED" if matched else "UNMATCHED",
            footprint=footprint, geographic_accuracy_metadata=acc, trigger=trigger,
        ).model_dump(mode="json")
        obs.update({"nearby_road_names": names, "is_bridge_site": is_bridge, "site_key": site_key,
                    "target": {"lon": tlon, "lat": tlat}, "linked_incident_id": incident_id, "close_inspection": close,
                    "task_label": task_label})
        self.observations[oid] = obs
        self.capture_sites.append((tx, ty, oid))
        self.db.put("observations", oid, obs, self.mission_id)
        self.emit("observation.created", obs)
        for e in matched:
            self.inspected_edges.add(e)
        self.pool.submit(self._analyze_job, oid)
        return oid

    def analyze_observation(self, oid: str) -> None:
        with self.lock:
            if oid not in self.observations:
                raise KeyError(oid)
            if self.observations[oid]["ai_status"] == "RUNNING":
                return
        self.pool.submit(self._analyze_job, oid)

    def _analyze_job(self, oid: str):
        with self.lock:
            obs = dict(self.observations[oid])
            obs["ai_status"] = "RUNNING"
            self.observations[oid]["ai_status"] = "RUNNING"
            self.emit("ai.analysis_started", {"observation_id": oid, "model_id": bedrock.model_id})
        path = RUNTIME.parent.parent / obs["image_file_location"]
        uri = s3.put_file(f"missions/{self.mission_id}/observations/{oid}.jpg", path, "image/jpeg")
        if uri is None and s3.enabled:
            with self.lock:
                self.emit("system.degraded", {"component": "S3", "reason": s3.last_error, "observation_id": oid,
                                              "impact": "Evidence kept locally; analysis continues."})
        inv, ha = hazard_analyzer.analyze(obs, path)
        with self.lock:
            if oid not in self.observations:  # mission was reset meanwhile
                return
            o = self.observations[oid]
            o["image_s3_uri"] = uri
            o["ai_invocation_id"] = inv.invocation_id
            invd = inv.model_dump(mode="json")
            invd["mission_id"] = self.mission_id
            invd["evidence_image_url"] = o["image_url"]
            invd["source_type"] = o["source_type"]
            if inv.latency_ms:
                self.metrics_extra["bedrock_latency_ms"].append(inv.latency_ms)
            if ha is None:
                o["ai_status"] = "FAILED"
                self.invocations[inv.invocation_id] = invd
                self.db.put("invocations", inv.invocation_id, invd, self.mission_id)
                self.db.put("observations", oid, o, self.mission_id)
                self.emit("ai.analysis_completed", {"observation_id": oid, "invocation": invd})
                self.emit("system.degraded", {"component": "BEDROCK", "reason": inv.failure_reason, "observation_id": oid,
                                              "impact": "No incident created. Simulation, 3D view and routing continue."})
                return
            o["ai_status"] = "COMPLETED"
            o["hazard_assessment"] = ha.model_dump(mode="json")
            inc_id = self._incident_from(o, ha, inv)
            invd["incident_id"] = inc_id
            self.invocations[inv.invocation_id] = invd
            self.db.put("invocations", inv.invocation_id, invd, self.mission_id)
            self.db.put("observations", oid, o, self.mission_id)
            self.emit("ai.analysis_completed", {"observation_id": oid, "invocation": invd})

    # ------------------------------------------------------------------ incidents
    def _incident_from(self, obs: dict, ha, inv) -> str | None:
        matched = obs["nearby_road_segment_ids"]
        linked = obs.get("linked_incident_id")
        if linked and linked in self.incidents:
            inc = self.incidents[linked]
            inc["observation_ids"].append(obs["observation_id"])
            inc["single_source"] = False
            inc.setdefault("assessments", []).append({"observation_id": obs["observation_id"], **ha.model_dump(mode="json"),
                                                      "invocation_id": inv.invocation_id, "source_type": obs["source_type"]})
            if inc["status"] == IncidentStatus.REINSPECTION_REQUESTED.value:
                inc["status"] = IncidentStatus.PENDING_REVIEW.value
            inc["latest_assessment"] = inc["assessments"][-1]
            self.obs_link(obs, linked)
            self.db.put("incidents", linked, inc, self.mission_id)
            self.emit("incident.updated", inc)
            return linked
        if not matched:
            return None  # UNMATCHED observations never become road incidents
        ev_ids = [obs["observation_id"]]
        prov = [Provenance.BEDROCK_INFERENCE, Provenance(obs["source_type"])]
        hist = None
        for hz in self.scenario["hazards"]:
            if hz.get("historical_basis") and set(hz["edge_ids"]) & set(matched):
                hist = hz["historical_basis"]
                prov.append(Provenance.OFFICIAL_HISTORICAL_RECORD)
        iid = f"INC-{uuid.uuid4().hex[:5].upper()}"
        inc = Incident(
            incident_id=iid, mission_id=self.mission_id, created_at=self.sim_time(), hazard_type=ha.hazard_type,
            severity=ha.severity, suggested_accessibility=ha.suggested_accessibility, confidence=ha.confidence,
            affected_road_segment_ids=matched, affected_road_names=obs["nearby_road_names"],
            location=obs["target"], observation_ids=ev_ids,
            scan_ids=[s["scan_id"] for s in self.scans_meta[-40:] if s["drone_id"] == obs["drone_id"]][-5:],
            visual_evidence=ha.visual_evidence, uncertainty_notes=ha.uncertainty_notes,
            recommended_next_inspection=ha.recommended_next_inspection, provenance=prov, historical_context=hist,
        ).model_dump(mode="json")
        inc["prior_status"] = {e: self.net.edges[e].access_status.value for e in matched}
        inc["is_bridge"] = obs["is_bridge_site"]
        inc["assessments"] = [{"observation_id": obs["observation_id"], **ha.model_dump(mode="json"),
                               "invocation_id": inv.invocation_id, "source_type": obs["source_type"]}]
        inc["latest_assessment"] = inc["assessments"][0]
        inc["kind"] = "ROAD_ASSESSMENT" if ha.suggested_accessibility == SuggestedAccess.LIKELY_PASSABLE or \
            ha.hazard_type == HazardType.NO_VISIBLE_HAZARD else "HAZARD"
        cur = self.routes.get(self.current_route_id or "")
        inc["on_current_route"] = bool(cur and set(cur["edge_ids"]) & set(matched))
        self.incidents[iid] = inc
        self.obs_link(obs, iid)
        if ha.suggested_accessibility == SuggestedAccess.LIKELY_BLOCKED:
            changed = []
            for e in matched:
                edge = self.net.edges[e]
                if edge.access_status in (AccessStatus.UNKNOWN, AccessStatus.OBSERVED_PASSABLE):
                    edge.access_status = AccessStatus.SUSPECTED_BLOCKED
                    edge.status_provenance = "BEDROCK_INFERENCE"
                    edge.evidence_ids = list(dict.fromkeys(edge.evidence_ids + ev_ids + [iid]))
                    changed.append(e)
            if changed:
                self.emit("road.status_changed", {"edges": [self.net.edges[e].public() for e in changed],
                                                  "reason": f"Bedrock suggests LIKELY_BLOCKED ({iid}); pending human review"})
                self._refresh_current_route_flags()
        self.db.put("incidents", iid, inc, self.mission_id)
        self.emit("incident.created", inc)
        if self.auto_pause and inc["on_current_route"] and inc["kind"] == "HAZARD":
            self.pause(reason=f"Decision required: {iid} affects the current route")
        return iid

    def obs_link(self, obs: dict, iid: str):
        obs["incident_id"] = iid
        self.observations[obs["observation_id"]]["incident_id"] = iid

    def _record_decision(self, action: str, target_type: str, target_id: str, op, changes: dict) -> dict:
        dec = OperatorDecision(
            decision_id=f"DEC-{uuid.uuid4().hex[:6].upper()}", mission_id=self.mission_id, action=action,
            target_type=target_type, target_id=target_id, operator=op.operator, note=op.note,
            evidence_reviewed=op.evidence_reviewed, simulated_timestamp=self.sim_time(), wall_timestamp=_now(),
            resulting_changes=changes).model_dump(mode="json")
        self.decisions.append(dec)
        self.db.put("decisions", dec["decision_id"], dec, self.mission_id)
        self.mission_row["operator"] = op.operator
        self.emit("operator.decision", dec)
        return dec

    def _set_edges(self, eids: list[str], status: AccessStatus, prov: str, evidence: list[str]) -> list[dict]:
        out = []
        for e in eids:
            edge = self.net.edges[e]
            edge.access_status = status
            edge.status_provenance = prov
            edge.evidence_ids = list(dict.fromkeys(edge.evidence_ids + evidence))
            if status in (AccessStatus.CONFIRMED_BLOCKED, AccessStatus.VERIFIED_PASSABLE):
                edge.last_verified_at = self.sim_time()
            out.append(edge.public())
        return out

    def verify_incident(self, iid: str, op, passable: bool = False) -> dict:
        with self.lock:
            inc = self._inc(iid)
            if inc["status"] in (IncidentStatus.CONFIRMED.value, IncidentStatus.VERIFIED_PASSABLE.value):
                raise ValueError(f"{iid} already decided")
            status = AccessStatus.VERIFIED_PASSABLE if passable else AccessStatus.CONFIRMED_BLOCKED
            edges = self._set_edges(inc["affected_road_segment_ids"], status, "HUMAN_VERIFIED", inc["observation_ids"] + [iid])
            inc["status"] = (IncidentStatus.VERIFIED_PASSABLE if passable else IncidentStatus.CONFIRMED).value
            inc["provenance"] = list(dict.fromkeys(inc["provenance"] + [Provenance.HUMAN_VERIFIED.value]))
            dec = self._record_decision("VERIFY_PASSABLE" if passable else "CONFIRM_BLOCKED", "incident", iid, op,
                                        {"edges": [e["edge_id"] for e in edges], "new_status": status.value})
            inc["decisions"].append(dec["decision_id"])
            self.db.put("incidents", iid, inc, self.mission_id)
            self.emit("incident.verified", inc)
            self.emit("road.status_changed", {"edges": edges, "reason": f"{dec['action']} by {op.operator} ({iid})"})
            route = self.recalculate(reason=f"{dec['action']} {iid} by {op.operator}")
            if not passable:
                self._auto_retask()
            return {"incident": inc, "decision": dec, "route": route}

    def reject_incident(self, iid: str, op) -> dict:
        with self.lock:
            inc = self._inc(iid)
            prior = inc.get("prior_status", {})
            edges = []
            for e in inc["affected_road_segment_ids"]:
                edge = self.net.edges[e]
                if edge.access_status == AccessStatus.SUSPECTED_BLOCKED:
                    edge.access_status = AccessStatus(prior.get(e, "UNKNOWN"))
                    edge.status_provenance = "HUMAN_VERIFIED"
                    edges.append(edge.public())
            inc["status"] = IncidentStatus.REJECTED.value
            dec = self._record_decision("REJECT_INCIDENT", "incident", iid, op, {"edges_restored": [e["edge_id"] for e in edges]})
            inc["decisions"].append(dec["decision_id"])
            self.db.put("incidents", iid, inc, self.mission_id)
            self.emit("incident.rejected", inc)
            if edges:
                self.emit("road.status_changed", {"edges": edges, "reason": f"REJECT {iid} by {op.operator}"})
                self._refresh_current_route_flags()
            return {"incident": inc, "decision": dec}

    def request_inspection(self, iid: str, op) -> dict:
        with self.lock:
            inc = self._inc(iid)
            tx, ty = to_local(inc["location"]["lon"], inc["location"]["lat"])
            drone = self._best_drone(tx, ty)
            if drone is None:
                raise ValueError("No drone available with sufficient battery")
            w = Waypoint(tx, ty, agl=25, action="inspect", hold_s=10, target=(tx, ty), close_inspection=True,
                         label=f"Re-inspect {iid} (low pass, 25 m AGL)", task_id=f"TASK-{iid}")
            w.incident_id = iid  # type: ignore[attr-defined]
            drone.insert_task([w])
            inc["status"] = IncidentStatus.REINSPECTION_REQUESTED.value
            dec = self._record_decision("REQUEST_INSPECTION", "incident", iid, op, {"drone_id": drone.cfg.drone_id})
            inc["decisions"].append(dec["decision_id"])
            self.db.put("incidents", iid, inc, self.mission_id)
            self.emit("incident.inspection_requested", inc)
            self.emit("drone.retasked", {"drone_id": drone.cfg.drone_id, "reason": f"Operator re-inspection of {iid}",
                                         "target": inc["location"], "by": op.operator})
            if self.state == MissionState.COMPLETE:
                self.state = MissionState.RUNNING
            return {"incident": inc, "decision": dec, "drone_id": drone.cfg.drone_id}

    def _inc(self, iid: str) -> dict:
        if iid not in self.incidents:
            raise KeyError(iid)
        return self.incidents[iid]

    def _best_drone(self, tx: float, ty: float, prefer: str | None = None) -> Drone | None:
        best = None
        for d in self.drones.values():
            if d.battery_pct < 25:
                continue
            cost = math.hypot(d.x - tx, d.y - ty) + (300 if d.state == FlightState.INSPECTING else 0)
            if prefer and d.cfg.drone_id == prefer:
                cost -= 400
            if best is None or cost < best[0]:
                best = (cost, d)
        return best[1] if best else None

    def retask(self, drone_id: str, req) -> dict:
        with self.lock:
            d = self.drones.get(drone_id)
            if d is None:
                raise KeyError(drone_id)
            if req.target_edge_id:
                e = self.net.edges.get(req.target_edge_id)
                if e is None:
                    raise KeyError(req.target_edge_id)
                p = e.line_local.interpolate(0.5, normalized=True)
                tx, ty = p.x, p.y
            elif req.lon is not None and req.lat is not None:
                tx, ty = to_local(req.lon, req.lat)
                if not self.coord.survey.buffer(800).contains(shapely.Point(tx, ty)):
                    raise ValueError("Target outside the mission area")
            else:
                raise ValueError("Provide target_edge_id or lon/lat")
            d.insert_task([Waypoint(tx, ty, agl=30, action="inspect", hold_s=10, target=(tx, ty), close_inspection=False,
                                    label=f"Operator retask: {req.reason}", task_id=f"TASK-{uuid.uuid4().hex[:4]}")])
            dec = self._record_decision("RETASK_DRONE", "drone", drone_id, req, {"target": list(to_geo(tx, ty))})
            self.emit("drone.retasked", {"drone_id": drone_id, "reason": req.reason, "target": dict(zip(("lon", "lat"), to_geo(tx, ty))),
                                         "by": req.operator, "decision_id": dec["decision_id"]})
            if self.state == MissionState.COMPLETE:
                self.state = MissionState.RUNNING
            return {"drone_id": drone_id, "decision": dec}

    def _auto_retask(self):
        """Information-gain retasking: send the best drone to the most valuable unverified
        element of the new recommended route (bridges first)."""
        cur = self.routes.get(self.current_route_id or "")
        if not cur:
            return
        cands = self.coord.score_targets(cur["edge_ids"], list(self.drones.values()), self.inspected_edges)
        if not cands:
            return
        top = cands[0]
        if not top["is_bridge"] and top["score"] < 0.5:
            return
        d = self.drones[top["drone_id"]]
        w = Waypoint(top["x"], top["y"], agl=30, action="inspect", hold_s=10, target=(top["x"], top["y"]),
                     label=f"Retask: verify {top['road_name']}{' bridge' if top['is_bridge'] else ''} on new route",
                     task_id=f"TASK-IG-{top['edge_id'][:12]}")
        d.insert_task([w])
        for t in self.net.twin_ids(top["edge_id"]):
            self.inspected_edges.add(t)
        entry = {"drone_id": d.cfg.drone_id, "reason": "Information-gain retask: unverified segment on recommended route",
                 "target": {"lon": top["lon"], "lat": top["lat"]}, "edge_id": top["edge_id"], "road_name": top["road_name"],
                 "candidates": cands[:5], "by": "COORDINATOR (automatic)"}
        self.retask_log.append(entry)
        self.emit("drone.retasked", entry)
        if self.state == MissionState.COMPLETE:
            self.state = MissionState.RUNNING

    # ------------------------------------------------------------------ roads
    def _update_observed_roads(self):
        changed = []
        now = self.sim_time()
        for eid, (xs, ys) in self.edge_samples.items():
            e = self.net.edges[eid]
            obs = self.recon.observed_at(xs, ys)
            frac = obs.mean()
            if frac > 0 and e.last_observed_at is None:
                e.last_observed_at = now
            if frac >= 0.85 and e.access_status == AccessStatus.UNKNOWN and not e.is_bridge and eid not in self.anomalous_edges:
                e.access_status = AccessStatus.OBSERVED_PASSABLE
                e.status_provenance = "SIMULATED_SENSOR"
                e.last_observed_at = now
                changed.append(e.public())
        if changed:
            self.emit("road.status_changed", {"edges": changed,
                                              "reason": "Lidar corridor coverage >= 85% with no change vs pre-storm baseline (bridges excluded)"})
            self._refresh_current_route_flags()

    # ------------------------------------------------------------------ routing
    def _plan_initial_route(self):
        st, ds = self.scenario["staging"], self.scenario["destination"]
        try:
            plans = plan_routes(self.net, st["node"], ds["node"], k=3, sim_time=self.sim_time())
        except NoRouteError:
            return
        for p in plans:
            pd = p.model_dump(mode="json")
            pd["route_status"] = "PROVISIONAL" if p.rank == 0 else "ALTERNATIVE"
            pd["mission_id"] = self.mission_id
            self.routes[p.route_id] = pd
            self.db.put("routes", p.route_id, pd, self.mission_id)
        self.current_route_id = plans[0].route_id
        self.alternative_ids = [p.route_id for p in plans[1:]]
        self.route_history.append({"route_id": plans[0].route_id, "reason": "Initial provisional route (all roads UNKNOWN)",
                                   "sim_time": self.sim_time()})

    def _refresh_current_route_flags(self):
        cur = self.routes.get(self.current_route_id or "")
        if not cur:
            return
        e = [self.net.edges[x] for x in cur["edge_ids"]]
        cur["unverified_edge_ids"] = [x.edge_id for x in e if x.access_status == AccessStatus.UNKNOWN]
        cur["unverified_edge_count"] = len(cur["unverified_edge_ids"])
        cur["suspected_edge_ids"] = [x.edge_id for x in e if x.access_status == AccessStatus.SUSPECTED_BLOCKED]
        cur["at_risk"] = bool(cur["suspected_edge_ids"])
        self.emit("route.updated", {"route": cur})

    def recalculate(self, reason: str) -> dict:
        with self.lock:
            st, ds = self.scenario["staging"], self.scenario["destination"]
            prev = self.routes.get(self.current_route_id or "")
            t0 = time.perf_counter()
            try:
                plans = plan_routes(self.net, st["node"], ds["node"], k=3, sim_time=self.sim_time())
            except NoRouteError as ex:
                ms = (time.perf_counter() - t0) * 1000
                if prev:
                    prev["route_status"] = "INVALIDATED"
                payload = {"status": "NO_ROUTE", "message": str(ex), "reason": reason, "previous": prev,
                           "compute_ms": round(ms, 2)}
                self.current_route_id = None
                self.emit("route.recalculated", payload)
                return payload
            ms = (time.perf_counter() - t0) * 1000
            self.metrics_extra["route_recalc_ms"].append(round(ms, 2))
            if prev:
                blocked = [e for e in prev["edge_ids"] if self.net.edges[e].access_status == AccessStatus.CONFIRMED_BLOCKED]
                same = prev["edge_ids"] == plans[0].edge_ids
                if not same:
                    prev["route_status"] = "INVALIDATED" if blocked else "SUPERSEDED"
                    prev["invalidated_by"] = blocked
                    self.db.put("routes", prev["route_id"], prev, self.mission_id)
            for rid in getattr(self, "alternative_ids", []):
                if rid in self.routes and self.routes[rid]["route_status"] == "ALTERNATIVE":
                    self.routes[rid]["route_status"] = "SUPERSEDED"
            new = []
            for p in plans:
                pd = p.model_dump(mode="json")
                pd["mission_id"] = self.mission_id
                pd["compute_ms"] = round(ms, 2)
                pd["at_risk"] = bool(pd["suspected_edge_ids"])
                if prev and pd["edge_ids"] == prev["edge_ids"]:
                    pd["route_id"] = prev["route_id"]
                    pd["route_status"] = "APPROVED" if prev.get("route_status") == "APPROVED" and p.rank == 0 else pd["route_status"]
                self.routes[pd["route_id"]] = pd
                self.db.put("routes", pd["route_id"], pd, self.mission_id)
                new.append(pd)
            self.current_route_id = new[0]["route_id"]
            self.alternative_ids = [p["route_id"] for p in new[1:]]
            self.route_history.append({"route_id": new[0]["route_id"], "reason": reason, "sim_time": self.sim_time()})
            payload = {"status": "OK", "reason": reason, "previous": prev, "current": new[0], "alternatives": new[1:],
                       "compute_ms": round(ms, 2),
                       "delta": {"distance_m": round(new[0]["distance_m"] - prev["distance_m"], 1) if prev else None,
                                 "travel_s": round(new[0]["estimated_travel_seconds"] - prev["estimated_travel_seconds"], 1) if prev else None}}
            self.emit("route.recalculated", payload)
            return payload

    def approve_route(self, rid: str, op) -> dict:
        with self.lock:
            r = self.routes.get(rid)
            if r is None:
                raise KeyError(rid)
            if r["route_status"] in ("INVALIDATED", "SUPERSEDED"):
                raise ValueError("Cannot approve a superseded or invalidated route")
            blocked = [e for e in r["edge_ids"] if self.net.edges[e].access_status == AccessStatus.CONFIRMED_BLOCKED]
            if blocked:
                raise ValueError("Route crosses confirmed-blocked segments")
            r["route_status"] = "APPROVED"
            r["approved_by"] = op.operator
            r["approved_at"] = self.sim_time()
            self.approved_route_id = rid
            dec = self._record_decision("APPROVE_ROUTE", "route", rid, op,
                                        {"distance_m": r["distance_m"], "estimated_travel_seconds": r["estimated_travel_seconds"],
                                         "unverified_edge_count": r["unverified_edge_count"],
                                         "suspected_edge_count": len(r["suspected_edge_ids"])})
            self.db.put("routes", rid, r, self.mission_id)
            self.emit("route.approved", {"route": r, "decision": dec})
            return {"route": r, "decision": dec}

    # ------------------------------------------------------------------ briefing
    def briefing_facts(self) -> dict:
        with self.lock:
            cur = self.routes.get(self.approved_route_id or self.current_route_id or "")
            first = self.routes.get(self.route_history[0]["route_id"]) if self.route_history else None
            confirmed = [i for i in self.incidents.values() if i["status"] == IncidentStatus.CONFIRMED.value]
            verified_ok = [i for i in self.incidents.values() if i["status"] == IncidentStatus.VERIFIED_PASSABLE.value]
            pending = [i for i in self.incidents.values() if i["status"] in (IncidentStatus.PENDING_REVIEW.value, IncidentStatus.REINSPECTION_REQUESTED.value)]
            fmt = lambda r: r and {"route_id": r["route_id"], "status": r["route_status"], "roads": r["road_names"],  # noqa: E731
                                   "distance_m": r["distance_m"], "simulated_travel_seconds": r["estimated_travel_seconds"],
                                   "unverified_edge_count": r["unverified_edge_count"], "approved_by": r.get("approved_by")}
            return {
                "scenario": self.scenario["name"], "disclaimer": self.scenario["disclaimer"],
                "simulated_time": self.sim_time(), "mission_id": self.mission_id,
                "staging": self.scenario["staging"]["name"], "destination": self.scenario["destination"]["name"],
                "confirmed_obstructions": [{"incident_id": i["incident_id"], "hazard_type": i["hazard_type"], "roads": i["affected_road_names"],
                                            "location": i["location"], "observation_ids": i["observation_ids"],
                                            "historical_context": i.get("historical_context"),
                                            "confirmed_by": next((d["operator"] for d in self.decisions if d["target_id"] == i["incident_id"]), None)}
                                           for i in confirmed],
                "verified_passable": [{"incident_id": i["incident_id"], "roads": i["affected_road_names"], "observation_ids": i["observation_ids"]}
                                      for i in verified_ok],
                "pending_incidents": [{"incident_id": i["incident_id"], "hazard_type": i["hazard_type"], "roads": i["affected_road_names"]}
                                      for i in pending],
                "previous_route": fmt(first), "current_route": fmt(cur),
                "route_difference": cur and first and {"distance_m": round(cur["distance_m"] - first["distance_m"], 1),
                                                       "simulated_travel_seconds": round(cur["estimated_travel_seconds"] - first["estimated_travel_seconds"], 1)},
                "remaining_unverified_segments": cur and sorted({self.net.edges[e].road_name for e in cur["unverified_edge_ids"]}),
                "survey": self.metrics(),
            }

    def generate_briefing(self, op_name: str) -> dict:
        facts = self.briefing_facts()
        inv, data = briefing_ai.generate(facts)
        with self.lock:
            bid = f"BRF-{uuid.uuid4().hex[:6].upper()}"
            invd = inv.model_dump(mode="json")
            invd["mission_id"] = self.mission_id
            self.invocations[inv.invocation_id] = invd
            self.db.put("invocations", inv.invocation_id, invd, self.mission_id)
            if inv.latency_ms:
                self.metrics_extra["bedrock_latency_ms"].append(inv.latency_ms)
            b = {"briefing_id": bid, "mission_id": self.mission_id, "status": inv.status, "requested_by": op_name,
                 "simulated_timestamp": self.sim_time(), "facts": facts, "briefing": data, "invocation": invd,
                 "provenance": ["BEDROCK_INFERENCE", "HUMAN_VERIFIED"] if data else []}
            if data:
                uri = s3.put_bytes(f"missions/{self.mission_id}/briefings/{bid}.json", json.dumps(b, default=str).encode(), "application/json")
                b["s3_uri"] = uri
            self.briefings[bid] = b
            self.db.put("briefings", bid, b, self.mission_id)
            self.emit("briefing.generated", b)
            if not data:
                self.emit("system.degraded", {"component": "BEDROCK", "reason": inv.failure_reason, "impact": "Briefing not generated."})
            return b

    # ------------------------------------------------------------------ views
    def coverage_summary(self) -> dict:
        return {"survey_coverage_pct": round(self.recon.coverage_fraction() * 100, 2),
                "observed_area_m2": round(self.recon.observed_area_m2()),
                "per_drone": {k: self.telemetry(d)["scan_coverage_percentage"] for k, d in self.drones.items()},
                "total_points": self.total_points, "scans": len(self.scans_meta)}

    def metrics(self) -> dict:
        assessed = [e for e in self.edge_samples if self.net.edges[e].last_observed_at]
        by_status: dict[str, int] = {}
        for eid in self.edge_samples:
            s = self.net.edges[eid].access_status.value
            by_status[s] = by_status.get(s, 0) + 1
        first = self.routes.get(self.route_history[0]["route_id"]) if self.route_history else None
        cur = self.routes.get(self.current_route_id or "")
        lat = self.metrics_extra["bedrock_latency_ms"]
        rr = self.metrics_extra["route_recalc_ms"]
        return {
            "survey_area_m2": round(self.coord.survey.area),
            "observed_area_m2": round(self.recon.observed_area_m2()),
            "survey_coverage_pct": round(self.recon.coverage_fraction() * 100, 2),
            "road_segments_in_survey": len(self.edge_samples),
            "road_segments_assessed": len(assessed),
            "road_status_counts": by_status,
            "scan_points": self.total_points,
            "scans": len(self.scans_meta),
            "observations": len(self.observations),
            "incidents": len(self.incidents),
            "confirmed_hazards": sum(1 for i in self.incidents.values() if i["status"] == "CONFIRMED"),
            "bedrock_calls_completed": sum(1 for v in self.invocations.values() if v["status"] == "SUCCESS"),
            "bedrock_calls_failed": sum(1 for v in self.invocations.values() if v["status"] in ("FAILED", "VALIDATION_FAILED")),
            "bedrock_latency_ms_mean": round(float(np.mean(lat)), 0) if lat else None,
            "route_recalc_ms_mean": round(float(np.mean(rr)), 2) if rr else None,
            "original_route_distance_m": first and first["distance_m"],
            "original_route_travel_s": first and first["estimated_travel_seconds"],
            "current_route_distance_m": cur and cur["distance_m"],
            "current_route_travel_s": cur and cur["estimated_travel_seconds"],
            "current_route_unverified_edges": cur and cur["unverified_edge_count"],
            "simulated_elapsed_s": self.tick_n,
            "note": "Distances/times are simulated estimates from OSM speeds; latencies are measured software execution times.",
        }

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "mission": {"mission_id": self.mission_id, "state": self.state.value, "speed": self.speed,
                            "simulated_timestamp": self.sim_time(), "tick": self.tick_n, "scenario": self.scenario_public(),
                            "survey_polygon": self.coord.survey_polygon_lonlat(), "operator": self.mission_row["operator"],
                            "auto_pause": self.auto_pause},
                "seq": self.bus.seq,
                "drones": [{**self.telemetry(d), "callsign": d.cfg.callsign, "role": d.cfg.role, "color": d.cfg.color,
                            "plan": [list(to_geo(w.x, w.y)) + [w.agl, w.action] for w in d.plan]} for d in self.drones.values()],
                "sectors": self.coord.sectors(),
                "observations": list(self.observations.values()),
                "incidents": list(self.incidents.values()),
                "invocations": list(self.invocations.values()),
                "routes": self.routes, "current_route_id": self.current_route_id,
                "alternative_ids": getattr(self, "alternative_ids", []), "approved_route_id": self.approved_route_id,
                "route_history": self.route_history,
                "road_status": {e.edge_id: e.access_status.value for e in self.net.edges.values() if e.access_status != AccessStatus.UNKNOWN},
                "decisions": self.decisions,
                "briefings": list(self.briefings.values()),
                "retask_log": self.retask_log,
                "coverage": self.coverage_summary(),
                "metrics": self.metrics(),
            }

    def scenario_public(self) -> dict:
        """Mission setup visible to the operator. Hidden hazards are NOT included."""
        s = self.scenario
        bridge = next(h for h in s["hazards"] if h["hazard_id"] == "GT-WHITSON-BRIDGE")
        return {"scenario_id": s["scenario_id"], "name": s["name"], "replay_window": s["replay_window"],
                "sim_start": s["sim_start"], "disclaimer": s["disclaimer"], "staging": s["staging"],
                "destination": s["destination"], "pois": s["pois"],
                "historical_record": {"title": "Whitson Avenue Bridge (SR 2727) — documented Helene damage",
                                      "text": bridge["historical_basis"], "source": bridge["historical_source"],
                                      "provenance": "OFFICIAL_HISTORICAL_RECORD",
                                      "note": "Known from the public record; in this replay the commander still requires drone evidence before changing road status."}}
