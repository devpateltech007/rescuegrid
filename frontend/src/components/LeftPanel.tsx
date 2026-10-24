import { Battery, Crosshair, Eye, Navigation, Radar, Send } from "lucide-react";
import { useState } from "react";
import { world3d } from "../cesium/world";
import { api } from "../services/api";
import { useMission } from "../store/mission";
import type { DroneInfo } from "../types";
import { KV, Prov, Section, fmtDist } from "./ui";

const STATE_COL: Record<string, string> = {
  IDLE: "text-slate-400", TAKEOFF: "text-sky-300", SURVEYING: "text-cyan-300", INSPECTING: "text-amber-300", RETURNING: "text-violet-300", COMPLETE: "text-green-300",
};

function DroneCard({ d }: { d: DroneInfo }) {
  const s = useMission();
  const [retask, setRetask] = useState(false);
  const following = s.followDrone === d.drone_id;
  const bat = d.battery_percentage;
  const sector = s.sectors.find((x) => x.drone_id === d.drone_id);
  const unverifiedBridge = (() => {
    const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
    if (!cur) return [];
    return cur.unverified_edge_ids.filter((e) => world3d.roadProps(e)?.is_bridge || false);
  })();
  return (
    <div className={`rounded-lg border bg-ops-panel2/80 p-2.5 ${following ? "border-ops-cyan glow-cyan" : "border-ops-line"}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: d.color, boxShadow: `0 0 10px ${d.color}` }} />
          <span className="font-bold text-[12.5px] tracking-wide">{d.callsign.toUpperCase()}</span>
        </div>
        <span className={`mono text-[10.5px] font-bold ${STATE_COL[d.flight_state]}`}>{d.flight_state}</span>
      </div>
      <div className="text-[10.5px] text-ops-dim mt-0.5">{d.role}</div>
      <div className="text-[10.5px] mt-1 text-ops-text/90 truncate" title={d.task}>▸ {d.task}</div>
      <div className="grid grid-cols-4 gap-1 mt-2 mono text-[10.5px]">
        <div><div className="text-ops-dim text-[9px]">AGL</div>{d.altitude_agl_m.toFixed(0)} m</div>
        <div><div className="text-ops-dim text-[9px]">SPD</div>{d.speed_mps.toFixed(1)} m/s</div>
        <div><div className="text-ops-dim text-[9px]">HDG</div>{d.heading_deg.toFixed(0).padStart(3, "0")}°</div>
        <div><div className="text-ops-dim text-[9px]">SCANS</div>{d.scans}</div>
      </div>
      <div className="mt-2 space-y-1">
        <div className="flex items-center gap-2 text-[10px]">
          <Battery size={12} className={bat < 30 ? "text-ops-red" : "text-ops-green"} />
          <div className="flex-1 h-1.5 bg-black/50 rounded"><div className="h-full rounded" style={{ width: `${bat}%`, background: bat < 30 ? "#ff4d4f" : bat < 55 ? "#f5a524" : "#22c55e" }} /></div>
          <span className="mono w-20 text-right">{bat.toFixed(0)}% · {d.battery_consumed_wh.toFixed(1)}Wh</span>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          <Radar size={12} className="text-ops-cyan" />
          <div className="flex-1 h-1.5 bg-black/50 rounded"><div className="h-full rounded bg-ops-cyan" style={{ width: `${Math.min(100, d.scan_coverage_percentage)}%` }} /></div>
          <span className="mono w-20 text-right">sector {d.scan_coverage_percentage.toFixed(0)}%</span>
        </div>
      </div>
      <div className="flex items-center justify-between mt-2 text-[9.5px] text-ops-dim mono">
        <span>{sector?.sector_id} · WP {Math.min(d.current_waypoint + 1, d.total_waypoints)}/{d.total_waypoints}</span>
        <span>{fmtDist(d.distance_m)} flown</span>
      </div>
      <div className="flex gap-1.5 mt-2">
        <button className="btn !px-2 !py-1 text-[10.5px]" onClick={() => world3d.cam.flyToDrone(d.drone_id)}><Navigation size={11} /> Fly to</button>
        <button className={`btn !px-2 !py-1 text-[10.5px] ${following ? "btn-cyan" : ""}`} onClick={() => s.set({ followDrone: following ? null : d.drone_id })}><Eye size={11} /> {following ? "Following" : "Follow"}</button>
        <button className="btn !px-2 !py-1 text-[10.5px]" onClick={() => setRetask(!retask)}><Crosshair size={11} /> Retask</button>
      </div>
      {retask && (
        <div className="mt-2 border-t border-ops-line pt-2 space-y-1.5">
          <div className="text-[10px] text-ops-dim">Send {d.callsign} to inspect:</div>
          {unverifiedBridge.length > 0 && (
            <button className="btn btn-amber w-full !justify-start text-[10.5px]" onClick={() => api.retask(d.drone_id, s.operator, { target_edge_id: unverifiedBridge[0], reason: "Unverified bridge on current route" }).then(() => setRetask(false)).catch((e) => s.toast({ tone: "red", title: "Retask failed", body: e.message }))}>
              <Send size={11} /> Unverified bridge on current route
            </button>
          )}
          {s.selected.kind === "road" && s.selected.id && (
            <button className="btn btn-cyan w-full !justify-start text-[10.5px]" onClick={() => api.retask(d.drone_id, s.operator, { target_edge_id: s.selected.id, reason: `Selected road ${world3d.roadProps(s.selected.id!)?.road_name}` }).then(() => setRetask(false)).catch((e) => s.toast({ tone: "red", title: "Retask failed", body: e.message }))}>
              <Send size={11} /> Selected road: {world3d.roadProps(s.selected.id)?.road_name}
            </button>
          )}
          {!unverifiedBridge.length && s.selected.kind !== "road" && <div className="text-[10px] text-ops-dim italic">Click a road in the 3D view to choose a target.</div>}
        </div>
      )}
    </div>
  );
}

export default function LeftPanel() {
  const s = useMission();
  const drones = Object.values(s.drones);
  const sc = s.scenario;
  const cov = s.coverage;
  return (
    <div className="w-[300px] shrink-0 panel border-y-0 border-l-0 flex flex-col overflow-hidden">
      <div className="p-3 border-b border-ops-line space-y-2">
        <Section title="Mission overview">
          <div className="text-[11.5px] leading-snug text-ops-text/90">
            Restore situational awareness of road access between <b className="text-ops-cyan">Staging S-1</b> and <b className="text-pink-300">Rescue Site R-7</b> after Hurricane Helene. Ground teams cannot reach the area; decisions rely on drone evidence reviewed by the commander.
          </div>
          <div className="flex flex-wrap gap-1 mt-1.5"><Prov p="SIMULATED_SCENARIO" /><Prov p="CURRENT_BASEMAP" /><Prov p="OFFICIAL_HISTORICAL_RECORD" /></div>
        </Section>
        {sc?.historical_record && (
          <details className="rounded-md border border-amber-800/60 bg-amber-950/20 p-2 text-[10.5px]">
            <summary className="cursor-pointer font-semibold text-amber-200">Documented: Whitson Ave Bridge damage (NCDOT)</summary>
            <div className="mt-1 text-amber-100/80 leading-snug">{sc.historical_record.text}</div>
            <div className="mt-1 text-ops-dim italic">{sc.historical_record.note}</div>
            <a className="text-ops-cyan underline break-all" href={sc.historical_record.source} target="_blank" rel="noreferrer">NCDOT press release, 2025-02-24</a>
          </details>
        )}
        <div className="grid grid-cols-3 gap-2 mono text-center">
          <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[15px] text-ops-cyan">{cov ? cov.survey_coverage_pct.toFixed(1) : "0.0"}%</div><div className="text-[9px] text-ops-dim">AREA OBSERVED</div></div>
          <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[15px]">{cov ? (cov.total_points / 1000).toFixed(0) : 0}k</div><div className="text-[9px] text-ops-dim">SCAN POINTS</div></div>
          <div className="rounded bg-black/30 border border-ops-line py-1"><div className="text-[15px]">{cov?.scans ?? 0}</div><div className="text-[9px] text-ops-dim">SCANS</div></div>
        </div>
      </div>
      <div className="p-3 flex-1 overflow-y-auto scroll space-y-2">
        <div className="hdr">Reconnaissance swarm</div>
        {drones.map((d) => <DroneCard key={d.drone_id} d={d} />)}
        {s.retaskLog.length > 0 && (
          <Section title="Coordinator retasking log" className="pt-1">
            {s.retaskLog.slice(-3).reverse().map((r, i) => (
              <div key={i} className="rounded border border-cyan-900/60 bg-cyan-950/20 p-2 mb-1.5 text-[10.5px]">
                <div><b className="text-ops-cyan">{r.drone_id}</b> ← {r.by}</div>
                <div className="text-ops-text/80">{r.reason}{r.road_name ? `: ${r.road_name}` : ""}</div>
                {r.candidates && (
                  <table className="w-full mt-1 mono text-[9.5px] text-ops-dim">
                    <thead><tr><th className="text-left">candidate</th><th>gain</th><th>cost</th><th>score</th></tr></thead>
                    <tbody>{r.candidates.slice(0, 4).map((c: any, j: number) => (
                      <tr key={j} className={j === 0 ? "text-ops-text" : ""}><td className="truncate max-w-[110px]">{c.road_name}{c.is_bridge ? " (bridge)" : ""}</td><td className="text-center">{c.gain}</td><td className="text-center">{c.cost}</td><td className="text-center">{c.score}</td></tr>
                    ))}</tbody>
                  </table>
                )}
              </div>
            ))}
          </Section>
        )}
        <KV k="Sim parameters" v="7 m/s · 40 m AGL · FOV 70° · 1 Hz lidar" />
        <div className="text-[9.5px] text-ops-dim italic">Simulation parameters only — not approved flight plans or operational safety limits.</div>
      </div>
    </div>
  );
}
