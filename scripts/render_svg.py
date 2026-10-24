"""Render an SVG to a 1920x1080 PNG with headless Chromium. Usage: python scripts/render_svg.py in.svg out.png"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(src.as_uri())
    pg.screenshot(path=str(dst))
    b.close()
print("wrote", dst)
