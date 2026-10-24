import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useMission } from "../store/mission";
import { KV, Status, fmtDist, fmtDur } from "./ui";

const TONE: Record<string, string> = { red: "text-red-300", amber: "text-amber-300", green: "text-green-300", cyan: "text-cyan-300", dim: "text-ops-dim" };

function Timeline() {
  const tl = useMission((s) => s.timeline);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [tl.length]);
  return (
    <div ref={ref} className="h-full overflow-y-auto scroll pr-1 mono text-[10.5px] leading-[1.55]">
      {tl.length === 0 && <div className="text-ops-dim italic font-sans">Mission event timeline — sequenced events from /ws/mission appear here.</div>}
      {tl.map((x) => (
        <div key={`${x.seq}-${x.type}-${x.text.slice(0, 12)}`} className="flex gap-2">
          <span className="text-ops-dim w-14 shrink-0">{x.t}</span>
          <span className="text-ops-dim/60 w-9 shrink-0 text-right">#{x.seq}</span>
          <span className={TONE[x.tone]}>{x.text}</span>
        </div>
      ))}
    </div>
  );
}

function RouteSummary() {
  const s = useMission();
  const first = (() => {
    const all = Object.values(s.routes).filter((r) => r.rank === 0);
    return all.sort((a, b) => a.route_generation_timestamp.localeCompare(b.route_generation_timestamp))[0];
  })();
  const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
  const prev = s.previousRouteId ? s.routes[s.previousRouteId] : first && cur && first.route_id !== cur.route_id ? first : null;
  const Row = ({ r, label, color }: { r: any; label: string; color: string }) => (
    <div className="rounded border border-ops-line bg-black/25 p-1.5">
      <div className="flex items-center justify-between">
        <span className={`text-[10px] font-bold ${color}`}>{label}</span>
        <Status s={s.approvedRouteId === r.route_id ? "APPROVED" : r.route_status} />
      </div>
      <div className="text-[10.5px] truncate" title={r.road_names.join(" → ")}>{r.road_names.join(" → ")}</div>
      <div className="flex gap-3 mono text-[11px] mt-0.5">
        <span>{fmtDist(r.distance_m)}</span>
        <span>{fmtDur(r.estimated_travel_seconds)}<span className="text-ops-dim text-[9px]"> sim</span></span>
        <span className="text-ops-amber">{r.unverified_edge_count} unverified</span>
      </div>
    </div>
  );
  return (
    <div className="space-y-1.5">
      {prev && <Row r={prev} label="PREVIOUS ROUTE" color="text-red-300" />}
      {cur ? <Row r={cur} label={prev ? "UPDATED ROUTE" : "PROVISIONAL ROUTE"} color="text-green-300" /> : <div className="text-[11px] text-red-300 border border-red-800 rounded p-1.5">{s.noRoute || "No verified route could be identified."}</div>}
      {prev && cur && (
        <div className="mono text-[10.5px] text-ops-dim">Δ {cur.distance_m - prev.distance_m >= 0 ? "+" : ""}{Math.round(cur.distance_m - prev.distance_m)} m · {cur.estimated_travel_seconds - prev.estimated_travel_seconds >= 0 ? "+" : ""}{Math.round(cur.estimated_travel_seconds - prev.estimated_travel_seconds)} s simulated · recalculated in {cur.compute_ms} ms</div>
      )}
      <div className="text-[9px] text-ops-dim italic">Travel times are simulated estimates from OSM speed assumptions, not emergency ETAs.</div>
    </div>
  );
}

function Coverage() {
  const cov = useMission((s) => s.coverage);
  const simTime = useMission((s) => s.simTime);
  const m = useMission((s) => s.metrics);
  const speed = useMission((s) => s.speed);
  const invOk = useMission((s) => Object.values(s.invocations).filter((i) => i.status === "SUCCESS").length);
  const [hist, setHist] = useState<{ t: number; c: number }[]>([]);
  const last = useRef(-1);
  useEffect(() => {
    if (!cov || !simTime) return;
    const t = Math.round((new Date(simTime).getTime() - new Date("2024-09-28T13:00:00Z").getTime()) / 1000);
    if (t === last.current) return;
    if (t < last.current) setHist([]);
    last.current = t;
    setHist((h) => [...h.slice(-400), { t, c: cov.survey_coverage_pct }]);
  }, [cov, simTime]);
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={hist} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
            <defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.5} /><stop offset="100%" stopColor="#22d3ee" stopOpacity={0} /></linearGradient></defs>
            <XAxis dataKey="t" tick={{ fontSize: 9, fill: "#7d8794" }} tickFormatter={(v) => `${v}s`} />
            <YAxis tick={{ fontSize: 9, fill: "#7d8794" }} />
            <Tooltip contentStyle={{ background: "#111418", border: "1px solid #232a33", fontSize: 11 }} formatter={(v: number) => [`${v.toFixed(2)}%`, "observed"]} labelFormatter={(l) => `T+${l}s`} />
            <Area type="monotone" dataKey="c" stroke="#22d3ee" fill="url(#cg)" strokeWidth={1.5} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-2 gap-x-3 mt-1">
        <KV k="Area observed" v={cov ? `${(cov.observed_area_m2 / 1e6).toFixed(3)} km²` : "—"} />
        <KV k="Sim speed" v={`${speed}x`} />
        <KV k="Roads assessed" v={m ? `${m.road_segments_assessed}/${m.road_segments_in_survey}` : "—"} />
        <KV k="Bedrock calls ✓" v={invOk} />
      </div>
    </div>
  );
}

export default function BottomPanel() {
  return (
    <div className="h-[190px] shrink-0 panel border-x-0 border-b-0 grid grid-cols-[1fr_340px_300px] gap-3 p-3">
      <div className="min-h-0 flex flex-col"><div className="hdr mb-1">Mission event timeline</div><div className="flex-1 min-h-0"><Timeline /></div></div>
      <div className="min-h-0 overflow-y-auto scroll"><div className="hdr mb-1">Before / after route</div><RouteSummary /></div>
      <div className="min-h-0 flex flex-col"><div className="hdr mb-1">Survey coverage</div><div className="flex-1 min-h-0"><Coverage /></div></div>
    </div>
  );
}
