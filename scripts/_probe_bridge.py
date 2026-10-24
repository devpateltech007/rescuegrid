"""Exploratory: find Whitson Ave ways in OSM near Swannanoa, NC (Overpass)."""
import json
import requests

Q = """
[out:json][timeout:60];
(
  way["name"~"Whitson",i](35.57,-82.45,35.63,-82.35);
  way["bridge"]["highway"](35.590,-82.420,35.610,-82.380);
);
out tags geom;
"""
r = requests.post("https://overpass-api.de/api/interpreter", data={"data": Q}, timeout=90,
                  headers={"User-Agent": "RESCUEGRID3D-hackathon/0.1"})
r.raise_for_status()
for el in r.json()["elements"]:
    g = el.get("geometry", [])
    print(el["id"], json.dumps(el.get("tags")), "n=", len(g),
          "first=", (g[0]["lat"], g[0]["lon"]) if g else None,
          "last=", (g[-1]["lat"], g[-1]["lon"]) if g else None)
