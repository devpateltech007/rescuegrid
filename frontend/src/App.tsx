import { useEffect } from "react";
import BottomPanel from "./components/BottomPanel";
import LeftPanel from "./components/LeftPanel";
import RightPanel from "./components/RightPanel";
import TopBar from "./components/TopBar";
import Viewport from "./components/Viewport";
import { connect, reloadSnapshot } from "./services/stream";
import { useMission } from "./store/mission";

export default function App() {
  const loaded = useMission((s) => s.loaded);
  useEffect(() => {
    reloadSnapshot().then(connect).catch((e) => console.error(e));
    // exposed for the scripted demo/headless capture (UI selection only; no privileged actions)
    window.__rg = { select: useMission.getState().select, set: useMission.getState().set };
  }, []);
  if (!loaded) return <div className="h-full flex items-center justify-center mono text-ops-cyan">Connecting to RESCUEGRID mission server…</div>;
  return (
    <div className="h-full flex flex-col">
      <TopBar />
      <div className="flex-1 flex min-h-0">
        <LeftPanel />
        <div className="flex-1 flex flex-col min-w-0">
          <Viewport />
          <BottomPanel />
        </div>
        <RightPanel />
      </div>
    </div>
  );
}
