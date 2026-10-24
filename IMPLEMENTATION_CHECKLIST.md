# Implementation checklist

Each item lists where it lives and how to verify it. ✅ = done and verified in the integrated app.

## Foundation
- ✅ AWS gate: STS identity, Bedrock model discovery, real image Converse call. `scripts/verify_bedrock.py` writes `data/aws_config.json` (Claude Sonnet 4.5 via `us.` inference profile, first call 4.3 s)
- ✅ S3 bucket with public-access block and SSE-S3 (`rescuegrid3d-663748689981-us-east-1`)
- ✅ signal-zero has no license, so ideas only and no code copied. `docs/reuse_notes.md`
- ✅ Whitson Ave bridge taken from OSM (way 388972121, `bridge=yes`). `scripts/bootstrap_geodata.py`, `data/geography/study_area.json`
- ✅ Real drive graph (706 nodes / 1,584 edges), river, 3,165 buildings, persisted locally
- ✅ USGS 3DEP DEM: 5 m fine grid and 30 m context grid. `scripts/prepare_terrain.py`
- ✅ Reroute scenario proven on the graph: 1,066 m → 2,595 m after blocking the bridge edges. `scripts/validate_route_scenario.py`, `data/scenarios/route_validation.png`
- ✅ NOAA coverage probed with real tiles (flight 20241005a has 100% coverage; 20241006a and 20241007a have 0%). Georeferenced crops cached. `scripts/fetch_noaa_imagery.py`
- ✅ Data manifest. `scripts/build_manifest.py` writes `data/manifest.json` and `docs/data_sources.md`

## 3D digital twin (CesiumJS, no ion token)
- ✅ Real terrain via `CustomHeightmapTerrainProvider` from the USGS grids. `frontend/src/cesium/terrain.ts`
- ✅ Esri basemap (labeled current) plus a NOAA 2024-10-05 overlay through a same-origin tile proxy. `scene.ts`, `GET /api/tiles/noaa/...`
- ✅ Roads draped on the DEM and colored by access status. Raised bridge decks, river, extruded buildings, staging and rescue markers. `staticLayers.ts`, `drape.ts`
- ✅ Hidden ground truth (washout craters, debris mounds, trunks, flood plane) kept server-side only. `simulation/world.py`. The smoke test checks it isn't exposed
- ✅ Synthetic lidar ray-march with seeded noise; points carry drone, scan id, time, source and class. `sensors/lidar.py`
- ✅ Progressive reconstruction tiles (4 m cells) with change cells in red. `reconstruction/tiles.py`, `dynamicLayers.ts::upsertTile`
- ✅ Layer toggles: Base Terrain, Drone Scan, Reconstructed Surface, Hazard Intelligence (plus NOAA, buildings, roads, sectors)
- ✅ Scan playback ("Replay scan growth", Director panel)
- ✅ Camera: orbit/tilt, fly-to drone, follow drone, the three scripted shots. `cesium/camera.ts`

## Swarm
- ✅ 3 drones with distinct corridor sectors built from OSM/river geometry. `simulation/coordinator.py`
- ✅ Flight state machine, battery in Wh, full telemetry contract, 1x/4x/10x speed, pause/resume/step/reset. `simulation/drones.py`, `engine.py`
- ✅ Deterministic replay (telemetry hash test)
- ✅ Information-gain retasking: bridges on the route first, with sector affinity and the scoring table shown in the UI
- ✅ Manual retask (drone card) and drone re-inspection on request

## Bedrock pipeline
- ✅ Real image bytes sent through Converse with a forced JSON-schema tool. `ai/hazard_analyzer.py`
- ✅ Pydantic validation. Failures are stored, emit `system.degraded`, and create no incident
- ✅ Coordinates and road ids come from telemetry and GIS matching, never from the model (schema test)
- ✅ S3 upload of evidence. Invocation log with model, latency, tokens, request id and status (AI inspect tab)
- ✅ Evidence-grounded briefing from database facts. `ai/briefing.py`
- ✅ Degraded mode (`RESCUEGRID_BEDROCK=0`) keeps the sim, 3D and routing usable. The offline fixture is opt-in and labeled

## Incidents, routing, decisions
- ✅ Statuses UNKNOWN / OBSERVED_PASSABLE / SUSPECTED / CONFIRMED / VERIFIED. Lidar never clears bridges
- ✅ Router: travel-time weights × status factor, confirmed edges excluded, one-way respected, alternatives, explicit NO_ROUTE
- ✅ Verify, reject and re-inspect each require a validated operator; evidence must be ticked in the UI; append-only decision log
- ✅ Route approval refuses superseded routes and routes crossing confirmed or suspected blocks

## Ops
- ✅ Tests: 26 passing (`scripts/run_tests.cmd`)
- ✅ Headless live e2e (`scripts/e2e_demo.py`), browser capture (`scripts/capture_story.py`)
- ✅ Render-error recovery; WebSocket reconnect rebuilds from snapshot
- ✅ EC2 deployment script with least-privilege role. `scripts/deploy/deploy.py`. Status is recorded in `data/deployment.json`

## Out of scope / not done
- Turn restrictions (OSMnx limitation)
- Authentication and multi-user sessions
- Full SfM photogrammetry
- PDF export (dropped by request)
