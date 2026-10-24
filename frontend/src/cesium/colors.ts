import * as Cesium from "cesium";

export const STATUS_COLOR: Record<string, string> = {
  UNKNOWN: "#9aa4b2",
  OBSERVED_PASSABLE: "#2dd4bf",
  VERIFIED_PASSABLE: "#22c55e",
  SUSPECTED_BLOCKED: "#fb923c",
  CONFIRMED_BLOCKED: "#ff3b3b",
};

export const STATUS_ALPHA: Record<string, number> = {
  UNKNOWN: 0.35,
  OBSERVED_PASSABLE: 0.85,
  VERIFIED_PASSABLE: 1,
  SUSPECTED_BLOCKED: 1,
  CONFIRMED_BLOCKED: 1,
};

export const statusColor = (s: string) => Cesium.Color.fromCssColorString(STATUS_COLOR[s] || STATUS_COLOR.UNKNOWN).withAlpha(STATUS_ALPHA[s] ?? 0.4);

/** Point colours: lidar returns tinted by simulated semantic class, change points hot. */
const CLASS_RGB: Record<number, [number, number, number]> = {
  0: [0.16, 0.85, 0.82], // ground
  1: [0.75, 0.86, 1.0], // road
  2: [0.66, 0.55, 0.98], // building
  3: [0.23, 0.51, 0.96], // water
  4: [1.0, 0.95, 0.75], // bridge deck
  5: [1.0, 0.45, 0.15], // debris
  6: [1.0, 0.55, 0.1], // fallen tree
  7: [1.0, 0.2, 0.2], // washout
  8: [0.3, 0.6, 1.0], // flood water
  9: [0.3, 0.9, 0.5],
};

export function pointColor(cls: number, anom: number, hNorm: number): Cesium.Color {
  if (anom) return new Cesium.Color(1.0, 0.25 + 0.2 * hNorm, 0.18, 1);
  const c = CLASS_RGB[cls] || CLASS_RGB[0];
  const k = 0.55 + 0.6 * hNorm;
  return new Cesium.Color(Math.min(1, c[0] * k), Math.min(1, c[1] * k), Math.min(1, c[2] * k), 0.95);
}
