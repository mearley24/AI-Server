"""Track NOAA/METAR forecast vs outcome for weather markets (position sizing hints)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DATA_PATH = Path(os.environ.get("WEATHER_ACCURACY_DB", "/data/weather_accuracy.db"))


class WeatherAccuracyStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or DATA_PATH
        self._local = threading.local()
        self._init()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(self._path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self._path))
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS station_scores (
                station_id TEXT PRIMARY KEY,
                samples INTEGER DEFAULT 0,
                hits INTEGER DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        c.commit()
        c.close()

    def record_outcome(self, station_id: str, predicted_ok: bool) -> None:
        hit_delta = 1 if predicted_ok else 0
        now = datetime.utcnow().isoformat() + "Z"
        self._conn.execute(
            """
            INSERT INTO station_scores(station_id, samples, hits, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(station_id) DO UPDATE SET
              samples = samples + 1,
              hits = hits + ?,
              updated_at = excluded.updated_at
            """,
            (station_id, hit_delta, now, hit_delta),
        )
        self._conn.commit()
        logger.info("weather_accuracy_record station=%s hit_delta=%s", station_id, hit_delta)

    def accuracy(self, station_id: str) -> Optional[float]:
        row = self._conn.execute(
            "SELECT samples, hits FROM station_scores WHERE station_id = ?", (station_id,)
        ).fetchone()
        if not row or row[0] == 0:
            return None
        return float(row[1]) / float(row[0])

    def summary_json(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT station_id, samples, hits FROM station_scores").fetchall()
        out = []
        for r in rows:
            s, n, h = r[0], int(r[1]), int(r[2])
            out.append({"station": s, "samples": n, "hit_rate": (h / n) if n else 0.0})
        return {"stations": out}

    def record_forecast(
        self,
        station: str,
        horizon_hours: int,
        predicted_temp: float,
        actual_temp: float,
        correct: bool,
    ) -> None:
        """Gap-aligned hook — keyed by station + horizon for future drill-down."""
        sid = f"{station}_{horizon_hours}h"
        self.record_outcome(sid, correct)

    def get_accuracy(self, station: str, horizon_hours: int | None = None) -> float | None:
        if horizon_hours is None:
            return self.accuracy(station)
        return self.accuracy(f"{station}_{horizon_hours}h")

    def get_best_stations(self, min_samples: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT station_id, samples, hits FROM station_scores WHERE samples >= ? ORDER BY (CAST(hits AS REAL) / samples) DESC",
            (min_samples,),
        ).fetchall()
        out = []
        for r in rows:
            s, n, h = r[0], int(r[1]), int(r[2])
            out.append({"station": s, "samples": n, "hit_rate": (h / n) if n else 0.0})
        return out


_store: Optional[WeatherAccuracyStore] = None


def get_store() -> WeatherAccuracyStore:
    global _store
    if _store is None:
        _store = WeatherAccuracyStore()
    return _store
