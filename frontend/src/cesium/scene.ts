import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { dem } from "./terrain";

// No Cesium ion: every asset here is either local or a keyless public tile service.
Cesium.Ion.defaultAccessToken = "";

export interface SceneCtx {
  viewer: Cesium.Viewer;
  noaaLayer: Cesium.ImageryLayer | null;
  baseLayer: Cesium.ImageryLayer;
}

export async function createScene(container: HTMLElement, noaaBounds: { west: number; south: number; east: number; north: number } | null): Promise<SceneCtx> {
  await Promise.all([dem.load(), Cesium.GroundPolylinePrimitive.initializeTerrainHeights()]);
  const esri = new Cesium.UrlTemplateImageryProvider({
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    maximumLevel: 19,
    credit: new Cesium.Credit("Basemap: Esri World Imagery (current, not historical)"),
  });
  const viewer = new Cesium.Viewer(container, {
    baseLayer: new Cesium.ImageryLayer(esri, { brightness: 0.78, saturation: 0.75, contrast: 1.08, gamma: 1.05 }),
    terrainProvider: dem.provider(),
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    shouldAnimate: true,
    requestRenderMode: false,
    msaaSamples: 4,
  });
  const scene = viewer.scene;
  (viewer.cesiumWidget.creditContainer as HTMLElement).style.display = "none";
  scene.globe.depthTestAgainstTerrain = true;
  scene.globe.enableLighting = false;
  scene.globe.baseColor = Cesium.Color.fromCssColorString("#0b0d10");
  scene.globe.showGroundAtmosphere = true;
  scene.globe.maximumScreenSpaceError = 1.5;
  scene.globe.tileCacheSize = 400;
  scene.backgroundColor = Cesium.Color.fromCssColorString("#05070a");
  scene.fog.enabled = true;
  scene.fog.density = 0.00012;
  if (scene.skyAtmosphere) {
    scene.skyAtmosphere.hueShift = -0.05;
    scene.skyAtmosphere.saturationShift = -0.35;
    scene.skyAtmosphere.brightnessShift = -0.35;
  }
  scene.highDynamicRange = false;
  // Never leave the demo frozen: log render errors and resume the render loop.
  viewer.cesiumWidget.showErrorPanel = () => undefined;
  scene.renderError.addEventListener((_s: unknown, err: unknown) => {
    console.error("Cesium render error (recovering):", err);
    setTimeout(() => (viewer.useDefaultRenderLoop = true), 50);
  });
  const bloom = scene.postProcessStages.bloom;
  bloom.enabled = true;
  bloom.uniforms.glowOnly = false;
  bloom.uniforms.contrast = 119;
  bloom.uniforms.brightness = -0.35;
  bloom.uniforms.delta = 1.0;
  bloom.uniforms.sigma = 2.2;
  bloom.uniforms.stepSize = 1.0;
  // historical sun angle: simulated 2024-09-28 ~13:00 local
  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601("2024-09-28T17:00:00Z");
  viewer.clock.shouldAnimate = false;
  scene.screenSpaceCameraController.minimumZoomDistance = 15;
  scene.screenSpaceCameraController.maximumZoomDistance = 60000;

  let noaaLayer: Cesium.ImageryLayer | null = null;
  if (noaaBounds) {
    const pad = 0.012;
    const noaa = new Cesium.UrlTemplateImageryProvider({
      url: "/api/tiles/noaa/{z}/{x}/{y}",
      minimumLevel: 13,
      maximumLevel: 19,
      rectangle: Cesium.Rectangle.fromDegrees(noaaBounds.west - pad, noaaBounds.south - pad, noaaBounds.east + pad, noaaBounds.north + pad),
      credit: new Cesium.Credit("NOAA NGS Hurricane Helene imagery 2024-10-05"),
    });
    noaaLayer = viewer.imageryLayers.addImageryProvider(noaa);
    noaaLayer.brightness = 0.95;
    noaaLayer.contrast = 1.1;
  }
  return { viewer, noaaLayer, baseLayer: viewer.imageryLayers.get(0) };
}

export function cart(lon: number, lat: number, h: number) {
  return Cesium.Cartesian3.fromDegrees(lon, lat, h);
}
