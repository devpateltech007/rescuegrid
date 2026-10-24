"""Smoke-test a running RESCUEGRID 3D server. Usage: python scripts/smoke_api.py [base_url]"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


for _ in range(120):  # up to ~10 min: EC2 bootstrap installs dependencies first (nginx returns 502 meanwhile)
    try:
        if requests.get(f"{BASE}/health", timeout=3).ok:
            break
    except requests.RequestException:
        pass
    time.sleep(5)
r = requests.get(f"{BASE}/health", timeout=5)
check("health", r.ok and r.json()["status"] == "ok")
st = requests.get(f"{BASE}/api/system/status", timeout=5).json()
check("system status", "bedrock" in st, json.dumps({k: st[k]["state"] for k in ("bedrock", "s3")}))
m = requests.get(f"{BASE}/api/mission", timeout=10).json()
check("mission snapshot", m["mission"]["mission_id"] and len(m["drones"]) == 3, m["mission"]["state"])
pub = json.dumps(m["mission"]["scenario"])
check("hidden hazards not exposed", "GT-DEBRIS" not in pub and "craters" not in pub)
roads = requests.get(f"{BASE}/api/geo/roads", timeout=20).json()
check("road graph", len(roads["features"]) > 1000, f"{len(roads['features'])} edges")
b = requests.get(f"{BASE}/api/geo/buildings", timeout=20).json()
check("buildings", len(b["features"]) > 1000, f"{len(b['features'])}")
t = requests.get(f"{BASE}/api/geo/terrain/dem_fine.json", timeout=5).json()
check("terrain header", t["width"] > 1000, f"{t['width']}x{t['height']} {t['vertical_datum']}")
cur = m["routes"][m["current_route_id"]]
check("provisional route", cur["distance_m"] > 0, f"{cur['distance_m']} m via {cur['road_names']}")
bad = requests.post(f"{BASE}/api/incidents/INC-XXXX/verify", json={"operator": "x<script>"}, timeout=5)
check("operator validation", bad.status_code == 422, str(bad.status_code))
img = requests.get(f"{BASE}/api/media/observations/..%2F..%2Fsecrets.jpg", timeout=5)
check("path traversal blocked", img.status_code in (400, 404), str(img.status_code))
tile = requests.get(f"{BASE}/api/tiles/noaa/19/{0}/{0}", timeout=20)
check("noaa proxy responds", tile.status_code in (200, 404))
print("SMOKE", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
