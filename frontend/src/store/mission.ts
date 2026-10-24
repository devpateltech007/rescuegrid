import { create } from "zustand";
import type { Briefing, Decision, DroneInfo, Incident, Invocation, MissionEvent, Observation, RoutePlan, Telemetry } from "../types";

export interface Toast {
  id: number;
  tone: "red" | "amber" | "green" | "cyan";
  title: string;
  body?: string;
}

export interface TimelineItem {
  seq: number;
  t: string;
  type: string;
  text: string;
  tone: "red" | "amber" | "green" | "cyan" | "dim";
}

export interface Layers {
  base: boolean;
  scan: boolean;
  recon: boolean;
  hazards: boolean;
  buildings: boolean;
  noaa: boolean;
  roads: boolean;
  sectors: boolean;
  coverage: boolean;
}

interface State {
  loaded: boolean;
  missionId: string;
  missionState: string;
  speed: number;
  simTime: string;
  scenario: any;
  surveyPolygon: [number, number][];
  autoPause: boolean;
  drones: Record<string, DroneInfo>;
  sectors: any[];
  observations: Record<string, Observation>;
  incidents: Record<string, Incident>;
  invocations: Record<string, Invocation>;
  routes: Record<string, RoutePlan>;
  currentRouteId: string | null;
  alternativeIds: string[];
  approvedRouteId: string | null;
  previousRouteId: string | null;
  roadStatus: Record<string, string>;
  decisions: Decision[];
  briefings: Briefing[];
  retaskLog: any[];
  coverage: any;
  metrics: any;
  system: any;
  degraded: { component: string; reason: string; t: string }[];
  timeline: TimelineItem[];
  toasts: Toast[];
  operator: string;
  selected: { kind: "incident" | "observation" | "road" | "drone" | "invocation" | null; id: string | null };
  followDrone: string | null;
  layers: Layers;
  rightTab: "feed" | "ai" | "incidents" | "briefing";
  lastSeq: number;
  wsConnected: boolean;
  noRoute: string | null;
  set: (p: Partial<State>) => void;
  applySnapshot: (s: any) => void;
  applyEvent: (e: MissionEvent) => void;
  toast: (t: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
  select: (kind: State["selected"]["kind"], id: string | null) => void;
  toggleLayer: (k: keyof Layers) => void;
}

let toastId = 1;
declare global {
  interface Window {
    __rg?: any;
  }
}
const fmtT = (iso: string) => (iso ? iso.slice(11, 19) : "");

export const useMission = create<State>((set, get) => ({
  loaded: false,
  missionId: "",
  missionState: "BRIEFING",
  speed: 1,
  simTime: "",
  scenario: null,
  surveyPolygon: [],
  autoPause: false,
  drones: {},
  sectors: [],
  observations: {},
  incidents: {},
  invocations: {},
  routes: {},
  currentRouteId: null,
  alternativeIds: [],
  approvedRouteId: null,
  previousRouteId: null,
  roadStatus: {},
  decisions: [],
  briefings: [],
  retaskLog: [],
  coverage: null,
  metrics: null,
  system: null,
  degraded: [],
  timeline: [],
  toasts: [],
  operator: localStorage.getItem("rg.operator") || "Planning Specialist J. Rivera",
  selected: { kind: null, id: null },
  followDrone: null,
  layers: { base: true, scan: true, recon: true, hazards: true, buildings: true, noaa: true, roads: true, sectors: true, coverage: false },
  rightTab: "feed",
  lastSeq: 0,
  wsConnected: false,
  noRoute: null,
  set: (p) => set(p as any),
  toast: (t) => {
    const id = toastId++;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { ...t, id }] }));
    setTimeout(() => get().dismiss(id), 7000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
  select: (kind, id) => set({ selected: { kind, id } }),
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),

  applySnapshot: (s) => {
    const drones: Record<string, DroneInfo> = {};
    s.drones.forEach((d: DroneInfo) => (drones[d.drone_id] = d));
    const byId = <T extends Record<string, any>>(arr: T[], k: string) => Object.fromEntries(arr.map((x) => [x[k], x]));
    const hist = s.route_history || [];
    set({
      loaded: true,
      missionId: s.mission.mission_id,
      missionState: s.mission.state,
      speed: s.mission.speed,
      simTime: s.mission.simulated_timestamp,
      scenario: s.mission.scenario,
      surveyPolygon: s.mission.survey_polygon,
      autoPause: s.mission.auto_pause,
      drones,
      sectors: s.sectors,
      observations: byId(s.observations, "observation_id"),
      incidents: byId(s.incidents, "incident_id"),
      invocations: byId(s.invocations, "invocation_id"),
      routes: s.routes,
      currentRouteId: s.current_route_id,
      alternativeIds: s.alternative_ids,
      approvedRouteId: s.approved_route_id,
      previousRouteId: hist.length > 1 ? hist[hist.length - 2].route_id : null,
      roadStatus: s.road_status,
      decisions: s.decisions,
      briefings: s.briefings,
      retaskLog: s.retask_log,
      coverage: s.coverage,
      metrics: s.metrics,
      lastSeq: s.seq,
      noRoute: null,
    });
  },

  applyEvent: (e) => {
    const s = get();
    const p = e.payload;
    const tl = (text: string, tone: TimelineItem["tone"] = "dim") =>
      set((st) => ({ timeline: [...st.timeline.slice(-300), { seq: e.seq, t: fmtT(e.simulated_timestamp), type: e.type, text, tone }] }));
    if (e.seq) set({ lastSeq: Math.max(s.lastSeq, e.seq), simTime: e.simulated_timestamp || s.simTime });
    switch (e.type) {
      case "drone.telemetry": {
        const t = p as Telemetry;
        const prev = s.drones[t.drone_id];
        if (prev) set((st) => ({ drones: { ...st.drones, [t.drone_id]: { ...prev, ...t } } }));
        break;
      }
      case "mission.started":
        set({ missionState: "RUNNING" });
        tl("Mission launched — 3 drones taking off from Staging Area S-1", "cyan");
        break;
      case "mission.paused":
        set({ missionState: "PAUSED" });
        tl(`Mission paused: ${p.reason}`, "amber");
        if (String(p.reason).startsWith("Decision")) s.toast({ tone: "amber", title: "Commander decision required", body: p.reason });
        break;
      case "mission.resumed":
        set({ missionState: "RUNNING" });
        tl("Mission resumed", "dim");
        break;
      case "mission.speed_changed":
        set({ speed: p.speed });
        break;
      case "mission.survey_complete":
        set({ missionState: "COMPLETE", metrics: p });
        tl("Survey complete — all drones landed", "green");
        break;
      case "mission.reset":
        break;
      case "drone.waypoint_reached":
        if (p.action === "inspect") tl(`${p.drone_id} on station: ${p.label}`, "cyan");
        break;
      case "scan.coverage_updated":
        set(p.metrics ? { coverage: p, metrics: p.metrics } : { coverage: p });
        break;
      case "scan.change_detected":
        tl(`${p.drone_id} lidar change detection: ${p.points} pts deviate from pre-storm baseline`, "amber");
        break;
      case "observation.created":
        set((st) => ({ observations: { ...st.observations, [p.observation_id]: p } }));
        tl(`${p.drone_id} captured ${p.observation_id} (${p.source_type === "PUBLIC_HISTORICAL_IMAGERY" ? "NOAA historical frame" : "simulated sensor"}) — ${(p.nearby_road_names || []).join(", ") || "unmatched"}`, "cyan");
        break;
      case "ai.analysis_started":
        set((st) => {
          const o = st.observations[p.observation_id];
          return o ? { observations: { ...st.observations, [p.observation_id]: { ...o, ai_status: "RUNNING" } } } : {};
        });
        tl(`Bedrock analyzing ${p.observation_id} (${p.model_id})`, "dim");
        break;
      case "ai.analysis_completed": {
        const inv = p.invocation as Invocation;
        set((st) => {
          const o = st.observations[p.observation_id];
          const obs = o
            ? { ...o, ai_status: inv.status === "SUCCESS" || inv.status === "OFFLINE_FIXTURE" ? "COMPLETED" : "FAILED", ai_invocation_id: inv.invocation_id,
                hazard_assessment: (inv.parsed_output as any) || o.hazard_assessment, incident_id: inv.incident_id || o.incident_id }
            : undefined;
          return { invocations: { ...st.invocations, [inv.invocation_id]: inv }, observations: obs ? { ...st.observations, [p.observation_id]: obs } : st.observations };
        });
        if (inv.status === "SUCCESS")
          tl(`Bedrock ✓ ${p.observation_id}: ${(inv.parsed_output as any)?.hazard_type} / ${(inv.parsed_output as any)?.suggested_accessibility} (${Math.round(inv.latency_ms || 0)} ms)`, "green");
        else tl(`Bedrock ✗ ${p.observation_id}: ${inv.failure_reason}`, "red");
        break;
      }
      case "incident.created":
      case "incident.updated":
      case "incident.verified":
      case "incident.rejected":
      case "incident.inspection_requested": {
        set((st) => ({ incidents: { ...st.incidents, [p.incident_id]: p } }));
        if (e.type === "incident.created") {
          const blocked = p.suggested_accessibility === "LIKELY_BLOCKED";
          tl(`${p.incident_id} created: ${p.hazard_type} on ${p.affected_road_names.join(", ")} — pending commander review`, blocked ? "red" : "amber");
          s.toast({ tone: blocked ? "red" : "amber", title: `New incident ${p.incident_id}`, body: `${p.hazard_type.replace(/_/g, " ")} · ${p.affected_road_names.join(", ")}` });
        } else if (e.type === "incident.verified") tl(`${p.incident_id} ${p.status === "CONFIRMED" ? "CONFIRMED BLOCKED" : "VERIFIED PASSABLE"} by commander`, p.status === "CONFIRMED" ? "red" : "green");
        else if (e.type === "incident.rejected") tl(`${p.incident_id} rejected by commander`, "dim");
        else if (e.type === "incident.inspection_requested") tl(`${p.incident_id}: re-inspection requested`, "amber");
        else tl(`${p.incident_id} updated with corroborating observation`, "cyan");
        break;
      }
      case "road.status_changed":
        set((st) => {
          const rs = { ...st.roadStatus };
          p.edges.forEach((ed: any) => (rs[ed.edge_id] = ed.access_status));
          return { roadStatus: rs };
        });
        if (!String(p.reason).startsWith("Lidar")) tl(`Road status: ${p.edges.length} segment(s) → ${p.edges[0]?.access_status} (${p.reason})`, "amber");
        break;
      case "route.updated":
        set((st) => ({ routes: { ...st.routes, [p.route.route_id]: p.route } }));
        break;
      case "route.recalculated": {
        if (p.status === "NO_ROUTE") {
          set({ noRoute: p.message, currentRouteId: null });
          tl(`NO VERIFIED ROUTE: ${p.message}`, "red");
          s.toast({ tone: "red", title: "No verified route", body: p.message });
          break;
        }
        const routes = { ...s.routes };
        if (p.previous) routes[p.previous.route_id] = p.previous;
        routes[p.current.route_id] = p.current;
        p.alternatives.forEach((a: RoutePlan) => (routes[a.route_id] = a));
        const changed = !p.previous || p.previous.route_id !== p.current.route_id;
        set({ routes, currentRouteId: p.current.route_id, alternativeIds: p.alternatives.map((a: RoutePlan) => a.route_id),
              previousRouteId: changed && p.previous ? p.previous.route_id : s.previousRouteId, noRoute: null });
        if (changed && p.previous) {
          const dd = p.delta.distance_m, dt = p.delta.travel_s;
          tl(`Route recalculated in ${p.compute_ms} ms: ${Math.round(p.previous.distance_m)} m → ${Math.round(p.current.distance_m)} m (${dd >= 0 ? "+" : ""}${Math.round(dd)} m, ${dt >= 0 ? "+" : ""}${Math.round(dt)} s simulated)`, "green");
          s.toast({ tone: "green", title: "Rescue route recalculated", body: `Now via ${p.current.road_names.join(" → ")} · ${(p.current.distance_m / 1000).toFixed(2)} km` });
        } else tl(`Route re-evaluated (${p.compute_ms} ms): unverified segments ${p.current.unverified_edge_count}`, "dim");
        break;
      }
      case "route.approved":
        set((st) => ({ routes: { ...st.routes, [p.route.route_id]: p.route }, approvedRouteId: p.route.route_id }));
        tl(`Route ${p.route.route_id} APPROVED by ${p.decision.operator} (simulated mission plan)`, "green");
        break;
      case "drone.retasked":
        set((st) => ({ retaskLog: [...st.retaskLog, p] }));
        tl(`${p.drone_id} retasked by ${p.by}: ${p.reason}${p.road_name ? ` → ${p.road_name}` : ""}`, "cyan");
        s.toast({ tone: "cyan", title: `${p.drone_id} retasked`, body: p.road_name ? `${p.reason} → ${p.road_name}` : p.reason });
        break;
      case "operator.decision":
        set((st) => ({ decisions: [...st.decisions, p] }));
        break;
      case "briefing.generated":
        set((st) => ({ briefings: [...st.briefings, p], invocations: { ...st.invocations, [p.invocation.invocation_id]: p.invocation } }));
        tl(`Mission briefing ${p.briefing_id} ${p.status === "SUCCESS" ? "generated by Bedrock" : "FAILED"}`, p.status === "SUCCESS" ? "green" : "red");
        break;
      case "system.degraded":
        set((st) => ({ degraded: [...st.degraded.slice(-10), { component: p.component, reason: p.reason, t: e.simulated_timestamp }] }));
        tl(`DEGRADED ${p.component}: ${p.reason} — ${p.impact}`, "red");
        s.toast({ tone: "red", title: `${p.component} degraded`, body: p.impact });
        break;
    }
  },
}));
