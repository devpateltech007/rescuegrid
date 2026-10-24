"""Step 2 of data preparation: real ground elevation from USGS 3DEP.

Downloads two GeoTIFFs from the public USGS 3DEP Elevation ImageServer (no account):
  - fine:   ~5 m grid over the routing area (study area + detour roads)
  - coarse: ~30 m grid over a 30 km context region (surrounding Blue Ridge valleys)
Both are requested directly in EPSG:4326 so the browser and backend can sample by lon/lat.
Heights are metres, NAVD88 (3DEP native vertical datum). 3DEP source lidar for Buncombe
County predates Hurricane Helene, so terrain represents PRE-STORM ground.

Outputs (data/terrain/):
  <name>.tif           raw GeoTIFF (git-ignored copy under data/raw)
  <name>.u16           little-endian uint16 heights, decimetres above `offset_m`, row 0 = north
  <name>.json          header: bounds, width, height, offset_m, scale, datum, source
Run: python scripts/prepare_terrain.py
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "terrain"
RAW = ROOT / "data" / "raw"
URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
H = {"User-Agent": "RESCUEGRID3D-hackathon/0.1"}


def fetch(name: str, lon: float, lat: float, half_m: float, res_m: float) -> dict:
    dlat = half_m / 111_320.0
    dlon = half_m / (111_320.0 * math.cos(math.radians(lat)))
    w, s, e, n = lon - dlon, lat - dlat, lon + dlon, lat + dlat
    size = int(round(2 * half_m / res_m))
    params = {
        "bbox": f"{w},{s},{e},{n}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{size},{size}", "format": "tiff", "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation", "noData": -9999, "f": "image",
    }
    print(f"  requesting {name}: {size}x{size} px @ ~{res_m} m ...")
    r = requests.get(URL, params=params, headers=H, timeout=300)
    r.raise_for_status()
    if not r.content[:4] in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError(f"3DEP did not return a GeoTIFF: {r.content[:300]!r}")
    RAW.mkdir(parents=True, exist_ok=True)
    tif = RAW / f"{name}.tif"
    tif.write_bytes(r.content)
    with rasterio.open(tif) as ds:
        z = ds.read(1).astype(np.float64)
        b = ds.bounds
        crs = str(ds.crs)
    bad = (z < -1000) | ~np.isfinite(z)
    if bad.any():
        print(f"  filling {int(bad.sum())} nodata cells with nearest valid mean")
        z[bad] = np.nanmean(np.where(bad, np.nan, z))
    offset = math.floor(z.min()) - 1
    q = np.clip(np.round((z - offset) * 10), 0, 65535).astype("<u2")
    OUT.mkdir(parents=True, exist_ok=True)
    q.tofile(OUT / f"{name}.u16")
    hdr = {
        "name": name,
        "width": int(z.shape[1]), "height": int(z.shape[0]),
        "bounds": {"west": b.left, "south": b.bottom, "east": b.right, "north": b.top},
        "crs": crs, "vertical_datum": "NAVD88 (metres)",
        "encoding": "uint16 LE, height_m = offset_m + value * scale, row 0 = north edge",
        "offset_m": offset, "scale": 0.1,
        "min_m": float(z.min()), "max_m": float(z.max()), "mean_m": float(z.mean()),
        "approx_resolution_m": res_m,
        "source": "USGS 3D Elevation Program (3DEP) Elevation ImageServer",
        "source_url": URL,
        "temporal_note": "3DEP lidar for Buncombe County predates Hurricane Helene (pre-storm terrain).",
        "provenance": "CURRENT_BASEMAP",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (OUT / f"{name}.json").write_text(json.dumps(hdr, indent=2))
    print(f"  saved {name}: {hdr['width']}x{hdr['height']}, elev {hdr['min_m']:.1f}..{hdr['max_m']:.1f} m")
    return hdr


def main() -> None:
    area = json.loads((ROOT / "data" / "geography" / "study_area.json").read_text())
    lon, lat = area["bridge"]["centroid"]["lon"], area["bridge"]["centroid"]["lat"]
    fetch("dem_fine", lon, lat, area["routing_half_m"] + 200, 5.0)
    fetch("dem_coarse", lon, lat, 15_000, 30.0)
    print("done.")


if __name__ == "__main__":
    main()
