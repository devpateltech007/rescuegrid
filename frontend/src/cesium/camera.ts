import * as Cesium from "cesium";
import type { DynamicLayers } from "./dynamicLayers";
import { dem } from "./terrain";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class CameraDirector {
  viewer: Cesium.Viewer;
  dyn: DynamicLayers;
  following: string | null = null;
  private followRange = 220;
  private followHeading = 0;
  private cancelToken = 0;

  constructor(viewer: Cesium.Viewer, dyn: DynamicLayers) {
    this.viewer = viewer;
    this.dyn = dyn;
    viewer.scene.preRender.addEventListener(() => this.tick());
  }

  private tick() {
    if (!this.following) return;
    const p = this.dyn.dronePosition(this.following);
    if (!p) return;
    const hd = Cesium.Math.toRadians(this.dyn.droneHeading(this.following));
    // smooth heading chase behind the drone
    const diff = Cesium.Math.negativePiToPi(hd - this.followHeading);
    this.followHeading += diff * 0.03;
    this.viewer.camera.lookAt(p, new Cesium.HeadingPitchRange(this.followHeading, Cesium.Math.toRadians(-28), this.followRange));
  }

  follow(id: string | null, range = 220) {
    this.cancelToken++;
    this.following = id;
    this.followRange = range;
    if (id) this.followHeading = Cesium.Math.toRadians(this.dyn.droneHeading(id));
    else this.viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
  }

  release() {
    if (this.following) this.follow(null);
  }

  flyToLonLat(lon: number, lat: number, range: number, headingDeg: number, pitchDeg: number, duration = 2.5) {
    this.release();
    const h = dem.height(lon, lat);
    return new Promise<void>((resolve) => {
      this.viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(lon, lat, h), 1), {
        offset: new Cesium.HeadingPitchRange(Cesium.Math.toRadians(headingDeg), Cesium.Math.toRadians(pitchDeg), range),
        duration,
        easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
        complete: () => resolve(),
        cancel: () => resolve(),
      });
    });
  }

  flyToDrone(id: string) {
    const p = this.dyn.dronePosition(id);
    if (!p) return;
    const c = Cesium.Cartographic.fromCartesian(p);
    return this.flyToLonLat(Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude), 260, this.dyn.droneHeading(id), -30, 2);
  }

  /** Shot 1: wide aerial view of the affected valley. */
  wideValley(center: { lon: number; lat: number }, duration = 3.5) {
    return this.flyToLonLat(center.lon, center.lat - 0.002, 3600, 22, -24, duration);
  }

  /** Shot 2: follow Drone Bravo toward the bridge while its scan point cloud appears. */
  async followBravo(ms = 9000) {
    const tok = ++this.cancelToken;
    const p = this.dyn.dronePosition("BRAVO");
    if (p) {
      const c = Cesium.Cartographic.fromCartesian(p);
      await this.flyToLonLat(Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude), 260, this.dyn.droneHeading("BRAVO") , -28, 2);
    }
    if (tok !== this.cancelToken - 1 && tok !== this.cancelToken) return;
    this.following = "BRAVO";
    this.followRange = 240;
    this.followHeading = Cesium.Math.toRadians(this.dyn.droneHeading("BRAVO"));
    const myTok = this.cancelToken;
    await sleep(ms);
    if (myTok === this.cancelToken) this.follow(null);
  }

  /** Shot 3: fly down to the bridge obstruction, hold, then pull back to reveal the route. */
  async bridgeReveal(bridge: { lon: number; lat: number }, routeCenter: { lon: number; lat: number }) {
    await this.flyToLonLat(bridge.lon, bridge.lat, 140, 205, -32, 3);
    await sleep(3500);
    await this.flyToLonLat(bridge.lon, bridge.lat, 420, 250, -38, 3);
    await sleep(1200);
    await this.flyToLonLat(routeCenter.lon, routeCenter.lat, 2300, 330, -52, 3.5);
  }
}
