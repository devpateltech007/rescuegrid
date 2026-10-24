import json

import pytest

from app.config import SCENARIOS
from app.models.schemas import AccessStatus
from app.routing.graph import RoadNetwork
from app.routing.planner import NoRouteError, plan_routes

SC = json.loads((SCENARIOS / "helene_swannanoa.json").read_text())


@pytest.fixture(scope="module")
def net():
    return RoadNetwork()


def test_graph_is_real_and_has_bridge(net):
    assert len(net.edges) > 1000
    b = net.bridge_edge_ids()
    assert len(b) == 2 and all(net.edges[e].is_bridge for e in b)
    assert all("Whitson" in net.edges[e].road_name for e in b)


def test_initial_route_crosses_bridge(net):
    net.reset_status()
    r = plan_routes(net, SC["staging"]["node"], SC["destination"]["node"], k=1)[0]
    assert set(r.edge_ids) & set(net.bridge_edge_ids())
    assert r.distance_m == pytest.approx(sum(net.edges[e].length_m for e in r.edge_ids), abs=0.1)


def test_blocking_bridge_reroutes_and_avoids_it(net):
    net.reset_status()
    before = plan_routes(net, SC["staging"]["node"], SC["destination"]["node"], k=1)[0]
    for e in net.bridge_edge_ids():
        net.edges[e].access_status = AccessStatus.CONFIRMED_BLOCKED
    after = plan_routes(net, SC["staging"]["node"], SC["destination"]["node"], k=3)
    assert not set(after[0].edge_ids) & set(net.bridge_edge_ids())
    assert all(not set(a.edge_ids) & set(net.bridge_edge_ids()) for a in after)
    assert after[0].distance_m > before.distance_m
    assert len(after) >= 2
    net.reset_status()


def test_unknown_edges_are_counted(net):
    net.reset_status()
    r = plan_routes(net, SC["staging"]["node"], SC["destination"]["node"], k=1)[0]
    assert r.unverified_edge_count == len(r.edge_ids)
    for e in r.edge_ids:
        net.edges[e].access_status = AccessStatus.VERIFIED_PASSABLE
    r2 = plan_routes(net, SC["staging"]["node"], SC["destination"]["node"], k=1)[0]
    assert r2.unverified_edge_count == 0
    net.reset_status()


def test_no_route_is_reported_not_invented(net):
    net.reset_status()
    dest = SC["destination"]["node"]
    for e in net.edges.values():
        if e.v == dest:
            e.access_status = AccessStatus.CONFIRMED_BLOCKED
    with pytest.raises(NoRouteError):
        plan_routes(net, SC["staging"]["node"], dest)
    net.reset_status()


def test_oneway_respected(net):
    net.reset_status()
    oneway = [e for e in net.edges.values() if e.oneway]
    assert oneway, "graph should contain one-way edges"
    e = oneway[0]
    assert not net.G.has_edge(e.v, e.u) or any(
        net.edges[x].osm_way_ids != e.osm_way_ids for x in (f"{e.v}-{e.u}-{k}" for k in range(3)) if x in net.edges)
