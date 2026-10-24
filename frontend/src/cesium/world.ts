import * as Cesium from "cesium";
import { bus } from "../services/bus";
import { api } from "../services/api";
import { onSnapshotReload } from "../services/stream";
import { useMission } from "../store/mission";
import type { RoutePlan } from "../types";
import { CameraDirector } from "./camera";
import { DynamicLayers } from "./dynamicLayers";
import { createScene, SceneCtx } from "./scene";
import { buildStatic, StaticLayers } from "./staticLayers";

/** Glue between the mission store / event bus and the Cesium scene. */
export class World3D {
  ctx!: SceneCtx;
  stat!: StaticLayers;
  dyn!: DynamicLayers;
  cam!: CameraDirector;
  edgeGeom = new Map<string, number[][]>();
  shortBridges = new Set<string>();
  ready = false;

  async init(el: HTMLElement) {
    const imagery = await api.get<any>("/api/geo/imagery").catch(() => null);
    const noaa = imagery?.coverage?.covered ? imagery.crops.find((c: any) => c.site === "whitson_bridge")?.bounds_wgs84 : null;
    const area = useMission.getState().surveyPolygon;
    const lons = area.map((p) => p[0]), lats = area.map((p) => p[1]);
    const bounds = area.length ? { west: Math.min(...lons) - 0.03, south: Math.min(...lats) - 0.02, east: Math.max(...lons) + 0.03, north: Math.max(...lats) + 0.02 } : noaa;
    this.ctx = await createScene(el, imagery?.coverage?.covered ? bounds : null);
    const viewer = this.ctx.viewer;
    const snap = await api.mission();
    this.stat = await buildStatic(viewer, snap);
    this.stat.roadProps.forEach((_p, eid) => void eid);
    const roads = await api.get<any>("/api/geo/roads");
    roads.features.forEach((f: any) => {
      this.edgeGeom.set(f.properties.edge_id, f.geometry.coordinates);
      if (f.properties.is_bridge && f.properties.length_m < 260) this.shortBridges.add(f.properties.edge_id);
    });
    this.dyn = new DynamicLayers(viewer);
    this.cam = new CameraDirector(viewer, this.dyn);
    this.dyn.hMin = 640;
    this.dyn.hMax = 720;
    await this.loadSnapshotGeometry(snap);
    this.wire();
    this.installPicking();
    const sc = snap.mission.scenario;
    this.cam.wideValley({ lon: (sc.staging.lon + sc.destination.lon) / 2, lat: (sc.staging.lat + sc.destination.lat) / 2 }, 0);
    this.ready = true;
  }

  async loadSnapshotGeometry(snap: any) {
    this.dyn.clearAll();
    this.dyn.periodMs = 1000 / Math.max(1, snap.mission.speed);
    this.dyn.initDrones(snap.drones);
    Object.entries(snap.road_status as Record<string, string>).forEach(([e, s]) => this.stat.setRoadStatus(e, s));
    // reset road colours of edges not in snapshot to UNKNOWN
    this.stat.roadIds.forEach((e) => { if (!snap.road_status[e]) this.stat.setRoadStatus(e, "UNKNOWN"); });
    const [points, tiles] = await Promise.all([api.get<any[]>("/api/scans/points"), api.get<any[]>("/api/scans/tiles")]);
    points.forEach((b) => this.dyn.addScan(b, b.seq));
    tiles.forEach((t) => this.dyn.upsertTile(t));
    snap.incidents.forEach((i: any) => this.dyn.upsertIncident(i));
    snap.observations.forEach((o: any) => this.dyn.addObservationFootprint(o));
    this.applyLayers();
    this.redrawRoutes();
  }

  wire() {
    bus.on("drone.telemetry", (e) => this.dyn.telemetry(e.payload));
    bus.on("scan.completed", (e) => this.dyn.addScan(e.payload, e.seq));
    bus.on("recon.tiles_updated", (e) => e.payload.tiles.forEach((t: any) => this.dyn.upsertTile(t)));
    bus.on("scan.change_detected", (e) => this.dyn.addChangeMark(e.payload.lon, e.payload.lat));
    bus.on("observation.created", (e) => this.dyn.addObservationFootprint(e.payload));
    ["incident.created", "incident.updated", "incident.verified", "incident.rejected", "incident.inspection_requested"].forEach((t) =>
      bus.on(t, (e) => this.dyn.upsertIncident(e.payload)),
    );
    bus.on("road.status_changed", (e) => {
      e.payload.edges.forEach((ed: any) => this.stat.setRoadStatus(ed.edge_id, ed.access_status));
      this.redrawRoutes();
    });
    ["route.recalculated", "route.updated", "route.approved"].forEach((t) => bus.on(t, () => setTimeout(() => this.redrawRoutes(), 0)));
    bus.on("mission.speed_changed", (e) => (this.dyn.periodMs = 1000 / e.payload.speed));
    onSnapshotReload(async () => {
      const snap = await api.mission();
      await this.loadSnapshotGeometry(snap);
    });
    let prevLayers = useMission.getState().layers;
    let prevFollow = useMission.getState().followDrone;
    useMission.subscribe((s) => {
      if (s.layers !== prevLayers) {
        prevLayers = s.layers;
        this.applyLayers();
      }
      if (s.followDrone !== prevFollow) {
        prevFollow = s.followDrone;
        this.cam.follow(s.followDrone);
      }
    });
  }

  applyLayers() {
    const L = useMission.getState().layers;
    const v = this.ctx.viewer;
    this.ctx.baseLayer.show = L.base;
    v.scene.globe.showGroundAtmosphere = L.base;
    if (this.ctx.noaaLayer) this.ctx.noaaLayer.show = L.noaa && L.base;
    this.dyn.setPointsVisible(L.scan);
    this.dyn.setReconVisible(L.recon);
    this.dyn.setHazardsVisible(L.hazards);
    if (this.stat.buildings) this.stat.buildings.show = L.buildings;
    this.stat.roads.show = L.roads;
    this.stat.sectors.forEach((s) => (s.show = L.sectors));
  }

  redrawRoutes() {
    const s = useMission.getState();
    const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
    const prev = s.previousRouteId ? s.routes[s.previousRouteId] : null;
    const alts = s.alternativeIds.map((id) => s.routes[id]).filter(Boolean) as RoutePlan[];
    this.dyn.drawRoutes(cur, prev, alts, s.roadStatus, this.edgeGeom, !!cur && s.approvedRouteId === cur.route_id, this.shortBridges);
  }

  installPicking() {
    const v = this.ctx.viewer;
    const h = new Cesium.ScreenSpaceEventHandler(v.scene.canvas);
    h.setInputAction((m: { position: Cesium.Cartesian2 }) => {
      const picked = v.scene.pick(m.position);
      const st = useMission.getState();
      if (!picked) return;
      const id = picked.id;
      if (id instanceof Cesium.Entity) {
        const kind = id.properties?.kind?.getValue();
        if (kind === "incident") {
          st.select("incident", id.properties!.incident_id.getValue());
          st.set({ rightTab: "incidents" });
        } else if (kind === "drone") st.select("drone", id.properties!.drone_id.getValue());
        else if (kind === "observation") {
          st.select("observation", id.properties!.observation_id.getValue());
          st.set({ rightTab: "feed" });
        }
        return;
      }
      if (id && typeof id === "object" && id.kind === "road") st.select("road", id.edge_id);
      else if (id && typeof id === "object" && id.kind === "bridge") st.select("road", id.edge_id);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    // user camera input cancels follow mode
    h.setInputAction(() => {
      if (useMission.getState().followDrone) useMission.getState().set({ followDrone: null });
    }, Cesium.ScreenSpaceEventType.RIGHT_DOWN);
  }

  roadProps(eid: string) {
    return this.stat?.roadProps.get(eid);
  }
}

export const world3d = new World3D();
