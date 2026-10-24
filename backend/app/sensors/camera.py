"""Aerial image observations.

Two honest image sources:
 * PUBLIC_HISTORICAL_IMAGERY — when the camera target lies inside a cached, georeferenced
   NOAA Helene crop (flown 2024-10-05). This is real post-storm evidence, NOT imagery captured
   by our simulated drones; the drone pose only determines which archived frame is retrieved.
 * SIMULATED_SENSOR — otherwise, a synthetic nadir render of the ground-truth scenario surface
   (DEM hillshade + OSM features + modeled hazards), stamped "SIMULATED SENSOR RENDER".
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import IMAGERY
from app.geospatial.crs import to_local
from app.simulation.world import World

PALETTE = {
    0: (96, 112, 70), 1: (92, 92, 94), 2: (150, 146, 140), 3: (112, 92, 62), 4: (128, 126, 120),
    5: (118, 92, 64), 6: (70, 58, 40), 7: (132, 104, 74), 8: (104, 94, 70), 9: (52, 84, 44),
}


class NoaaCatalog:
    def __init__(self):
        self.crops = []
        for meta in sorted(IMAGERY.glob("noaa_*.json")):
            if meta.name == "noaa_coverage.json":
                continue
            m = json.loads(meta.read_text())
            b = m["bounds_wgs84"]
            m["_x0"], m["_y0"] = to_local(b["west"], b["south"])
            m["_x1"], m["_y1"] = to_local(b["east"], b["north"])
            m["_cx"], m["_cy"] = to_local(m["center"]["lon"], m["center"]["lat"])
            m["path"] = IMAGERY / Path(m["file"]).name
            self.crops.append(m)

    def find(self, x: float, y: float, prefer_close: bool) -> dict | None:
        """Crop whose centre is within 25 m of the target; smallest footprint first when a
        closer re-inspection is requested."""
        cands = [m for m in self.crops if math.hypot(m["_cx"] - x, m["_cy"] - y) < 25]
        if not cands:
            return None
        cands.sort(key=lambda m: m["half_size_m"] if prefer_close else -m["half_size_m"])
        return cands[0]


def render_synthetic(world: World, x: float, y: float, half_m: float, heading_deg: float, seed: int,
                     px: int = 640) -> bytes:
    """Nadir render of the hidden ground-truth surface around (x, y)."""
    from app.simulation.world import RES
    r0, c0 = world.idx(x - half_m, y + half_m)
    r1, c1 = world.idx(x + half_m, y - half_m)
    r0, c0, r1, c1 = int(r0), int(c0), int(r1), int(c1)
    k = world.klass[r0:r1, c0:c1]
    s = world.surface[r0:r1, c0:c1].astype(np.float64)
    hz = world.hazard[r0:r1, c0:c1]
    h, w = k.shape
    scale = px / max(h, w)
    up = lambda a, mode: np.asarray(Image.fromarray(a).resize((px, px), mode))  # noqa: E731
    K = up(k, Image.NEAREST)
    S = up(s.astype(np.float32), Image.BILINEAR).astype(np.float64)
    HZ = up(hz.astype(np.float32), Image.BILINEAR)
    # hillshade from the true surface (sun from NW, 45 deg)
    gy, gx = np.gradient(S, RES / scale)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    shade = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
    rng = np.random.default_rng(seed)
    base = np.zeros((px, px, 3), np.float64)
    for cls, col in PALETTE.items():
        base[K == cls] = col
    noise = rng.normal(0, 1, (px, px))
    noise = np.asarray(Image.fromarray(((noise + 3) * 40).clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), np.float64) / 255 - 0.5
    tex = np.where(np.isin(K, [5, 6, 7]), 70, np.where(K == 0, 30, 10))[..., None]
    img = base * (0.55 + 0.6 * shade[..., None]) + tex * noise[..., None]
    # flood water: muddy, smooth, slightly reflective
    fw = K == 8
    img[fw] = img[fw] * 0.25 + np.array([110, 96, 70]) * 0.75 + 8 * noise[fw][:, None]
    # debris: add chunky high-contrast clutter
    db = (K == 5) | (K == 6)
    img[db] += (rng.random((int(db.sum()), 1)) - 0.5) * 60
    # crown foliage on fallen trees
    crown = (K == 6) & (HZ > 0.6)
    img[crown] = img[crown] * 0.4 + np.array([58, 88, 40]) * 0.6
    im = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    # rotate to camera heading so the image is "as captured" (top = heading)
    im = im.rotate(heading_deg, resample=Image.BILINEAR, expand=False, fillcolor=(20, 20, 20))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle([0, px - 22, px, px], fill=(0, 0, 0))
    d.text((6, px - 19), "SIMULATED SENSOR RENDER - synthetic exercise data, not a photograph", fill=(255, 200, 0), font=font)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
