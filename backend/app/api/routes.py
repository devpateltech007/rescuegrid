"""REST + WebSocket interfaces (spec section 10)."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.ai.bedrock import bedrock
from app.config import GEO, IMAGERY, RUNTIME, TERRAIN, aws_config
from app.models.schemas import OperatorAction, RetaskRequest, RoutePlanRequest
from app.routing.planner import NoRouteError, plan_routes
from app.storage.s3 import s3

router = APIRouter()


def eng(request: Request):
    return request.app.state.engine


def _404(e: KeyError):
    raise HTTPException(404, f"not found: {e.args[0] if e.args else ''}")


# ---------------- health ----------------
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/system/status")
def system_status(request: Request):
    e = eng(request)
    return {"bedrock": bedrock.status(), "s3": s3.status(), "mission_state": e.state.value,
            "event_seq": e.bus.seq, "subscribers": len(e.bus.subscribers),
            "model_verified_at": aws_config().get("verified_at"),
            "offline_fixture_enabled": __import__("app.config", fromlist=["settings"]).settings.allow_offline_fixture}


# ---------------- mission ----------------
class SpeedReq(BaseModel):
    speed: int = Field(ge=1, le=10)


class AutoPauseReq(BaseModel):
    enabled: bool


@router.get("/api/mission")
def get_mission(request: Request):
    return eng(request).snapshot()


@router.post("/api/mission/start")
def start(request: Request):
    eng(request).start()
    return {"state": eng(request).state.value}


@router.post("/api/mission/pause")
def pause(request: Request):
    eng(request).pause()
    return {"state": eng(request).state.value}


@router.post("/api/mission/resume")
def resume(request: Request):
    eng(request).resume()
    return {"state": eng(request).state.value}


@router.post("/api/mission/reset")
def reset(request: Request):
    eng(request).reset()
    return {"mission_id": eng(request).mission_id}


@router.post("/api/mission/step")
def step(request: Request, n: int = Query(1, ge=1, le=600)):
    e = eng(request)
    if e.state.value == "BRIEFING":
        e.start()
        e.pause("step mode")
    for _ in range(n):
        e.tick(force=True)
    return {"tick": e.tick_n, "simulated_timestamp": e.sim_time()}


@router.post("/api/mission/speed")
def speed(req: SpeedReq, request: Request):
    if req.speed not in (1, 4, 10):
        raise HTTPException(422, "speed must be 1, 4 or 10")
    eng(request).set_speed(req.speed)
    return {"speed": req.speed}


@router.post("/api/mission/auto-pause")
def auto_pause(req: AutoPauseReq, request: Request):
    eng(request).auto_pause = req.enabled
    return {"auto_pause": req.enabled}


@router.get("/api/events")
def events(request: Request, after_seq: int = Query(0, ge=0), limit: int = Query(2000, le=10000)):
    e = eng(request)
    return e.db.list("events", e.mission_id, limit=limit, after_seq=after_seq)


# ---------------- drones ----------------
@router.get("/api/drones")
def drones(request: Request):
    return eng(request).snapshot()["drones"]


@router.get("/api/drones/{drone_id}")
def drone(drone_id: str, request: Request):
    for d in eng(request).snapshot()["drones"]:
        if d["drone_id"] == drone_id.upper():
            return d
    raise HTTPException(404, "drone not found")


@router.post("/api/drones/{drone_id}/retask")
def retask(drone_id: str, req: RetaskRequest, request: Request):
    try:
        return eng(request).retask(drone_id.upper(), req)
    except KeyError as e:
        _404(e)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- scans ----------------
@router.get("/api/scans")
def scans(request: Request, drone_id: str | None = None, limit: int = Query(200, le=5000)):
    s = eng(request).scans_meta
    if drone_id:
        s = [x for x in s if x["drone_id"] == drone_id.upper()]
    return s[-limit:]


@router.get("/api/scans/coverage")
def coverage(request: Request):
    e = eng(request)
    with e.lock:
        return {**e.coverage_summary(), "grid": e.recon.coverage_grid()}


@router.get("/api/scans/points")
def scan_points(request: Request, after_seq: int = Query(0, ge=0)):
    """Decimated streamed point batches (for reconnect / snapshot rebuild)."""
    e = eng(request)
    with e.lock:
        return [b for b in e.point_batches if b["seq"] > after_seq]


@router.get("/api/scans/tiles")
def tiles(request: Request):
    e = eng(request)
    with e.lock:
        out = []
        for tr in range(e.recon.ntiles):
            for tc in range(e.recon.ntiles):
                r0, c0 = tr * 32, tc * 32
                if (e.recon.cnt[r0:r0 + 32, c0:c0 + 32] > 0).any():
                    out.append(e.recon.tile_payload(tr, tc))
        return out


@router.get("/api/scans/{scan_id}")
def scan_one(scan_id: str, request: Request):
    for s in eng(request).scans_meta:
        if s["scan_id"] == scan_id:
            return s
    raise HTTPException(404, "scan not found")


# ---------------- observations / AI ----------------
@router.get("/api/observations")
def observations(request: Request):
    return list(eng(request).observations.values())


@router.get("/api/observations/{oid}")
def observation(oid: str, request: Request):
    o = eng(request).observations.get(oid)
    if not o:
        raise HTTPException(404, "observation not found")
    return o


@router.post("/api/observations/{oid}/analyze")
def analyze(oid: str, request: Request):
    try:
        eng(request).analyze_observation(oid)
    except KeyError as e:
        _404(e)
    return {"queued": oid}


@router.get("/api/ai/invocations")
def invocations(request: Request):
    return list(eng(request).invocations.values())


_SAFE_ID = re.compile(r"^OBS-[A-F0-9]{6}\.jpg$")


@router.get("/api/media/observations/{name}")
def media(name: str):
    if not _SAFE_ID.match(name):
        raise HTTPException(400, "bad name")
    p = RUNTIME / "observations" / name
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type="image/jpeg")


@router.get("/api/media/evidence/{name}")
def evidence(name: str):
    if not re.match(r"^noaa_[a-z_]+\.jpg$", name):
        raise HTTPException(400, "bad name")
    p = IMAGERY / name
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type="image/jpeg")


# ---------------- incidents ----------------
@router.get("/api/incidents")
def incidents(request: Request):
    return list(eng(request).incidents.values())


@router.get("/api/incidents/{iid}")
def incident(iid: str, request: Request):
    i = eng(request).incidents.get(iid)
    if not i:
        raise HTTPException(404, "incident not found")
    return i


class VerifyReq(OperatorAction):
    outcome: str = Field(default="BLOCKED", pattern="^(BLOCKED|PASSABLE)$")


@router.post("/api/incidents/{iid}/verify")
def verify(iid: str, req: VerifyReq, request: Request):
    try:
        return eng(request).verify_incident(iid, req, passable=req.outcome == "PASSABLE")
    except KeyError as e:
        _404(e)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/api/incidents/{iid}/reject")
def reject(iid: str, req: OperatorAction, request: Request):
    try:
        return eng(request).reject_incident(iid, req)
    except KeyError as e:
        _404(e)


@router.post("/api/incidents/{iid}/request-inspection")
def request_inspection(iid: str, req: OperatorAction, request: Request):
    try:
        return eng(request).request_inspection(iid, req)
    except KeyError as e:
        _404(e)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/api/decisions")
def decisions(request: Request):
    e = eng(request)
    return e.db.list("decisions", None, limit=5000)


# ---------------- routing ----------------
@router.post("/api/routes/plan")
def plan(req: RoutePlanRequest, request: Request):
    e = eng(request)
    with e.lock:
        s = e.scenario["staging"]["node"] if req.start_lon is None else e.net.nearest_node(req.start_lon, req.start_lat)
        d = e.scenario["destination"]["node"] if req.dest_lon is None else e.net.nearest_node(req.dest_lon, req.dest_lat)
        try:
            plans = plan_routes(e.net, s, d, k=req.alternatives, sim_time=e.sim_time())
        except NoRouteError as ex:
            return {"status": "NO_ROUTE", "message": str(ex), "routes": []}
        out = []
        for p in plans:
            pd = p.model_dump(mode="json")
            pd["mission_id"] = e.mission_id
            e.routes.setdefault(pd["route_id"], pd)
            out.append(pd)
        return {"status": "OK", "routes": out}


@router.post("/api/routes/recalculate")
def recalc(request: Request):
    return eng(request).recalculate("Manual recalculation")


@router.get("/api/routes/{rid}")
def route(rid: str, request: Request):
    r = eng(request).routes.get(rid)
    if not r:
        raise HTTPException(404, "route not found")
    return r


@router.post("/api/routes/{rid}/approve")
def approve(rid: str, req: OperatorAction, request: Request):
    try:
        return eng(request).approve_route(rid, req)
    except KeyError as e:
        _404(e)
    except ValueError as e:
        raise HTTPException(409, str(e))


# ---------------- briefings ----------------
@router.post("/api/briefings/generate")
async def gen_briefing(req: OperatorAction, request: Request):
    e = eng(request)
    return await asyncio.to_thread(e.generate_briefing, req.operator)


@router.get("/api/briefings/{bid}")
def briefing(bid: str, request: Request):
    b = eng(request).briefings.get(bid)
    if not b:
        raise HTTPException(404, "briefing not found")
    return b


# ---------------- geography (static world) ----------------
@router.get("/api/geo/terrain/{name}.json")
def terrain_hdr(name: str):
    if name not in ("dem_fine", "dem_coarse"):
        raise HTTPException(404)
    return JSONResponse(json.loads((TERRAIN / f"{name}.json").read_text()), headers={"Cache-Control": "max-age=3600"})


@router.get("/api/geo/terrain/{name}.u16")
def terrain_bin(name: str):
    if name not in ("dem_fine", "dem_coarse"):
        raise HTTPException(404)
    return FileResponse(TERRAIN / f"{name}.u16", media_type="application/octet-stream", headers={"Cache-Control": "max-age=3600"})


@router.get("/api/geo/roads")
def roads(request: Request):
    e = eng(request)
    with e.lock:
        return e.net.geojson()


@router.get("/api/geo/buildings")
def buildings(request: Request):
    return request.app.state.cache["buildings"]


@router.get("/api/geo/bridges")
def bridges(request: Request):
    return request.app.state.cache["bridges"]


@router.get("/api/geo/water")
def water(request: Request):
    return request.app.state.cache["water"]


@router.get("/api/geo/imagery")
def imagery():
    cov = json.loads((IMAGERY / "noaa_coverage.json").read_text())
    crops = []
    for m in sorted(IMAGERY.glob("noaa_*.json")):
        if m.name != "noaa_coverage.json":
            d = json.loads(m.read_text())
            d["url"] = f"/api/media/evidence/{Path(d['file']).name}"
            crops.append(d)
    return {"coverage": cov, "crops": crops}


_TILE_CACHE = RUNTIME.parent / "cache" / "noaa_tiles_proxy"


@router.get("/api/tiles/noaa/{z}/{x}/{y}")
def noaa_tile(z: int, x: int, y: int):
    """Same-origin proxy (with disk cache) for NOAA Helene XYZ tiles so WebGL can use them."""
    if not (10 <= z <= 20) or x < 0 or y < 0:
        raise HTTPException(400)
    cov = json.loads((IMAGERY / "noaa_coverage.json").read_text())
    tpl = cov["tile_template"]
    p = _TILE_CACHE / f"{z}_{x}_{y}"
    if p.exists():
        data = p.read_bytes()
    else:
        try:
            r = requests.get(tpl.format(z=z, x=x, y=y), timeout=15, headers={"User-Agent": "RESCUEGRID3D/0.1"})
            data = r.content if r.status_code == 200 else b""
        except requests.RequestException:
            data = b""
        _TILE_CACHE.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if not data:
        return Response(status_code=404)
    mt = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(content=data, media_type=mt, headers={"Cache-Control": "max-age=86400"})


# ---------------- websocket ----------------
@router.websocket("/ws/mission")
async def ws_mission(ws: WebSocket):
    await ws.accept()
    e = ws.app.state.engine
    q = e.bus.subscribe()
    try:
        await ws.send_text(json.dumps({"type": "hello", "seq": e.bus.seq, "mission_id": e.mission_id}))
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        e.bus.unsubscribe(q)
