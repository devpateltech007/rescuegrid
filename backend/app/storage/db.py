"""SQLite persistence (MVP). Each record type is a table of JSON documents keyed by id.
Operator decisions and AI invocations are append-only audit records that survive resets."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.config import settings

TABLES = ["events", "observations", "scans", "incidents", "decisions", "invocations", "routes", "briefings", "missions"]
AUDIT_TABLES = {"decisions", "invocations"}  # kept across mission resets


class DB:
    def __init__(self, path: Path = settings.db_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            for t in TABLES:
                self.conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, mission_id TEXT, seq INTEGER, "
                    f"created TEXT DEFAULT CURRENT_TIMESTAMP, data TEXT NOT NULL)")
            self.conn.commit()

    def put(self, table: str, id_: str, data: dict[str, Any], mission_id: str = "", seq: int | None = None) -> None:
        assert table in TABLES
        with self.lock:
            self.conn.execute(
                f"INSERT INTO {table}(id, mission_id, seq, data) VALUES(?,?,?,?) "
                f"ON CONFLICT(id) DO UPDATE SET data=excluded.data, seq=COALESCE(excluded.seq, {table}.seq)",
                (id_, mission_id, seq, json.dumps(data, default=str)))
            self.conn.commit()

    def put_many(self, table: str, rows: list[tuple[str, dict]], mission_id: str = "") -> None:
        assert table in TABLES
        with self.lock:
            self.conn.executemany(
                f"INSERT INTO {table}(id, mission_id, seq, data) VALUES(?,?,NULL,?) "
                f"ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                [(i, mission_id, json.dumps(d, default=str)) for i, d in rows])
            self.conn.commit()

    def get(self, table: str, id_: str) -> dict | None:
        assert table in TABLES
        with self.lock:
            r = self.conn.execute(f"SELECT data FROM {table} WHERE id=?", (id_,)).fetchone()
        return json.loads(r[0]) if r else None

    def list(self, table: str, mission_id: str | None = None, limit: int = 1000, after_seq: int | None = None) -> list[dict]:
        assert table in TABLES
        q, args = f"SELECT data FROM {table}", []
        conds = []
        if mission_id is not None:
            conds.append("mission_id=?")
            args.append(mission_id)
        if after_seq is not None:
            conds.append("seq>?")
            args.append(after_seq)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY COALESCE(seq, 0), created LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.conn.execute(q, args).fetchall()
        return [json.loads(r[0]) for r in rows]

    def clear_mission(self, mission_id: str) -> None:
        with self.lock:
            for t in TABLES:
                if t not in AUDIT_TABLES:
                    self.conn.execute(f"DELETE FROM {t} WHERE mission_id=?", (mission_id,))
            self.conn.commit()
