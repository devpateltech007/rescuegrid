"""Headless end-to-end storyline run (no browser). Uses LIVE Bedrock + S3 when credentials exist.

Asserts the final definition of done:
  drones launch -> scans grow -> bridge observation analyzed by Bedrock -> incident ->
  operator confirms -> real graph route changes and avoids bridge -> coordinator retasks ->
  alternate crossing assessed -> operator verifies -> route approved -> Bedrock briefing.
Writes measured results to docs/evaluation_run.json.
Run: python scripts/e2e_demo.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.schemas import OperatorAction  # noqa: E402
from app.services.events import EventBus  # noqa: E402
from app.simulation.engine import MissionEngine  # noqa: E402
from app.storage.db import DB  # noqa: E402

OP = OperatorAction(operator="Planning Specialist J. Rivera", note="e2e run")


def wait_ai(e, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with e.lock:
            busy = [o for o in e.observations.values() if o["ai_status"] in ("PENDING", "RUNNING")]
        if not busy:
            return
        time.sleep(0.5)
    raise SystemExit("FAIL: Bedrock analyses did not finish in time")


def main():
    t_init = time.perf_counter()
    db = DB(ROOT / "data" / "runtime" / "e2e.sqlite")
    e = MissionEngine(db, EventBus(db))
    print(f"engine init {time.perf_counter() - t_init:.1f}s, mission {e.mission_id}")
    r0 = e.routes[e.current_route_id]
    bridge = set(e.net.bridge_edge_ids())
    assert set(r0["edge_ids"]) & bridge, "initial route must cross Whitson bridge"
    print(f"initial route {r0['distance_m']} m / {r0['estimated_travel_seconds']} s via {r0['road_names']}")

    e.start()
    bridge_inc = None
    t_sim = time.perf_counter()
    for i in range(1500):
        e.tick()
        if i % 50 == 0:
            with e.lock:
                print(f"  t={e.tick_n:4d}s cov={e.recon.coverage_fraction()*100:5.1f}% pts={e.total_points:7d} "
                      f"obs={len(e.observations)} inc={len(e.incidents)} " +
                      " ".join(f"{k}:{d.state.value[:4]}/{d.battery_pct:.0f}%" for k, d in e.drones.items()))
        with e.lock:
            bridge_inc = next((x for x in e.incidents.values() if set(x["affected_road_segment_ids"]) & bridge), None)
        if bridge_inc:
            break
        if not e.observations and i > 400:
            break
        # give Bedrock time when a bridge observation exists
        with e.lock:
            pend = any(set(o["nearby_road_segment_ids"]) & bridge and o["ai_status"] in ("PENDING", "RUNNING")
                       for o in e.observations.values())
        if pend:
            wait_ai(e)
    tick_ms = (time.perf_counter() - t_sim) / max(e.tick_n, 1) * 1000
    print(f"mean tick wall time {tick_ms:.1f} ms")
    for o in e.observations.values():
        ha = o.get("hazard_assessment") or {}
        print(f"  OBS {o['observation_id']} {o['drone_id']} {o['trigger']} {o['source_type']} roads={o['nearby_road_names']} "
              f"ai={o['ai_status']} -> {ha.get('hazard_type')} {ha.get('suggested_accessibility')}")
    assert bridge_inc, "FAIL: no Bedrock-backed incident on the Whitson bridge"
    inv = e.invocations[e.observations[bridge_inc["observation_ids"][0]]["ai_invocation_id"]]
    print(f"bridge incident {bridge_inc['incident_id']} {bridge_inc['hazard_type']} {bridge_inc['suggested_accessibility']} "
          f"model={inv['model_id']} live={inv['live']} latency={inv['latency_ms']}ms tokens={inv['input_tokens']}/{inv['output_tokens']}")
    assert inv["live"] and inv["status"] == "SUCCESS"

    res = e.verify_incident(bridge_inc["incident_id"], OP)
    route = res["route"]
    assert route["status"] == "OK"
    new = route["current"]
    assert not set(new["edge_ids"]) & bridge, "new route must avoid the bridge"
    print(f"REROUTE {route['previous']['distance_m']} m -> {new['distance_m']} m, "
          f"{route['previous']['estimated_travel_seconds']} s -> {new['estimated_travel_seconds']} s via {new['road_names']} "
          f"(recalc {route['compute_ms']} ms, unverified edges {new['unverified_edge_count']})")
    print("retask:", e.retask_log[-1]["drone_id"] if e.retask_log else None, e.retask_log[-1]["road_name"] if e.retask_log else None)

    alt_inc = None
    for i in range(900):
        e.tick(force=True)
        wait_ai(e) if any(o["ai_status"] in ("PENDING", "RUNNING") for o in e.observations.values()) else None
        with e.lock:
            alt_inc = next((x for x in e.incidents.values() if x["incident_id"] != bridge_inc["incident_id"]
                            and set(x["affected_road_segment_ids"]) & set(new["edge_ids"])), None)
        if alt_inc:
            break
    if alt_inc:
        print(f"alt-route incident {alt_inc['incident_id']} {alt_inc['hazard_type']} {alt_inc['suggested_accessibility']} roads={alt_inc['affected_road_names']}")
        if alt_inc["suggested_accessibility"] == "LIKELY_PASSABLE":
            r2 = e.verify_incident(alt_inc["incident_id"], OP, passable=True)["route"]
            print(f"after verify-passable: unverified edges {r2['current']['unverified_edge_count']}")
    cur = e.routes[e.current_route_id]
    e.approve_route(cur["route_id"], OP)
    b = e.generate_briefing(OP.operator)
    print("briefing:", b["status"], (b.get("briefing") or {}).get("headline"))
    m = e.metrics()
    out = {"mission_id": e.mission_id, "mean_tick_ms": round(tick_ms, 1), "metrics": m,
           "bridge_incident": bridge_inc["incident_id"], "bridge_invocation": {k: inv[k] for k in ("model_id", "latency_ms", "input_tokens", "output_tokens", "status")},
           "reroute": {"from_m": route["previous"]["distance_m"], "to_m": new["distance_m"],
                       "from_s": route["previous"]["estimated_travel_seconds"], "to_s": new["estimated_travel_seconds"],
                       "recalc_ms": route["compute_ms"]},
           "briefing_status": b["status"]}
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "evaluation_run.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(m, indent=1))
    print("E2E PASS")
    e.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
