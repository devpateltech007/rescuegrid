"""Road network loaded from the persisted OSMnx drive graph (real OpenStreetMap data).

Each directed edge gets a stable edge_id "<u>-<v>-<k>" and the fields required by spec
section 7. Access status is mutable mission state; geometry is immutable basemap data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString

from app.config import ROADS, WHITSON_BRIDGE_OSM_WAY
from app.geospatial.crs import to_local
from app.models.schemas import AccessStatus

GRAPH_FILE = ROADS / "swannanoa_drive.graphml"


def _first(v):
    return v[0] if isinstance(v, list) else v


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


@dataclass
class RoadEdge:
    edge_id: str
    u: int
    v: int
    k: int
    osm_way_ids: list[int]
    geometry: list[tuple[float, float]]  # lon, lat
    length_m: float
    road_name: str
    road_class: str
    speed_kph: float
    estimated_travel_seconds: float
    oneway: bool
    is_bridge: bool
    access_status: AccessStatus = AccessStatus.UNKNOWN
    evidence_ids: list[str] = field(default_factory=list)
    last_verified_at: str | None = None
    last_observed_at: str | None = None
    status_provenance: str = "CURRENT_BASEMAP"
    line_local: LineString | None = None

    def public(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "source_node": self.u,
            "target_node": self.v,
            "osm_way_ids": self.osm_way_ids,
            "length_m": round(self.length_m, 1),
            "road_name": self.road_name,
            "road_class": self.road_class,
            "speed_assumption_kph": round(self.speed_kph, 1),
            "estimated_travel_seconds": round(self.estimated_travel_seconds, 1),
            "oneway": self.oneway,
            "is_bridge": self.is_bridge,
            "access_status": self.access_status.value,
            "evidence_ids": self.evidence_ids,
            "last_verified_at": self.last_verified_at,
            "last_observed_at": self.last_observed_at,
            "status_provenance": self.status_provenance,
            "geometry_provenance": "CURRENT_BASEMAP",
        }


class RoadNetwork:
    def __init__(self, path: Path = GRAPH_FILE):
        self.G: nx.MultiDiGraph = ox.load_graphml(path)
        self.edges: dict[str, RoadEdge] = {}
        self.by_uvk: dict[tuple[int, int, int], str] = {}
        for u, v, k, d in self.G.edges(keys=True, data=True):
            geom = d.get("geometry")
            if geom is None:
                geom = LineString([(self.G.nodes[u]["x"], self.G.nodes[u]["y"]), (self.G.nodes[v]["x"], self.G.nodes[v]["y"])])
            coords = [(float(x), float(y)) for x, y in geom.coords]
            xs, ys = to_local([c[0] for c in coords], [c[1] for c in coords])
            ways = [int(w) for w in _as_list(d.get("osmid"))]
            name = _as_list(d.get("name"))
            ref = _as_list(d.get("ref"))
            label = " / ".join(str(n) for n in name) if name else (" / ".join(str(r) for r in ref) if ref else "Unnamed road")
            bridge = _as_list(d.get("bridge"))
            eid = f"{u}-{v}-{k}"
            e = RoadEdge(
                edge_id=eid, u=u, v=v, k=k, osm_way_ids=ways, geometry=coords,
                length_m=float(d.get("length", 0.0)), road_name=label,
                road_class=str(_first(d.get("highway", "road"))),
                speed_kph=float(d.get("speed_kph", 40.0)),
                estimated_travel_seconds=float(d.get("travel_time", 0.0)),
                oneway=bool(d.get("oneway", False)),
                is_bridge=any(str(b).lower() not in ("no", "false", "nan") for b in bridge),
                line_local=LineString(list(zip(xs, ys))),
            )
            self.edges[eid] = e
            self.by_uvk[(u, v, k)] = eid
        self.node_xy = {n: to_local(d["x"], d["y"]) for n, d in self.G.nodes(data=True)}
        self._node_ids = np.array(list(self.node_xy.keys()))
        self._node_arr = np.array(list(self.node_xy.values()))

    # ----- lookup -----
    def bridge_edge_ids(self, way_id: int = WHITSON_BRIDGE_OSM_WAY) -> list[str]:
        return [e.edge_id for e in self.edges.values() if way_id in e.osm_way_ids]

    def nearest_node(self, lon: float, lat: float) -> int:
        x, y = to_local(lon, lat)
        d = np.hypot(self._node_arr[:, 0] - x, self._node_arr[:, 1] - y)
        return int(self._node_ids[int(np.argmin(d))])

    def node_lonlat(self, n: int) -> tuple[float, float]:
        return float(self.G.nodes[n]["x"]), float(self.G.nodes[n]["y"])

    def edges_near(self, x: float, y: float, radius_m: float) -> list[tuple[str, float]]:
        from shapely.geometry import Point
        p = Point(x, y)
        out = []
        for e in self.edges.values():
            b = e.line_local.bounds
            if b[0] - radius_m > x or b[2] + radius_m < x or b[1] - radius_m > y or b[3] + radius_m < y:
                continue
            d = e.line_local.distance(p)
            if d <= radius_m:
                out.append((e.edge_id, d))
        return sorted(out, key=lambda t: t[1])

    def twin_ids(self, eid: str) -> list[str]:
        """Same physical road segment in both directions (u,v) and (v,u)."""
        e = self.edges[eid]
        out = [eid]
        for (u, v, k), oid in self.by_uvk.items():
            if u == e.v and v == e.u and set(self.edges[oid].osm_way_ids) == set(e.osm_way_ids):
                out.append(oid)
        return out

    def reset_status(self) -> None:
        for e in self.edges.values():
            e.access_status = AccessStatus.UNKNOWN
            e.evidence_ids = []
            e.last_verified_at = None
            e.last_observed_at = None
            e.status_provenance = "CURRENT_BASEMAP"

    def geojson(self) -> dict:
        feats = []
        for e in self.edges.values():
            feats.append({"type": "Feature", "id": e.edge_id,
                          "geometry": {"type": "LineString", "coordinates": e.geometry},
                          "properties": e.public()})
        return {"type": "FeatureCollection", "features": feats}


def path_length(net: RoadNetwork, edge_ids: list[str]) -> tuple[float, float]:
    return (sum(net.edges[e].length_m for e in edge_ids), sum(net.edges[e].estimated_travel_seconds for e in edge_ids))


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
