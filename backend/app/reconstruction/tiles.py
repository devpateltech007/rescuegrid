"""Progressive surface reconstruction + coverage from scan points.

Points are binned into CELL x CELL m cells over the survey area. Each cell keeps a running
sum / count / max of measured heights and the max |deviation| from the pre-storm baseline.
Cells are grouped into TILE x TILE tiles; changed tiles are emitted as height grids that the
frontend turns into mesh patches. Coverage = fraction of cells with >= 1 point.
"""
from __future__ import annotations

import numpy as np

from app.geospatial.crs import to_geo

CELL = 4.0
TILE = 32  # cells per tile side -> 128 m tiles


class Reconstruction:
    def __init__(self, cx: float, cy: float, half: float):
        self.x0, self.y0 = cx - half, cy - half  # south-west corner
        self.n = int(2 * half / CELL)
        self.sum = np.zeros((self.n, self.n), np.float64)
        self.cnt = np.zeros((self.n, self.n), np.int32)
        self.dev = np.zeros((self.n, self.n), np.float32)
        self.cls = np.zeros((self.n, self.n), np.uint8)
        self.first_seen = np.full((self.n, self.n), -1, np.int32)
        self.dirty: set[tuple[int, int]] = set()
        self.ntiles = int(np.ceil(self.n / TILE))

    def reset(self) -> None:
        self.__init__(self.x0 + self.n * CELL / 2, self.y0 + self.n * CELL / 2, self.n * CELL / 2)

    def add(self, xyz: np.ndarray, dev: np.ndarray, klass: np.ndarray, tick: int) -> int:
        c = ((xyz[:, 0] - self.x0) / CELL).astype(int)
        r = ((xyz[:, 1] - self.y0) / CELL).astype(int)
        ok = (c >= 0) & (c < self.n) & (r >= 0) & (r < self.n)
        r, c, z, d, k = r[ok], c[ok], xyz[ok, 2], np.abs(dev[ok]), klass[ok]
        new_before = int((self.cnt == 0).sum())
        np.add.at(self.sum, (r, c), z)
        np.add.at(self.cnt, (r, c), 1)
        np.maximum.at(self.dev, (r, c), d)
        np.maximum.at(self.cls, (r, c), k)
        fresh = self.first_seen[r, c] < 0
        self.first_seen[r[fresh], c[fresh]] = tick
        for tr, tc in set(zip((r // TILE).tolist(), (c // TILE).tolist())):
            self.dirty.add((tr, tc))
        return new_before - int((self.cnt == 0).sum())

    def coverage_fraction(self) -> float:
        return float((self.cnt > 0).mean())

    def observed_area_m2(self) -> float:
        return float((self.cnt > 0).sum() * CELL * CELL)

    def observed_at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        c = ((x - self.x0) / CELL).astype(int)
        r = ((y - self.y0) / CELL).astype(int)
        ok = (c >= 0) & (c < self.n) & (r >= 0) & (r < self.n)
        out = np.zeros(len(x), bool)
        out[ok] = self.cnt[r[ok], c[ok]] > 0
        return out

    def tile_payload(self, tr: int, tc: int) -> dict:
        """Vertex grid (TILE+1)^2 at cell corners; NaN where no neighbouring cell observed."""
        r0, c0 = tr * TILE, tc * TILE
        r1, c1 = min(r0 + TILE, self.n), min(c0 + TILE, self.n)
        cnt = self.cnt[r0:r1, c0:c1]
        mean = np.where(cnt > 0, self.sum[r0:r1, c0:c1] / np.maximum(cnt, 1), np.nan)
        dev = self.dev[r0:r1, c0:c1]
        cls = self.cls[r0:r1, c0:c1]
        h, w = mean.shape
        # corner heights = mean of adjacent observed cells
        pad = np.full((h + 2, w + 2), np.nan)
        pad[1:-1, 1:-1] = mean
        stack = np.stack([pad[:-1, :-1], pad[:-1, 1:], pad[1:, :-1], pad[1:, 1:]])
        valid = np.isfinite(stack)
        num = valid.sum(axis=0)
        corners = np.where(num > 0, np.where(valid, stack, 0).sum(axis=0) / np.maximum(num, 1), np.nan)
        x0 = self.x0 + c0 * CELL
        y0 = self.y0 + r0 * CELL
        lon0, lat0 = to_geo(x0, y0)
        lon1, lat1 = to_geo(x0 + w * CELL, y0 + h * CELL)
        return {
            "tile_id": f"T{tr:02d}_{tc:02d}",
            "rows": h + 1, "cols": w + 1,
            "west": lon0, "south": lat0, "east": lon1, "north": lat1,
            "heights": [None if not np.isfinite(v) else round(float(v), 2) for v in corners.ravel()],  # row 0 = south
            # cells whose measured surface departs from the pre-storm baseline by > 0.5 m
            "change_cells": [[int(i), round(float(dev.ravel()[i]), 1), int(cls.ravel()[i])]
                             for i in np.nonzero((dev.ravel() > 0.5) & (cnt.ravel() > 0))[0]],
            "observed_cells": int((cnt > 0).sum()),
            "cell_m": CELL,
        }

    def pop_dirty(self) -> list[dict]:
        out = [self.tile_payload(tr, tc) for tr, tc in sorted(self.dirty)]
        self.dirty.clear()
        return out

    def coverage_grid(self, factor: int = 5) -> dict:
        """Downsampled coverage raster (20 m cells) for the frontend heatmap."""
        n2 = self.n // factor
        c = (self.cnt[: n2 * factor, : n2 * factor] > 0).reshape(n2, factor, n2, factor).mean(axis=(1, 3))
        lon0, lat0 = to_geo(self.x0, self.y0)
        lon1, lat1 = to_geo(self.x0 + n2 * factor * CELL, self.y0 + n2 * factor * CELL)
        return {"rows": n2, "cols": n2, "west": lon0, "south": lat0, "east": lon1, "north": lat1,
                "values": (c * 100).round().astype(int).ravel().tolist()}  # row 0 = south
