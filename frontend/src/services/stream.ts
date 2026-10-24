import { useMission } from "../store/mission";
import { api } from "./api";
import { bus } from "./bus";
import type { MissionEvent } from "../types";

let ws: WebSocket | null = null;
let retry = 0;
let resyncing = false;
const onResync = new Set<() => void>();

export function onSnapshotReload(fn: () => void) {
  onResync.add(fn);
  return () => onResync.delete(fn);
}

export async function reloadSnapshot() {
  const snap = await api.mission();
  useMission.getState().applySnapshot(snap);
  onResync.forEach((f) => f());
  return snap;
}

/** Initial snapshot + ordered events. On reconnect or mission reset the client rebuilds
 * from a fresh snapshot, so state is always reconstructible. */
export function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/mission`);
  ws.onopen = async () => {
    retry = 0;
    useMission.getState().set({ wsConnected: true });
  };
  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "hello") {
      const st = useMission.getState();
      if (!st.loaded || e.mission_id !== st.missionId || e.seq !== st.lastSeq) resync();
      return;
    }
    const ev = e as MissionEvent;
    const st = useMission.getState();
    if (ev.type === "mission.reset") {
      resync();
      return;
    }
    if (resyncing) return;
    if (st.missionId && ev.mission_id !== st.missionId) return;
    st.applyEvent(ev);
    bus.emit(ev);
  };
  ws.onclose = () => {
    useMission.getState().set({ wsConnected: false });
    retry = Math.min(retry + 1, 6);
    setTimeout(connect, 500 * retry);
  };
}

async function resync() {
  resyncing = true;
  try {
    await reloadSnapshot();
  } finally {
    resyncing = false;
  }
}
