import { Building2, Clapperboard, Eye, Layers3, Map as MapIcon, Mountain, Play, Radar, Route, ScanLine, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { STATUS_COLOR } from "../cesium/colors";
import { world3d } from "../cesium/world";
import { api } from "../services/api";
import { bus } from "../services/bus";
import { useMission } from "../store/mission";
import { KV, Prov, Status, fmtDist, fmtTime } from "./ui";

function LayerBar() {
  const s = useMission();
  const L = s.layers;
  const main: [keyof typeof L, string, JSX.Element][] = [
    ["base", "Base Terrain", <Mountain size={13} />],
    ["scan", "Drone Scan", <ScanLine size={13} />],
    ["recon", "Reconstructed Surface", <Layers3 size={13} />],
    ["hazards", "Hazard Intelligence", <ShieldAlert size={13} />],
  ];
  const extra: [keyof typeof L, string, JSX.Element][] = [
    ["noaa", "NOAA 2024-10-05", <MapIcon size={12} />],
    ["buildings", "Buildings", <Building2 size={12} />],
    ["roads", "Road status", <Route size={12} />],
    ["sectors", "Sectors", <Radar size={12} />],
  ];
  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-1.5">
      <div className="panel rounded-lg flex p-1 gap-1">
        {main.map(([k, label, icon], i) => (
          <button key={k} onClick={() => s.toggleLayer(k)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11.5px] font-semibold transition ${L[k] ? "bg-cyan-500/15 text-cyan-200 border border-cyan-700/60" : "text-ops-dim border border-transparent hover:text-white"}`}>
            {icon}{label}{i < main.length - 1 && <span className="sr-only">|</span>}
          </button>
        ))}
      </div>
      <div className="panel rounded-md flex p-0.5 gap-0.5">
        {extra.map(([k, label, icon]) => (
          <button key={k} onClick={() => s.toggleLayer(k)} className={`flex items-center gap-1 px-2 py-1 rounded text-[10.5px] ${L[k] ? "text-white" : "text-ops-dim/70 line-through"}`}>{icon}{label}</button>
        ))}
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 z-10 panel rounded-lg p-2 text-[10px] space-y-1 w-[200px]">
      <div className="hdr">Road access status</div>
      {Object.entries(STATUS_COLOR).map(([k, c]) => (
        <div key={k} className="flex items-center gap-2"><span className="w-5 h-1.5 rounded" style={{ background: c }} />{k.replace(/_/g, " ")}</div>
      ))}
      <div className="hdr pt-1">Routes</div>
      <div className="flex items-center gap-2"><span className="w-5 h-1.5 rounded bg-green-400 shadow-[0_0_8px_#22c55e]" />Recommended</div>
      <div className="flex items-center gap-2"><span className="w-5 h-1.5 rounded bg-[repeating-linear-gradient(90deg,#ff3b3b_0_5px,transparent_5px_8px)]" />Previous (invalidated)</div>
      <div className="flex items-center gap-2"><span className="w-5 h-1.5 rounded bg-amber-400" />Unverified on route</div>
      <div className="hdr pt-1">Scan points</div>
      <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-cyan-300" />Lidar return · <span className="w-2 h-2 rounded-full bg-red-500" />Change vs pre-storm</div>
    </div>
  );
}

function RoadInspector() {
  const s = useMission();
  if (s.selected.kind !== "road" || !s.selected.id) return null;
  const p = world3d.roadProps(s.selected.id);
  if (!p) return null;
  const status = s.roadStatus[s.selected.id] || "UNKNOWN";
  const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
  return (
    <div className="absolute top-24 right-3 z-10 panel rounded-lg p-3 w-[280px] space-y-1 animate-slideIn">
      <div className="flex items-start justify-between"><div><div className="hdr">Road segment</div><div className="font-semibold text-[13px]">{p.road_name}</div></div><button onClick={() => s.select(null, null)}><X size={14} /></button></div>
      <div className="flex gap-1 flex-wrap"><Status s={status} /><Prov p="CURRENT_BASEMAP" />{p.is_bridge && <span className="chip text-yellow-200 border-yellow-700">BRIDGE</span>}{cur?.edge_ids.includes(p.edge_id) && <span className="chip text-green-200 border-green-700">ON ROUTE</span>}</div>
      <KV k="Edge id" v={<span className="text-[9.5px]">{p.edge_id}</span>} />
      <KV k="OSM way(s)" v={p.osm_way_ids.join(", ")} />
      <KV k="Class" v={p.road_class} />
      <KV k="Length" v={fmtDist(p.length_m)} />
      <KV k="Speed assumption" v={`${p.speed_assumption_kph} km/h`} />
      <KV k="Direction" v={p.oneway ? "one-way" : "two-way"} />
      <div className="text-[9.5px] text-ops-dim italic pt-1">Geometry: OpenStreetMap (current basemap). Status reflects simulated sensing, Bedrock suggestions and commander decisions only.</div>
    </div>
  );
}

function Director() {
  const s = useMission();
  const [open, setOpen] = useState(false);
  const [replayP, setReplayP] = useState<number | null>(null);
  const sc = s.scenario;
  const bridge = sc?.pois?.[0];
  const mid = sc ? { lon: (sc.staging.lon + sc.destination.lon) / 2 - 0.004, lat: (sc.staging.lat + sc.destination.lat) / 2 } : null;
  const autoRef = useRef(false);
  useEffect(() => {
    // Director mode: when the bridge incident appears, fly the camera down to it.
    const off = bus.on("incident.created", (e) => {
      if (!autoRef.current || !e.payload.is_bridge || !bridge) return;
      world3d.cam.flyToLonLat(bridge.lon, bridge.lat, 160, 205, -33, 3);
    });
    return () => void off();
  }, [bridge]);
  useEffect(() => {
    const off = bus.on("route.recalculated", (e) => {
      if (!autoRef.current || !bridge || !mid || e.payload.status !== "OK" || !e.payload.previous || e.payload.previous.route_id === e.payload.current.route_id) return;
      world3d.cam.bridgeReveal(bridge, mid);
    });
    return () => void off();
  }, [bridge, mid]);
  const runDirector = async () => {
    autoRef.current = true;
    await api.autoPause(true);
    s.set({ autoPause: true });
    if (mid) await world3d.cam.wideValley(mid, 3);
    if (s.missionState === "BRIEFING") await api.start();
    await api.speed(4);
    setTimeout(() => world3d.cam.followBravo(14000), 2500);
  };
  return (
    <div className="absolute bottom-3 right-3 z-10 flex flex-col items-end gap-1.5">
      {open && (
        <div className="panel rounded-lg p-2 w-[240px] space-y-1.5 animate-slideIn">
          <div className="hdr">Demo director · camera</div>
          <button className="btn btn-cyan w-full" onClick={runDirector}><Play size={12} /> Run storyline (auto-pause at decisions)</button>
          <button className="btn w-full" onClick={() => mid && world3d.cam.wideValley(mid)}>1 · Wide valley view</button>
          <button className="btn w-full" onClick={() => world3d.cam.followBravo(12000)}>2 · Follow Bravo to bridge</button>
          <button className="btn w-full" onClick={() => bridge && mid && world3d.cam.bridgeReveal(bridge, mid)}>3 · Bridge dive → route reveal</button>
          <button className="btn w-full" disabled={replayP !== null} onClick={async () => { setReplayP(0); await world3d.dyn.replay(12000, setReplayP); setReplayP(null); }}>
            <Clapperboard size={12} /> {replayP !== null ? `Replaying scan… ${Math.round(replayP * 100)}%` : "Replay scan growth (12 s)"}
          </button>
          <label className="flex items-center gap-2 text-[10.5px]"><input type="checkbox" checked={s.autoPause} onChange={async (e) => { await api.autoPause(e.target.checked); s.set({ autoPause: e.target.checked }); }} /> Auto-pause when a decision is required</label>
          <label className="flex items-center gap-1 text-[10.5px]">Operator <input value={s.operator} maxLength={60} onChange={(e) => { localStorage.setItem("rg.operator", e.target.value); s.set({ operator: e.target.value }); }} className="flex-1 bg-black/40 border border-ops-line rounded px-1.5 py-0.5 text-[10.5px]" /></label>
        </div>
      )}
      <button className="btn btn-cyan" onClick={() => setOpen(!open)}><Clapperboard size={13} /> Director</button>
    </div>
  );
}

function Toasts() {
  const toasts = useMission((s) => s.toasts);
  const dismiss = useMission((s) => s.dismiss);
  const C: Record<string, string> = { red: "border-red-600 bg-red-950/85", amber: "border-amber-600 bg-amber-950/85", green: "border-green-600 bg-green-950/85", cyan: "border-cyan-600 bg-cyan-950/85" };
  return (
    <div className="absolute top-24 left-3 z-20 space-y-1.5 w-[300px]">
      {toasts.map((t) => (
        <div key={t.id} onClick={() => dismiss(t.id)} className={`rounded-lg border px-3 py-2 cursor-pointer animate-slideIn backdrop-blur ${C[t.tone]}`}>
          <div className="text-[12px] font-bold">{t.title}</div>
          {t.body && <div className="text-[11px] opacity-90">{t.body}</div>}
        </div>
      ))}
    </div>
  );
}

function Briefing() {
  const s = useMission();
  if (s.missionState !== "BRIEFING" || !s.scenario) return null;
  const cur = s.currentRouteId ? s.routes[s.currentRouteId] : null;
  return (
    <div className="absolute bottom-16 left-1/2 -translate-x-1/2 z-10 panel rounded-xl p-4 w-[640px] glow-cyan animate-slideIn">
      <div className="flex items-center gap-2"><span className="chip text-amber-200 border-amber-700 bg-amber-950/50">STAGE 1 · DISASTER BRIEFING</span><span className="text-[11px] text-ops-dim mono">{fmtTime(s.simTime)} EDT · 28 Sep 2024 (replay)</span></div>
      <div className="text-[15px] font-bold mt-1.5">Hurricane Helene — Swannanoa River corridor, Buncombe County NC</div>
      <div className="text-[11.5px] text-ops-text/85 leading-snug mt-1">
        Catastrophic flooding has cut communications and damaged roads and bridges. Buncombe County's after-action report cites 43 storm-related deaths in the county. Road conditions inside the 2 × 2 km survey area are <b className="text-ops-amber">unknown</b>. Ground teams cannot safely reach the area, so a three-drone swarm will survey it and the commander will decide from drone evidence.
      </div>
      {cur && (
        <div className="mt-2 rounded border border-amber-800/60 bg-amber-950/20 p-2 text-[11px]">
          <b className="text-amber-200">Provisional route</b> S-1 → R-7: {cur.road_names.join(" → ")} · <span className="mono">{fmtDist(cur.distance_m)}</span> · <span className="text-ops-amber">{cur.unverified_edge_count} unverified segments</span> (crosses the Whitson Avenue Bridge)
        </div>
      )}
      <div className="flex items-center justify-between mt-2.5">
        <div className="flex gap-1"><Prov p="OFFICIAL_HISTORICAL_RECORD" /><Prov p="SIMULATED_SCENARIO" /><Prov p="CURRENT_BASEMAP" /></div>
        <button className="btn btn-cyan" onClick={() => api.start()}><Play size={13} /> Launch reconnaissance</button>
      </div>
      <div className="text-[9.5px] text-ops-dim mt-1.5 italic">{s.scenario.disclaimer}</div>
    </div>
  );
}

function DegradedBanner() {
  const d = useMission((s) => s.degraded);
  const last = d[d.length - 1];
  if (!last) return null;
  return (
    <div className="absolute top-[86px] left-1/2 -translate-x-1/2 z-10 rounded-md border border-red-700 bg-red-950/90 px-3 py-1 text-[11px] text-red-100">
      <b>DEGRADED · {last.component}</b> — {last.reason?.slice(0, 140)} · Simulation, 3D and routing remain available.
    </div>
  );
}

export default function Viewport() {
  const ref = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Loading real USGS 3DEP terrain…");
  const loaded = useMission((s) => s.loaded);
  const follow = useMission((s) => s.followDrone);
  useEffect(() => {
    if (!loaded || !ref.current || world3d.ready) return;
    world3d.init(ref.current).then(() => setStatus("")).catch((e) => setStatus(`3D init failed: ${e.message}`));
  }, [loaded]);
  return (
    <div className="relative flex-1 min-w-0 bg-black">
      <div ref={ref} className="absolute inset-0" />
      {status && <div className="absolute inset-0 flex items-center justify-center text-ops-cyan mono text-sm scanlines">{status}</div>}
      <LayerBar />
      <Legend />
      <RoadInspector />
      <Director />
      <Toasts />
      <Briefing />
      <DegradedBanner />
      {follow && <div className="absolute top-24 left-1/2 -translate-x-1/2 z-10 chip text-cyan-200 border-cyan-600 bg-cyan-950/80 !text-[11px]"><Eye size={12} /> FOLLOWING {follow} · right-click to release</div>}
    </div>
  );
}
