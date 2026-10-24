"""Engine tests with Bedrock/S3 disabled (no AWS calls). They verify determinism, sensing,
reset, pause/resume, and that a failed AI call never creates an incident."""
import hashlib
import json
import time

import numpy as np
import pytest

from app.ai.bedrock import bedrock
from app.models.schemas import AccessStatus, HazardAssessment, OperatorAction
from app.sensors.lidar import LidarConfig, scan
from app.services.events import EventBus
from app.simulation.engine import MissionEngine
from app.storage.db import DB
from app.config import RUNTIME


@pytest.fixture(scope="module")
def eng():
    db = DB(RUNTIME / "test_engine.sqlite")
    return MissionEngine(db, EventBus(db))


def run(e, n):
    for _ in range(n):
        e.tick()


def telemetry_hash(e):
    return hashlib.sha256(json.dumps([e.telemetry(d) | {"mission_id": "", "simulated_timestamp": ""} for d in e.drones.values()],
                                     sort_keys=True).encode()).hexdigest()


def test_no_points_before_scan(eng):
    eng.reset()
    assert eng.total_points == 0 and not eng.point_batches and eng.recon.coverage_fraction() == 0


def test_deterministic_replay(eng):
    eng.reset()
    eng.start()
    run(eng, 40)
    h1, p1 = telemetry_hash(eng), eng.total_points
    eng.reset()
    eng.start()
    run(eng, 40)
    assert telemetry_hash(eng) == h1 and eng.total_points == p1


def test_pause_resume(eng):
    eng.reset()
    eng.start()
    run(eng, 5)
    eng.pause()
    t = eng.tick_n
    run(eng, 5)
    assert eng.tick_n == t
    eng.resume()
    run(eng, 3)
    assert eng.tick_n == t + 3


def test_three_drones_distinct_missions(eng):
    eng.reset()
    labels = {k: d.plan[1].label for k, d in eng.drones.items()}
    assert len(set(labels.values())) == 3
    eng.start()
    run(eng, 30)
    for d in eng.drones.values():
        assert d.battery_pct < 100 and d.z - d.ground > 10


def test_lidar_samples_real_geometry(eng):
    w = eng.world
    x, y = eng.coord.home
    z = w.ground_height(x, y) + 40
    res = scan(w, x, y, z, 0, -90, LidarConfig(rays_across=12, rays_along=12), np.random.default_rng(1))
    surf, _, _ = w.sample_surface(res.xyz[:, 0], res.xyz[:, 1])
    err = np.abs(res.xyz[:, 2] - surf)
    # hits on building walls legitimately land between roof and ground heights of a 1 m cell
    assert np.quantile(err, 0.9) < 0.2
    assert np.median(err) < 0.08  # ~ range-noise sigma 0.05 m


def test_bridge_damage_is_visible_to_change_detection(eng):
    bx, by = eng.coord.bridge_xy
    w = eng.world
    res = scan(w, bx, by, w.ground_height(bx, by) + 40, 0, -90, LidarConfig(), np.random.default_rng(2))
    assert (np.abs(res.deviation) > 0.45).sum() > 10


def test_reset_clears_results(eng):
    eng.reset()
    eng.start()
    run(eng, 20)
    assert eng.total_points > 0
    eng.reset()
    assert eng.total_points == 0 and not eng.recon.dirty and not eng.observations


def test_failed_bedrock_creates_no_incident(eng):
    assert not bedrock.enabled  # conftest disables live AWS
    eng.reset()
    eng.start()
    for _ in range(200):
        eng.tick()
        if eng.observations:
            break
    eng.pool.submit(lambda: None).result()
    time.sleep(1.0)
    assert eng.observations, "drones should capture at least one observation"
    assert not eng.incidents
    assert any(v["status"] == "FAILED" for v in eng.invocations.values())


def test_verification_changes_route_and_is_recorded(eng):
    eng.reset()
    # inject a validated assessment for the bridge (as if Bedrock returned it) through the normal path
    from app.ai.bedrock import BedrockClient  # noqa: F401
    obs_id = None
    eng.start()
    bx, by = eng.coord.bridge_xy
    d = eng.drones["BRAVO"]
    with eng.lock:
        obs_id = eng._capture(d, bx, by, trigger="TEST")
    time.sleep(0.5)
    ha = HazardAssessment(hazard_type="BRIDGE_DAMAGE", affected_feature="bridge approach", visual_evidence="test",
                          severity="HIGH", suggested_accessibility="LIKELY_BLOCKED", confidence=0.9, uncertainty_notes="test",
                          requires_human_review=True, recommended_next_inspection="test")
    from app.models.schemas import AIInvocation
    inv = AIInvocation(invocation_id="AI-TEST", kind="HAZARD_ANALYSIS", model_id="stub (test only)", observation_id=obs_id,
                       status="SUCCESS", live=False, started_at="t")
    with eng.lock:
        iid = eng._incident_from(eng.observations[obs_id], ha, inv)
    assert all(eng.net.edges[e].access_status == AccessStatus.SUSPECTED_BLOCKED for e in eng.incidents[iid]["affected_road_segment_ids"])
    before = eng.routes[eng.current_route_id]
    out = eng.verify_incident(iid, OperatorAction(operator="Test Operator"))
    assert out["route"]["status"] == "OK"
    assert out["route"]["current"]["distance_m"] > before["distance_m"]
    assert not set(out["route"]["current"]["edge_ids"]) & set(eng.net.bridge_edge_ids())
    assert eng.decisions[-1]["operator"] == "Test Operator"
    assert eng.db.get("decisions", eng.decisions[-1]["decision_id"])
    assert eng.retask_log, "coordinator should retask a drone to the new route's unverified bridge"
    assert eng.retask_log[-1]["candidates"][0]["is_bridge"]
