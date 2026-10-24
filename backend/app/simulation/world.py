"""Ground-truth world for the simulation (hidden from the frontend).

surface(x, y) = pre-storm DEM (real USGS 3DEP)
              + static structures (OSM building footprints extruded; bridge deck over the river)
              + scenario hazards (modeled washout craters, debris mounds, fallen trunks, flood water)

Two rasters at 1 m resolution in UTM 17N over the survey area (+margin):
  delta[y, x]    metres added to the DEM by structures/hazards
  klass[y, x]    semantic class (used for simulated on-board classification + colouring)
`expected` = DEM + static structures only, i.e. what the pre-storm baseline predicts. The
change-detection step compares measured lidar heights to this baseline.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import geopandas as gpd
import numpy as np
from rasterio import features
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, shape

from app.config import GEO, SCENARIOS
from app.geospatial.crs import to_geo, to_local
from app.geospatial.terrain import terrain

CLASSES = {0: "GROUND", 1: "ROAD", 2: "BUILDING", 3: "WATER", 4: "BRIDGE_DECK", 5: "DEBRIS",
           6: "FALLEN_TREE", 7: "WASHOUT", 8: "FLOOD_WATER", 9: "VEGETATION"}
HAZARD_CLASSES = {5, 6, 7, 8}
RES = 1.0
MARGIN = 250.0


class World:
    def __init__(self, road_network):
        area = json.loads((GEO / "study_area.json").read_text())
        self.area = area
        self.cx, self.cy = area["center_local"]["x"], area["center_local"]["y"]
        half = area["survey_half_m"] + MARGIN
        self.x0, self.y1 = self.cx - half, self.cy + half  # west, north
        self.n = int(2 * half / RES)
        self.transform = from_origin(self.x0, self.y1, RES, RES)
        self.scenario = json.loads((SCENARIOS / "helene_swannanoa.json").read_text())

        # DEM resampled onto the 1 m UTM grid (cell centres).
        xs = self.x0 + (np.arange(self.n) + 0.5) * RES
        ys = self.y1 - (np.arange(self.n) + 0.5) * RES
        X, Y = np.meshgrid(xs, ys)
        lon, lat = to_geo(X.ravel(), Y.ravel())
        self.dem = terrain().height(lon, lat).reshape(self.n, self.n).astype(np.float32)

        self.klass = np.zeros((self.n, self.n), np.uint8)
        self.static = np.zeros((self.n, self.n), np.float32)  # structures in the pre-storm baseline
        self.hazard = np.zeros((self.n, self.n), np.float32)  # modeled storm changes

        self._rasterize_water()
        self._rasterize_roads(road_network)
        self._rasterize_buildings()
        self._bridge_decks(road_network)
        self._apply_hazards()
        self.expected = self.dem + self.static
        self.surface = self.expected + self.hazard
        # 3x3 envelope of the baseline: lidar hits on vertical walls/edges land in a neighbouring
        # 1 m cell, so change detection tests against the local min/max rather than one cell.
        pad = np.pad(self.expected, 1, mode="edge")
        stack = [pad[1 + dy:1 + dy + self.n, 1 + dx:1 + dx + self.n] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
        self.expected_min = np.minimum.reduce(stack)
        self.expected_max = np.maximum.reduce(stack)

    def deviation(self, x, y, z):
        """Measured height minus the pre-storm baseline envelope (0 inside the envelope)."""
        r, c = self.idx(x, y)
        lo, hi = self.expected_min[r, c], self.expected_max[r, c]
        return np.where(z > hi, z - hi, np.where(z < lo, z - lo, 0.0))

    # ---------- helpers ----------
    def _burn(self, geoms, value_fn=None, dtype=np.uint8, fill=0):
        shapes = list(geoms)
        if not shapes:
            return np.full((self.n, self.n), fill, dtype)
        return features.rasterize(shapes, out_shape=(self.n, self.n), transform=self.transform,
                                  fill=fill, dtype=dtype, all_touched=True)

    def _local_geom(self, g):
        from shapely.ops import transform as shp_transform
        return shp_transform(lambda x, y, z=None: to_local(x, y), g)

    def idx(self, x, y):
        c = np.clip(((np.asarray(x) - self.x0) / RES).astype(int), 0, self.n - 1)
        r = np.clip(((self.y1 - np.asarray(y)) / RES).astype(int), 0, self.n - 1)
        return r, c

    def inside(self, x, y):
        return (x >= self.x0) & (x < self.x0 + self.n * RES) & (y <= self.y1) & (y > self.y1 - self.n * RES)

    # ---------- layers ----------
    def _rasterize_water(self):
        w = gpd.read_file(GEO / "water.geojson")
        shapes = []
        for _, r in w.iterrows():
            g = self._local_geom(r.geometry)
            if g.geom_type in ("LineString", "MultiLineString"):
                width = 14.0 if str(r.get("waterway")) == "river" else 3.0
                g = g.buffer(width / 2)
            shapes.append((g, 3))
        m = self._burn(shapes)
        self.klass[m == 3] = 3
        self.water_mask = m == 3

    def _rasterize_roads(self, net):
        shapes = []
        for e in net.edges.values():
            w = 9.0 if e.road_class in ("primary", "trunk", "motorway") else 7.0 if e.road_class in ("secondary", "tertiary") else 5.5
            shapes.append((e.line_local.buffer(w / 2), 1))
        m = self._burn(shapes)
        self.road_mask = m == 1
        self.klass[self.road_mask] = 1

    def _rasterize_buildings(self):
        b = gpd.read_file(GEO / "buildings.geojson")
        shapes = []
        self.building_heights = []
        for _, r in b.iterrows():
            h = None
            try:
                h = float(str(r.get("height")).replace("m", "")) if r.get("height") not in (None, "") else None
            except ValueError:
                h = None
            if h is None or not math.isfinite(h):
                try:
                    lv = float(r.get("building:levels"))
                    h = 3.2 * lv if math.isfinite(lv) else None
                except (TypeError, ValueError):
                    h = None
            h = h or 6.0
            shapes.append((self._local_geom(r.geometry), h))
        hm = self._burn(shapes, dtype=np.float32, fill=0.0)
        bm = hm > 0
        self.static[bm] = np.maximum(self.static[bm], hm[bm])
        self.klass[bm] = 2

    def _bridge_decks(self, net):
        """Bridges are not in the bare-earth DEM. Model each deck as a linear ramp between the
        DEM heights at the edge endpoints, lifted 1 m."""
        self.bridge_cells = np.zeros((self.n, self.n), bool)
        for e in net.edges.values():
            if not e.is_bridge:
                continue
            line = e.line_local
            mask = self._burn([(line.buffer(5.5), 1)]) == 1
            if not mask.any():
                continue
            rr, cc = np.nonzero(mask)
            px = self.x0 + (cc + 0.5) * RES
            py = self.y1 - (rr + 0.5) * RES
            a, b = line.coords[0], line.coords[-1]
            za = float(self.dem[self.idx(a[0], a[1])])
            zb = float(self.dem[self.idx(b[0], b[1])])
            t = np.array([line.project(Point(x, y), normalized=True) for x, y in zip(px, py)])
            deck = za + (zb - za) * t + 1.0
            lift = np.maximum(deck - self.dem[rr, cc], 0)
            self.static[rr, cc] = np.maximum(self.static[rr, cc], lift)
            self.klass[rr, cc] = 4
            self.bridge_cells[rr, cc] = True

    def _apply_hazards(self):
        self.hazard_index = []
        for hz in self.scenario["hazards"]:
            g = hz["geometry"]
            lx, ly = to_local(hz["location"]["lon"], hz["location"]["lat"])
            if g["type"] == "washout":
                for c in g["craters"]:
                    x, y = to_local(c["lon"], c["lat"])
                    self._bowl(x, y, c["radius_m"], -(c["depth_m"]), 7, relative_to_expected=True)
            elif g["type"] == "mounds":
                hd = math.radians(g["road_heading_deg"])
                for m in g["mounds"]:
                    x = lx + m["dx"] * math.cos(hd) + m["dy"] * math.sin(hd)
                    y = ly - m["dx"] * math.sin(hd) + m["dy"] * math.cos(hd)
                    self._mound(x, y, m["radius_m"], m["height_m"], 5)
            elif g["type"] == "trees":
                for t in g["trunks"]:
                    ang = math.radians(g["road_heading_deg"] + t["angle_off_road_deg"])
                    x, y = lx + t["dx"], ly + t["dy"]
                    dx, dy = math.sin(ang) * t["len_m"] / 2, math.cos(ang) * t["len_m"] / 2
                    self._trunk(x - dx, y - dy, x + dx, y + dy, t["radius_m"], 6)
            elif g["type"] == "flood":
                self._flood(lx, ly, g["radius_m"], g["depth_m"])
            self.hazard_index.append({"hazard_id": hz["hazard_id"], "x": lx, "y": ly, "kind": hz["kind"]})

    def _window(self, x, y, r):
        r0, c0 = self.idx(x - r, y + r)
        r1, c1 = self.idx(x + r, y - r)
        rr, cc = np.mgrid[int(r0):int(r1) + 1, int(c0):int(c1) + 1]
        px = self.x0 + (cc + 0.5) * RES
        py = self.y1 - (rr + 0.5) * RES
        return rr, cc, px, py

    def _bowl(self, x, y, radius, depth, k, relative_to_expected=False):
        rr, cc, px, py = self._window(x, y, radius * 1.3)
        d = np.hypot(px - x, py - y) / radius
        rng = np.random.default_rng(int(abs(x * 7 + y * 3)) % 2**31)
        prof = np.where(d < 1, depth * (1 - d ** 2) * (0.85 + 0.3 * rng.random(d.shape)), 0)
        # Washout removes structure (deck approach / fill) as well as ground.
        removed = self.static[rr, cc] * (d < 1)
        self.hazard[rr, cc] = np.minimum(self.hazard[rr, cc], prof - removed)
        self.klass[rr, cc] = np.where(d < 1, k, self.klass[rr, cc])

    def _mound(self, x, y, radius, h, k):
        rr, cc, px, py = self._window(x, y, radius * 1.6)
        d = np.hypot(px - x, py - y) / radius
        rng = np.random.default_rng(int(abs(x * 5 + y * 11)) % 2**31)
        prof = h * np.exp(-2.2 * d ** 2) * (0.75 + 0.5 * rng.random(d.shape))
        prof[d > 1.5] = 0
        self.hazard[rr, cc] = np.maximum(self.hazard[rr, cc], prof)
        self.klass[rr, cc] = np.where(prof > 0.25, k, self.klass[rr, cc])

    def _trunk(self, xa, ya, xb, yb, radius, k):
        line = LineString([(xa, ya), (xb, yb)])
        rr, cc, px, py = self._window((xa + xb) / 2, (ya + yb) / 2, line.length / 2 + 4)
        d = np.array([line.distance(Point(a, b)) for a, b in zip(px.ravel(), py.ravel())]).reshape(px.shape)
        trunk = np.where(d < radius * 1.6, 2 * radius * np.sqrt(np.clip(1 - (d / (radius * 1.6)) ** 2, 0, 1)), 0)
        crown = np.where(d < 3.2, 1.2 * np.exp(-((d / 2.2) ** 2)), 0)  # branches/leaves near the crown end
        t = np.array([line.project(Point(a, b), normalized=True) for a, b in zip(px.ravel(), py.ravel())]).reshape(px.shape)
        prof = np.maximum(trunk, crown * (t > 0.65))
        self.hazard[rr, cc] = np.maximum(self.hazard[rr, cc], prof)
        self.klass[rr, cc] = np.where(prof > 0.2, k, self.klass[rr, cc])

    def _flood(self, x, y, radius, depth):
        rr, cc, px, py = self._window(x, y, radius)
        d = np.hypot(px - x, py - y)
        level = float(self.dem[self.idx(x, y)]) + depth
        ground = self.dem[rr, cc] + self.static[rr, cc]
        wet = (d < radius) & (ground < level) & (self.klass[rr, cc] != 2)
        self.hazard[rr, cc] = np.where(wet, np.maximum(self.hazard[rr, cc], level - ground), self.hazard[rr, cc])
        self.klass[rr, cc] = np.where(wet, 8, self.klass[rr, cc])

    # ---------- queries ----------
    def sample_surface(self, x, y):
        r, c = self.idx(x, y)
        return self.surface[r, c], self.expected[r, c], self.klass[r, c]

    def ground_height(self, x, y) -> float:
        """Height of the true surface (for drone AGL). Falls back to DEM outside the grid."""
        if self.inside(x, y):
            return float(self.surface[self.idx(x, y)])
        lon, lat = to_geo(x, y)
        return float(terrain().height(lon, lat))

    def dem_height(self, x, y) -> float:
        if self.inside(x, y):
            return float(self.dem[self.idx(x, y)])
        lon, lat = to_geo(x, y)
        return float(terrain().height(lon, lat))


@lru_cache
def get_world(net_id: int, net=None) -> World:  # pragma: no cover - cache helper
    return World(net)
