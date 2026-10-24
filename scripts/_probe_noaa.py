"""Exploratory: dump NOAA Helene app.js layer config and probe tile coverage at the bridge."""
import math
import re
import requests

H = {"User-Agent": "RESCUEGRID3D-hackathon/0.1"}
t = requests.get("https://storms.ngs.noaa.gov/storms/helene/js/app.js", headers=H, timeout=30).text
print("app.js len", len(t))
for m in re.finditer(r"stormscdn|tiles|metadata|catalog|\.json", t):
    s = max(0, m.start() - 150)
    print("...", t[s:m.start() + 150].replace("\n", " "))
    print("----")
