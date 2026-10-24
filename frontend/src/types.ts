export type Provenance =
  | "OFFICIAL_HISTORICAL_RECORD"
  | "PUBLIC_HISTORICAL_IMAGERY"
  | "CURRENT_BASEMAP"
  | "SIMULATED_SCENARIO"
  | "SIMULATED_SENSOR"
  | "BEDROCK_INFERENCE"
  | "HUMAN_VERIFIED";

export type AccessStatus = "UNKNOWN" | "OBSERVED_PASSABLE" | "SUSPECTED_BLOCKED" | "CONFIRMED_BLOCKED" | "VERIFIED_PASSABLE";

export interface Telemetry {
  drone_id: string;
  mission_id: string;
  simulated_timestamp: string;
  latitude: number;
  longitude: number;
  altitude_agl_m: number;
  altitude_msl_m: number;
  terrain_elevation_m: number;
  heading_deg: number;
  pitch_deg: number;
  roll_deg: number;
  speed_mps: number;
  battery_percentage: number;
  battery_consumed_wh: number;
  flight_state: string;
  current_waypoint: number;
  total_waypoints: number;
  scan_coverage_percentage: number;
  current_sensor_mode: string;
  communication_state: string;
  sector_id: string;
  task: string;
  scans: number;
  distance_m: number;
  camera_target: [number, number] | null;
}

export interface DroneInfo extends Telemetry {
  callsign: string;
  role: string;
  color: string;
  plan: [number, number, number, string][];
}

export interface HazardAssessment {
  hazard_type: string;
  affected_feature: string;
  visual_evidence: string;
  severity: string;
  suggested_accessibility: string;
  confidence: number;
  uncertainty_notes: string;
  requires_human_review: boolean;
  recommended_next_inspection: string;
}

export interface Observation {
  observation_id: string;
  drone_id: string;
  simulated_timestamp: string;
  camera_position: { longitude: number; latitude: number; altitude_msl_m: number; heading_deg: number; pitch_deg: number };
  sensor_field_of_view: number;
  image_source: string;
  image_url: string;
  image_s3_uri: string | null;
  source_type: Provenance;
  nearby_road_segment_ids: string[];
  nearby_road_names: string[];
  match_status: string;
  footprint: [number, number][];
  geographic_accuracy_metadata: Record<string, unknown>;
  trigger: string;
  ai_status: string;
  ai_invocation_id: string | null;
  incident_id: string | null;
  hazard_assessment: HazardAssessment | null;
  target: { lon: number; lat: number };
  close_inspection?: boolean;
  is_bridge_site?: boolean;
}

export interface Invocation {
  invocation_id: string;
  kind: string;
  model_id: string;
  observation_id: string | null;
  status: string;
  live: boolean;
  started_at: string;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  attempts: number;
  parsed_output: Record<string, unknown> | null;
  failure_reason: string | null;
  incident_id: string | null;
  image_bytes: number | null;
  request_id: string | null;
  evidence_image_url?: string;
  source_type?: string;
}

export interface Incident {
  incident_id: string;
  created_at: string;
  hazard_type: string;
  severity: string;
  suggested_accessibility: string;
  confidence: number;
  affected_road_segment_ids: string[];
  affected_road_names: string[];
  location: { lon: number; lat: number };
  observation_ids: string[];
  scan_ids: string[];
  visual_evidence: string;
  uncertainty_notes: string;
  recommended_next_inspection: string;
  status: string;
  provenance: Provenance[];
  single_source: boolean;
  historical_context: string | null;
  decisions: string[];
  kind: "HAZARD" | "ROAD_ASSESSMENT";
  is_bridge: boolean;
  on_current_route: boolean;
  assessments: (HazardAssessment & { observation_id: string; invocation_id: string; source_type: string })[];
}

export interface RoutePlan {
  route_id: string;
  rank: number;
  label: string;
  edge_ids: string[];
  geometry: [number, number][];
  distance_m: number;
  estimated_travel_seconds: number;
  unverified_edge_count: number;
  unverified_edge_ids: string[];
  suspected_edge_ids: string[];
  blocked_edge_avoidance: string[];
  road_names: string[];
  route_status: string;
  route_generation_timestamp: string;
  compute_ms: number;
  travel_estimate_note: string;
  at_risk?: boolean;
  approved_by?: string;
}

export interface Decision {
  decision_id: string;
  action: string;
  target_type: string;
  target_id: string;
  operator: string;
  note: string;
  evidence_reviewed: string[];
  simulated_timestamp: string;
  wall_timestamp: string;
  resulting_changes: Record<string, unknown>;
}

export interface MissionEvent {
  event_id: string;
  seq: number;
  mission_id: string;
  type: string;
  simulated_timestamp: string;
  wall_timestamp: string;
  payload: any;
}

export interface Tile {
  tile_id: string;
  rows: number;
  cols: number;
  west: number;
  south: number;
  east: number;
  north: number;
  heights: (number | null)[];
  change_cells: [number, number, number][];
  observed_cells: number;
  cell_m: number;
}

export interface ScanBatch {
  scan_id: string;
  drone_id: string;
  ref: [number, number];
  stride: number;
  points: number[];
  footprint: [number, number][];
  observed_point_count: number;
  seq?: number;
}

export interface Briefing {
  briefing_id: string;
  status: string;
  requested_by: string;
  simulated_timestamp: string;
  facts: any;
  briefing: {
    headline: string;
    situation: string;
    confirmed_obstructions: string[];
    route_recommendation: string;
    remaining_uncertainty: string[];
    recommended_actions: string[];
    evidence_cited: string[];
    limitations: string;
  } | null;
  invocation: Invocation;
  s3_uri?: string | null;
}
