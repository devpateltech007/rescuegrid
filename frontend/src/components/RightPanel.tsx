import { AlertTriangle, BrainCircuit, CheckCircle2, FileText, Image as ImageIcon, Loader2, RefreshCw, ScanSearch, ShieldCheck, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { world3d } from "../cesium/world";
import { api } from "../services/api";
import { useMission } from "../store/mission";
import type { Incident, Invocation, Observation } from "../types";
import { KV, Prov, Section, Status, fmtDist, fmtDur, fmtTime } from "./ui";

function ObservationCard({ o, active, onClick }: { o: Observation; active: boolean; onClick: () => void }) {
  const ha = o.hazard_assessment;
  return (
    <div onClick={onClick} className={`rounded-lg border p-2 cursor-pointer transition ${active ? "border-ops-cyan bg-cyan-950/20" : "border-ops-line bg-ops-panel2/70 hover:border-slate-500"} animate-slideIn`}>
      <div className="flex gap-2">
        <img src={o.image_url} className="w-16 h-16 object-cover rounded border border-ops-line" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span className="mono text-[11px] font-bold">{o.observation_id}</span>
            <span className="mono text-[10px] text-ops-dim">{fmtTime(o.simulated_timestamp)}</span>
          </div>
          <div className="text-[10.5px] text-ops-dim truncate">{o.drone_id} · {o.trigger.replace(/_/g, " ").toLowerCase()}</div>
          <div className="text-[10.5px] truncate">{o.nearby_road_names?.join(", ") || <span className="text-ops-amber">UNMATCHED</span>}</div>
          <div className="flex flex-wrap gap-1 mt-1">
            <Prov p={o.source_type} />
            {o.ai_status === "RUNNING" || o.ai_status === "PENDING" ? (
              <span className="chip text-cyan-200 border-cyan-700"><Loader2 size={10} className="animate-spin" /> BEDROCK</span>
            ) : o.ai_status === "FAILED" ? <Status s="FAILED" /> : ha ? <Status s={ha.suggested_accessibility} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function ObservationDetail({ o }: { o: Observation }) {
  const s = useMission();
  const inv = o.ai_invocation_id ? s.invocations[o.ai_invocation_id] : null;
  const acc = o.geographic_accuracy_metadata as any;
  return (
    <div className="rounded-lg border border-ops-line bg-black/30 p-2.5 space-y-2">
      <a href={o.image_url} target="_blank" rel="noreferrer"><img src={o.image_url} className="w-full rounded border border-ops-line" /></a>
      <div className="text-[10px] text-ops-dim leading-snug">{o.image_source}{acc?.drone_role ? ` — ${acc.drone_role}` : ""}</div>
      <KV k="Camera" v={`${o.camera_position.latitude.toFixed(5)}, ${o.camera_position.longitude.toFixed(5)} · ${o.camera_position.altitude_msl_m.toFixed(0)} m MSL`} />
      <KV k="Gimbal target" v={`${o.target.lat.toFixed(5)}, ${o.target.lon.toFixed(5)}`} />
      <KV k="Footprint" v={`${acc?.footprint_m ?? "?"} m${acc?.approx_gsd_m ? ` · GSD ${acc.approx_gsd_m} m` : ""}`} />
      {acc?.acquisition_date && <KV k="Acquired" v={`${acc.acquisition_date} · ${acc.flight_id}`} />}
      <KV k="Road match (GIS)" v={o.match_status === "MATCHED" ? `${o.nearby_road_segment_ids.length / 2 || 1} segment(s)` : "UNMATCHED"} />
      <KV k="S3 evidence" v={o.image_s3_uri ? <span className="text-ops-green">stored</span> : <span className="text-ops-dim">local only</span>} />
      <div className="flex gap-1.5">
        {inv && <button className="btn !py-1 text-[10.5px]" onClick={() => { s.select("invocation", inv.invocation_id); s.set({ rightTab: "ai" }); }}><BrainCircuit size={11} /> AI inspection</button>}
        {o.incident_id && <button className="btn !py-1 text-[10.5px]" onClick={() => { s.select("incident", o.incident_id); s.set({ rightTab: "incidents" }); }}><AlertTriangle size={11} /> {o.incident_id}</button>}
        {o.ai_status === "FAILED" && <button className="btn btn-cyan !py-1 text-[10.5px]" onClick={() => api.analyze(o.observation_id)}><RefreshCw size={11} /> Retry Bedrock</button>}
      </div>
    </div>
  );
}

function Feed() {
  const s = useMission();
  const obs = Object.values(s.observations).sort((a, b) => b.simulated_timestamp.localeCompare(a.simulated_timestamp));
  const sel = s.selected.kind === "observation" ? s.observations[s.selected.id!] : obs[0];
  return (
    <div className="space-y-2">
      {sel && <ObservationDetail o={sel} />}
      <div className="hdr pt-1">Observation feed ({obs.length})</div>
      {obs.length === 0 && <div className="text-[11px] text-ops-dim italic">No observations yet. Drones capture imagery at planned inspection points and when lidar change detection flags a road anomaly.</div>}
      {obs.map((o) => <ObservationCard key={o.observation_id} o={o} active={sel?.observation_id === o.observation_id} onClick={() => s.select("observation", o.observation_id)} />)}
    </div>
  );
}

function AIInspector() {
  const s = useMission();
  const invs = Object.values(s.invocations).sort((a, b) => b.started_at.localeCompare(a.started_at));
  const sel: Invocation | undefined = s.selected.kind === "invocation" ? s.invocations[s.selected.id!] : invs[0];
  return (
    <div className="space-y-2">
      {sel ? (
        <div className={`rounded-lg border p-2.5 space-y-1.5 ${sel.status === "SUCCESS" ? "border-cyan-800 bg-cyan-950/10" : "border-red-800 bg-red-950/10"}`}>
          <div className="flex items-center justify-between">
            <span className="mono text-[11px] font-bold">{sel.invocation_id}</span>
            <div className="flex gap-1">
              <Status s={sel.status} />
              {sel.live ? <span className="chip text-green-200 border-green-700 bg-green-950/40">LIVE AWS INFERENCE</span> : <span className="chip text-fuchsia-200 border-fuchsia-700">NOT LIVE</span>}
            </div>
          </div>
          <KV k="Kind" v={sel.kind} />
          <KV k="Model ID" v={<span className="text-ops-cyan break-all">{sel.model_id}</span>} />
          <KV k="API" v="bedrock-runtime Converse · forced tool (JSON schema)" />
          {sel.observation_id && <KV k="Observation" v={sel.observation_id} />}
          <KV k="Invoked" v={new Date(sel.started_at).toLocaleTimeString()} />
          <KV k="Latency" v={sel.latency_ms ? `${Math.round(sel.latency_ms)} ms` : "—"} />
          <KV k="Tokens in / out" v={`${sel.input_tokens ?? "—"} / ${sel.output_tokens ?? "—"}`} />
          <KV k="Attempts" v={sel.attempts} />
          {sel.image_bytes && <KV k="Image bytes sent" v={sel.image_bytes.toLocaleString()} />}
          {sel.request_id && <KV k="AWS request id" v={<span className="text-[9.5px]">{sel.request_id}</span>} />}
          {sel.incident_id && <KV k="Incident" v={<button className="text-ops-amber underline" onClick={() => { s.select("incident", sel.incident_id); s.set({ rightTab: "incidents" }); }}>{sel.incident_id}</button>} />}
          {sel.failure_reason && <div className="text-[10.5px] text-red-300 border border-red-900 rounded p-1.5">Failure: {sel.failure_reason}</div>}
          {sel.evidence_image_url && <img src={sel.evidence_image_url} className="w-full rounded border border-ops-line" />}
          <div className="hdr pt-1">Parsed model output (validated with Pydantic)</div>
          <pre className="mono text-[10px] leading-snug bg-black/50 border border-ops-line rounded p-2 whitespace-pre-wrap break-words max-h-72 overflow-auto scroll">{JSON.stringify(sel.parsed_output, null, 2)}</pre>
          <div className="text-[9.5px] text-ops-dim italic">The model never supplies coordinates or road IDs — those come from telemetry and GIS matching. Output is advisory until a commander decides.</div>
        </div>
      ) : (
        <div className="text-[11px] text-ops-dim italic">No Bedrock invocations yet.</div>
      )}
      <div className="hdr pt-1">Invocation log ({invs.length})</div>
      {invs.map((i) => (
        <div key={i.invocation_id} onClick={() => s.select("invocation", i.invocation_id)} className={`flex items-center justify-between rounded border px-2 py-1.5 cursor-pointer text-[10.5px] ${sel?.invocation_id === i.invocation_id ? "border-ops-cyan" : "border-ops-line hover:border-slate-500"}`}>
          <span className="mono">{i.invocation_id} · {i.kind === "HAZARD_ANALYSIS" ? i.observation_id : "BRIEFING"}</span>
          <span className="flex items-center gap-1.5"><span className="mono text-ops-dim">{i.latency_ms ? `${Math.round(i.latency_ms)}ms` : ""}</span><Status s={i.status} /></span>
        </div>
      ))}
    </div>
  );
}

function IncidentDetail({ i }: { i: Incident }) {
  const s = useMission();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const la = i.assessments?.[i.assessments.length - 1] || (i as any);
  const decided = ["CONFIRMED", "VERIFIED_PASSABLE", "REJECTED"].includes(i.status);
  const evidence = i.observation_ids;
  const allReviewed = evidence.every((e) => reviewed[e]);
  const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
  const onRoute = !!cur && i.affected_road_segment_ids.some((e) => cur.edge_ids.includes(e));
  const run = async (fn: () => Promise<any>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      s.toast({ tone: "red", title: "Decision failed", body: e.message });
    } finally {
      setBusy(false);
    }
  };
  const ev = evidence.filter((e) => reviewed[e]);
  return (
    <div className={`rounded-lg border p-2.5 space-y-2 ${i.status === "PENDING_REVIEW" ? (i.suggested_accessibility === "LIKELY_BLOCKED" ? "border-red-700 glow-red" : "border-amber-700") : "border-ops-line"}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="mono text-[12px] font-bold">{i.incident_id}</div>
          <div className="text-[13px] font-semibold">{i.hazard_type.replace(/_/g, " ")} · {i.affected_road_names.join(", ")}</div>
        </div>
        <Status s={i.status} />
      </div>
      <div className="flex flex-wrap gap-1">{i.provenance.map((p) => <Prov key={p} p={p} />)}{i.single_source && <span className="chip text-amber-200 border-amber-700">SINGLE SOURCE</span>}{onRoute && <span className="chip text-red-200 border-red-700">ON CURRENT ROUTE</span>}</div>
      <div className="grid grid-cols-3 gap-1.5 text-center mono text-[10.5px]">
        <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[9px] text-ops-dim">SEVERITY</div>{la.severity}</div>
        <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[9px] text-ops-dim">AI SUGGESTS</div>{String(la.suggested_accessibility).replace("LIKELY_", "")}</div>
        <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[9px] text-ops-dim">CONFIDENCE</div>{Math.round((la.confidence ?? i.confidence) * 100)}%</div>
      </div>
      <Section title="Drone evidence (review each before deciding)">
        <div className="grid grid-cols-2 gap-1.5">
          {evidence.map((oid) => {
            const o = s.observations[oid];
            return (
              <label key={oid} className={`block rounded border p-1 cursor-pointer ${reviewed[oid] ? "border-green-700" : "border-ops-line"}`}>
                {o && <img src={o.image_url} className="w-full h-24 object-cover rounded" onClick={(e) => { e.preventDefault(); s.select("observation", oid); s.set({ rightTab: "feed" }); }} />}
                <div className="flex items-center gap-1 text-[10px] mt-0.5"><input type="checkbox" checked={!!reviewed[oid]} onChange={(e) => setReviewed({ ...reviewed, [oid]: e.target.checked })} /> <span className="mono">{oid}</span></div>
                {o && <div className="text-[9px] text-ops-dim">{o.drone_id} · {o.source_type === "PUBLIC_HISTORICAL_IMAGERY" ? "NOAA 2024-10-05" : "sim sensor"}</div>}
              </label>
            );
          })}
        </div>
      </Section>
      <Section title="Visual evidence (Bedrock)"><div className="text-[11px] leading-snug text-ops-text/90">{la.visual_evidence}</div></Section>
      <Section title="Uncertainty"><div className="text-[11px] leading-snug text-amber-100/80">{la.uncertainty_notes}</div></Section>
      <Section title="Recommended next inspection"><div className="text-[11px] leading-snug text-ops-text/80">{la.recommended_next_inspection}</div></Section>
      {i.historical_context && <div className="text-[10.5px] rounded border border-amber-800/60 bg-amber-950/20 p-1.5 text-amber-100/90"><b>Historical record:</b> {i.historical_context}</div>}
      <KV k="Location (telemetry + GIS)" v={`${i.location.lat.toFixed(5)}, ${i.location.lon.toFixed(5)}`} />
      <KV k="Affected segments" v={`${i.affected_road_segment_ids.length} directed edges`} />
      {i.assessments?.length > 1 && <KV k="Corroborating passes" v={i.assessments.length} />}
      <button className="btn !py-1 text-[10.5px]" onClick={() => world3d.cam.flyToLonLat(i.location.lon, i.location.lat, 180, 200, -35)}><ScanSearch size={11} /> Fly to incident</button>
      {!decided && (
        <div className="border-t border-ops-line pt-2 space-y-1.5">
          <div className="hdr">Commander decision · {s.operator}</div>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Decision note (optional)" className="w-full bg-black/40 border border-ops-line rounded px-2 py-1 text-[11px] outline-none focus:border-ops-cyan" />
          {!allReviewed && <div className="text-[10px] text-ops-amber">Tick each evidence item after reviewing it.</div>}
          <div className="grid grid-cols-2 gap-1.5">
            {i.kind === "HAZARD" || i.suggested_accessibility !== "LIKELY_PASSABLE" ? (
              <button disabled={busy || !allReviewed} className="btn btn-red justify-center" onClick={() => run(() => api.verify(i.incident_id, s.operator, "BLOCKED", ev, note))}><XCircle size={12} /> Confirm blocked</button>
            ) : null}
            <button disabled={busy || !allReviewed} className="btn btn-green justify-center" onClick={() => run(() => api.verify(i.incident_id, s.operator, "PASSABLE", ev, note))}><ShieldCheck size={12} /> Verify passable</button>
            <button disabled={busy} className="btn btn-cyan justify-center" onClick={() => run(() => api.reinspect(i.incident_id, s.operator, ev, note))}><RefreshCw size={12} /> Re-inspect (drone)</button>
            <button disabled={busy} className="btn justify-center" onClick={() => run(() => api.reject(i.incident_id, s.operator, ev, note))}>Reject</button>
          </div>
          <div className="text-[9.5px] text-ops-dim italic">Simulated exercise. Real dispatch requires authorized personnel. "Re-inspect" sends the nearest drone for a low, close pass — no ground team is assumed.</div>
        </div>
      )}
      {i.decisions.length > 0 && (
        <Section title="Decision record">
          {s.decisions.filter((d) => d.target_id === i.incident_id).map((d) => (
            <div key={d.decision_id} className="text-[10.5px] mono text-ops-text/80">{fmtTime(d.simulated_timestamp)} {d.action} · {d.operator} · reviewed {d.evidence_reviewed.join(", ") || "—"}</div>
          ))}
        </Section>
      )}
    </div>
  );
}

function Incidents() {
  const s = useMission();
  const list = Object.values(s.incidents).sort((a, b) => {
    const p = (x: Incident) => (x.status === "PENDING_REVIEW" ? 0 : x.status === "REINSPECTION_REQUESTED" ? 1 : 2);
    return p(a) - p(b) || b.created_at.localeCompare(a.created_at);
  });
  const sel = s.selected.kind === "incident" ? s.incidents[s.selected.id!] : list[0];
  return (
    <div className="space-y-2">
      {sel && <IncidentDetail key={sel.incident_id} i={sel} />}
      <div className="hdr pt-1">Verification queue ({list.filter((x) => x.status === "PENDING_REVIEW").length} pending)</div>
      {list.map((i) => (
        <div key={i.incident_id} onClick={() => s.select("incident", i.incident_id)} className={`rounded border px-2 py-1.5 cursor-pointer ${sel?.incident_id === i.incident_id ? "border-ops-cyan" : "border-ops-line hover:border-slate-500"}`}>
          <div className="flex items-center justify-between text-[11px]"><span className="mono font-bold">{i.incident_id}</span><Status s={i.status} /></div>
          <div className="text-[10.5px] text-ops-dim truncate">{i.hazard_type.replace(/_/g, " ")} · {i.affected_road_names.join(", ")}</div>
        </div>
      ))}
      {list.length === 0 && <div className="text-[11px] text-ops-dim italic">No incidents. Incidents are created only from validated Bedrock analyses matched to road segments.</div>}
    </div>
  );
}

function BriefingTab() {
  const s = useMission();
  const [busy, setBusy] = useState(false);
  const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
  const b = s.briefings[s.briefings.length - 1];
  const gen = async () => {
    setBusy(true);
    try {
      await api.briefing(s.operator);
    } catch (e: any) {
      s.toast({ tone: "red", title: "Briefing failed", body: e.message });
    } finally {
      setBusy(false);
    }
  };
  const approve = async () => {
    if (!cur) return;
    try {
      await api.approve(cur.route_id, s.operator, Object.values(s.incidents).flatMap((i) => i.observation_ids).slice(0, 20));
    } catch (e: any) {
      s.toast({ tone: "red", title: "Approval failed", body: e.message });
    }
  };
  const approved = cur && s.approvedRouteId === cur.route_id;
  return (
    <div className="space-y-2">
      {cur ? (
        <div className="rounded-lg border border-ops-line p-2.5 space-y-1">
          <div className="flex justify-between items-center"><span className="hdr">Recommended route</span><Status s={approved ? "APPROVED" : cur.route_status} /></div>
          <div className="text-[11.5px]">{cur.road_names.join(" → ")}</div>
          <KV k="Distance" v={fmtDist(cur.distance_m)} />
          <KV k="Simulated travel estimate" v={fmtDur(cur.estimated_travel_seconds)} />
          <KV k="Unverified segments" v={<span className="text-ops-amber">{cur.unverified_edge_count}</span>} />
          <KV k="Suspected segments" v={cur.suspected_edge_ids.length} />
          <div className="text-[9.5px] text-ops-dim italic">{cur.travel_estimate_note}</div>
          <button disabled={!!approved || cur.suspected_edge_ids.length > 0} onClick={approve} className="btn btn-green w-full justify-center mt-1"><CheckCircle2 size={12} /> {approved ? `Approved by ${cur.approved_by || s.operator}` : "Approve simulated mission route"}</button>
          {cur.suspected_edge_ids.length > 0 && <div className="text-[10px] text-ops-amber">Resolve suspected segments before approval.</div>}
        </div>
      ) : (
        <div className="rounded border border-red-800 bg-red-950/30 p-2 text-[11px] text-red-200">{s.noRoute || "No route"}</div>
      )}
      <button disabled={busy} onClick={gen} className="btn btn-cyan w-full justify-center">{busy ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />} Generate Bedrock mission briefing</button>
      {b && (
        <div className="rounded-lg border border-cyan-900 bg-cyan-950/10 p-2.5 space-y-2">
          <div className="flex items-center justify-between"><span className="mono text-[11px] font-bold">{b.briefing_id}</span><div className="flex gap-1"><Status s={b.status} /><Prov p="BEDROCK_INFERENCE" /></div></div>
          {b.briefing ? (
            <>
              <div className="text-[13px] font-semibold text-ops-cyan">{b.briefing.headline}</div>
              <Section title="Situation"><div className="text-[11px] leading-snug">{b.briefing.situation}</div></Section>
              <Section title="Confirmed obstructions"><ul className="list-disc pl-4 text-[11px] space-y-0.5">{b.briefing.confirmed_obstructions.map((x, k) => <li key={k}>{x}</li>)}</ul></Section>
              <Section title="Route recommendation"><div className="text-[11px] leading-snug">{b.briefing.route_recommendation}</div></Section>
              <Section title="Remaining uncertainty"><ul className="list-disc pl-4 text-[11px] text-amber-100/80 space-y-0.5">{b.briefing.remaining_uncertainty.map((x, k) => <li key={k}>{x}</li>)}</ul></Section>
              <Section title="Recommended actions"><ul className="list-disc pl-4 text-[11px] space-y-0.5">{b.briefing.recommended_actions.map((x, k) => <li key={k}>{x}</li>)}</ul></Section>
              <Section title="Evidence cited"><div className="flex flex-wrap gap-1">{b.briefing.evidence_cited.map((x, k) => <span key={k} className="chip text-slate-300 border-slate-600 mono">{x}</span>)}</div></Section>
              <div className="text-[10px] text-ops-dim italic">{b.briefing.limitations}</div>
            </>
          ) : <div className="text-[11px] text-red-300">{b.invocation.failure_reason}</div>}
          <div className="text-[9.5px] text-ops-dim mono">model {b.invocation.model_id} · {Math.round(b.invocation.latency_ms || 0)} ms · tokens {b.invocation.input_tokens}/{b.invocation.output_tokens}{b.s3_uri ? " · archived to S3" : ""}</div>
          <details><summary className="text-[10px] text-ops-dim cursor-pointer">Facts given to the model (from the mission database)</summary><pre className="mono text-[9.5px] bg-black/50 rounded p-2 whitespace-pre-wrap max-h-64 overflow-auto scroll">{JSON.stringify(b.facts, null, 1)}</pre></details>
        </div>
      )}
    </div>
  );
}

export default function RightPanel() {
  const s = useMission();
  const pending = Object.values(s.incidents).filter((i) => i.status === "PENDING_REVIEW").length;
  const tabs = useMemo(() => [
    { k: "feed", label: "Observations", icon: <ImageIcon size={12} />, n: Object.keys(s.observations).length },
    { k: "ai", label: "AI inspect", icon: <BrainCircuit size={12} />, n: Object.keys(s.invocations).length },
    { k: "incidents", label: "Incidents", icon: <AlertTriangle size={12} />, n: pending, alert: pending > 0 },
    { k: "briefing", label: "Route & brief", icon: <FileText size={12} /> },
  ] as const, [s.observations, s.invocations, pending]);
  return (
    <div className="w-[380px] shrink-0 panel border-y-0 border-r-0 flex flex-col overflow-hidden">
      <div className="flex border-b border-ops-line">
        {tabs.map((t) => (
          <button key={t.k} onClick={() => s.set({ rightTab: t.k as any })} className={`flex-1 flex items-center justify-center gap-1 py-2 text-[10.5px] font-semibold border-b-2 ${s.rightTab === t.k ? "border-ops-cyan text-white" : "border-transparent text-ops-dim hover:text-white"}`}>
            {t.icon}{t.label}{"n" in t && t.n ? <span className={`mono text-[9px] px-1 rounded ${"alert" in t && t.alert ? "bg-ops-red text-white animate-pulseRing" : "bg-ops-line"}`}>{t.n}</span> : null}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto scroll p-3">
        {s.rightTab === "feed" && <Feed />}
        {s.rightTab === "ai" && <AIInspector />}
        {s.rightTab === "incidents" && <Incidents />}
        {s.rightTab === "briefing" && <BriefingTab />}
      </div>
    </div>
  );
}
