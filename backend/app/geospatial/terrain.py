"""Real USGS 3DEP terrain sampling (bilinear) from the preprocessed lon/lat height grids."""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from app.config import TERRAIN


class HeightGrid:
    def __init__(self, name: str):
        self.hdr = json.loads((TERRAIN / f"{name}.json").read_text())
        w, h = self.hdr["width"], self.hdr["height"]
        q = np.fromfile(TERRAIN / f"{name}.u16", dtype="<u2").reshape(h, w)
        self.z = q.astype(np.float32) * self.hdr["scale"] + self.hdr["offset_m"]
        b = self.hdr["bounds"]
        self.w, self.s, self.e, self.n = b["west"], b["south"], b["east"], b["north"]
        self.W, self.H = w, h

    def contains(self, lon, lat):
        lon, lat = np.asarray(lon), np.asarray(lat)
        return (lon >= self.w) & (lon <= self.e) & (lat >= self.s) & (lat <= self.n)

    def sample(self, lon, lat):
        """Bilinear sample at pixel centres; clamps outside the grid."""
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        fx = (lon - self.w) / (self.e - self.w) * self.W - 0.5
        fy = (self.n - lat) / (self.n - self.s) * self.H - 0.5
        fx = np.clip(fx, 0, self.W - 1.001)
        fy = np.clip(fy, 0, self.H - 1.001)
        x0 = np.floor(fx).astype(int)
        y0 = np.floor(fy).astype(int)
        tx, ty = fx - x0, fy - y0
        z = self.z
        a = z[y0, x0] * (1 - tx) + z[y0, x0 + 1] * tx
        b = z[y0 + 1, x0] * (1 - tx) + z[y0 + 1, x0 + 1] * tx
        return a * (1 - ty) + b * ty


class Terrain:
    def __init__(self):
        self.fine = HeightGrid("dem_fine")
        self.coarse = HeightGrid("dem_coarse")

    def height(self, lon, lat):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        inside = self.fine.contains(lon, lat)
        out = np.where(inside, self.fine.sample(lon, lat), self.coarse.sample(lon, lat))
        return out if out.ndim else float(out)


@lru_cache
def terrain() -> Terrain:
    return Terrain()
