"""Step 6 of data preparation: data/manifest.json + docs/data_sources.md from the files on disk."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"


def jl(p):
    return json.loads(p.read_text()) if p.exists() else {}


def main():
    area = jl(D / "geography" / "study_area.json")
    fine = jl(D / "terrain" / "dem_fine.json")
    coarse = jl(D / "terrain" / "dem_coarse.json")
    cov = jl(D / "imagery" / "noaa_coverage.json")
    rb = area.get("routing_bbox_wgs84")
    items = [
        {"dataset": "OpenStreetMap drivable road graph (OSMnx)", "publisher": "OpenStreetMap contributors",
         "source_url": "https://www.openstreetmap.org/ (Overpass API via OSMnx 2.0)", "acquisition_date": area.get("created_at", "")[:10],
         "spatial_coverage": f"bbox {rb}", "crs": "EPSG:4326 (stored); EPSG:32617 for calculations", "license": "ODbL 1.0",
         "local_file": "data/road_graph/swannanoa_drive.graphml", "classification": "CURRENT_BASEMAP",
         "limitations": "Present-day map, not the Sept 2024 network state. Turn restrictions not modelled. Speeds are OSMnx imputations."},
        {"dataset": "OSM building footprints", "publisher": "OpenStreetMap contributors", "source_url": "https://www.openstreetmap.org/",
         "acquisition_date": area.get("created_at", "")[:10], "spatial_coverage": "survey area + 600 m", "crs": "EPSG:4326", "license": "ODbL 1.0",
         "local_file": "data/geography/buildings.geojson", "classification": "CURRENT_BASEMAP",
         "limitations": "Heights from OSM height/levels where tagged; otherwise a 6 m estimate (flagged)."},
        {"dataset": "OSM waterways (Swannanoa River, streams)", "publisher": "OpenStreetMap contributors", "source_url": "https://www.openstreetmap.org/",
         "acquisition_date": area.get("created_at", "")[:10], "spatial_coverage": "routing area", "crs": "EPSG:4326", "license": "ODbL 1.0",
         "local_file": "data/geography/water.geojson", "classification": "CURRENT_BASEMAP", "limitations": "Centerlines; river width approximated (14 m) in the simulation."},
        {"dataset": "Whitson Avenue Bridge location (OSM way 388972121, bridge=yes, SR 2727)", "publisher": "OpenStreetMap contributors",
         "source_url": "https://www.openstreetmap.org/way/388972121", "acquisition_date": area.get("created_at", "")[:10],
         "spatial_coverage": f"centroid {area.get('bridge', {}).get('centroid')}", "crs": "EPSG:4326", "license": "ODbL 1.0",
         "local_file": "data/geography/study_area.json", "classification": "CURRENT_BASEMAP", "limitations": "Taken programmatically from the graph; never hand-entered."},
        {"dataset": "USGS 3DEP elevation — fine (~5 m)", "publisher": "U.S. Geological Survey", "source_url": fine.get("source_url"),
         "acquisition_date": fine.get("retrieved_at", "")[:10], "spatial_coverage": fine.get("bounds"), "crs": f"{fine.get('crs')}, vertical {fine.get('vertical_datum')}",
         "license": "Public domain (USGS)", "local_file": "data/terrain/dem_fine.u16 (+ .json header)", "classification": "CURRENT_BASEMAP",
         "limitations": fine.get("temporal_note", "") + " Bare-earth model: bridge decks are modelled separately."},
        {"dataset": "USGS 3DEP elevation — context (~30 m)", "publisher": "U.S. Geological Survey", "source_url": coarse.get("source_url"),
         "acquisition_date": coarse.get("retrieved_at", "")[:10], "spatial_coverage": coarse.get("bounds"), "crs": f"{coarse.get('crs')}, vertical {coarse.get('vertical_datum')}",
         "license": "Public domain (USGS)", "local_file": "data/terrain/dem_coarse.u16 (+ .json header)", "classification": "CURRENT_BASEMAP",
         "limitations": "Context only (surrounding valleys). Heights used directly as scene heights (no geoid correction)."},
        {"dataset": f"NOAA NGS Hurricane Helene aerial imagery, flight {cov.get('selected_layer')}", "publisher": "NOAA National Geodetic Survey, Remote Sensing Division",
         "source_url": "https://storms.ngs.noaa.gov/storms/helene/index.html (metadata: https://www.fisheries.noaa.gov/inport/item/73570)",
         "acquisition_date": cov.get("acquisition_date"), "spatial_coverage": f"flight envelope {cov.get('layer_bounds')}; probed coverage at bridge {cov.get('probe')}",
         "crs": "Web Mercator XYZ tiles (EPSG:3857), crops georeferenced in EPSG:4326", "license": "Public domain (U.S. Government work); NOAA disclaims accuracy/completeness",
         "local_file": ", ".join(v for v in (cov.get("crops") or {}).values() if v), "classification": "PUBLIC_HISTORICAL_IMAGERY",
         "limitations": "Real post-storm imagery acquired 2024-10-05, i.e. ~8 days after the storm and after some clean-up; NOT captured by the simulated drones. ~15-30 cm GSD."},
        {"dataset": "NCDOT press release: Whitson Avenue Bridge repairs (2025-02-24)", "publisher": "North Carolina Department of Transportation",
         "source_url": "https://www.ncdot.gov/news/press-releases/Pages/2025/2025-02-24-ncdot-completes-repairs-swannanoa-bridge.aspx",
         "acquisition_date": "2025-02-24", "spatial_coverage": "Whitson Avenue Bridge, Swannanoa", "crs": "n/a", "license": "Public government information",
         "local_file": "data/scenarios/helene_swannanoa.json (historical_basis)", "classification": "OFFICIAL_HISTORICAL_RECORD",
         "limitations": "Describes damage (approaches + piles washed out) and Feb 2025 reopening; no geometry or depths."},
        {"dataset": "Buncombe County After-Action Report announcement (Tropical Storm Helene)", "publisher": "Buncombe County Government",
         "source_url": "https://www.buncombenc.gov/m/newsflash/Home/Detail/389", "acquisition_date": "2025-09-12", "spatial_coverage": "Buncombe County",
         "crs": "n/a", "license": "Public government information", "local_file": "(cited in UI/briefing context)", "classification": "OFFICIAL_HISTORICAL_RECORD",
         "limitations": "43 county fatalities cited; RESCUEGRID makes no claim attributing deaths to response delays."},
        {"dataset": "Scenario ground truth (washout geometry, debris, fallen trees, floodwater, staging S-1, rescue site R-7)", "publisher": "RESCUEGRID 3D team",
         "source_url": "scripts/build_scenario.py", "acquisition_date": "generated", "spatial_coverage": "survey area", "crs": "EPSG:4326 / EPSG:32617",
         "license": "Project", "local_file": "data/scenarios/helene_swannanoa.json", "classification": "SIMULATED_SCENARIO",
         "limitations": "Modeled values; not historical measurements. Hazards anchored to real OSM edges."},
        {"dataset": "Esri World Imagery basemap (frontend only)", "publisher": "Esri, Maxar, Earthstar Geographics et al.",
         "source_url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer", "acquisition_date": "current",
         "spatial_coverage": "global", "crs": "EPSG:3857", "license": "Esri terms of use (attribution)", "local_file": "(streamed)", "classification": "CURRENT_BASEMAP",
         "limitations": "Present-day imagery; shown under the NOAA 2024-10-05 historical overlay; labelled 'current, not historical'."},
    ]
    (D / "manifest.json").write_text(json.dumps({"datasets": items}, indent=2, default=str))
    md = ["# Data sources\n", "Generated from `data/manifest.json` by `scripts/build_manifest.py`.\n"]
    for it in items:
        md.append(f"## {it['dataset']}\n")
        for k in ("publisher", "source_url", "acquisition_date", "spatial_coverage", "crs", "license", "local_file", "classification", "limitations"):
            md.append(f"- **{k.replace('_', ' ')}**: {it[k]}")
        md.append("")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "data_sources.md").write_text("\n".join(md), encoding="utf-8")
    print(f"manifest: {len(items)} datasets")


if __name__ == "__main__":
    main()
