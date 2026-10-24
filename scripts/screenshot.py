"""Headless visual check of the command center (Chromium + SwiftShader WebGL).
Usage: python scripts/screenshot.py [url] [out.png] [wait_seconds] [actions]
actions: comma list of  start | speed4 | speed10 | wait:N | shot:name | click:text
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/screens/main.png")
wait = float(sys.argv[3]) if len(sys.argv) > 3 else 20
actions = sys.argv[4].split(",") if len(sys.argv) > 4 else []
out.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    logs = []
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
    pg.goto(url)
    time.sleep(wait)
    pg.screenshot(path=str(out))
    for a in actions:
        if a.startswith("wait:"):
            time.sleep(float(a[5:]))
        elif a.startswith("shot:"):
            pg.screenshot(path=str(out.parent / f"{a[5:]}.png"))
        elif a.startswith("click:"):
            pg.get_by_text(a[6:], exact=False).first.click()
        elif a.startswith("eval:"):
            pg.evaluate(a[5:])
    b.close()
print("\n".join(logs[-60:]))
print("saved", out)
