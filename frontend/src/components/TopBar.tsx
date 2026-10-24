import { Activity, Cloud, CloudOff, Pause, Play, RotateCcw, SkipForward, Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useMission } from "../store/mission";

export default function TopBar() {
  const s = useMission();
  const [sys, setSys] = useState<any>(null);
  useEffect(() => {
    const f = () => api.status().then(setSys).catch(() => setSys(null));
    f();
    const t = setInterval(f, 5000);
    return () => clearInterval(t);
  }, []);
  const br = sys?.bedrock;
  const brOk = br?.state === "OK" || br?.state === "UNVERIFIED";
  const s3ok = sys?.s3?.state === "OK";
  const clock = s.simTime ? new Date(s.simTime) : null;
  const clockStr = clock
    ? clock.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : "—";
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e: any) {
      s.toast({ tone: "red", title: "Action failed", body: e.message });
    }
  };
  return (
    <div className="h-12 flex items-center gap-4 px-4 border-b border-ops-line bg-[#0d1014] relative z-20">
      <div className="flex items-center gap-2.5">
        <svg width="26" height="26" viewBox="0 0 32 32"><path d="M5 25 L16 5 L27 25 Z" fill="none" stroke="#22d3ee" strokeWidth="2.6" /><circle cx="16" cy="19" r="3.2" fill="#ff4d4f" /></svg>
        <div className="leading-tight">
          <div className="font-extrabold tracking-[0.18em] text-[13px]">RESCUEGRID <span className="text-ops-cyan">3D</span></div>
          <div className="text-[9.5px] text-ops-dim tracking-wider">AUTONOMOUS DISASTER RECONNAISSANCE & RESCUE INTELLIGENCE</div>
        </div>
      </div>
      <div className="h-7 w-px bg-ops-line" />
      <div className="leading-tight">
        <div className="text-[11px] font-semibold"><span className="chip text-amber-200 border-amber-700 bg-amber-950/50 mr-2">HISTORICAL REPLAY · SIMULATION</span>Hurricane Helene · Swannanoa, NC</div>
        <div className="text-[10px] text-ops-dim mono">MISSION {s.missionId} · Whitson Ave Bridge corridor · {s.scenario?.replay_window}</div>
      </div>
      <div className="flex-1" />
      <div className="text-right leading-tight">
        <div className="hdr">Simulation clock (EDT)</div>
        <div className="mono text-[13px] text-ops-cyan">{clockStr}</div>
      </div>
      <div className="h-7 w-px bg-ops-line" />
      <div className="flex items-center gap-3 text-[10.5px]">
        <span className={`flex items-center gap-1 ${brOk ? "text-ops-green" : "text-ops-red"}`} title={br?.last_error || br?.model_id}>
          {brOk ? <Cloud size={13} /> : <CloudOff size={13} />} BEDROCK {br ? br.state : "…"}
        </span>
        <span className={`flex items-center gap-1 ${s3ok ? "text-ops-green" : sys?.s3?.state === "DISABLED" ? "text-ops-dim" : "text-ops-amber"}`} title={sys?.s3?.last_error || sys?.s3?.bucket}>
          <Activity size={13} /> S3 {sys?.s3?.state ?? "…"}
        </span>
        <span className={`flex items-center gap-1 ${s.wsConnected ? "text-ops-green" : "text-ops-red"}`}>
          {s.wsConnected ? <Wifi size={13} /> : <WifiOff size={13} />} LINK
        </span>
      </div>
      <div className="h-7 w-px bg-ops-line" />
      <div className="flex items-center gap-1.5">
        {s.missionState === "BRIEFING" && (
          <button className="btn btn-cyan" onClick={() => act(api.start)}><Play size={13} /> Launch drones</button>
        )}
        {s.missionState === "RUNNING" && <button className="btn" onClick={() => act(api.pause)}><Pause size={13} /> Pause</button>}
        {s.missionState === "PAUSED" && <button className="btn btn-cyan" onClick={() => act(api.resume)}><Play size={13} /> Resume</button>}
        <button className="btn" title="Advance one simulated second" disabled={s.missionState === "RUNNING"} onClick={() => act(() => api.step(1))}><SkipForward size={13} /></button>
        <div className="flex rounded-md overflow-hidden border border-ops-line">
          {[1, 4, 10].map((v) => (
            <button key={v} onClick={() => act(() => api.speed(v))} className={`px-2 py-1 text-[11px] mono font-bold ${s.speed === v ? "bg-ops-cyan text-black" : "bg-ops-panel2 text-ops-dim hover:text-white"}`}>{v}x</button>
          ))}
        </div>
        <button className="btn" title="Reset mission" onClick={() => confirm("Reset the mission? Scan results are cleared; the decision audit log is kept.") && act(api.reset)}><RotateCcw size={13} /></button>
      </div>
    </div>
  );
}
