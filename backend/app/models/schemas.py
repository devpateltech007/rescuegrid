"""Typed operational data model (spec section 9). Every geographic or incident record
carries a Provenance so historical, simulated, AI and human data are never silently mixed."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Provenance(str, Enum):
    OFFICIAL_HISTORICAL_RECORD = "OFFICIAL_HISTORICAL_RECORD"
    PUBLIC_HISTORICAL_IMAGERY = "PUBLIC_HISTORICAL_IMAGERY"
    CURRENT_BASEMAP = "CURRENT_BASEMAP"
    SIMULATED_SCENARIO = "SIMULATED_SCENARIO"
    SIMULATED_SENSOR = "SIMULATED_SENSOR"
    BEDROCK_INFERENCE = "BEDROCK_INFERENCE"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"


class AccessStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    OBSERVED_PASSABLE = "OBSERVED_PASSABLE"
    SUSPECTED_BLOCKED = "SUSPECTED_BLOCKED"
    CONFIRMED_BLOCKED = "CONFIRMED_BLOCKED"
    VERIFIED_PASSABLE = "VERIFIED_PASSABLE"


class FlightState(str, Enum):
    IDLE = "IDLE"
    TAKEOFF = "TAKEOFF"
    SURVEYING = "SURVEYING"
    INSPECTING = "INSPECTING"
    RETURNING = "RETURNING"
    COMPLETE = "COMPLETE"


class MissionState(str, Enum):
    BRIEFING = "BRIEFING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"


class HazardType(str, Enum):
    FLOODING = "FLOODING"
    DEBRIS_OBSTRUCTION = "DEBRIS_OBSTRUCTION"
    FALLEN_TREES = "FALLEN_TREES"
    BRIDGE_DAMAGE = "BRIDGE_DAMAGE"
    ROAD_WASHOUT = "ROAD_WASHOUT"
    DAMAGED_INFRASTRUCTURE = "DAMAGED_INFRASTRUCTURE"
    NO_VISIBLE_HAZARD = "NO_VISIBLE_HAZARD"
    UNCERTAIN = "UNCERTAIN"


class Severity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class SuggestedAccess(str, Enum):
    LIKELY_PASSABLE = "LIKELY_PASSABLE"
    LIKELY_BLOCKED = "LIKELY_BLOCKED"
    UNCERTAIN = "UNCERTAIN"


class IncidentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    REINSPECTION_REQUESTED = "REINSPECTION_REQUESTED"
    VERIFIED_PASSABLE = "VERIFIED_PASSABLE"


# ---------- telemetry / sensors ----------

class Telemetry(BaseModel):
    drone_id: str
    mission_id: str
    simulated_timestamp: str
    latitude: float
    longitude: float
    altitude_agl_m: float
    altitude_msl_m: float
    terrain_elevation_m: float
    heading_deg: float
    pitch_deg: float
    roll_deg: float
    speed_mps: float
    battery_percentage: float
    battery_consumed_wh: float
    flight_state: FlightState
    current_waypoint: int
    total_waypoints: int
    scan_coverage_percentage: float
    current_sensor_mode: str
    communication_state: str
    sector_id: str
    task: str


class Pose(BaseModel):
    longitude: float
    latitude: float
    altitude_msl_m: float
    heading_deg: float
    pitch_deg: float
    roll_deg: float = 0.0


class ScanRecord(BaseModel):
    scan_id: str
    drone_id: str
    mission_id: str
    scan_timestamp: str
    sensor_type: str = "SIMULATED_LIDAR"
    camera_or_sensor_pose: Pose
    observed_point_count: int
    surveyed_polygon: list[list[float]]  # lon/lat ring
    point_cloud_file: str
    reconstructed_tile_ids: list[str]
    quality_metadata: dict[str, Any]
    provenance: Provenance = Provenance.SIMULATED_SENSOR


class Observation(BaseModel):
    observation_id: str
    mission_id: str
    drone_id: str
    simulated_timestamp: str
    camera_position: Pose
    camera_orientation: dict[str, float]
    sensor_field_of_view: float
    image_source: str
    image_file_location: str
    image_s3_uri: str | None = None
    image_url: str
    source_type: Provenance
    nearby_road_segment_ids: list[str]
    match_status: Literal["MATCHED", "UNMATCHED"]
    footprint: list[list[float]]
    geographic_accuracy_metadata: dict[str, Any]
    trigger: str
    ai_status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"] = "PENDING"
    ai_invocation_id: str | None = None
    incident_id: str | None = None
    hazard_assessment: dict[str, Any] | None = None


# ---------- AI ----------

class HazardAssessment(BaseModel):
    """Structured output demanded from Bedrock. Coordinates and road ids are NOT in here:
    those come from telemetry + spatial matching, never from the model."""
    hazard_type: HazardType
    affected_feature: str = Field(max_length=300)
    visual_evidence: str = Field(max_length=1500)
    severity: Severity
    suggested_accessibility: SuggestedAccess
    confidence: float = Field(ge=0, le=1)
    uncertainty_notes: str = Field(max_length=1500)
    requires_human_review: bool
    recommended_next_inspection: str = Field(max_length=600)


class AIInvocation(BaseModel):
    invocation_id: str
    kind: Literal["HAZARD_ANALYSIS", "MISSION_BRIEFING"]
    model_id: str
    observation_id: str | None = None
    status: Literal["RUNNING", "SUCCESS", "FAILED", "VALIDATION_FAILED", "OFFLINE_FIXTURE"]
    live: bool
    started_at: str
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 0
    parsed_output: dict[str, Any] | None = None
    raw_text: str | None = None
    failure_reason: str | None = None
    incident_id: str | None = None
    image_bytes: int | None = None
    request_id: str | None = None


# ---------- incidents / decisions ----------

class Incident(BaseModel):
    incident_id: str
    mission_id: str
    created_at: str
    hazard_type: HazardType
    severity: Severity
    suggested_accessibility: SuggestedAccess
    confidence: float
    affected_road_segment_ids: list[str]
    affected_road_names: list[str]
    location: dict[str, float]  # from telemetry/georeferencing, never from the model
    observation_ids: list[str]
    scan_ids: list[str] = []
    visual_evidence: str
    uncertainty_notes: str
    recommended_next_inspection: str
    status: IncidentStatus = IncidentStatus.PENDING_REVIEW
    provenance: list[Provenance]
    single_source: bool = True
    historical_context: str | None = None
    decisions: list[str] = []


_OPERATOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .,'\-]{1,59}$")


class OperatorAction(BaseModel):
    operator: str = Field(min_length=2, max_length=60)
    note: str = Field(default="", max_length=500)
    evidence_reviewed: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("operator")
    @classmethod
    def _op(cls, v: str) -> str:
        v = v.strip()
        if not _OPERATOR_RE.match(v):
            raise ValueError("operator must be 2-60 chars: letters, digits, space, . , ' -")
        return v

    @field_validator("evidence_reviewed")
    @classmethod
    def _ev(cls, v: list[str]) -> list[str]:
        for e in v:
            if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", e):
                raise ValueError("invalid evidence id")
        return v


class OperatorDecision(BaseModel):
    decision_id: str
    mission_id: str
    action: str
    target_type: str
    target_id: str
    operator: str
    note: str
    evidence_reviewed: list[str]
    simulated_timestamp: str
    wall_timestamp: str
    resulting_changes: dict[str, Any] = {}


class RetaskRequest(OperatorAction):
    lon: float | None = Field(default=None, ge=-180, le=180)
    lat: float | None = Field(default=None, ge=-90, le=90)
    target_edge_id: str | None = Field(default=None, max_length=80)
    reason: str = Field(default="manual", max_length=200)


# ---------- routing ----------

class RoutePlan(BaseModel):
    route_id: str
    rank: int
    label: str
    start: dict[str, float]
    destination: dict[str, float]
    edge_ids: list[str]
    geometry: list[list[float]]  # [lon, lat, z?]
    distance_m: float
    estimated_travel_seconds: float
    unverified_edge_count: int
    unverified_edge_ids: list[str]
    suspected_edge_ids: list[str]
    blocked_edge_avoidance: list[str]
    road_names: list[str]
    evidence_timestamp: str | None
    route_status: Literal["PROVISIONAL", "RECOMMENDED", "ALTERNATIVE", "SUPERSEDED", "APPROVED", "INVALIDATED"]
    route_generation_timestamp: str
    compute_ms: float
    travel_estimate_note: str = "Simulated travel estimate from OSM speed assumptions; not an emergency ETA."


class RoutePlanRequest(BaseModel):
    start_lon: float | None = Field(default=None, ge=-180, le=180)
    start_lat: float | None = Field(default=None, ge=-90, le=90)
    dest_lon: float | None = Field(default=None, ge=-180, le=180)
    dest_lat: float | None = Field(default=None, ge=-90, le=90)
    alternatives: int = Field(default=3, ge=1, le=5)


class MissionEvent(BaseModel):
    event_id: str
    seq: int
    mission_id: str
    type: str
    simulated_timestamp: str
    wall_timestamp: str
    payload: dict[str, Any]
