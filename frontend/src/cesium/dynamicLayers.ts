import * as Cesium from "cesium";
import type { DroneInfo, Incident, Observation, RoutePlan, ScanBatch, Telemetry, Tile } from "../types";
import { pointColor } from "./colors";
import { drape } from "./drape";
import { dem } from "./terrain";

const POINT_BUDGET = 650_000;
const CHUNK = 40_000;

interface DroneVis {
  entity: Cesium.Entity;
  cone: Cesium.Entity;
  trail: Cesium.Entity;
  beam: Cesium.Entity;
  from: Cesium.Cartesian3;
  to: Cesium.Cartesian3;
  t0: number;
  period: number;
  heading: number;
  pitch: number;
  roll: number;
  agl: number;
  trailPts: Cesium.Cartesian3[];
  state: string;
  color: Cesium.Color;
  target: [number, number] | null;
}

export class DynamicLayers {
  viewer: Cesium.Viewer;
  drones = new Map<string, DroneVis>();
  pointCols: Cesium.PointPrimitiveCollection[] = [];
  pointBatches: { seq: number; col: Cesium.PointPrimitiveCollection; start: number; count: number }[] = [];
  totalPoints = 0;
  tiles = new Map<string, Cesium.Primitive[]>();
  tileOrder: string[] = [];
  hazards = new Map<string, Cesium.Entity>();
  changeMarks: Cesium.Entity[] = [];
  footprints: Cesium.Entity[] = [];
  routeEntities: Cesium.Entity[] = [];
  periodMs = 1000;
  hMin = 640;
  hMax = 760;
  show = { scan: true, recon: true, hazards: true };

  constructor(viewer: Cesium.Viewer) {
    this.viewer = viewer;
    viewer.scene.preRender.addEventListener(() => this.animate());
  }

  // ------------------------------------------------------------ drones
  initDrones(drones: DroneInfo[]) {
    for (const d of drones) {
      if (this.drones.has(d.drone_id)) continue;
      const color = Cesium.Color.fromCssColorString(d.color);
      const pos = Cesium.Cartesian3.fromDegrees(d.longitude, d.latitude, d.altitude_msl_m);
      const vis: DroneVis = {
        from: pos, to: pos, t0: performance.now(), period: this.periodMs, heading: d.heading_deg, pitch: 0, roll: 0,
        agl: d.altitude_agl_m, trailPts: [], state: d.flight_state, color, target: d.camera_target,
      } as unknown as DroneVis;
      const posProp = new Cesium.CallbackProperty(() => this.dronePos(vis), false) as unknown as Cesium.PositionProperty;
      vis.entity = this.viewer.entities.add({
        id: `drone-${d.drone_id}`,
        position: posProp,
        orientation: new Cesium.CallbackProperty(() => {
          const p = this.dronePos(vis);
          return Cesium.Transforms.headingPitchRollQuaternion(p, new Cesium.HeadingPitchRoll(
            Cesium.Math.toRadians(vis.heading - 90), Cesium.Math.toRadians(vis.pitch * 0.6), Cesium.Math.toRadians(vis.roll * 0.4)));
        }, false) as any,
        model: {
          uri: "/models/drone.glb", minimumPixelSize: 54, maximumScale: 40, scale: 5,
          color: color, colorBlendMode: Cesium.ColorBlendMode.MIX, colorBlendAmount: 0.35,
          silhouetteColor: color.withAlpha(0.9), silhouetteSize: 1.5,
        },
        label: {
          text: d.callsign.replace("Drone ", "").toUpperCase(), font: "700 12px 'JetBrains Mono', monospace",
          fillColor: color, outlineColor: Cesium.Color.BLACK, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -34), disableDepthTestDistance: Number.POSITIVE_INFINITY,
          showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0b0d10").withAlpha(0.7),
        },
        properties: { kind: "drone", drone_id: d.drone_id },
      });
      // sensor frustum: 4-sided pyramid (square FOV) from the drone to the ground
      vis.cone = this.viewer.entities.add({
        position: new Cesium.CallbackProperty(() => {
          const p = Cesium.Cartographic.fromCartesian(this.dronePos(vis));
          return Cesium.Cartesian3.fromRadians(p.longitude, p.latitude, p.height - vis.agl / 2);
        }, false) as unknown as Cesium.PositionProperty,
        orientation: new Cesium.CallbackProperty(() => Cesium.Transforms.headingPitchRollQuaternion(
          this.dronePos(vis), new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(vis.heading + 45), 0, 0)), false) as any,
        cylinder: {
          length: new Cesium.CallbackProperty(() => Math.max(vis.agl, 1), false),
          topRadius: 0.3,
          bottomRadius: new Cesium.CallbackProperty(() => Math.max(vis.agl, 1) * Math.tan(Cesium.Math.toRadians(35)) * Math.SQRT2, false),
          slices: 4,
          material: color.withAlpha(0.13),
          outline: true,
          outlineColor: color.withAlpha(0.55),
          numberOfVerticalLines: 4,
        },
      });
      (vis.cone as any).show = new Cesium.CallbackProperty(() => this.show.scan && ["SURVEYING", "INSPECTING", "RETURNING"].includes(vis.state), false);
      vis.trail = this.viewer.entities.add({
        polyline: {
          positions: new Cesium.CallbackProperty(() => vis.trailPts, false),
          width: 3,
          material: new Cesium.PolylineGlowMaterialProperty({ color: color.withAlpha(0.85), glowPower: 0.25, taperPower: 0.6 }),
        },
      });
      // camera gimbal beam to the inspection target
      vis.beam = this.viewer.entities.add({
        polyline: {
          positions: new Cesium.CallbackProperty(() => {
            if (!vis.target) return [];
            const t = Cesium.Cartesian3.fromDegrees(vis.target[0], vis.target[1], dem.height(vis.target[0], vis.target[1]) + 1);
            return [this.dronePos(vis), t];
          }, false),
          width: 2,
          material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.WHITE.withAlpha(0.8), dashLength: 8 }),
        },
      });
      vis.beam.polyline!.show = new Cesium.CallbackProperty(() => vis.state === "INSPECTING" && !!vis.target, false);
      this.drones.set(d.drone_id, vis);
    }
  }

  dronePos(v: DroneVis): Cesium.Cartesian3 {
    const f = Math.min(1, (performance.now() - v.t0) / v.period);
    return Cesium.Cartesian3.lerp(v.from, v.to, f, new Cesium.Cartesian3());
  }

  telemetry(t: Telemetry) {
    const v = this.drones.get(t.drone_id);
    if (!v) return;
    v.from = this.dronePos(v);
    v.to = Cesium.Cartesian3.fromDegrees(t.longitude, t.latitude, t.altitude_msl_m);
    v.t0 = performance.now();
    v.period = this.periodMs;
    v.heading = t.heading_deg;
    v.pitch = t.pitch_deg;
    v.roll = t.roll_deg;
    v.agl = t.altitude_agl_m;
    v.state = t.flight_state;
    v.target = t.camera_target;
    if (t.flight_state !== "IDLE") {
      v.trailPts.push(v.to);
      if (v.trailPts.length > 900) v.trailPts.shift();
    }
  }

  dronePosition(id: string) {
    const v = this.drones.get(id);
    return v ? this.dronePos(v) : null;
  }
  droneHeading(id: string) {
    return this.drones.get(id)?.heading ?? 0;
  }

  animate() {
    /* positions are callback-driven; nothing else per frame */
  }

  // ------------------------------------------------------------ points
  addScan(b: ScanBatch, seq = 0) {
    const [rl, ra] = b.ref;
    const n = b.points.length / b.stride;
    let col = this.pointCols[this.pointCols.length - 1];
    if (!col || col.length + n > CHUNK) {
      col = this.viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection({ blendOption: Cesium.BlendOption.OPAQUE })) as Cesium.PointPrimitiveCollection;
      col.show = this.show.scan;
      this.pointCols.push(col);
    }
    const start = col.length;
    for (let i = 0; i < n; i++) {
      const k = i * b.stride;
      const lon = rl + b.points[k] / 1e6;
      const lat = ra + b.points[k + 1] / 1e6;
      const h = b.points[k + 2] / 100;
      const hn = Math.min(1, Math.max(0, (h - this.hMin) / (this.hMax - this.hMin)));
      col.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, h + 0.25),
        color: pointColor(b.points[k + 3], b.points[k + 4], hn),
        pixelSize: b.points[k + 4] ? 4 : 2.4,
      });
    }
    this.pointBatches.push({ seq, col, start, count: n });
    this.totalPoints += n;
    while (this.totalPoints > POINT_BUDGET && this.pointCols.length > 1) {
      const old = this.pointCols.shift()!;
      this.totalPoints -= old.length;
      this.pointBatches = this.pointBatches.filter((pb) => pb.col !== old);
      this.viewer.scene.primitives.remove(old);
    }
    // momentary footprint flash
    if (this.show.scan && b.footprint?.length === 4) {
      const e = this.viewer.entities.add({
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(b.footprint.flat()),
          material: Cesium.Color.fromCssColorString("#22d3ee").withAlpha(0.12),
          classificationType: Cesium.ClassificationType.TERRAIN,
        },
      });
      this.footprints.push(e);
      if (this.footprints.length > 6) this.viewer.entities.remove(this.footprints.shift()!);
    }
  }

  setPointsVisible(v: boolean) {
    this.show.scan = v;
    this.pointCols.forEach((c) => (c.show = v));
    if (!v) this.footprints.forEach((f) => this.viewer.entities.remove(f)), (this.footprints = []);
  }

  /** Playback: hide all points, then reveal batches in capture order. */
  async replay(durationMs: number, onProgress?: (f: number) => void) {
    const batches = [...this.pointBatches];
    batches.forEach((b) => { for (let i = 0; i < b.count; i++) b.col.get(b.start + i).show = false; });
    const tiles = [...this.tileOrder];
    tiles.forEach((t) => this.tiles.get(t)?.forEach((p) => (p.show = false)));
    const t0 = performance.now();
    return new Promise<void>((resolve) => {
      let bi = 0, ti = 0;
      const step = () => {
        const f = Math.min(1, (performance.now() - t0) / durationMs);
        const nb = Math.floor(f * batches.length);
        for (; bi < nb; bi++) { const b = batches[bi]; for (let i = 0; i < b.count; i++) b.col.get(b.start + i).show = true; }
        const nt = Math.floor(f * tiles.length);
        for (; ti < nt; ti++) this.tiles.get(tiles[ti])?.forEach((p) => (p.show = this.show.recon));
        onProgress?.(f);
        if (f < 1) requestAnimationFrame(step);
        else {
          for (; bi < batches.length; bi++) { const b = batches[bi]; for (let i = 0; i < b.count; i++) b.col.get(b.start + i).show = true; }
          tiles.forEach((t) => this.tiles.get(t)?.forEach((p) => (p.show = this.show.recon)));
          resolve();
        }
      };
      step();
    });
  }

  // ------------------------------------------------------------ reconstruction tiles
  upsertTile(t: Tile) {
    const old = this.tiles.get(t.tile_id);
    if (old) old.forEach((p) => this.viewer.scene.primitives.remove(p));
    else this.tileOrder.push(t.tile_id);
    const R = t.rows, C = t.cols;
    const pos: number[] = [];
    const idx: number[] = [];
    const changeIdx: number[] = [];
    const lines: number[] = [];
    const vid = new Int32Array(R * C).fill(-1);
    const dLon = (t.east - t.west) / (C - 1), dLat = (t.north - t.south) / (R - 1);
    for (let r = 0; r < R; r++)
      for (let c = 0; c < C; c++) {
        const h = t.heights[r * C + c];
        if (h === null) continue;
        const p = Cesium.Cartesian3.fromDegrees(t.west + c * dLon, t.south + r * dLat, h + 0.6);
        vid[r * C + c] = pos.length / 3;
        pos.push(p.x, p.y, p.z);
      }
    const change = new Set(t.change_cells.map((cc) => cc[0]));
    const cellsW = C - 1;
    for (let r = 0; r < R - 1; r++)
      for (let c = 0; c < C - 1; c++) {
        const a = vid[r * C + c], b = vid[r * C + c + 1], d = vid[(r + 1) * C + c], e = vid[(r + 1) * C + c + 1];
        if (a < 0 || b < 0 || d < 0 || e < 0) continue;
        const target = change.has(r * cellsW + c) ? changeIdx : idx;
        target.push(a, b, e, a, e, d);
        if (r % 2 === 0) lines.push(a, b);
        if (c % 2 === 0) lines.push(a, d);
      }
    const prims: Cesium.Primitive[] = [];
    const mk = (indices: number[], type: Cesium.PrimitiveType, color: Cesium.Color) => {
      if (!indices.length) return;
      const geom = new Cesium.Geometry({
        attributes: {
          position: new Cesium.GeometryAttribute({ componentDatatype: Cesium.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(pos) }),
        } as any,
        indices: pos.length / 3 > 65535 ? new Uint32Array(indices) : new Uint16Array(indices),
        primitiveType: type,
        boundingSphere: Cesium.BoundingSphere.fromVertices(pos),
      });
      const prim = this.viewer.scene.primitives.add(new Cesium.Primitive({
        geometryInstances: new Cesium.GeometryInstance({ geometry: geom, attributes: { color: Cesium.ColorGeometryInstanceAttribute.fromColor(color) }, id: { kind: "tile", tile_id: t.tile_id } }),
        appearance: new Cesium.PerInstanceColorAppearance({ flat: true, translucent: color.alpha < 1 }),
        asynchronous: false,
      })) as Cesium.Primitive;
      prim.show = this.show.recon && (type === Cesium.PrimitiveType.LINES || indices !== changeIdx || this.show.hazards);
      prims.push(prim);
    };
    if (pos.length) {
      mk(idx, Cesium.PrimitiveType.TRIANGLES, Cesium.Color.fromCssColorString("#06b6d4").withAlpha(0.22));
      mk(lines, Cesium.PrimitiveType.LINES, Cesium.Color.fromCssColorString("#67e8f9").withAlpha(0.35));
      mk(changeIdx, Cesium.PrimitiveType.TRIANGLES, Cesium.Color.fromCssColorString("#ff3b3b").withAlpha(0.75));
    }
    this.tiles.set(t.tile_id, prims);
  }

  setReconVisible(v: boolean) {
    this.show.recon = v;
    this.tiles.forEach((ps) => ps.forEach((p) => (p.show = v)));
  }

  // ------------------------------------------------------------ hazards / observations
  hazardIcon(color: string, label: string) {
    const c = document.createElement("canvas");
    c.width = 72;
    c.height = 72;
    const g = c.getContext("2d")!;
    g.shadowColor = color;
    g.shadowBlur = 16;
    g.fillStyle = "rgba(12,12,14,0.9)";
    g.strokeStyle = color;
    g.lineWidth = 4;
    g.beginPath();
    g.moveTo(36, 8); g.lineTo(64, 60); g.lineTo(8, 60); g.closePath();
    g.fill();
    g.stroke();
    g.shadowBlur = 0;
    g.fillStyle = color;
    g.font = "bold 30px Inter, Arial";
    g.textAlign = "center";
    g.fillText(label, 36, 54);
    return c.toDataURL();
  }

  upsertIncident(i: Incident) {
    const color =
      i.status === "CONFIRMED" ? "#ff3b3b" : i.status === "VERIFIED_PASSABLE" ? "#22c55e" : i.status === "REJECTED" ? "#7d8794" :
      i.suggested_accessibility === "LIKELY_BLOCKED" ? "#fb923c" : "#f5a524";
    const glyph = i.status === "VERIFIED_PASSABLE" ? "✓" : "!";
    const existing = this.hazards.get(i.incident_id);
    if (existing) this.viewer.entities.remove(existing);
    const h = dem.height(i.location.lon, i.location.lat);
    const pulse = i.status === "PENDING_REVIEW";
    const t0 = performance.now();
    const e = this.viewer.entities.add({
      id: `incident-${i.incident_id}`,
      position: Cesium.Cartesian3.fromDegrees(i.location.lon, i.location.lat, h + 18),
      billboard: {
        image: this.hazardIcon(color, glyph),
        width: 46, height: 46,
        scale: pulse ? (new Cesium.CallbackProperty(() => 1 + 0.18 * Math.sin((performance.now() - t0) / 220), false) as any) : 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: `${i.incident_id} · ${i.hazard_type.replace(/_/g, " ")}${i.status === "CONFIRMED" ? " · CONFIRMED" : i.status === "VERIFIED_PASSABLE" ? " · VERIFIED OK" : ""}`,
        font: "600 12px Inter, sans-serif", fillColor: Cesium.Color.fromCssColorString(color), outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cesium.Cartesian2(0, -36), disableDepthTestDistance: Number.POSITIVE_INFINITY,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0b0d10").withAlpha(0.8),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 6000),
      },
      polyline: {
        positions: [Cesium.Cartesian3.fromDegrees(i.location.lon, i.location.lat, h), Cesium.Cartesian3.fromDegrees(i.location.lon, i.location.lat, h + 16)],
        width: 2, material: Cesium.Color.fromCssColorString(color).withAlpha(0.8),
      },
      ellipse: i.status === "CONFIRMED" ? {
        semiMajorAxis: 28, semiMinorAxis: 28, material: Cesium.Color.fromCssColorString("#ff3b3b").withAlpha(0.22),
        classificationType: Cesium.ClassificationType.TERRAIN,
      } : undefined,
      properties: { kind: "incident", incident_id: i.incident_id },
      show: this.show.hazards,
    });
    this.hazards.set(i.incident_id, e);
  }

  addChangeMark(lon: number, lat: number) {
    const h = dem.height(lon, lat);
    this.changeMarks.push(this.viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, h + 2),
      ellipse: {
        // fixed radius (separately animated axes can momentarily violate major >= minor)
        semiMajorAxis: 16,
        semiMinorAxis: 16,
        material: new Cesium.ColorMaterialProperty(new Cesium.CallbackProperty(
          () => Cesium.Color.fromCssColorString("#f5a524").withAlpha(0.12 + 0.12 * (1 + Math.sin(performance.now() / 300))), false)),
        outline: false,
        classificationType: Cesium.ClassificationType.TERRAIN,
      },
      show: this.show.hazards,
    }));
  }

  addObservationFootprint(o: Observation) {
    if (!o.footprint?.length) return;
    this.changeMarks.push(this.viewer.entities.add({
      id: `obsfp-${o.observation_id}`,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([...o.footprint, o.footprint[0]].flat()),
        clampToGround: true, width: 2,
        material: Cesium.Color.fromCssColorString(o.source_type === "PUBLIC_HISTORICAL_IMAGERY" ? "#fde68a" : "#e879f9").withAlpha(0.9),
      },
      properties: { kind: "observation", observation_id: o.observation_id },
      show: this.show.hazards,
    }));
  }

  setHazardsVisible(v: boolean) {
    this.show.hazards = v;
    this.hazards.forEach((e) => (e.show = v));
    this.changeMarks.forEach((e) => (e.show = v));
    this.tiles.forEach((ps) => ps[2] && (ps[2].show = v && this.show.recon));
  }

  // ------------------------------------------------------------ routes
  drawRoutes(cur: RoutePlan | null, prev: RoutePlan | null, alts: RoutePlan[], roadStatus: Record<string, string>, edgeGeom: Map<string, number[][]>, approved: boolean, bridgeEdges: Set<string> = new Set()) {
    this.routeEntities.forEach((e) => this.viewer.entities.remove(e));
    this.routeEntities = [];
    // routes are draped per edge so bridge edges ride on their deck instead of the river bed
    const routeLine = (r: RoutePlan, lift: number) =>
      r.edge_ids.flatMap((eid, i) => {
        const g = edgeGeom.get(eid);
        if (!g) return [];
        const pts = drape(g, lift, bridgeEdges.has(eid));
        return i === 0 ? pts : pts.slice(1);
      });
    const add = (positions: Cesium.Cartesian3[], width: number, material: Cesium.MaterialProperty) =>
      this.routeEntities.push(this.viewer.entities.add({ polyline: { positions, width, material, arcType: Cesium.ArcType.NONE } }));
    const line = (coords: number[][], width: number, material: Cesium.MaterialProperty, _z = 0, eid?: string) =>
      add(drape(coords, 3.2, !!eid && bridgeEdges.has(eid)), width, material);
    alts.forEach((a) => add(routeLine(a, 2.4), 3, new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.WHITE.withAlpha(0.6), dashLength: 14 })));
    if (prev && (!cur || prev.route_id !== cur.route_id))
      add(routeLine(prev, 2.8), 7, new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString("#ff3b3b").withAlpha(0.95), gapColor: Cesium.Color.BLACK.withAlpha(0.35), dashLength: 18 }));
    if (cur) {
      const col = approved ? "#4ade80" : cur.at_risk ? "#fb923c" : "#22c55e";
      add(routeLine(cur, 3.0), 16, new Cesium.PolylineGlowMaterialProperty({ color: Cesium.Color.fromCssColorString(col).withAlpha(0.95), glowPower: 0.28, taperPower: 1 }));
      cur.edge_ids.forEach((eid) => {
        const s = roadStatus[eid] || "UNKNOWN";
        const g = edgeGeom.get(eid);
        if (!g) return;
        if (s === "UNKNOWN") line(g, 5, new Cesium.ColorMaterialProperty(Cesium.Color.fromCssColorString("#f5a524").withAlpha(0.95)), 0, eid);
        if (s === "SUSPECTED_BLOCKED") line(g, 7, new Cesium.ColorMaterialProperty(Cesium.Color.fromCssColorString("#fb923c")), 0, eid);
      });
    }
  }

  clearAll() {
    this.pointCols.forEach((c) => this.viewer.scene.primitives.remove(c));
    this.pointCols = [];
    this.pointBatches = [];
    this.totalPoints = 0;
    this.tiles.forEach((ps) => ps.forEach((p) => this.viewer.scene.primitives.remove(p)));
    this.tiles.clear();
    this.tileOrder = [];
    this.hazards.forEach((e) => this.viewer.entities.remove(e));
    this.hazards.clear();
    this.changeMarks.forEach((e) => this.viewer.entities.remove(e));
    this.changeMarks = [];
    this.footprints.forEach((e) => this.viewer.entities.remove(e));
    this.footprints = [];
    this.drones.forEach((v) => {
      [v.entity, v.cone, v.trail, v.beam].forEach((e) => this.viewer.entities.remove(e));
    });
    this.drones.clear();
  }
}
