"""Step 5 of data preparation: scenario ground truth.

Hazards are anchored to real OSM graph edges (selected programmatically by OSM way id or
road name + distance from the bridge), so the route graph, 3D geometry and image
observations all refer to the same geographic locations. No coordinate is typed by hand.

Writes:
  data/scenarios/helene_swannanoa.json   hidden ground truth + public mission setup
  data/scenarios/evidence_sites.json     points where NOAA crops are pre-cached
Run: python scripts/build_scenario.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from app.config import SCENARIOS, WHITSON_BRIDGE_OSM_WAY  # noqa: E402
from app.geospatial.crs import to_geo  # noqa: E402
from app.routing.graph import RoadNetwork  # noqa: E402

RIVERWOOD_BRIDGE_OSM_WAY = 300953585  # Riverwood Road bridge (bridge=yes), found via Overpass


def point_on(net, eid, frac=0.5):
    line = net.edges[eid].line_local
    p = line.interpolate(frac, normalized=True)
    q = line.interpolate(min(frac + 0.02, 1.0), normalized=True)
    hd = float(np.degrees(np.arctan2(q.x - p.x, q.y - p.y))) % 360
    lon, lat = to_geo(p.x, p.y)
    return {"lon": float(lon), "lat": float(lat), "x": p.x, "y": p.y, "road_heading_deg": hd}


def pick_edge(net, name_sub, cx, cy, dmin, dmax, side=None, exclude=()):
    best = None
    for e in net.edges.values():
        if name_sub.lower() not in e.road_name.lower() or e.edge_id in exclude or e.length_m < 60:
            continue
        c = e.line_local.interpolate(0.5, normalized=True)
        d = np.hypot(c.x - cx, c.y - cy)
        if not (dmin <= d <= dmax):
            continue
        if side == "east" and c.x < cx:
            continue
        if side == "west" and c.x > cx:
            continue
        if best is None or abs(d - (dmin + dmax) / 2) < best[0]:
            best = (abs(d - (dmin + dmax) / 2), e.edge_id)
    if best is None:
        sys.exit(f"FAIL: no edge for {name_sub}")
    return best[1]


def main() -> None:
    net = RoadNetwork()
    area = json.loads((ROOT / "data" / "geography" / "study_area.json").read_text())
    rv = json.loads((SCENARIOS / "route_validation.json").read_text())
    cx, cy = area["center_local"]["x"], area["center_local"]["y"]
    route_edges = set(rv["original"]["edge_ids"]) | set(rv["detour"]["edge_ids"])

    bridge = net.bridge_edge_ids(WHITSON_BRIDGE_OSM_WAY)
    bmid = point_on(net, bridge[0])
    bline = net.edges[bridge[0]].line_local
    bend_a = bline.interpolate(0.12, normalized=True)
    bend_b = bline.interpolate(0.88, normalized=True)

    riverwood = net.bridge_edge_ids(RIVERWOOD_BRIDGE_OSM_WAY)
    if not riverwood:
        sys.exit("FAIL: Riverwood Road bridge not in graph")
    rmid = point_on(net, riverwood[0])

    debris_e = pick_edge(net, "State Street", cx, cy, 700, 1200, side="east", exclude=route_edges)
    trees_e = pick_edge(net, "Old US Highway 70", cx, cy, 450, 850, side="east", exclude=route_edges)
    flood_e = pick_edge(net, "Whitson", cx, cy, 150, 450, exclude=route_edges | set(bridge))
    # Debris sits on the long State Street edge ~550 m east of the bridge (inside the survey area).
    dl = net.edges[debris_e].line_local
    fr = np.linspace(0, 1, 201)
    dists = [abs(np.hypot(dl.interpolate(f, normalized=True).x - cx, dl.interpolate(f, normalized=True).y - cy) - 600) for f in fr]
    dpt = point_on(net, debris_e, float(fr[int(np.argmin(dists))]))
    tpt, fpt = point_on(net, trees_e, 0.45), point_on(net, flood_e, 0.5)

    def lonlat(p):
        lon, lat = to_geo(p.x, p.y)
        return {"lon": float(lon), "lat": float(lat)}

    hazards = [
        {
            "hazard_id": "GT-WHITSON-BRIDGE",
            "kind": "BRIDGE_DAMAGE",
            "title": "Whitson Avenue Bridge — approaches and piles washed out",
            "edge_ids": [e for b in bridge for e in net.twin_ids(b)],
            "location": {"lon": bmid["lon"], "lat": bmid["lat"]},
            "provenance": ["OFFICIAL_HISTORICAL_RECORD", "SIMULATED_SCENARIO"],
            "historical_basis": ("NCDOT (2025-02-24): Helene flooding washed out the approaches on both sides of the "
                                 "Whitson Avenue Bridge and the piles in the river, 'almost everything but the deck'. "
                                 "Repaired and reopened February 2025."),
            "historical_source": "https://www.ncdot.gov/news/press-releases/Pages/2025/2025-02-24-ncdot-completes-repairs-swannanoa-bridge.aspx",
            "modeled_geometry_note": "Washout depth/extent below is MODELED for the simulation, not a historical measurement.",
            "geometry": {
                "type": "washout",
                "craters": [
                    {**lonlat(bend_a), "radius_m": 11, "depth_m": 3.2},
                    {**lonlat(bend_b), "radius_m": 10, "depth_m": 2.6},
                ],
                "deck": {"line": [list(c) for c in net.edges[bridge[0]].geometry], "width_m": 12, "deck_height_m": 0.0},
            },
            "image_site": "noaa_whitson_bridge",
            "ground_truth_access": "BLOCKED",
        },
        {
            "hazard_id": "GT-DEBRIS-US70",
            "kind": "DEBRIS_OBSTRUCTION",
            "title": "Debris pile across West State Street (US 70)",
            "edge_ids": net.twin_ids(debris_e),
            "location": {"lon": dpt["lon"], "lat": dpt["lat"]},
            "provenance": ["SIMULATED_SCENARIO"],
            "modeled_geometry_note": "Entirely simulated hazard for the exercise; not a historical record.",
            "geometry": {"type": "mounds", "road_heading_deg": dpt["road_heading_deg"],
                         "mounds": [{"dx": 0, "dy": 0, "radius_m": 9, "height_m": 2.8},
                                    {"dx": 6, "dy": -4, "radius_m": 5, "height_m": 1.9},
                                    {"dx": -7, "dy": 3, "radius_m": 6, "height_m": 1.5}]},
            "image_site": None,
            "ground_truth_access": "BLOCKED",
        },
        {
            "hazard_id": "GT-TREES-OLD70",
            "kind": "FALLEN_TREES",
            "title": "Fallen trees across Old US Highway 70",
            "edge_ids": net.twin_ids(trees_e),
            "location": {"lon": tpt["lon"], "lat": tpt["lat"]},
            "provenance": ["SIMULATED_SCENARIO"],
            "modeled_geometry_note": "Entirely simulated hazard for the exercise; not a historical record.",
            "geometry": {"type": "trees", "road_heading_deg": tpt["road_heading_deg"],
                         "trunks": [{"dx": -4, "dy": 0, "len_m": 22, "angle_off_road_deg": 75, "radius_m": 0.45},
                                    {"dx": 5, "dy": 2, "len_m": 18, "angle_off_road_deg": 105, "radius_m": 0.35}]},
            "image_site": None,
            "ground_truth_access": "BLOCKED",
        },
        {
            "hazard_id": "GT-FLOOD-WHITSON-S",
            "kind": "FLOODING",
            "title": "Standing floodwater on Whitson Avenue (south)",
            "edge_ids": net.twin_ids(flood_e),
            "location": {"lon": fpt["lon"], "lat": fpt["lat"]},
            "provenance": ["SIMULATED_SCENARIO"],
            "modeled_geometry_note": "Simulated water level; not a historical flood-depth measurement.",
            "geometry": {"type": "flood", "radius_m": 45, "depth_m": 0.6},
            "image_site": None,
            "ground_truth_access": "PASSABLE_WITH_CAUTION",
        },
    ]

    # Points of interest where drones capture camera observations (besides lidar anomalies).
    pois = [
        {"poi_id": "POI-WHITSON-BRIDGE", "name": "Whitson Avenue Bridge", "lon": bmid["lon"], "lat": bmid["lat"],
         "edge_ids": bridge, "is_bridge": True},
        {"poi_id": "POI-RIVERWOOD-BRIDGE", "name": "Riverwood Road Bridge", "lon": rmid["lon"], "lat": rmid["lat"],
         "edge_ids": [e for b in riverwood for e in net.twin_ids(b)], "is_bridge": True},
    ]

    scenario = {
        "scenario_id": "helene-swannanoa-2024",
        "name": "Hurricane Helene historical replay — Swannanoa, NC",
        "replay_window": "Selected conditions, late September – early October 2024",
        "sim_start": "2024-09-28T09:00:00-04:00",
        "disclaimer": ("Historical disaster replay for training/demonstration. Drones, debris, trees, floodwater and "
                       "staging/destination points are SIMULATED. Only the Whitson Avenue Bridge damage is a documented "
                       "historical event (NCDOT). Not a depiction of current road conditions."),
        "staging": {**rv["staging"], "node": rv["staging_node"], "name": "Staging Area S-1 (simulated)",
                    "provenance": "SIMULATED_SCENARIO"},
        "destination": {**rv["destination"], "node": rv["destination_node"],
                        "name": "Rescue Site R-7: isolated residents reported (simulated)", "provenance": "SIMULATED_SCENARIO"},
        "hazards": hazards,
        "pois": pois,
    }
    (SCENARIOS / "helene_swannanoa.json").write_text(json.dumps(scenario, indent=2))
    sites = [
        {"id": "riverwood_bridge", "lon": rmid["lon"], "lat": rmid["lat"], "half_m": 80},
        {"id": "whitson_bridge_close", "lon": bmid["lon"], "lat": bmid["lat"], "half_m": 45},
        {"id": "riverwood_bridge_close", "lon": rmid["lon"], "lat": rmid["lat"], "half_m": 40},
    ]
    (SCENARIOS / "evidence_sites.json").write_text(json.dumps(sites, indent=2))
    for h in hazards:
        print(h["hazard_id"], h["edge_ids"][:2], h["location"])
    print("POIs:", [(p["poi_id"], round(p["lon"], 5), round(p["lat"], 5)) for p in pois])


if __name__ == "__main__":
    main()
