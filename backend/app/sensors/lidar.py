"""Synthetic depth / LiDAR sensor.

For each scan:
 1. sensor pose from drone telemetry (position, heading, pitch)
 2. footprint from altitude and field of view
 3. a grid of rays is cast through the FOV and ray-marched against the ground-truth
    surface (real DEM + structures + modeled hazards), refined by bisection
 4. hit points get seeded Gaussian range noise (reproducible)
 5. points are transformed UTM -> WGS84 and labelled with drone, scan id, timestamp,
    sensor source and simulated semantic class
Every point is a measurement of the underlying geometry; nothing is decorative.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.geospatial.crs import to_geo
from app.simulation.world import World


@dataclass
class LidarConfig:
    fov_deg: float = 70.0
    rays_across: int = 30
    rays_along: int = 30
    range_noise_m: float = 0.05
    max_range_m: float = 250.0
    step_m: float = 2.0


@dataclass
class ScanResult:
    xyz: np.ndarray          # N x 3 UTM (x, y, z) metres
    lonlat_h: np.ndarray     # N x 3 (lon, lat, height)
    klass: np.ndarray        # N simulated semantic class
    deviation: np.ndarray    # N measured - pre-storm expected surface (m)
    footprint: np.ndarray    # 4 x 2 UTM corners
    footprint_lonlat: list[list[float]]
    mean_range_m: float


def ray_directions(heading_deg: float, pitch_deg: float, cfg: LidarConfig) -> np.ndarray:
    """Unit rays in ENU for a camera whose optical axis has the given heading and pitch
    (pitch -90 = nadir)."""
    half = math.radians(cfg.fov_deg / 2)
    u = np.tan(np.linspace(-half, half, cfg.rays_across))
    v = np.tan(np.linspace(-half, half, cfg.rays_along))
    U, V = np.meshgrid(u, v)
    # camera frame: forward f, right r, up(of image) d
    h, p = math.radians(heading_deg), math.radians(pitch_deg)
    f = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])
    r = np.array([math.cos(h), -math.sin(h), 0.0])
    d = np.cross(r, f)
    dirs = f[None, :] + U.ravel()[:, None] * r[None, :] + V.ravel()[:, None] * d[None, :]
    return dirs / np.linalg.norm(dirs, axis=1, keepdims=True)


def scan(world: World, x: float, y: float, z: float, heading_deg: float, pitch_deg: float,
         cfg: LidarConfig, rng: np.random.Generator) -> ScanResult | None:
    dirs = ray_directions(heading_deg, pitch_deg, cfg)
    n = len(dirs)
    origin = np.array([x, y, z])
    t_hi = np.full(n, np.nan)
    # Skip empty air: start each ray where it descends to 60 m above the ground under the
    # sensor (taller than any structure in the survey area). Pure optimisation; same hits.
    top = world.ground_height(x, y) + 60.0
    down = np.maximum(-dirs[:, 2], 1e-3)
    t_cur = np.maximum(0.0, (z - top) / down)
    t_prev = t_cur.copy()
    alive = np.ones(n, bool)
    t_cur = t_cur + cfg.step_m
    while alive.any():
        idx = np.nonzero(alive)[0]
        tt = t_cur[idx]
        p = origin + dirs[idx] * tt[:, None]
        inside = world.inside(p[:, 0], p[:, 1]) & (tt <= cfg.max_range_m)
        surf = np.full(len(idx), np.inf)
        surf[inside] = world.sample_surface(p[inside, 0], p[inside, 1])[0]
        alive[idx[~inside]] = False
        hit = inside & (p[:, 2] <= surf)
        t_hi[idx[hit]] = tt[hit]
        alive[idx[hit]] = False
        miss = inside & ~hit
        t_prev[idx[miss]] = tt[miss]
        t_cur[idx[miss]] = tt[miss] + cfg.step_m
    ok = np.isfinite(t_hi)
    if ok.sum() < 10:
        return None
    lo, hi, D = t_prev[ok], t_hi[ok], dirs[ok]
    for _ in range(6):  # bisection refinement to ~3 cm
        mid = (lo + hi) / 2
        p = origin + D * mid[:, None]
        s = world.sample_surface(p[:, 0], p[:, 1])[0]
        below = p[:, 2] <= s
        hi = np.where(below, mid, hi)
        lo = np.where(below, lo, mid)
    rng_m = (lo + hi) / 2 + rng.normal(0, cfg.range_noise_m, len(lo))
    pts = origin + D * rng_m[:, None]
    surf, expected, klass = world.sample_surface(pts[:, 0], pts[:, 1])
    dev = world.deviation(pts[:, 0], pts[:, 1], pts[:, 2])
    lon, lat = to_geo(pts[:, 0], pts[:, 1])
    # Footprint = hits of the four corner rays (or their projection on the mean plane).
    corners_i = [0, cfg.rays_across - 1, n - 1, n - cfg.rays_across]
    zmean = float(np.mean(pts[:, 2]))
    fp = []
    for ci in corners_i:
        dvec = dirs[ci]
        tt = (z - zmean) / max(-dvec[2], 1e-3)
        fp.append([x + dvec[0] * tt, y + dvec[1] * tt])
    fp = np.array(fp)
    flon, flat = to_geo(fp[:, 0], fp[:, 1])
    return ScanResult(
        xyz=pts, lonlat_h=np.column_stack([lon, lat, pts[:, 2]]), klass=klass.astype(np.uint8),
        deviation=dev.astype(np.float32), footprint=fp,
        footprint_lonlat=[[float(a), float(b)] for a, b in zip(flon, flat)],
        mean_range_m=float(np.mean(rng_m)),
    )
