import * as Cesium from "cesium";

/** Real USGS 3DEP heights served by the backend as quantised uint16 grids (lon/lat aligned).
 * A Cesium CustomHeightmapTerrainProvider samples them per tile — no Cesium ion token needed. */
export interface Grid {
  w: number;
  s: number;
  e: number;
  n: number;
  W: number;
  H: number;
  z: Float32Array;
  min: number;
  max: number;
}

async function loadGrid(name: string): Promise<Grid> {
  const hdr = await (await fetch(`/api/geo/terrain/${name}.json`)).json();
  const buf = await (await fetch(`/api/geo/terrain/${name}.u16`)).arrayBuffer();
  const q = new Uint16Array(buf);
  const z = new Float32Array(q.length);
  for (let i = 0; i < q.length; i++) z[i] = hdr.offset_m + q[i] * hdr.scale;
  const b = hdr.bounds;
  return { w: b.west, s: b.south, e: b.east, n: b.north, W: hdr.width, H: hdr.height, z, min: hdr.min_m, max: hdr.max_m };
}

function sampleGrid(g: Grid, lon: number, lat: number): number {
  let fx = ((lon - g.w) / (g.e - g.w)) * g.W - 0.5;
  let fy = ((g.n - lat) / (g.n - g.s)) * g.H - 0.5;
  fx = Math.min(Math.max(fx, 0), g.W - 1.001);
  fy = Math.min(Math.max(fy, 0), g.H - 1.001);
  const x0 = Math.floor(fx), y0 = Math.floor(fy);
  const tx = fx - x0, ty = fy - y0;
  const i = y0 * g.W + x0;
  const a = g.z[i] * (1 - tx) + g.z[i + 1] * tx;
  const b = g.z[i + g.W] * (1 - tx) + g.z[i + g.W + 1] * tx;
  return a * (1 - ty) + b * ty;
}

const inside = (g: Grid, lon: number, lat: number) => lon >= g.w && lon <= g.e && lat >= g.s && lat <= g.n;

export class DemTerrain {
  fine!: Grid;
  coarse!: Grid;

  async load() {
    [this.fine, this.coarse] = await Promise.all([loadGrid("dem_fine"), loadGrid("dem_coarse")]);
  }

  /** Height in metres (NAVD88 orthometric, used consistently as the scene height datum). */
  height(lon: number, lat: number): number {
    if (inside(this.fine, lon, lat)) return sampleGrid(this.fine, lon, lat);
    const v = sampleGrid(this.coarse, lon, lat);
    if (inside(this.coarse, lon, lat)) return v;
    // fade the clamped edge value towards 0 far outside the context DEM
    const c = this.coarse;
    const dx = Math.max(c.w - lon, 0, lon - c.e);
    const dy = Math.max(c.s - lat, 0, lat - c.n);
    const d = Math.hypot(dx, dy);
    return v * Math.max(0, 1 - d / 0.35);
  }

  provider(): Cesium.TerrainProvider {
    const size = 65;
    const tiling = new Cesium.GeographicTilingScheme();
    return new Cesium.CustomHeightmapTerrainProvider({
      width: size,
      height: size,
      tilingScheme: tiling,
      callback: (x: number, y: number, level: number) => {
        const r = tiling.tileXYToRectangle(x, y, level);
        const w = Cesium.Math.toDegrees(r.west), e = Cesium.Math.toDegrees(r.east);
        const s = Cesium.Math.toDegrees(r.south), n = Cesium.Math.toDegrees(r.north);
        const out = new Float32Array(size * size);
        for (let j = 0; j < size; j++) {
          const lat = n - ((n - s) * j) / (size - 1);
          for (let i = 0; i < size; i++) {
            const lon = w + ((e - w) * i) / (size - 1);
            out[j * size + i] = this.height(lon, lat);
          }
        }
        return out;
      },
    });
  }
}

export const dem = new DemTerrain();
