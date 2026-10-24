# RESCUEGRID 3D — Architecture

RESCUEGRID 3D is built as a live disaster-response system: drone data streams in, Bedrock assesses
it, a commander decides, and the route updates. The showcase mission runs it on Hurricane Helene in
Swannanoa, NC, with a simulated drone fleet supplying the telemetry, lidar and camera frames. A real
fleet would replace the simulator through an adapter; everything downstream stays the same.

```mermaid
flowchart LR
  subgraph Browser["Browser (React + TypeScript + Tailwind)"]
    UI[Command center panels<br/>drones · observations · AI inspector · incidents · route & briefing]
    CZ[CesiumJS viewer<br/>USGS 3DEP terrain (CustomHeightmapTerrainProvider)<br/>NOAA 2024-10-05 overlay · OSM roads/buildings/river<br/>drones · scan cones · lidar points · recon tiles · routes]
  end
  subgraph EC2["Amazon EC2 (t3.large, AL2023) · nginx → uvicorn"]
    API[FastAPI REST + WebSocket /ws/mission<br/>sequenced events]
    ENG[Mission engine (deterministic tick)<br/>coordinator · 3 drones · flight state machine]
    LID[Synthetic LiDAR<br/>ray-march vs DEM + structures + modeled hazards]
    CHG[Change detection<br/>measured vs pre-storm baseline]
    REC[Reconstruction<br/>4 m cells → 128 m mesh tiles]
    CAM[Camera observations<br/>NOAA crop or labeled synthetic render]
    MATCH[GIS matcher<br/>observation → OSM edges]
    AI[Bedrock service<br/>hazard analysis · briefing]
    RT[NetworkX router<br/>travel time × status factor]
    DB[(SQLite<br/>events · observations · incidents<br/>decisions · invocations · routes)]
  end
  BR[[Amazon Bedrock Runtime<br/>Converse API · Claude Sonnet 4.5<br/>us. cross-region inference profile]]
  S3[(Amazon S3<br/>observations · scan chunks · briefings · releases)]
  CW[(CloudWatch Logs<br/>/rescuegrid3d/app)]
  IAM{{IAM instance role<br/>least privilege}}

  UI <-->|REST / WebSocket| API
  CZ <-->|geo assets, tiles| API
  ENG --> LID --> CHG --> CAM
  LID --> REC
  CAM --> MATCH
  CAM -->|image bytes| AI
  AI ==>|"converse(image bytes + context, forced JSON-schema tool)"| BR
  BR ==>|tool_use JSON| AI
  AI -->|Pydantic-validated HazardAssessment| API
  CAM --> S3
  AI --> S3
  API --> RT
  API --> DB
  EC2 --> CW
  IAM -.-> EC2
```

## The real Bedrock request path (hazard analysis)

1. A drone reaches an inspection waypoint, or lidar change detection flags a road anomaly
   (`simulation/engine.py::_detect_changes`) → `_capture()` builds an **Observation** whose pose,
   footprint and target come from telemetry; the image is a georeferenced NOAA crop
   (`PUBLIC_HISTORICAL_IMAGERY`) or a synthetic render (`SIMULATED_SENSOR`).
2. GIS matching (`RoadNetwork.edges_near`) attaches OSM edge ids — **never** the model.
3. A worker thread uploads the image to `s3://<bucket>/missions/<mission>/observations/<id>.jpg`.
4. `ai/hazard_analyzer.py` calls `bedrock-runtime.converse` with the **image bytes**, source type,
   observation context and a forced tool `report_hazard_assessment` (JSON schema with enums).
   Timeouts (90 s read) and retry with exponential backoff for throttling / 5xx (`ai/bedrock.py`).
5. Output is treated as untrusted: Pydantic `HazardAssessment` validation; failures are stored as
   `FAILED` / `VALIDATION_FAILED` invocations, emit `system.degraded`, and create **no incident**.
6. A valid result creates an **Incident** (`PENDING_REVIEW`); `LIKELY_BLOCKED` sets the matched edges
   to `SUSPECTED_BLOCKED` (router penalises them, route flagged *at risk*), but does **not** reroute.
7. The commander reviews each evidence item and confirms / verifies passable / rejects / requests a
   drone re-inspection. Only these human decisions set `CONFIRMED_BLOCKED` / `VERIFIED_PASSABLE`,
   trigger route recalculation, and are written to the append-only decision log.
8. After approval, `ai/briefing.py` sends **facts from the database** (no images) to Bedrock and asks
   for a summary only — it must not compute distances, times or routes.

## Module map

| Concern | File |
|---|---|
| Config / paths | `backend/app/config.py` |
| Data model + provenance enums | `backend/app/models/schemas.py` |
| WGS84 ↔ UTM 17N | `backend/app/geospatial/crs.py` |
| DEM sampling | `backend/app/geospatial/terrain.py` |
| Ground-truth world (hidden) | `backend/app/simulation/world.py` |
| Drones / coordinator / engine | `backend/app/simulation/{drones,coordinator,engine}.py` |
| Synthetic LiDAR | `backend/app/sensors/lidar.py` |
| Camera / NOAA catalog / renders | `backend/app/sensors/camera.py` |
| Reconstruction + coverage | `backend/app/reconstruction/tiles.py` |
| Road graph + planner | `backend/app/routing/{graph,planner}.py` |
| Bedrock client / hazard / briefing | `backend/app/ai/{bedrock,hazard_analyzer,briefing}.py` |
| SQLite / S3 | `backend/app/storage/{db,s3}.py` |
| Event bus | `backend/app/services/events.py` |
| REST + WS | `backend/app/api/routes.py` |
| 3D scene | `frontend/src/cesium/*` |
| State (snapshot + events) | `frontend/src/store/mission.ts`, `frontend/src/services/stream.ts` |

## Key design decisions

- **CesiumJS only, no ion token.** Terrain comes from our own USGS grid through
  `CustomHeightmapTerrainProvider`; roads/routes are draped by sampling the same grid in JS, so
  geometry is consistent between backend physics and the 3D view.
- **One local metric CRS (EPSG:32617)** for all geometry math; WGS84 for APIs and rendering.
- **Deterministic simulation**: seeded RNG per (seed, drone, scan); AI latency does not affect
  telemetry. `tests/test_simulation.py::test_deterministic_replay` hashes telemetry across runs.
- **Change detection, not oracle classes**: incidents are triggered by measured-vs-baseline height
  deviation on road corridors; point class colours are a labelled simulated on-board classifier.
- **Bridges are never auto-cleared by lidar** — structural passability requires imagery + a human.
- **Information-gain retasking**: unverified edges on the current route are scored by travel-time share
  (×3 for bridges) over distance cost with sector affinity; the scoring table is shown in the UI.
