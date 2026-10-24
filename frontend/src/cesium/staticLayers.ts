import * as Cesium from "cesium";
import { statusColor } from "./colors";
import { drape, lengthM } from "./drape";
import { dem } from "./terrain";

export interface StaticLayers {
  roads: Cesium.PolylineCollection;
  roadIds: Set<string>;
  roadProps: Map<string, any>;
  buildings: Cesium.Primitive | null;
  water: Cesium.GroundPolylinePrimitive | null;
  bridges: Cesium.PolylineCollection;
  survey: Cesium.Entity;
  sectors: Cesium.Entity[];
  markers: Cesium.Entity[];
  setRoadStatus: (eid: string, status: string) => void;
  pending: Map<string, string>;
}

function icon(color: string, glyph: "S" | "R" | "B"): string {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.shadowColor = color;
  g.shadowBlur = 14;
  g.strokeStyle = color;
  g.lineWidth = 4;
  g.fillStyle = "rgba(10,12,16,0.85)";
  if (glyph === "R") {
    g.beginPath();
    g.moveTo(32, 6); g.lineTo(58, 32); g.lineTo(32, 58); g.lineTo(6, 32); g.closePath();
  } else {
    g.beginPath();
    g.arc(32, 32, 24, 0, Math.PI * 2);
  }
  g.fill();
  g.stroke();
  g.shadowBlur = 0;
  g.fillStyle = color;
  g.font = "bold 24px Inter, Arial";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(glyph === "S" ? "S1" : glyph === "R" ? "R7" : "B", 32, 33);
  return c.toDataURL();
}

export async function buildStatic(viewer: Cesium.Viewer, snap: any): Promise<StaticLayers> {
  const [roadsGj, bldGj, waterGj, bridges] = await Promise.all([
    fetch("/api/geo/roads").then((r) => r.json()),
    fetch("/api/geo/buildings").then((r) => r.json()),
    fetch("/api/geo/water").then((r) => r.json()),
    fetch("/api/geo/bridges").then((r) => r.json()),
  ]);
  const scene = viewer.scene;

  // ---- roads (real OSM drive graph) draped on the real DEM; per-edge colour = access status
  const roadProps = new Map<string, any>();
  const roads = scene.primitives.add(new Cesium.PolylineCollection()) as Cesium.PolylineCollection;
  const lines = new Map<string, Cesium.Polyline>();
  const drawn = new Set<string>(); // one polyline per physical segment (skip reverse twin)
  const twinOf = new Map<string, string>();
  for (const f of roadsGj.features) {
    const p = f.properties;
    roadProps.set(p.edge_id, p);
    const key = [p.source_node, p.target_node].sort().join("-") + ":" + p.osm_way_ids.slice().sort().join(",");
    if (drawn.has(key)) {
      twinOf.set(p.edge_id, key);
      continue;
    }
    drawn.add(key);
    twinOf.set(p.edge_id, key);
    const coords = f.geometry.coordinates as number[][];
    const shortBridge = p.is_bridge && lengthM(coords) < 260;
    const w = p.road_class === "primary" || p.road_class === "motorway" || p.road_class === "trunk" ? 4.5 : p.road_class === "residential" || p.road_class === "service" || p.road_class === "unclassified" ? 2 : 3.2;
    const pl = roads.add({
      positions: drape(coords, 1.8, shortBridge),
      width: w,
      material: Cesium.Material.fromType("Color", { color: statusColor(snap.road_status[p.edge_id] || "UNKNOWN") }),
      id: { kind: "road", edge_id: p.edge_id },
    });
    lines.set(key, pl);
  }
  const roadIds = new Set<string>(roadProps.keys());
  const pending = new Map<string, string>();
  const setRoadStatus = (eid: string, status: string) => {
    const key = twinOf.get(eid);
    const pl = key && lines.get(key);
    if (!pl) return;
    pl.material.uniforms.color = statusColor(status);
    pl.width = status === "UNKNOWN" ? Math.min(pl.width, 3.2) : Math.max(pl.width, 4);
  };

  // ---- buildings (OSM footprints, extruded; estimated heights flagged)
  let buildings: Cesium.Primitive | null = null;
  const binst: Cesium.GeometryInstance[] = [];
  for (const f of bldGj.features) {
    const ring = f.geometry.coordinates[0];
    if (ring.length < 4) continue;
    const base = f.properties.base_m - 1.5;
    const h = f.properties.height_m;
    try {
      binst.push(new Cesium.GeometryInstance({
        geometry: new Cesium.PolygonGeometry({
          polygonHierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(ring.flat())),
          height: base,
          extrudedHeight: base + 1.5 + h,
          vertexFormat: Cesium.PerInstanceColorAppearance.VERTEX_FORMAT,
        }),
        attributes: { color: Cesium.ColorGeometryInstanceAttribute.fromColor(Cesium.Color.fromCssColorString(f.properties.height_estimated ? "#46505e" : "#5b6677").withAlpha(0.88)) },
        id: { kind: "building", ...f.properties },
      }));
    } catch {
      /* skip degenerate footprint */
    }
  }
  if (binst.length) {
    buildings = scene.primitives.add(new Cesium.Primitive({
      geometryInstances: binst,
      appearance: new Cesium.PerInstanceColorAppearance({ translucent: true, closed: true }),
      shadows: Cesium.ShadowMode.DISABLED,
    })) as Cesium.Primitive;
  }

  // ---- water: Swannanoa River & streams
  let water: Cesium.GroundPolylinePrimitive | null = null;
  const winst: Cesium.GeometryInstance[] = [];
  for (const f of waterGj.features) {
    const g = f.geometry;
    if (!g || (g.type !== "LineString" && g.type !== "MultiLineString")) continue;
    const lines = g.type === "LineString" ? [g.coordinates] : g.coordinates;
    const river = f.properties.waterway === "river";
    for (const l of lines) {
      if (l.length < 2) continue;
      winst.push(new Cesium.GeometryInstance({
        geometry: new Cesium.GroundPolylineGeometry({ positions: Cesium.Cartesian3.fromDegreesArray(l.flat()), width: river ? 5 : 1.5 }),
        attributes: { color: Cesium.ColorGeometryInstanceAttribute.fromColor(Cesium.Color.fromCssColorString(river ? "#38bdf8" : "#1d4ed8").withAlpha(river ? 0.75 : 0.45)) },
        id: { kind: "water", name: f.properties.name },
      }));
    }
  }
  if (winst.length) water = scene.groundPrimitives.add(new Cesium.GroundPolylinePrimitive({ geometryInstances: winst, appearance: new Cesium.PolylineColorAppearance() })) as Cesium.GroundPolylinePrimitive;

  // ---- bridge decks (raised; DEM is bare earth). Only short bridge edges: long merged
  // edges (e.g. I-40) contain a bridge way but are mostly on grade.
  const bridgeCol = scene.primitives.add(new Cesium.PolylineCollection()) as Cesium.PolylineCollection;
  for (const b of bridges) {
    const whitson = b.osm_way_ids.includes(388972121);
    if (lengthM(b.coords) > 260) continue;
    bridgeCol.add({
      positions: drape(b.coords.map((c: number[]) => [c[0], c[1]]), 2.2, true),
      width: whitson ? 9 : 6,
      material: Cesium.Material.fromType("PolylineOutline", {
        color: Cesium.Color.fromCssColorString(whitson ? "#fde68a" : "#e5e7eb").withAlpha(0.95),
        outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
        outlineWidth: 2,
      }),
      id: { kind: "bridge", ...b },
    });
  }

  // ---- survey area + sectors
  const ring = snap.mission.survey_polygon as [number, number][];
  const survey = viewer.entities.add({
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(ring.flat()),
      clampToGround: true,
      width: 3,
      material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString("#22d3ee").withAlpha(0.8), dashLength: 24 }),
    },
  });
  const sectors = snap.sectors.map((s: any) =>
    viewer.entities.add({
      id: `sector-${s.sector_id}`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(s.polygon.flat()),
        material: Cesium.Color.fromCssColorString(s.color).withAlpha(0.1),
        classificationType: Cesium.ClassificationType.TERRAIN,
      },
      properties: { kind: "sector", ...s },
    }),
  );

  // ---- staging & destination (SIMULATED_SCENARIO)
  const sc = snap.mission.scenario;
  const mk = (lon: number, lat: number, color: string, glyph: "S" | "R" | "B", text: string, kind: string) =>
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, dem.height(lon, lat) + 3),
      billboard: { image: icon(color, glyph), width: 44, height: 44, disableDepthTestDistance: Number.POSITIVE_INFINITY, verticalOrigin: Cesium.VerticalOrigin.CENTER },
      label: {
        text, font: "600 13px Inter, sans-serif", fillColor: Cesium.Color.fromCssColorString(color), outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cesium.Cartesian2(0, 34), disableDepthTestDistance: Number.POSITIVE_INFINITY,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0b0d10").withAlpha(0.75),
        verticalOrigin: Cesium.VerticalOrigin.TOP,
      },
      properties: { kind },
    });
  const markers = [
    mk(sc.staging.lon, sc.staging.lat, "#22d3ee", "S", "STAGING S-1 · simulated", "staging"),
    mk(sc.destination.lon, sc.destination.lat, "#f472b6", "R", "RESCUE SITE R-7 · simulated", "destination"),
  ];
  return { roads, roadIds, roadProps, buildings, water, bridges: bridgeCol, survey, sectors, markers, setRoadStatus, pending };
}
