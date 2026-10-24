"""Evidence-grounded mission briefing. Bedrock summarises facts pulled from the database;
it is told not to compute routes, distances or times itself."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.ai.bedrock import BedrockError, bedrock, extract_tool_input
from app.config import settings
from app.models.schemas import AIInvocation

SYSTEM = """You draft a concise mission intelligence briefing for a FEMA US&R planning specialist \
in a SIMULATED disaster-response exercise (historical replay of Hurricane Helene, Swannanoa NC).
Use ONLY the facts in the provided JSON. Do not compute, estimate or alter any distance, time, \
coordinate or route; quote the numbers exactly as given. Cite supporting observation and incident IDs \
in square brackets. Clearly state remaining unverified segments and that travel times are simulated \
estimates, not ETAs. State that dispatch requires authorized human personnel. No speculation about \
casualties. Plain, operational language."""

TOOL = {"toolSpec": {
    "name": "write_briefing",
    "description": "Write the mission briefing.",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "One line, max 120 chars."},
            "situation": {"type": "string"},
            "confirmed_obstructions": {"type": "array", "items": {"type": "string"}},
            "route_recommendation": {"type": "string"},
            "remaining_uncertainty": {"type": "array", "items": {"type": "string"}},
            "recommended_actions": {"type": "array", "items": {"type": "string"}},
            "evidence_cited": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "string"},
        },
        "required": ["headline", "situation", "confirmed_obstructions", "route_recommendation",
                     "remaining_uncertainty", "recommended_actions", "evidence_cited", "limitations"],
    }},
}}


def generate(facts: dict) -> tuple[AIInvocation, dict | None]:
    inv = AIInvocation(invocation_id=f"AI-{uuid.uuid4().hex[:8]}", kind="MISSION_BRIEFING",
                       model_id=settings.briefing_model_id or bedrock.model_id, status="RUNNING", live=True,
                       started_at=datetime.now(timezone.utc).isoformat())
    messages = [{"role": "user", "content": [{"text": "FACTS (from mission database):\n" + json.dumps(facts, indent=1, default=str)}]}]
    try:
        r = bedrock.converse(messages, SYSTEM, TOOL, max_tokens=1500, model_id=inv.model_id)
    except BedrockError as e:
        inv.status, inv.failure_reason, inv.attempts = "FAILED", e.reason, e.attempts
        return inv, None
    resp = r["response"]
    u = resp.get("usage", {})
    inv.latency_ms, inv.attempts, inv.request_id = round(r["latency_ms"], 1), r["attempts"], r["request_id"]
    inv.input_tokens, inv.output_tokens = u.get("inputTokens"), u.get("outputTokens")
    data, text = extract_tool_input(resp)
    if not data or not isinstance(data.get("headline"), str):
        inv.status, inv.failure_reason = "VALIDATION_FAILED", "Briefing tool output missing or malformed."
        inv.raw_text = (text or "")[:1000]
        return inv, None
    inv.status, inv.parsed_output = "SUCCESS", data
    return inv, data
