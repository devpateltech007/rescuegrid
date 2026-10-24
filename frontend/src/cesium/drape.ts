import * as Cesium from "cesium";
import { dem } from "./terrain";

const M_PER_DEG = 111_320;

/** Densify a lon/lat polyline every `step` metres and drape it on the real DEM.
 * Short bridge edges are drawn as a straight deck between their end heights
 * (the bare-earth DEM has no bridge decks). */
export function drape(coords: number[][], lift = 1.6, bridge = false, step = 8): Cesium.Cartesian3[] {
  const out: number[] = [];
  const lat0 = coords[0][1];
  const kx = M_PER_DEG * Math.cos((lat0 * Math.PI) / 180);
  let total = 0;
  const seg: number[] = [];
  for (let i = 1; i < coords.length; i++) {
    const d = Math.hypot((coords[i][0] - coords[i - 1][0]) * kx, (coords[i][1] - coords[i - 1][1]) * M_PER_DEG);
    seg.push(d);
    total += d;
  }
  const h0 = dem.height(coords[0][0], coords[0][1]);
  const h1 = dem.height(coords[coords.length - 1][0], coords[coords.length - 1][1]);
  let acc = 0;
  for (let i = 1; i < coords.length; i++) {
    const [ax, ay] = coords[i - 1];
    const [bx, by] = coords[i];
    const n = Math.max(1, Math.ceil(seg[i - 1] / step));
    for (let k = i === 1 ? 0 : 1; k <= n; k++) {
      const t = k / n;
      const lon = ax + (bx - ax) * t;
      const lat = ay + (by - ay) * t;
      const along = (acc + seg[i - 1] * t) / Math.max(total, 1e-6);
      const h = bridge ? h0 + (h1 - h0) * along + 1.0 : dem.height(lon, lat);
      out.push(lon, lat, h + lift);
    }
    acc += seg[i - 1];
  }
  return Cesium.Cartesian3.fromDegreesArrayHeights(out);
}

export function lengthM(coords: number[][]): number {
  const kx = M_PER_DEG * Math.cos((coords[0][1] * Math.PI) / 180);
  let L = 0;
  for (let i = 1; i < coords.length; i++) L += Math.hypot((coords[i][0] - coords[i - 1][0]) * kx, (coords[i][1] - coords[i - 1][1]) * M_PER_DEG);
  return L;
}
