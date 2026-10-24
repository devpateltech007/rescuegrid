"""Step 4 of data preparation: NOAA Hurricane Helene post-storm aerial imagery.

1. Reads NOAA's layer index (services/index.json) for the Helene response.
2. Keeps flights whose envelope contains the Whitson Avenue bridge.
3. Probes real z19 tiles over the bridge to confirm actual pixel coverage (envelopes lie).
4. For the best-covered flight, mosaics georeferenced crops at the bridge and at
   other evidence sites (scenario sites read from data/scenarios/evidence_sites.json if present),
   saves them to data/imagery/ with a JSON sidecar of exact geographic bounds.

Imagery is real NOAA aerial evidence (PUBLIC_HISTORICAL_IMAGERY), NOT simulated drone capture.
Run: python scripts/fetch_noaa_imagery.py
"""
from __future__ import annotations

import io
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "data" / "imagery"
CACHE = ROOT / "data" / "cache" / "noaa_tiles"
H = {"User-Agent": "RESCUEGRID3D-hackathon/0.1 (research demo)"}
INDEX = "https://storms.ngs.noaa.gov/storms/helene/services/index.json"
Z = 19


def deg2tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile2deg(x, y, z):
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def get_tile(layer_tpl: str, layer: str, z: int, x: int, y: int) -> Image.Image | None:
    p = CACHE / layer / f"{z}_{x}_{y}.png"
    if p.exists():
        return Image.open(p).convert("RGBA") if p.stat().st_size > 0 else None
    p.parent.mkdir(parents=True, exist_ok=True)
    url = layer_tpl.format(z=z, x=x, y=y)
    try:
        r = requests.get(url, headers=H, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code != 200 or len(r.content) < 200:
        p.write_bytes(b"")
        return None
    p.write_bytes(r.content)
    try:
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:  # noqa: BLE001
        p.write_bytes(b"")
        return None


def coverage(img: Image.Image | None) -> float:
    if img is None:
        return 0.0
    a = np.asarray(img)
    valid = (a[..., 3] > 0) & (a[..., :3].sum(axis=2) > 15)
    return float(valid.mean())


def crop(layer_tpl, layer, lon, lat, half_m, out_name, meta_extra) -> dict | None:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    w, e = lon - half_m / m_per_deg_lon, lon + half_m / m_per_deg_lon
    s, n = lat - half_m / m_per_deg_lat, lat + half_m / m_per_deg_lat
    x0, y0 = deg2tile(w, n, Z)
    x1, y1 = deg2tile(e, s, Z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    W, Hh = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    mosaic = Image.new("RGBA", (W, Hh), (0, 0, 0, 0))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            t = get_tile(layer_tpl, layer, Z, tx, ty)
            if t is not None:
                mosaic.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
    px0, py0 = int((x0 - tx0) * 256), int((y0 - ty0) * 256)
    px1, py1 = int((x1 - tx0) * 256), int((y1 - ty0) * 256)
    c = mosaic.crop((px0, py0, px1, py1))
    cov = coverage(c)
    if cov < 0.6:
        print(f"      {out_name}: coverage {cov:.0%} too low, skipped")
        return None
    rgb = Image.new("RGB", c.size, (0, 0, 0))
    rgb.paste(c, mask=c.split()[3])
    if max(rgb.size) > 1024:
        rgb.thumbnail((1024, 1024))
    IMG.mkdir(parents=True, exist_ok=True)
    rgb.save(IMG / f"{out_name}.jpg", quality=90)
    meta = {
        "file": f"data/imagery/{out_name}.jpg",
        "source_type": "PUBLIC_HISTORICAL_IMAGERY",
        "publisher": "NOAA National Geodetic Survey, Remote Sensing Division",
        "layer": layer,
        "tile_template": layer_tpl,
        "zoom": Z,
        "bounds_wgs84": {"west": w, "south": s, "east": e, "north": n},
        "center": {"lon": lon, "lat": lat},
        "half_size_m": half_m,
        "pixel_size": list(rgb.size),
        "valid_pixel_fraction": round(cov, 3),
        "approx_gsd_m": round(2 * half_m / rgb.size[0], 3),
        "accuracy_note": "NOAA states no accuracy or completeness guarantee; mosaic GSD ~15-30 cm.",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta_extra,
    }
    (IMG / f"{out_name}.json").write_text(json.dumps(meta, indent=2))
    print(f"      saved {out_name}.jpg ({rgb.size[0]}x{rgb.size[1]}, coverage {cov:.0%})")
    return meta


def main() -> None:
    area = json.loads((ROOT / "data" / "geography" / "study_area.json").read_text())
    blon, blat = area["bridge"]["centroid"]["lon"], area["bridge"]["centroid"]["lat"]
    layers = requests.get(INDEX, headers=H, timeout=30).json()
    cands = [l for l in layers if l["bounds"][0] <= blon <= l["bounds"][2] and l["bounds"][1] <= blat <= l["bounds"][3]]
    print(f"[1/3] {len(cands)} NOAA flights have envelopes containing the bridge: {[c['name'] for c in cands]}")

    print("[2/3] probing real tiles at z19 over the bridge ...")
    cx, cy = deg2tile(blon, blat, Z)
    results = []
    for l in cands:
        tpl = l["tiles"][0]  # NOAA XYZ template, no file extension
        name = l["name"]
        covs = [coverage(get_tile(tpl, name, Z, int(cx) + dx, int(cy) + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        score = float(np.mean(covs))
        print(f"      {name}: mean coverage {score:.0%}")
        results.append((score, l, tpl))
    results.sort(key=lambda r: -r[0])
    if not results or results[0][0] < 0.5:
        report = {"covered": False, "probed": [r[1]["name"] for r in results]}
        IMG.mkdir(parents=True, exist_ok=True)
        (IMG / "noaa_coverage.json").write_text(json.dumps(report, indent=2))
        sys.exit("NOAA imagery does not cover the bridge; simulated render fallback must be used.")
    score, layer, tpl = results[0]
    date = layer["name"][:8]
    acq = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    print(f"      selected {layer['name']} (acquired {acq})")

    print("[3/3] building georeferenced evidence crops ...")
    extra = {"acquisition_date": acq, "flight_id": layer["name"]}
    saved = {"bridge": crop(tpl, layer["name"], blon, blat, 90, "noaa_whitson_bridge", {**extra, "site": "whitson_bridge"})}
    sites_p = ROOT / "data" / "scenarios" / "evidence_sites.json"
    if sites_p.exists():
        for s in json.loads(sites_p.read_text()):
            saved[s["id"]] = crop(tpl, layer["name"], s["lon"], s["lat"], s.get("half_m", 70), f"noaa_{s['id']}", {**extra, "site": s["id"]})
    report = {
        "covered": True,
        "selected_layer": layer["name"],
        "tile_template": tpl,
        "acquisition_date": acq,
        "layer_bounds": layer["bounds"],
        "maxzoom": layer["maxzoom"],
        "probe": [{"layer": r[1]["name"], "bridge_coverage": round(r[0], 3)} for r in results],
        "crops": {k: v["file"] if v else None for k, v in saved.items()},
    }
    (IMG / "noaa_coverage.json").write_text(json.dumps(report, indent=2))
    print("done.")


if __name__ == "__main__":
    main()
