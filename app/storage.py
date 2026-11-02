"""SQLite persistence for generated SignalHub signals."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.models import Signal


class SignalStore:
    """Small SQLite store with explicit connection and transaction lifecycle."""

    def __init__(self, path: str):
        if not path or path == ":memory:":
            # A single in-memory database needs a shared connection; this store
            # deliberately supports file-backed databases only.
            if path != ":memory:":
                raise ValueError("Database path must not be empty")
        self.path = path
        if path != ":memory:" and os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._db() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def check(self) -> None:
        """Raise if the database cannot execute a trivial read."""
        with self._db() as db:
            db.execute("SELECT 1").fetchone()

    def save(self, signal: Signal) -> int:
        with self._db() as db:
            cursor = db.execute(
                """INSERT INTO signals
                   (symbol, market, side, status, score, created_at_ms, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.symbol,
                    signal.market,
                    signal.side,
                    signal.status,
                    signal.score,
                    signal.created_at_ms,
                    json.dumps(signal.to_dict(), allow_nan=False),
                ),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {"id": row["id"], **json.loads(row["payload"])}

    def get(self, signal_id: int) -> dict | None:
        if signal_id <= 0:
            return None
        with self._db() as db:
            row = db.execute(
                "SELECT id, payload FROM signals WHERE id = ?", (signal_id,)
            ).fetchone()
        return self._decode(row)

    def latest(self, n: int = 50) -> list[dict]:
        if n < 1:
            raise ValueError("n must be at least 1")
        limit = min(n, 200)
        with self._db() as db:
            rows = db.execute(
                "SELECT id, payload FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode(row) for row in rows]
