"""Multimodal hazard analysis of aerial observations via Amazon Bedrock.

The model receives the actual image bytes, the source type and observation context. It
returns a HazardAssessment through a forced JSON-schema tool call. Its output is treated as
untrusted: validated with Pydantic, never allowed to supply coordinates or road ids.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.ai.bedrock import BedrockError, bedrock, extract_tool_input
from app.config import FIXTURES, settings
from app.models.schemas import AIInvocation, HazardAssessment, HazardType, Severity, SuggestedAccess

SYSTEM = """You are an imagery analyst supporting a FEMA US&R planning specialist during a disaster \
response exercise. You inspect ONE aerial image of a road corridor and report road hazards.
Rules:
- Report only what is visibly supported by the pixels. If unsure, say so and use UNCERTAIN.
- Never invent GPS coordinates, road IDs, street names, dates, casualty figures or measurements.
- A visually damaged road is not automatically impassable; a road that looks clear is not \
necessarily structurally safe. Reflect that in uncertainty_notes.
- If there is no visible hazard, use NO_VISIBLE_HAZARD. Do not force a finding.
- Your output is advisory. A human commander makes every decision."""

TOOL = {
    "toolSpec": {
        "name": "report_hazard_assessment",
        "description": "Report the structured road-hazard assessment for this aerial observation.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "hazard_type": {"type": "string", "enum": [h.value for h in HazardType],
                                "description": "Dominant hazard affecting the road/bridge in the image."},
                "affected_feature": {"type": "string", "description": "Which visible feature is affected, e.g. 'bridge approach', 'road surface'. No coordinates or IDs."},
                "visual_evidence": {"type": "string", "description": "Concrete visual cues observed in the image."},
                "severity": {"type": "string", "enum": [s.value for s in Severity]},
                "suggested_accessibility": {"type": "string", "enum": [s.value for s in SuggestedAccess]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "uncertainty_notes": {"type": "string", "description": "What cannot be determined from this image."},
                "requires_human_review": {"type": "boolean"},
                "recommended_next_inspection": {"type": "string", "description": "What a follow-up drone pass should look at."},
            },
            "required": ["hazard_type", "affected_feature", "visual_evidence", "severity", "suggested_accessibility",
                         "confidence", "uncertainty_notes", "requires_human_review", "recommended_next_inspection"],
        }},
    }
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_context(obs: dict) -> str:
    src = obs["source_type"]
    src_desc = {
        "PUBLIC_HISTORICAL_IMAGERY": "real post-storm NOAA aerial orthophoto (historical evidence, nadir view)",
        "SIMULATED_SENSOR": "synthetic rendering from a simulated drone sensor (exercise data)",
    }.get(src, src)
    roads = obs.get("nearby_road_names") or []
    return (
        f"Observation {obs['observation_id']} from drone {obs['drone_id']}.\n"
        f"Image source type: {src} — {src_desc}.\n"
        f"Approximate ground footprint: {obs['geographic_accuracy_metadata'].get('footprint_m', 'unknown')} m across.\n"
        f"Context: the image is centred on a road segment{' that includes a river bridge' if obs.get('is_bridge_site') else ''}. "
        f"Nearby mapped roads (from GIS, not from you): {', '.join(roads) if roads else 'none matched'}.\n"
        + ("GIS fact: the mapped Swannanoa River channel normally flows under this bridge, so water in the channel "
           "itself is expected; distinguish the normal channel from out-of-bank flooding, washouts or structural damage.\n"
           if obs.get("is_bridge_site") else "")
        + f"Road hazard focus: {obs.get('focus', 'the road surface at the image centre')}.\n"
        "Inspect for: flooding, debris obstruction, fallen trees, bridge damage, road washout, damaged infrastructure. "
        "Call report_hazard_assessment exactly once."
    )


def analyze(obs: dict, image_path: Path) -> tuple[AIInvocation, HazardAssessment | None]:
    inv = AIInvocation(invocation_id=f"AI-{uuid.uuid4().hex[:8]}", kind="HAZARD_ANALYSIS", model_id=bedrock.model_id,
                       observation_id=obs["observation_id"], status="RUNNING", live=True, started_at=_now())
    img = image_path.read_bytes()
    inv.image_bytes = len(img)
    fmt = "jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "png"
    messages = [{"role": "user", "content": [
        {"image": {"format": fmt, "source": {"bytes": img}}},
        {"text": build_context(obs)},
    ]}]
    try:
        r = bedrock.converse(messages, SYSTEM, TOOL, max_tokens=1200)
    except BedrockError as e:
        inv.status, inv.failure_reason, inv.attempts = "FAILED", e.reason, e.attempts
        if settings.allow_offline_fixture:
            return _offline_fixture(obs, inv)
        return inv, None
    resp = r["response"]
    usage = resp.get("usage", {})
    inv.latency_ms = round(r["latency_ms"], 1)
    inv.attempts = r["attempts"]
    inv.request_id = r["request_id"]
    inv.input_tokens, inv.output_tokens = usage.get("inputTokens"), usage.get("outputTokens")
    data, text = extract_tool_input(resp)
    inv.raw_text = (text or "")[:1000] or None
    if data is None:
        inv.status, inv.failure_reason = "VALIDATION_FAILED", "Model did not return the required tool call."
        return inv, None
    inv.parsed_output = data
    try:
        ha = HazardAssessment.model_validate(data)
    except ValidationError as e:
        inv.status = "VALIDATION_FAILED"
        inv.failure_reason = "Schema validation failed: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:400]
        return inv, None
    inv.status = "SUCCESS"
    return inv, ha


def _offline_fixture(obs: dict, inv: AIInvocation) -> tuple[AIInvocation, HazardAssessment | None]:
    """Explicitly-enabled rehearsal fixture. Always labeled OFFLINE_FIXTURE, never 'live'."""
    p = FIXTURES / "offline_hazard_fixture.json"
    if not p.exists():
        return inv, None
    fx = json.loads(p.read_text()).get(obs.get("site_key") or "", None)
    if not fx:
        return inv, None
    inv.status, inv.live, inv.model_id = "OFFLINE_FIXTURE", False, "offline-fixture (NOT a live AWS inference)"
    inv.parsed_output = fx
    return inv, HazardAssessment.model_validate(fx)
