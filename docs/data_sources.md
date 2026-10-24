# Data sources

Generated from `data/manifest.json` by `scripts/build_manifest.py`.

## OpenStreetMap drivable road graph (OSMnx)

- **publisher**: OpenStreetMap contributors
- **source url**: https://www.openstreetmap.org/ (Overpass API via OSMnx 2.0)
- **acquisition date**: 2026-10-24
- **spatial coverage**: bbox [-82.43596259743151, 35.570227501148416, -82.35980177470528, 35.63422080940429]
- **crs**: EPSG:4326 (stored); EPSG:32617 for calculations
- **license**: ODbL 1.0
- **local file**: data/road_graph/swannanoa_drive.graphml
- **classification**: CURRENT_BASEMAP
- **limitations**: Present-day map, not the Sept 2024 network state. Turn restrictions not modelled. Speeds are OSMnx imputations.

## OSM building footprints

- **publisher**: OpenStreetMap contributors
- **source url**: https://www.openstreetmap.org/
- **acquisition date**: 2026-10-24
- **spatial coverage**: survey area + 600 m
- **crs**: EPSG:4326
- **license**: ODbL 1.0
- **local file**: data/geography/buildings.geojson
- **classification**: CURRENT_BASEMAP
- **limitations**: Heights from OSM height/levels where tagged; otherwise a 6 m estimate (flagged).

## OSM waterways (Swannanoa River, streams)

- **publisher**: OpenStreetMap contributors
- **source url**: https://www.openstreetmap.org/
- **acquisition date**: 2026-10-24
- **spatial coverage**: routing area
- **crs**: EPSG:4326
- **license**: ODbL 1.0
- **local file**: data/geography/water.geojson
- **classification**: CURRENT_BASEMAP
- **limitations**: Centerlines; river width approximated (14 m) in the simulation.

## Whitson Avenue Bridge location (OSM way 388972121, bridge=yes, SR 2727)

- **publisher**: OpenStreetMap contributors
- **source url**: https://www.openstreetmap.org/way/388972121
- **acquisition date**: 2026-10-24
- **spatial coverage**: centroid {'lon': -82.39789733872244, 'lat': 35.60222991233717}
- **crs**: EPSG:4326
- **license**: ODbL 1.0
- **local file**: data/geography/study_area.json
- **classification**: CURRENT_BASEMAP
- **limitations**: Taken programmatically from the graph; never hand-entered.

## USGS 3DEP elevation — fine (~5 m)

- **publisher**: U.S. Geological Survey
- **source url**: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage
- **acquisition date**: 2026-10-24
- **spatial coverage**: {'west': -82.43877596192776, 'south': 35.561351289131856, 'east': -82.35701871551713, 'north': 35.64310853554249}
- **crs**: EPSG:4326, vertical NAVD88 (metres)
- **license**: Public domain (USGS)
- **local file**: data/terrain/dem_fine.u16 (+ .json header)
- **classification**: CURRENT_BASEMAP
- **limitations**: 3DEP lidar for Buncombe County predates Hurricane Helene (pre-storm terrain). Bare-earth model: bridge decks are modelled separately.

## USGS 3DEP elevation — context (~30 m)

- **publisher**: U.S. Geological Survey
- **source url**: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage
- **acquisition date**: 2026-10-24
- **spatial coverage**: {'west': -82.56362148685213, 'south': 35.43650576420749, 'east': -82.23217319059276, 'north': 35.767954060466856}
- **crs**: EPSG:4326, vertical NAVD88 (metres)
- **license**: Public domain (USGS)
- **local file**: data/terrain/dem_coarse.u16 (+ .json header)
- **classification**: CURRENT_BASEMAP
- **limitations**: Context only (surrounding valleys). Heights used directly as scene heights (no geoid correction).

## NOAA NGS Hurricane Helene aerial imagery, flight 20241005a_RGB

- **publisher**: NOAA National Geodetic Survey, Remote Sensing Division
- **source url**: https://storms.ngs.noaa.gov/storms/helene/index.html (metadata: https://www.fisheries.noaa.gov/inport/item/73570)
- **acquisition date**: 2024-10-05
- **spatial coverage**: flight envelope [-83.4876, 35.32490003, -81.62489943, 36.2376]; probed coverage at bridge [{'layer': '20241005a_RGB', 'bridge_coverage': 1.0}, {'layer': '20241006a_RGB', 'bridge_coverage': 0.0}, {'layer': '20241007a_RGB', 'bridge_coverage': 0.0}]
- **crs**: Web Mercator XYZ tiles (EPSG:3857), crops georeferenced in EPSG:4326
- **license**: Public domain (U.S. Government work); NOAA disclaims accuracy/completeness
- **local file**: data/imagery/noaa_whitson_bridge.jpg, data/imagery/noaa_riverwood_bridge.jpg, data/imagery/noaa_whitson_bridge_close.jpg, data/imagery/noaa_riverwood_bridge_close.jpg
- **classification**: PUBLIC_HISTORICAL_IMAGERY
- **limitations**: Real post-storm imagery acquired 2024-10-05, i.e. ~8 days after the storm and after some clean-up; NOT captured by the simulated drones. ~15-30 cm GSD.

## NCDOT press release: Whitson Avenue Bridge repairs (2025-02-24)

- **publisher**: North Carolina Department of Transportation
- **source url**: https://www.ncdot.gov/news/press-releases/Pages/2025/2025-02-24-ncdot-completes-repairs-swannanoa-bridge.aspx
- **acquisition date**: 2025-02-24
- **spatial coverage**: Whitson Avenue Bridge, Swannanoa
- **crs**: n/a
- **license**: Public government information
- **local file**: data/scenarios/helene_swannanoa.json (historical_basis)
- **classification**: OFFICIAL_HISTORICAL_RECORD
- **limitations**: Describes damage (approaches + piles washed out) and Feb 2025 reopening; no geometry or depths.

## Buncombe County After-Action Report announcement (Tropical Storm Helene)

- **publisher**: Buncombe County Government
- **source url**: https://www.buncombenc.gov/m/newsflash/Home/Detail/389
- **acquisition date**: 2025-09-12
- **spatial coverage**: Buncombe County
- **crs**: n/a
- **license**: Public government information
- **local file**: (cited in UI/briefing context)
- **classification**: OFFICIAL_HISTORICAL_RECORD
- **limitations**: 43 county fatalities cited; RESCUEGRID makes no claim attributing deaths to response delays.

## Scenario ground truth (washout geometry, debris, fallen trees, floodwater, staging S-1, rescue site R-7)

- **publisher**: RESCUEGRID 3D team
- **source url**: scripts/build_scenario.py
- **acquisition date**: generated
- **spatial coverage**: survey area
- **crs**: EPSG:4326 / EPSG:32617
- **license**: Project
- **local file**: data/scenarios/helene_swannanoa.json
- **classification**: SIMULATED_SCENARIO
- **limitations**: Modeled values; not historical measurements. Hazards anchored to real OSM edges.

## Esri World Imagery basemap (frontend only)

- **publisher**: Esri, Maxar, Earthstar Geographics et al.
- **source url**: https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer
- **acquisition date**: current
- **spatial coverage**: global
- **crs**: EPSG:3857
- **license**: Esri terms of use (attribution)
- **local file**: (streamed)
- **classification**: CURRENT_BASEMAP
- **limitations**: Present-day imagery; shown under the NOAA 2024-10-05 historical overlay; labelled 'current, not historical'.
