# Kiro workflow record

RESCUEGRID 3D was planned and built with Kiro (agentic IDE) in a single autonomous session.

1. **Requirements clarification** — Kiro asked about 3D stack, AWS access and team size before planning;
   answers: CesiumJS allowed, temporary STS credentials (Workshop Studio role), solo build, zero extra setup.
2. **Plan** — a 16-task implementation plan (architecture diagram, data flow, per-task tests/demos),
   revised after feedback: PDF export dropped; verification reframed as *remote, drone-evidence-only*
   (no ground teams), with "request inspection" = drone re-pass.
3. **Gate-first execution** — before any app code: STS identity, Bedrock model discovery and a real
   image `converse` call (`scripts/verify_bedrock.py`), S3 bucket creation with public-access block + SSE.
4. **Data before UI** — OSM bridge/graph, USGS 3DEP DEM, NOAA coverage probing (found the bug where
   envelope ≠ coverage; picked flight 20241005a by probing real tiles), route-scenario validation.
5. **Vertical slice** — headless `scripts/e2e_demo.py` proved launch → scan → Bedrock → incident →
   verify → reroute → retask → approve → briefing before the frontend existed.
6. **Visual verification** — headless Chromium screenshots (`scripts/capture_story.py`) were used to
   inspect the 3D scene and fix issues (bridge decks dipping into the river, label overlap, stale metrics).

Artifacts: `IMPLEMENTATION_CHECKLIST.md`, `docs/*.md`, `docs/screens/*.png`, `docs/evaluation_run.json`.
