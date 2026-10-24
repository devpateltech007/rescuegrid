"""RESCUEGRID 3D — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import FRONTEND_DIST, GEO
from app.services.events import EventBus
from app.simulation.engine import MissionEngine
from app.storage.db import DB

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("rescuegrid")
logging.getLogger("botocore.credentials").setLevel(logging.WARNING)  # rasterio opens many AWS sessions


def build_geo_cache(e: MissionEngine) -> dict:
    """Static geography for the 3D client, enriched with real terrain heights."""
    import numpy as np
    from shapely.geometry import shape

    from app.geospatial.terrain import terrain

    T = terrain()
    b = json.loads((GEO / "buildings.geojson").read_text())
    feats = []
    cents = []
    for f in b["features"]:
        g = shape(f["geometry"])
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        cents.append((g.centroid.x, g.centroid.y, g))
    if cents:
        base = T.height(np.array([c[0] for c in cents]), np.array([c[1] for c in cents]))
    for (cx, cy, g), f, z in zip(cents, b["features"], base if cents else []):
        p = f["properties"]
        h = None
        for k in ("height",):
            try:
                h = float(str(p.get(k)).replace("m", "")) if p.get(k) not in (None, "") else None
            except ValueError:
                h = None
        if h is None:
            try:
                h = 3.2 * float(p.get("building:levels"))
            except (TypeError, ValueError):
                h = None
        est = h is None
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [list(map(list, g.exterior.coords))]},
                      "properties": {"base_m": round(float(z), 2), "height_m": round(h or 6.0, 1), "height_estimated": est,
                                     "building": p.get("building"), "name": p.get("name"), "provenance": "CURRENT_BASEMAP"}})
    # bridge decks with modelled deck heights from the world model (bare-earth DEM has no decks)
    bridges = []
    for ed in e.net.edges.values():
        if not ed.is_bridge:
            continue
        xs, ys = zip(*ed.line_local.coords)
        zs = []
        for x, y in zip(xs, ys):
            zs.append(float(e.world.expected[e.world.idx(x, y)]) if e.world.inside(x, y) else float(T.height(*__import__("app.geospatial.crs", fromlist=["to_geo"]).to_geo(x, y))))
        bridges.append({"edge_id": ed.edge_id, "road_name": ed.road_name, "osm_way_ids": ed.osm_way_ids,
                        "coords": [[lo, la, z] for (lo, la), z in zip(ed.geometry, zs)]})
    return {"buildings": {"type": "FeatureCollection", "features": feats, "note": "Heights from OSM height/levels; else 6 m estimate."},
            "water": json.loads((GEO / "water.geojson").read_text()), "bridges": bridges}


async def sim_loop(app: FastAPI):
    e: MissionEngine = app.state.engine
    while True:
        t0 = time.perf_counter()
        try:
            if e.state.value == "RUNNING":
                await asyncio.to_thread(e.tick)
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
            e.pause("internal error")
        period = 1.0 / max(1, e.speed)
        await asyncio.sleep(max(0.0, period - (time.perf_counter() - t0)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = DB()
    bus = EventBus(db)
    bus.bind_loop(asyncio.get_running_loop())
    app.state.engine = await asyncio.to_thread(MissionEngine, db, bus)
    app.state.cache = await asyncio.to_thread(build_geo_cache, app.state.engine)
    task = asyncio.create_task(sim_loop(app))
    log.info("RESCUEGRID 3D ready — mission %s", app.state.engine.mission_id)
    yield
    task.cancel()


app = FastAPI(title="RESCUEGRID 3D", version="1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(router)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    if (FRONTEND_DIST / "cesium").exists():
        app.mount("/cesium", StaticFiles(directory=FRONTEND_DIST / "cesium"), name="cesium")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "ws/")) or ".." in path:
            from fastapi import HTTPException
            raise HTTPException(404, "not found")
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
