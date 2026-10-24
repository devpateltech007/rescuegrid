"""Step 3 validation: prove the rerouting scenario exists on the real road graph.

Searches staging/destination node pairs (both SIMULATED_SCENARIO points) such that:
  1. a route exists between them,
  2. the best route crosses the Whitson Avenue bridge edges,
  3. a feasible alternative exists after removing those edges,
  4. the detour is measurably longer.
Writes data/scenarios/route_validation.json and a PNG preview.
Run: python scripts/validate_route_scenario.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402

from app.config import SCENARIOS  # noqa: E402
from app.geospatial.crs import to_local  # noqa: E402
from app.models.schemas import AccessStatus  # noqa: E402
from app.routing.graph import RoadNetwork  # noqa: E402
from app.routing.planner import NoRouteError, plan_routes  # noqa: E402

MAJOR = {"primary", "secondary", "tertiary", "trunk", "primary_link", "secondary_link", "tertiary_link"}


def main() -> None:
    net = RoadNetwork()
    area = json.loads((ROOT / "data" / "geography" / "study_area.json").read_text())
    bx, by = area["center_local"]["x"], area["center_local"]["y"]
    bridge = set(net.bridge_edge_ids())
    print(f"bridge edges: {sorted(bridge)}")
    for b in bridge:
        e = net.edges[b]
        print(f"   {b}: {e.road_name} len={e.length_m:.0f}m ways={e.osm_way_ids}")

    # Plain travel-time digraph for candidate search.
    D = nx.DiGraph()
    cheapest = {}
    for e in net.edges.values():
        if (e.u, e.v) not in cheapest or e.estimated_travel_seconds < net.edges[cheapest[(e.u, e.v)]].estimated_travel_seconds:
            cheapest[(e.u, e.v)] = e.edge_id
            D.add_edge(e.u, e.v, w=e.estimated_travel_seconds)
    Dno = D.copy()
    for b in bridge:
        e = net.edges[b]
        if Dno.has_edge(e.u, e.v):
            Dno.remove_edge(e.u, e.v)

    # Candidate nodes: on major roads, 300-1400 m from the bridge, inside the survey square.
    cand = set()
    for e in net.edges.values():
        if e.road_class in MAJOR:
            for n in (e.u, e.v):
                x, y = net.node_xy[n]
                d = np.hypot(x - bx, y - by)
                if 300 < d < 1400 and abs(x - bx) < 950 and abs(y - by) < 950:
                    cand.add(n)
    cand = sorted(cand)
    north = [n for n in cand if net.node_xy[n][1] > by + 50]
    south = [n for n in cand if net.node_xy[n][1] < by - 50]
    print(f"candidates north={len(north)} south={len(south)}")

    best = None
    for s in north:
        try:
            ds = nx.single_source_dijkstra(D, s, weight="w")
            dn = nx.single_source_dijkstra_path_length(Dno, s, weight="w")
        except nx.NetworkXError:
            continue
        for t in south:
            if t not in ds[0] or t not in dn:
                continue
            p = ds[1][t]
            used = {cheapest[(a, b)] for a, b in zip(p[:-1], p[1:])}
            if not used & bridge:
                continue
            t0, t1 = ds[0][t], dn[t]
            ratio = t1 / max(t0, 1)
            if not (1.4 <= ratio <= 4.5) or t0 < 60:
                continue
            score = (t1 - t0) - 0.2 * t0  # meaningful detour, not absurd
            if best is None or score > best[0]:
                best = (score, s, t, t0, t1)
    if best is None:
        sys.exit("FAIL: no staging/destination pair satisfies the rerouting conditions; widen the graph.")
    _, s, t, t0, t1 = best

    plans = plan_routes(net, s, t, k=1)
    original = plans[0]
    assert set(original.edge_ids) & bridge, "planner's original route must cross the bridge"
    for b in bridge:
        net.edges[b].access_status = AccessStatus.CONFIRMED_BLOCKED
    try:
        detours = plan_routes(net, s, t, k=3)
    except NoRouteError as e:
        sys.exit(f"FAIL: {e}")
    detour = detours[0]
    assert not set(detour.edge_ids) & bridge
    print("\nORIGINAL :", f"{original.distance_m:.0f} m, {original.estimated_travel_seconds:.0f} s via {original.road_names}")
    print("DETOUR   :", f"{detour.distance_m:.0f} m, {detour.estimated_travel_seconds:.0f} s via {detour.road_names}")
    print("alternatives after block:", [(round(d.distance_m), round(d.estimated_travel_seconds)) for d in detours])

    slon, slat = net.node_lonlat(s)
    tlon, tlat = net.node_lonlat(t)
    out = {
        "staging_node": s, "staging": {"lon": slon, "lat": slat},
        "destination_node": t, "destination": {"lon": tlon, "lat": tlat},
        "bridge_edge_ids": sorted(bridge),
        "original": {"distance_m": original.distance_m, "travel_s": original.estimated_travel_seconds,
                     "roads": original.road_names, "edge_ids": original.edge_ids},
        "detour": {"distance_m": detour.distance_m, "travel_s": detour.estimated_travel_seconds,
                   "roads": detour.road_names, "edge_ids": detour.edge_ids},
        "alternatives_after_block": [{"distance_m": d.distance_m, "travel_s": d.estimated_travel_seconds, "roads": d.road_names} for d in detours],
        "unknown_penalty": 1.3,
        "provenance": {"staging": "SIMULATED_SCENARIO", "destination": "SIMULATED_SCENARIO", "graph": "CURRENT_BASEMAP"},
    }
    SCENARIOS.mkdir(parents=True, exist_ok=True)
    (SCENARIOS / "route_validation.json").write_text(json.dumps(out, indent=2))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 9), facecolor="#111")
    ax.set_facecolor("#111")
    for e in net.edges.values():
        xs, ys = zip(*e.geometry)
        ax.plot(xs, ys, color="#444", lw=0.6)
    for r, c, lw in ((original, "#ff4040", 4), (detour, "#40ff80", 2.5)):
        xs, ys = zip(*r.geometry)
        ax.plot(xs, ys, color=c, lw=lw, alpha=0.9)
    for b in bridge:
        xs, ys = zip(*net.edges[b].geometry)
        ax.plot(xs, ys, color="yellow", lw=6)
    ax.scatter([slon], [slat], c="cyan", s=80, zorder=5, label="staging (simulated)")
    ax.scatter([tlon], [tlat], c="magenta", s=80, zorder=5, label="destination (simulated)")
    ax.legend(facecolor="#222", labelcolor="white")
    ax.set_title(f"original {original.distance_m:.0f} m / detour {detour.distance_m:.0f} m", color="white")
    ax.set_aspect(1 / np.cos(np.radians(slat)))
    fig.savefig(SCENARIOS / "route_validation.png", dpi=110, bbox_inches="tight")
    print("wrote data/scenarios/route_validation.json + .png")


if __name__ == "__main__":
    main()
