"""Central mission coordinator: sectors, waypoint plans and information-gain retasking.

Sectors are corridors (buffered flight lines) so assignments do not overlap needlessly:
  Alpha   — US 70 / West State Street corridor
  Bravo   — Whitson Avenue Bridge, then the Swannanoa River corridor
  Charlie — Old US Highway 70 (alternate corridor)
Plans are derived from real OSM road / river geometry, never hand-drawn.
"""
from __future__ import annotations

import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import LineString, MultiLineString, box, mapping
from shapely.ops import linemerge, transform as shp_transform

from app.config import GEO
from app.geospatial.crs import to_geo, to_local
from app.simulation.drones import DroneConfig, Waypoint

DRONES = [
    DroneConfig("ALPHA", "Drone Alpha", "Highway Recon — US 70 / West State St", "#38bdf8", "S-ALPHA"),
    DroneConfig("BRAVO", "Drone Bravo", "Bridge Inspection — Whitson Ave Bridge & river crossings", "#f59e0b", "S-BRAVO"),
    DroneConfig("CHARLIE", "Drone Charlie", "Alternate Corridor — Old US 70", "#a78bfa", "S-CHARLIE"),
]


def densify(line: LineString, step: float) -> list[tuple[float, float]]:
    n = max(2, int(line.length / step) + 1)
    return [(p.x, p.y) for p in (line.interpolate(i / (n - 1), normalized=True) for i in range(n))]


def road_corridor(net, name: str, survey: box) -> LineString:
    """Longest connected path along edges with the given road name inside the survey box."""
    H = nx.Graph()
    for e in net.edges.values():
        if e.road_name == name and e.line_local.intersects(survey):
            H.add_edge(e.u, e.v, w=e.length_m, eid=e.edge_id)
    comp = max(nx.connected_components(H), key=lambda c: sum(H[u][v]["w"] for u, v in H.subgraph(c).edges))
    S = H.subgraph(comp)
    xs = {n: net.node_xy[n][0] for n in S.nodes}
    a, b = min(xs, key=xs.get), max(xs, key=xs.get)
    path = nx.shortest_path(S, a, b, weight="w")
    coords: list[tuple[float, float]] = []
    for u, v in zip(path[:-1], path[1:]):
        e = net.edges[S[u][v]["eid"]]
        c = list(e.line_local.coords)
        if math.dist(c[0], net.node_xy[u]) > math.dist(c[-1], net.node_xy[u]):
            c = c[::-1]
        coords.extend(c if not coords else c[1:])
    line = LineString(coords).intersection(survey.buffer(-20))
    if isinstance(line, MultiLineString):
        line = max(line.geoms, key=lambda g: g.length)
    return line


def river_corridor(survey: box) -> LineString:
    w = gpd.read_file(GEO / "water.geojson")
    w = w[(w.get("waterway") == "river") & w["name"].fillna("").str.contains("Swannanoa")]
    geoms = [shp_transform(lambda x, y, z=None: to_local(x, y), g) for g in w.geometry]
    merged = linemerge([g for g in geoms if g.geom_type == "LineString"])
    clip = merged.intersection(survey.buffer(-20))
    if isinstance(clip, MultiLineString):
        clip = max(clip.geoms, key=lambda g: g.length)
    return clip


class Coordinator:
    def __init__(self, net, world, scenario: dict):
        self.net, self.world, self.scenario = net, world, scenario
        area = world.area
        cx, cy, half = area["center_local"]["x"], area["center_local"]["y"], area["survey_half_m"]
        self.survey = box(cx - half, cy - half, cx + half, cy + half)
        st = scenario["staging"]
        self.home = to_local(st["lon"], st["lat"])
        self.bridge_xy = to_local(scenario["pois"][0]["lon"], scenario["pois"][0]["lat"])
        self.lines = {
            "ALPHA": road_corridor(net, "West State Street", self.survey),
            "CHARLIE": road_corridor(net, "Old US Highway 70", self.survey),
            "BRAVO": river_corridor(self.survey),
        }

    def _oriented(self, line: LineString, start_east: bool) -> list[tuple[float, float]]:
        pts = densify(line, 35.0)
        if (pts[0][0] < pts[-1][0]) == start_east:
            pts = pts[::-1]
        return pts

    def plans(self) -> dict[str, list[Waypoint]]:
        hx, hy = self.home
        out: dict[str, list[Waypoint]] = {}
        # Alpha: east end of US 70 first, then sweep west along the corridor.
        a = self._oriented(self.lines["ALPHA"], start_east=True)
        out["ALPHA"] = ([Waypoint(*a[0], action="transit", label="Transit to US 70 east sector")] +
                        [Waypoint(x, y, label="US 70 corridor survey") for x, y in a[1:]] +
                        [Waypoint(hx, hy, action="land", label="Return to staging")])
        # Bravo: straight to the Whitson Avenue Bridge, inspect, then river corridor west->east.
        bx, by = self.bridge_xy
        r = self._oriented(self.lines["BRAVO"], start_east=False)
        out["BRAVO"] = ([Waypoint(bx, by, agl=35, action="inspect", hold_s=12, target=(bx, by),
                                  label="Inspect Whitson Avenue Bridge", task_id="TASK-WHITSON")] +
                        [Waypoint(x, y, label="Swannanoa River corridor survey") for x, y in r] +
                        [Waypoint(hx, hy, action="land", label="Return to staging")])
        # Charlie: Old US 70 east end first, then sweep west (alternate corridor).
        c = self._oriented(self.lines["CHARLIE"], start_east=True)
        out["CHARLIE"] = ([Waypoint(*c[0], action="transit", label="Transit to Old US 70 east")] +
                          [Waypoint(x, y, label="Old US 70 corridor survey") for x, y in c[1:]] +
                          [Waypoint(hx, hy, action="land", label="Return to staging")])
        return out

    def sectors(self) -> list[dict]:
        out = []
        names = {"ALPHA": "US 70 / West State St corridor", "BRAVO": "Swannanoa River crossings",
                 "CHARLIE": "Old US 70 alternate corridor"}
        for d in DRONES:
            poly = self.lines[d.drone_id].buffer(30, cap_style=2)
            ring = [list(to_geo(x, y)) for x, y in poly.exterior.coords]
            out.append({"sector_id": d.sector_id, "drone_id": d.drone_id, "name": names[d.drone_id],
                        "polygon": ring, "area_m2": round(poly.area), "color": d.color})
        return out

    def survey_polygon_lonlat(self) -> list[list[float]]:
        return [list(to_geo(x, y)) for x, y in self.survey.exterior.coords]

    # ----- information-gain retasking -----
    def score_targets(self, route_edge_ids: list[str], drones: list, inspected: set[str]) -> list[dict]:
        """Score unverified edges on the current recommended route.
        gain = travel-time share of the edge on the route x (3 if bridge else 1)
        cost = distance from the best available drone (km) + battery penalty
        Bridges dominate because lidar cannot establish structural passability."""
        from app.models.schemas import AccessStatus, FlightState
        total = sum(self.net.edges[e].estimated_travel_seconds for e in route_edge_ids) or 1
        seen_phys: set[frozenset] = set()
        cands = []
        for eid in route_edge_ids:
            e = self.net.edges[eid]
            if e.access_status not in (AccessStatus.UNKNOWN, AccessStatus.OBSERVED_PASSABLE):
                continue
            if e.access_status == AccessStatus.OBSERVED_PASSABLE and not e.is_bridge:
                continue
            key = frozenset((e.u, e.v))
            if key in seen_phys or eid in inspected:
                continue
            seen_phys.add(key)
            mid = e.line_local.interpolate(0.5, normalized=True)
            gain = (e.estimated_travel_seconds / total) * (3.0 if e.is_bridge else 1.0) + (0.5 if e.is_bridge else 0)
            best = None
            for d in drones:
                if d.state in (FlightState.IDLE,) or d.battery_pct < 25:
                    continue
                busy = 1.0 if d.state == FlightState.INSPECTING else 0.0
                dist_km = math.hypot(d.x - mid.x, d.y - mid.y) / 1000
                # sector affinity: the drone whose corridor passes near the target is preferred
                near_sector = self.lines[d.cfg.drone_id].distance(mid) < 350
                cost = dist_km + busy + (0.3 if d.cfg.drone_id == "BRAVO" else 0) - (0.35 if near_sector else 0)
                cost = max(cost, 0.01)
                if best is None or cost < best[0]:
                    best = (cost, d.cfg.drone_id, dist_km)
            if best is None:
                continue
            cands.append({"edge_id": eid, "road_name": e.road_name, "is_bridge": e.is_bridge,
                          "x": mid.x, "y": mid.y, "lon": to_geo(mid.x, mid.y)[0], "lat": to_geo(mid.x, mid.y)[1],
                          "gain": round(gain, 3), "cost": round(best[0], 3), "drone_id": best[1],
                          "distance_km": round(best[2], 3), "score": round(gain / (0.2 + best[0]), 3)})
        # Unverified bridges on the route come first (lidar cannot establish structural
        # passability), then everything else by information gain per unit cost.
        return sorted(cands, key=lambda c: (not c["is_bridge"], -c["score"]))
