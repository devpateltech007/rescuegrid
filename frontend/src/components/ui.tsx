import type { ReactNode } from "react";

const PROV: Record<string, { label: string; cls: string; tip: string }> = {
  OFFICIAL_HISTORICAL_RECORD: { label: "HISTORICAL RECORD", cls: "text-amber-200 border-amber-700/70 bg-amber-950/40", tip: "Documented in an official public record (NCDOT / Buncombe County)" },
  PUBLIC_HISTORICAL_IMAGERY: { label: "NOAA IMAGERY 2024-10-05", cls: "text-yellow-200 border-yellow-700/70 bg-yellow-950/40", tip: "Real post-storm NOAA aerial imagery — not captured by the simulated drones" },
  CURRENT_BASEMAP: { label: "CURRENT BASEMAP", cls: "text-slate-300 border-slate-600 bg-slate-800/50", tip: "Present-day OSM / USGS / Esri data" },
  SIMULATED_SCENARIO: { label: "SIMULATED", cls: "text-fuchsia-200 border-fuchsia-700/70 bg-fuchsia-950/40", tip: "Exercise scenario data — not a historical record" },
  SIMULATED_SENSOR: { label: "SIM SENSOR", cls: "text-fuchsia-200 border-fuchsia-700/70 bg-fuchsia-950/40", tip: "Produced by the simulated drone sensors" },
  BEDROCK_INFERENCE: { label: "BEDROCK AI", cls: "text-cyan-200 border-cyan-700/70 bg-cyan-950/40", tip: "Amazon Bedrock model output — advisory, untrusted until reviewed" },
  HUMAN_VERIFIED: { label: "HUMAN VERIFIED", cls: "text-green-200 border-green-700/70 bg-green-950/40", tip: "Decision recorded by a named operator" },
};

export function Prov({ p }: { p: string }) {
  const d = PROV[p] || { label: p, cls: "text-slate-300 border-slate-600", tip: p };
  return <span className={`chip ${d.cls}`} title={d.tip}>{d.label}</span>;
}

const STATUS: Record<string, string> = {
  UNKNOWN: "text-slate-300 border-slate-600 bg-slate-800/40",
  OBSERVED_PASSABLE: "text-teal-200 border-teal-700 bg-teal-950/40",
  VERIFIED_PASSABLE: "text-green-200 border-green-600 bg-green-950/50",
  SUSPECTED_BLOCKED: "text-orange-200 border-orange-600 bg-orange-950/50",
  CONFIRMED_BLOCKED: "text-red-200 border-red-600 bg-red-950/60",
  PENDING_REVIEW: "text-amber-200 border-amber-600 bg-amber-950/50",
  CONFIRMED: "text-red-200 border-red-600 bg-red-950/60",
  REJECTED: "text-slate-400 border-slate-600 bg-slate-800/40",
  REINSPECTION_REQUESTED: "text-cyan-200 border-cyan-600 bg-cyan-950/50",
  LIKELY_BLOCKED: "text-red-200 border-red-700 bg-red-950/40",
  LIKELY_PASSABLE: "text-green-200 border-green-700 bg-green-950/40",
  UNCERTAIN: "text-amber-200 border-amber-700 bg-amber-950/40",
  RECOMMENDED: "text-green-200 border-green-600 bg-green-950/50",
  APPROVED: "text-green-100 border-green-500 bg-green-900/60",
  INVALIDATED: "text-red-200 border-red-600 bg-red-950/60",
  SUPERSEDED: "text-slate-400 border-slate-600",
  PROVISIONAL: "text-amber-200 border-amber-600 bg-amber-950/40",
  ALTERNATIVE: "text-slate-300 border-slate-600",
  SUCCESS: "text-green-200 border-green-600 bg-green-950/50",
  FAILED: "text-red-200 border-red-600 bg-red-950/60",
  VALIDATION_FAILED: "text-red-200 border-red-600 bg-red-950/60",
  RUNNING: "text-cyan-200 border-cyan-600 bg-cyan-950/50",
  OFFLINE_FIXTURE: "text-fuchsia-200 border-fuchsia-600 bg-fuchsia-950/50",
};

export function Status({ s }: { s: string }) {
  return <span className={`chip ${STATUS[s] || "text-slate-300 border-slate-600"}`}>{s.replace(/_/g, " ")}</span>;
}

export function KV({ k, v, mono = true }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3 text-[11px] leading-5">
      <span className="text-ops-dim">{k}</span>
      <span className={`${mono ? "mono" : ""} text-right text-ops-text`}>{v}</span>
    </div>
  );
}

export function Section({ title, right, children, className = "" }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="hdr">{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

export const fmtDist = (m?: number | null) => (m == null ? "—" : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
export const fmtDur = (s?: number | null) => (s == null ? "—" : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60).toString().padStart(2, "0")}s` : `${Math.round(s)} s`);
export const fmtTime = (iso?: string) => (iso ? iso.slice(11, 19) : "—");
