"""Sequenced mission event bus. Every event gets a monotonically increasing seq, is
persisted, and is fanned out to WebSocket subscribers. Frontend state = snapshot + events."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.storage.db import DB

log = logging.getLogger("rescuegrid.events")

# High-frequency events that are streamed but not persisted (keeps SQLite small).
# Bulk geometry (scan points, recon tiles) is kept in engine memory / scan files and served by
# /api/scans/points and /api/scans/tiles instead of being duplicated into the event table.
EPHEMERAL = {"drone.telemetry", "sim.clock", "scan.completed", "recon.tiles_updated", "scan.coverage_updated"}


class EventBus:
    def __init__(self, db: DB):
        self.db = db
        self.seq = 0
        self.subscribers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def emit(self, mission_id: str, type_: str, payload: dict[str, Any], sim_time: str) -> dict:
        """Thread-safe: may be called from worker threads (e.g. Bedrock calls)."""
        self.seq += 1
        ev = {
            "event_id": f"EV-{uuid.uuid4().hex[:10]}",
            "seq": self.seq,
            "mission_id": mission_id,
            "type": type_,
            "simulated_timestamp": sim_time,
            "wall_timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        if type_ not in EPHEMERAL:
            self.db.put("events", ev["event_id"], ev, mission_id, ev["seq"])
        msg = json.dumps(ev, default=str)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._fanout, msg)
        return ev

    def _fanout(self, msg: str) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning("subscriber queue full; dropping subscriber")
                self.subscribers.discard(q)
