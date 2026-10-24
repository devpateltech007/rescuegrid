# Evaluation: measured results

These numbers come from one headless run of `scripts/e2e_demo.py` (mission M-AC617C). It used live
Amazon Bedrock and S3 in us-east-1 and the real OSM graph and USGS DEM. The raw output is in
`docs/evaluation_run.json`.

**Two kinds of numbers appear below:**
- *Simulated* values are outputs of the exercise: coverage, distances, travel estimates.
- *Measured* values are software execution times: Bedrock latency, recalculation time, tick time.

## Workflow (definition of done)

| Step | Result |
|---|---|
| Launch 3 drones over real Swannanoa terrain | ✅ Alpha (US 70), Bravo (bridge and river), Charlie (Old US 70) |
| Growing 3D scan | ✅ 1,059 scans and 715,884 lidar points; reconstruction tiles grow with coverage |
| Image analyzed by Bedrock | ✅ The real NOAA 2024-10-05 frame of the Whitson Ave bridge went to `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. Result: LIKELY_BLOCKED, 11.4 s, 2,100 input / 463 output tokens |
| Incident created | ✅ INC-4A348 (PENDING_REVIEW); edges set to SUSPECTED_BLOCKED, not rerouted |
| Human verification | ✅ CONFIRM_BLOCKED by a named operator, recorded in the decision log |
| Real graph reroute | ✅ 1,066.2 m / 62.3 s → **2,595.1 m / 155.6 s** (+1,528.9 m, +93.3 s simulated), via Riverwood Road. The new route uses no bridge edges |
| Information-gain retask | ✅ The coordinator sent Charlie to the unverified Riverwood Road bridge |
| Alternate crossing assessed | ✅ The NOAA frame of the Riverwood bridge went to Bedrock: LIKELY_PASSABLE (vehicles crossing). The operator then marked it VERIFIED_PASSABLE; unverified edges on the route went from 16 to 14 |
| Route approval + briefing | ✅ Approved; Bedrock briefing SUCCESS, citing incident and observation IDs |

## Metrics

| Metric | Value | Kind |
|---|---|---|
| Survey area | 4.00 km² (2 × 2 km) | simulated |
| Area observed | 0.31 km² (7.75 %) at t = 366 s | simulated |
| Road segments in survey / assessed | 372 / 66 | simulated |
| Lidar points / scans | 715,884 / 1,059 | simulated |
| Image observations / incidents | 4 / 4 | simulated |
| Confirmed hazards | 1 | simulated + human |
| Bedrock calls completed / failed | 5 / 0 (4 hazard + 1 briefing) | **measured** |
| Bedrock latency, mean | 10.5 s | **measured** |
| Route recalculation, mean | 26.9 ms | **measured** |
| Simulation tick (3 drones, lidar + reconstruction), mean | ~197 ms wall | **measured** |
| Original → revised route distance | 1,066.2 m → 2,595.1 m | simulated (graph) |
| Original → revised travel estimate | 62.3 s → 155.6 s | simulated (OSM speeds) |
| Unverified edges on the final route | 14 | simulated |

## Tests

`scripts\run_tests.cmd` runs 26 tests and makes no AWS calls. They cover:

- Real graph and bridge
- Reroute avoids the bridge
- One-way edges
- Explicit NO_ROUTE
- Unknown-edge counting
- Deterministic replay hash
- Pause/resume
- Reset clears results
- Lidar matches geometry
- Bridge damage is visible to change detection
- A failed Bedrock call creates no incident
- Verification reroutes and records the decision
- Retask targets a bridge
- Schema rejects invalid output and has no geo fields
- Operator validation

`scripts\smoke_api.py` passes against the local server, including checks that hidden hazards stay
hidden, operator injection is rejected, and path traversal is blocked.

## Observations on model behavior

- On the Whitson Ave bridge frame, Claude classified the dominant hazard as **FLOODING**, not
  BRIDGE_DAMAGE, and flagged that it couldn't assess the piers from a nadir view. The pipeline
  doesn't rewrite model output. The commander saw that assessment, the NOAA frame, and the NCDOT
  record, and confirmed the closure.
- On the synthetic fallen-tree render, the model correctly reported FALLEN_TREES / LIKELY_BLOCKED.
- Nothing here claims lives saved or response-time improvement.
