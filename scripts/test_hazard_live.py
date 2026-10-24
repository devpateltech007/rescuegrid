"""Live check: run the production hazard prompt on cached NOAA crops (real Bedrock call)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.hazard_analyzer import analyze  # noqa: E402

for site, bridge in (("noaa_whitson_bridge", True), ("noaa_riverwood_bridge", True)):
    obs = {"observation_id": f"TEST-{site}", "drone_id": "TEST", "source_type": "PUBLIC_HISTORICAL_IMAGERY",
           "geographic_accuracy_metadata": {"footprint_m": 180}, "is_bridge_site": bridge, "nearby_road_names": []}
    inv, ha = analyze(obs, ROOT / "data" / "imagery" / f"{site}.jpg")
    print(site, inv.status, inv.latency_ms, inv.input_tokens, inv.output_tokens, inv.failure_reason)
    print(json.dumps(ha.model_dump(mode="json") if ha else inv.parsed_output, indent=1))
