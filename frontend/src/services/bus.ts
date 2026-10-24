import type { MissionEvent } from "../types";

type Fn = (e: MissionEvent) => void;
const subs = new Map<string, Set<Fn>>();

/** Lightweight pub/sub so high-frequency events go straight to Cesium layers without React re-renders. */
export const bus = {
  on(type: string, fn: Fn) {
    if (!subs.has(type)) subs.set(type, new Set());
    subs.get(type)!.add(fn);
    return () => subs.get(type)!.delete(fn);
  },
  emit(e: MissionEvent) {
    subs.get(e.type)?.forEach((f) => f(e));
    subs.get("*")?.forEach((f) => f(e));
  },
};
