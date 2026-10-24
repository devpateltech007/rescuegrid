"""Drive the live app through the storyline in headless Chromium and save screenshots.
Usage: python scripts/capture_story.py [base_url] [out_dir] [--full]
Uses the real API (live Bedrock). Resets the mission first.
"""
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/screens")
FULL = "--full" in sys.argv
OUT.mkdir(parents=True, exist_ok=True)
OP = {"operator": "Planning Specialist J. Rivera", "note": "headless capture"}
stamp = time.strftime("%H%M%S")


def post(p, j=None):
    r = requests.post(BASE + p, json=j, timeout=120)
    r.raise_for_status()
    return r.json()


def mission():
    return requests.get(BASE + "/api/mission", timeout=30).json()


def wait_for(pred, timeout=240, every=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = mission()
        v = pred(m)
        if v:
            return v
        time.sleep(every)
    return None


post("/api/mission/reset")
time.sleep(2)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(BASE)
    time.sleep(30)
    shot = lambda n: (pg.screenshot(path=str(OUT / f"{n}_{stamp}.png")), print("shot", n))  # noqa: E731
    shot("s1_briefing")
    post("/api/mission/start")
    post("/api/mission/speed", {"speed": 4})
    time.sleep(25)
    shot("s2_swarm")
    if FULL:
        bridge = wait_for(lambda m: next((i for i in m["incidents"] if i.get("is_bridge")), None), timeout=300)
        print("bridge incident:", bridge and bridge["incident_id"])
        post("/api/mission/pause")
        time.sleep(4)
        pg.evaluate("""() => { const s = window.__rg; if (s) { s.select('incident', '%s'); s.set({rightTab: 'incidents'}); } }""" % (bridge["incident_id"] if bridge else ""))
        time.sleep(3)
        shot("s3_incident")
        if bridge:
            post(f"/api/incidents/{bridge['incident_id']}/verify", {**OP, "outcome": "BLOCKED", "evidence_reviewed": bridge["observation_ids"]})
            time.sleep(8)
            shot("s4_reroute")
            post("/api/mission/resume")
            alt = wait_for(lambda m: next((i for i in m["incidents"] if i["incident_id"] != bridge["incident_id"]
                                           and i["is_bridge"]), None), timeout=400)
            print("alt incident:", alt and alt["incident_id"])
            if alt and alt["suggested_accessibility"] == "LIKELY_PASSABLE":
                post(f"/api/incidents/{alt['incident_id']}/verify", {**OP, "outcome": "PASSABLE", "evidence_reviewed": alt["observation_ids"]})
            time.sleep(4)
            m = mission()
            post(f"/api/routes/{m['current_route_id']}/approve", OP)
            post("/api/briefings/generate", {"operator": OP["operator"]})
            pg.evaluate("() => window.__rg && window.__rg.set({rightTab: 'briefing'})")
            time.sleep(5)
            shot("s5_briefing")
    b.close()
print("errors:", errs[:20])
