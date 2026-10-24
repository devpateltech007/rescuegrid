"""Deterministic route planner on the real OSM road graph (NetworkX).

Weight = estimated travel seconds x status factor:
  CONFIRMED_BLOCKED  -> edge excluded
  SUSPECTED_BLOCKED  -> large penalty; any route still using it is flagged, never "safe"
  UNKNOWN            -> configurable uncertainty penalty
  OBSERVED/VERIFIED_PASSABLE -> 1.0
Directionality comes from the MultiDiGraph (OSM oneway respected). Turn restrictions are
not modelled by OSMnx (documented limitation). If no path exists, we say so — no fallback.
"""
from __future__ import annotations

import itertools
import time
import uuid
from datetime import datetime, timezone

import networkx as nx

from app.config import settings
from app.models.schemas import AccessStatus, RoutePlan
from app.routing.graph import RoadNetwork

PASSABLE = {AccessStatus.OBSERVED_PASSABLE, AccessStatus.VERIFIED_PASSABLE}


def status_factor(s: AccessStatus) -> float | None:
    if s == AccessStatus.CONFIRMED_BLOCKED:
        return None
    if s == AccessStatus.SUSPECTED_BLOCKED:
        return settings.suspected_penalty
    if s == AccessStatus.UNKNOWN:
        return settings.unknown_penalty
    return 1.0


def build_digraph(net: RoadNetwork) -> tuple[nx.DiGraph, dict[tuple[int, int], str]]:
    """Collapse the MultiDiGraph to a DiGraph keeping the cheapest usable parallel edge."""
    D = nx.DiGraph()
    chosen: dict[tuple[int, int], str] = {}
    for e in net.edges.values():
        f = status_factor(e.access_status)
        if f is None:
            continue
        w = max(e.estimated_travel_seconds, 0.1) * f
        key = (e.u, e.v)
        if key not in chosen or w < D[e.u][e.v]["weight"]:
            D.add_edge(e.u, e.v, weight=w)
            chosen[key] = e.edge_id
    return D, chosen


class NoRouteError(Exception):
    pass


def plan_routes(net: RoadNetwork, start_node: int, dest_node: int, k: int = 3,
                sim_time: str | None = None) -> list[RoutePlan]:
    t0 = time.perf_counter()
    D, chosen = build_digraph(net)
    if start_node not in D or dest_node not in D or not nx.has_path(D, start_node, dest_node):
        raise NoRouteError("No verified route could be identified: confirmed blockages disconnect the destination.")
    paths: list[list[int]] = []
    gen = nx.shortest_simple_paths(D, start_node, dest_node, weight="weight")
    for p in itertools.islice(gen, 40):
        eids = [chosen[(a, b)] for a, b in zip(p[:-1], p[1:])]
        if paths:
            # Drop near-duplicates: require <70% shared length with every kept route.
            L = sum(net.edges[e].length_m for e in eids)
            dup = False
            for q in paths:
                qe = {chosen[(a, b)] for a, b in zip(q[:-1], q[1:])}
                shared = sum(net.edges[e].length_m for e in eids if e in qe)
                if shared / max(L, 1) > 0.7:
                    dup = True
                    break
            if dup:
                continue
        paths.append(p)
        if len(paths) >= k:
            break
    compute_ms = (time.perf_counter() - t0) * 1000
    now = datetime.now(timezone.utc).isoformat()
    s_lon, s_lat = net.node_lonlat(start_node)
    d_lon, d_lat = net.node_lonlat(dest_node)
    plans = []
    for rank, p in enumerate(paths):
        eids = [chosen[(a, b)] for a, b in zip(p[:-1], p[1:])]
        edges = [net.edges[e] for e in eids]
        geom: list[list[float]] = []
        for e in edges:
            pts = [list(c) for c in e.geometry]
            geom.extend(pts if not geom else pts[1:])
        unverified = [e.edge_id for e in edges if e.access_status == AccessStatus.UNKNOWN]
        suspected = [e.edge_id for e in edges if e.access_status == AccessStatus.SUSPECTED_BLOCKED]
        blocked_avoided = [e.edge_id for e in net.edges.values() if e.access_status == AccessStatus.CONFIRMED_BLOCKED]
        names: list[str] = []
        for e in edges:
            if not names or names[-1] != e.road_name:
                names.append(e.road_name)
        ev_times = [e.last_verified_at or e.last_observed_at for e in edges if (e.last_verified_at or e.last_observed_at)]
        plans.append(RoutePlan(
            route_id=f"RT-{uuid.uuid4().hex[:8]}",
            rank=rank,
            label="Recommended" if rank == 0 else f"Alternative {rank}",
            start={"lon": s_lon, "lat": s_lat, "node": start_node},
            destination={"lon": d_lon, "lat": d_lat, "node": dest_node},
            edge_ids=eids,
            geometry=geom,
            distance_m=round(sum(e.length_m for e in edges), 1),
            estimated_travel_seconds=round(sum(e.estimated_travel_seconds for e in edges), 1),
            unverified_edge_count=len(unverified),
            unverified_edge_ids=unverified,
            suspected_edge_ids=suspected,
            blocked_edge_avoidance=blocked_avoided,
            road_names=names,
            evidence_timestamp=max(ev_times) if ev_times else None,
            route_status="RECOMMENDED" if rank == 0 else "ALTERNATIVE",
            route_generation_timestamp=sim_time or now,
            compute_ms=round(compute_ms, 2),
        ))
    return plans


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
