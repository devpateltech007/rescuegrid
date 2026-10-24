import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
from app.routing.graph import RoadNetwork
net = RoadNetwork()
a = json.loads((ROOT / "data/geography/study_area.json").read_text())
cx, cy = a["center_local"]["x"], a["center_local"]["y"]
rows = []
for e in net.edges.values():
    c = e.line_local.interpolate(0.5, normalized=True)
    d = np.hypot(c.x - cx, c.y - cy)
    if d < 1200 and e.road_class not in ("residential", "service", "unclassified"):
        rows.append((round(d), e.road_name, e.road_class, round(e.length_m), round(c.x - cx), round(c.y - cy), e.edge_id, e.is_bridge))
for r in sorted(rows):
    print(r)
