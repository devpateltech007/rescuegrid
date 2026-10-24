"""Step 1 + 3 of data preparation: real pilot geography from OpenStreetMap.

- Locates the Whitson Avenue bridge from OSM (way 388972121, bridge=yes). Fails loudly if absent.
- Defines a 2x2 km survey area and a wider ~7x7 km routing area centred on the bridge.
- Downloads the drivable road graph, river/stream geometry and building footprints.
- Persists everything locally so the demo never depends on live Overpass.

Run: python scripts/bootstrap_geodata.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import geopandas as gpd  # noqa: E402
import osmnx as ox  # noqa: E402
from shapely.geometry import box, mapping  # noqa: E402

from app.config import GEO, ROADS, WHITSON_BRIDGE_OSM_WAY  # noqa: E402
from app.geospatial.crs import to_geo, to_local  # noqa: E402

SURVEY_HALF_M = 1000
ROUTING_HALF_M = 3500

ox.settings.use_cache = True
ox.settings.cache_folder = str(ROOT / "data" / "cache" / "osmnx")
ox.settings.log_console = False
ox.settings.requests_timeout = 180
ox.settings.overpass_rate_limit = False
ox.settings.http_user_agent = "RESCUEGRID3D-hackathon/0.1 (SpartHill Hacks 2026 research demo)"
ox.settings.overpass_url = "https://overpass-api.de/api"


def bbox_wgs(cx: float, cy: float, half: float) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a square of half-size `half` m around UTM point."""
    w, s = to_geo(cx - half, cy - half)
    e, n = to_geo(cx + half, cy + half)
    return (w, s, e, n)


def main() -> None:
    GEO.mkdir(parents=True, exist_ok=True)
    ROADS.mkdir(parents=True, exist_ok=True)

    # 1+2. Drivable graph; bridge geometry is taken from the graph edge whose OSM way id
    # is the Whitson Ave bridge (never typed in by hand). The routing area is centred on
    # an approximate seed point and recentred on the true bridge centroid afterwards.
    print("[1/5] downloading drivable road graph ...")
    seed_x, seed_y = to_local(-82.3979, 35.6023)  # seed only; replaced by OSM centroid below
    routing_seed = bbox_wgs(seed_x, seed_y, ROUTING_HALF_M + 300)
    G = ox.graph_from_bbox(routing_seed, network_type="drive", simplify=True, retain_all=False, truncate_by_edge=True)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    ox.save_graphml(G, ROADS / "swannanoa_drive.graphml")
    print(f"      nodes={G.number_of_nodes()} edges={G.number_of_edges()}")

    print("[2/5] locating Whitson Avenue bridge edge in OSM graph ...")
    bridge_edges = []
    for u, v, k, d in G.edges(keys=True, data=True):
        osmid = d.get("osmid")
        ids = osmid if isinstance(osmid, list) else [osmid]
        if WHITSON_BRIDGE_OSM_WAY in [int(i) for i in ids]:
            bridge_edges.append((u, v, k, d))
    if not bridge_edges:
        sys.exit("FAIL: Whitson Avenue bridge way not found in OSM drive graph")
    from shapely.geometry import LineString
    d0 = bridge_edges[0][3]
    bgeom = d0.get("geometry") or LineString([(G.nodes[bridge_edges[0][0]]["x"], G.nodes[bridge_edges[0][0]]["y"]),
                                              (G.nodes[bridge_edges[0][1]]["x"], G.nodes[bridge_edges[0][1]]["y"])])
    c = bgeom.centroid
    cx, cy = to_local(c.x, c.y)
    print(f"      bridge way {WHITSON_BRIDGE_OSM_WAY}: {len(bridge_edges)} directed edges, centroid lon={c.x:.6f} lat={c.y:.6f}")
    survey = bbox_wgs(cx, cy, SURVEY_HALF_M)
    routing = bbox_wgs(cx, cy, ROUTING_HALF_M)

    # 3. Water features.
    print("[3/5] downloading river / stream geometry ...")
    water = ox.features_from_bbox(routing, {"waterway": ["river", "stream", "canal"], "natural": ["water"]})
    water = water.reset_index()[["element", "id", "geometry"] + [c for c in ("name", "waterway", "natural") if c in water.columns]]
    water = water[water.geometry.notna()]
    water.to_file(GEO / "water.geojson", driver="GeoJSON")
    print(f"      water features={len(water)}")

    # 4. Buildings in survey area (plus a margin).
    print("[4/5] downloading building footprints ...")
    bbig = bbox_wgs(cx, cy, SURVEY_HALF_M + 600)
    bld = ox.features_from_bbox(bbig, {"building": True}).reset_index()
    bld = bld[bld.geometry.type.isin(["Polygon", "MultiPolygon"])]
    keep = [c for c in ("element", "id", "building", "height", "building:levels", "name") if c in bld.columns]
    bld = bld[keep + ["geometry"]]
    bld.to_file(GEO / "buildings.geojson", driver="GeoJSON")
    print(f"      buildings={len(bld)}")

    # 5. Study-area description.
    print("[5/5] writing study_area.json ...")
    area = {
        "name": "Swannanoa, Buncombe County, NC — Whitson Avenue Bridge corridor",
        "bridge": {
            "osm_way_id": WHITSON_BRIDGE_OSM_WAY,
            "name": "Whitson Avenue Bridge (SR 2727)",
            "centroid": {"lon": c.x, "lat": c.y},
            "geometry": mapping(bgeom),
            "provenance": "CURRENT_BASEMAP",
        },
        "local_crs": "EPSG:32617",
        "center_local": {"x": cx, "y": cy},
        "survey_bbox_wgs84": survey,
        "survey_polygon": mapping(box(*survey)),
        "survey_half_m": SURVEY_HALF_M,
        "routing_bbox_wgs84": routing,
        "routing_half_m": ROUTING_HALF_M,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (GEO / "study_area.json").write_text(json.dumps(area, indent=2))
    print("done.")


if __name__ == "__main__":
    main()
