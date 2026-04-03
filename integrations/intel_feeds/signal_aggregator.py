"""
Signal Aggregator
=================
The central brain of the intel layer.

Responsibilities:
  - Subscribe to all intel:* Redis channels
  - Deduplicate and score incoming signals
  - Route signals by urgency:
      critical (score > 80) → publish to notifications:trading (iMessage alert)
      medium / high         → persist to SQLite for daily briefing
      low                   → log only
  - Maintain a rolling 24-hour context window in SQLite
  - Expose an async query API for the bot:
      aggregator.query_sentiment("market slug or keyword") → summary dict

SQLite DB path: /data/intel_feeds/signals.db
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("intel_feeds.aggregator")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_URL = "redis://172.18.0.100:6379"
INTEL_CHANNEL_PATTERN = "intel:*"
NOTIFICATIONS_CHANNEL = "notifications:trading"
DB_PATH = Path("/data/intel_feeds/signals.db")
CRITICAL_THRESHOLD = 80     # score >= this → immediate alert
MEDIUM_THRESHOLD = 40       # score >= this → persist to SQLite
CONTEXT_WINDOW_HOURS = 24   # rolling context window
RBI_IDEAS_PATH = os.environ.get("RBI_IDEAS_PATH", "/app/polymarket-bot/ideas.txt")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    received_at TEXT NOT NULL,
    relevance   INTEGER NOT NULL,
    urgency     TEXT NOT NULL,
    category    TEXT NOT NULL,
    markets     TEXT NOT NULL,   -- JSON array
    summary     TEXT NOT NULL,
    raw         TEXT NOT NULL,   -- JSON object
    notified    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_signals_timestamp  ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_relevance  ON signals(relevance);
CREATE INDEX IF NOT EXISTS idx_signals_category   ON signals(category);
CREATE INDEX IF NOT EXISTS idx_signals_source     ON signals(source);

CREATE TABLE IF NOT EXISTS dedup_seen (
    signal_hash TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL
);
"""


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _signal_hash(signal: dict) -> str:
    """
    Content-based dedup hash.  Two signals with the same source + summary
    within the same hour are considered duplicates.
    """
    hour_bucket = signal.get("timestamp", "")[:13]  # "2026-04-01T07"
    raw = f"{signal.get('source','')}|{signal.get('summary','')}|{hour_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _is_duplicate(conn: sqlite3.Connection, h: str) -> bool:
    row = conn.execute("SELECT 1 FROM dedup_seen WHERE signal_hash = ?", (h,)).fetchone()
    return row is not None


def _mark_seen(conn: sqlite3.Connection, h: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO dedup_seen(signal_hash, first_seen) VALUES (?,?)",
        (h, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _insert_signal(conn: sqlite3.Connection, signal: dict, sig_id: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO signals
          (id, source, timestamp, received_at, relevance, urgency, category,
           markets, summary, raw, notified)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sig_id,
            signal.get("source", ""),
            signal.get("timestamp", ""),
            datetime.now(timezone.utc).isoformat(),
            signal.get("relevance_score", 0),
            signal.get("urgency", "low"),
            signal.get("category", "general"),
            json.dumps(signal.get("markets_affected", [])),
            signal.get("summary", ""),
            json.dumps(signal.get("raw", {})),
            0,
        ),
    )
    conn.commit()


def _prune_old_signals(conn: sqlite3.Connection) -> None:
    """Remove signals older than the context window."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=CONTEXT_WINDOW_HOURS)
    ).isoformat()
    conn.execute("DELETE FROM signals WHERE timestamp < ?", (cutoff,))
    conn.execute("DELETE FROM dedup_seen WHERE first_seen < ?", (cutoff,))
    conn.commit()


# ---------------------------------------------------------------------------
# Sentiment / context query engine
# ---------------------------------------------------------------------------


def _query_sentiment(conn: sqlite3.Connection, topic: str) -> dict:
    """
    Search the last 24 hours of signals for mentions of `topic`.
    Returns a summary dict with signal list, average relevance, category breakdown,
    and a human-readable verdict.
    """
    topic_lower = topic.lower()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=CONTEXT_WINDOW_HOURS)
    ).isoformat()

    rows = conn.execute(
        "SELECT * FROM signals WHERE timestamp >= ? ORDER BY relevance DESC",
        (cutoff,),
    ).fetchall()

    matching = []
    for row in rows:
        text = f"{row['summary']} {row['markets']}".lower()
        if topic_lower in text:
            matching.append(dict(row))

    if not matching:
        return {
            "topic": topic,
            "signal_count": 0,
            "avg_relevance": 0,
            "max_relevance": 0,
            "categories": {},
            "urgency_counts": {},
            "verdict": "no_data",
            "signals": [],
        }

    avg_rel = sum(m["relevance"] for m in matching) / len(matching)
    max_rel = max(m["relevance"] for m in matching)

    categories: dict[str, int] = defaultdict(int)
    urgency_counts: dict[str, int] = defaultdict(int)
    for m in matching:
        categories[m["category"]] += 1
        urgency_counts[m["urgency"]] += 1

    # Simple verdict
    if max_rel >= 80 or urgency_counts.get("critical", 0) > 0:
        verdict = "high_activity"
    elif avg_rel >= 50:
        verdict = "moderate_activity"
    else:
        verdict = "low_activity"

    return {
        "topic": topic,
        "signal_count": len(matching),
        "avg_relevance": round(avg_rel, 1),
        "max_relevance": max_rel,
        "categories": dict(categories),
        "urgency_counts": dict(urgency_counts),
        "verdict": verdict,
        "signals": matching[:10],  # top 10 most relevant
    }


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


class SignalAggregator:
    """
    Subscribes to all intel:* channels, processes signals, and routes them.

    Usage:
        agg = SignalAggregator()
        await agg.run()

    Bot API:
        result = await agg.query_sentiment("bitcoin")
        result = await agg.get_recent_signals(hours=1, min_relevance=60)
        result = await agg.get_daily_briefing()
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        db_path: Path = DB_PATH,
        critical_threshold: int = CRITICAL_THRESHOLD,
        medium_threshold: int = MEDIUM_THRESHOLD,
    ):
        self.redis_url = redis_url
        self.db_path = db_path
        self.critical_threshold = critical_threshold
        self.medium_threshold = medium_threshold
        self._running = False
        self._conn: sqlite3.Connection | None = None
        self._redis_pub: aioredis.Redis | None = None
        # In-memory cache of recent signals (last N) for fast queries
        self._recent: list[dict] = []
        self._max_recent = 500
        self._ideas_path_candidates = [
            Path(RBI_IDEAS_PATH),
            Path("/data/intel_feeds/ideas.txt"),
            Path("/Users/bob/AI-Server/polymarket-bot/ideas.txt"),
        ]

    # -----------------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------------

    async def _handle_signal(self, signal: dict) -> None:
        """Process a single incoming signal: dedup, score, route."""
        h = _signal_hash(signal)

        if _is_duplicate(self._conn, h):
            logger.debug("Duplicate signal suppressed: %s", signal.get("summary", "")[:60])
            return

        _mark_seen(self._conn, h)

        relevance = signal.get("relevance_score", 0)
        urgency = signal.get("urgency", "low")
        summary = signal.get("summary", "")

        # Update in-memory cache
        self._recent.append(signal)
        if len(self._recent) > self._max_recent:
            self._recent.pop(0)

        # Always persist medium+ signals to SQLite
        if relevance >= self.medium_threshold:
            sig_id = hashlib.sha256(
                (signal.get("source", "") + signal.get("timestamp", "") + summary).encode()
            ).hexdigest()[:24]
            _insert_signal(self._conn, signal, sig_id)

        # Critical signals → immediate iMessage notification channel
        if relevance >= self.critical_threshold:
            notification = {
                "type": "intel_alert",
                "urgency": urgency,
                "source": signal.get("source", ""),
                "summary": summary,
                "relevance_score": relevance,
                "category": signal.get("category", ""),
                "markets_affected": signal.get("markets_affected", []),
                "timestamp": signal.get("timestamp", ""),
            }
            await self._redis_pub.publish(
                NOTIFICATIONS_CHANNEL, json.dumps(notification)
            )
            self._append_pending_idea(signal)
            logger.warning(
                "CRITICAL ALERT published: relevance=%d summary=%s",
                relevance,
                summary[:80],
            )
        else:
            logger.info(
                "Signal processed: relevance=%d urgency=%s source=%s summary=%s",
                relevance,
                urgency,
                signal.get("source", ""),
                summary[:80],
            )

    def _resolve_ideas_path(self) -> Path:
        """Pick the first usable ideas.txt path."""
        for path in self._ideas_path_candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.is_file():
                    return path
                if not path.exists():
                    return path
            except Exception:
                continue
        return self._ideas_path_candidates[0]

    def _append_pending_idea(self, signal: dict) -> None:
        """Auto-create RBI pending idea from critical intel signal."""
        summary = (signal.get("summary") or "").strip()
        if not summary:
            return
        source = (signal.get("source") or "intel").strip()
        category = (signal.get("category") or "general").strip()
        title = re.sub(r"\s+", " ", summary)[:72]
        title = re.sub(r"[^A-Za-z0-9 _\-\u2014]", "", title).strip() or "IntelSignalIdea"
        description = summary
        hypothesis = (
            f"Critical intel signal from {source} (category={category}, "
            f"relevance={signal.get('relevance_score', 0)}) indicates tradable edge."
        )
        notes = (
            f"Auto-generated from intel feed at {datetime.now(timezone.utc).isoformat()} | "
            f"markets={','.join(signal.get('markets_affected', [])[:5])}"
        )

        path = self._resolve_ideas_path()
        existing = ""
        try:
            existing = path.read_text() if path.exists() else ""
        except Exception:
            existing = ""
        if f"IDEA: {title}" in existing:
            logger.info("RBI idea already exists, skipping auto-add: %s", title)
            return

        entry = (
            f"\nIDEA: {title}\n"
            f"DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"DESCRIPTION: {description}\n"
            f"HYPOTHESIS: {hypothesis}\n"
            f"STATUS: pending\n"
            f"NOTES: {notes}\n"
            "---\n"
        )
        try:
            with open(path, "a") as f:
                f.write(entry)
            logger.info("Auto-added pending RBI idea from intel signal: %s (%s)", title, path)
        except Exception as exc:
            logger.warning("Failed to append RBI idea: %s", str(exc)[:200])

    # -----------------------------------------------------------------------
    # Subscription loop
    # -----------------------------------------------------------------------

    async def _listen(self, redis_sub: aioredis.Redis) -> None:
        pubsub = redis_sub.pubsub()
        await pubsub.psubscribe(INTEL_CHANNEL_PATTERN)
        logger.info("Subscribed to pattern: %s", INTEL_CHANNEL_PATTERN)

        async for message in pubsub.listen():
            if not self._running:
                break
            if message["type"] not in ("pmessage", "message"):
                continue
            try:
                data = message.get("data", "")
                if isinstance(data, bytes):
                    data = data.decode()
                signal = json.loads(data)
                await self._handle_signal(signal)
            except json.JSONDecodeError as exc:
                logger.warning("JSON decode error: %s — data=%s", exc, str(data)[:80])
            except Exception as exc:  # noqa: BLE001
                logger.error("Error handling signal: %s", exc, exc_info=True)

    async def _prune_loop(self) -> None:
        """Periodically prune old signals from SQLite."""
        while self._running:
            await asyncio.sleep(3600)  # every hour
            try:
                _prune_old_signals(self._conn)
                logger.debug("Pruned old signals from SQLite")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Prune error: %s", exc)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def query_sentiment(self, topic: str) -> dict:
        """
        Query the last 24 hours of intelligence for a topic/market keyword.

        Returns:
          {
            topic, signal_count, avg_relevance, max_relevance,
            categories, urgency_counts, verdict, signals
          }
        """
        if self._conn is None:
            return {"error": "aggregator not running"}
        return await asyncio.get_event_loop().run_in_executor(
            None, _query_sentiment, self._conn, topic
        )

    async def get_recent_signals(
        self,
        hours: int = 1,
        min_relevance: int = 0,
        category: str | None = None,
    ) -> list[dict]:
        """Return recent signals from the in-memory cache."""
        cutoff_ts = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()
        results = []
        for sig in reversed(self._recent):
            if sig.get("timestamp", "") < cutoff_ts:
                continue
            if sig.get("relevance_score", 0) < min_relevance:
                continue
            if category and sig.get("category") != category:
                continue
            results.append(sig)
        return results

    async def get_daily_briefing(self) -> dict:
        """
        Compile a daily briefing from the last 24 hours of signals.
        Grouped by category, sorted by relevance.
        """
        if self._conn is None:
            return {"error": "aggregator not running"}

        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).isoformat()

        rows = self._conn.execute(
            """
            SELECT category, urgency, relevance, summary, source, timestamp
            FROM signals
            WHERE timestamp >= ?
            ORDER BY relevance DESC
            """,
            (cutoff,),
        ).fetchall()

        by_category: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_category[row["category"]].append(dict(row))

        total = len(rows)
        critical_count = sum(1 for r in rows if r["urgency"] == "critical")
        high_count = sum(1 for r in rows if r["urgency"] == "high")

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_hours": 24,
            "total_signals": total,
            "critical": critical_count,
            "high": high_count,
            "by_category": {cat: sigs[:20] for cat, sigs in by_category.items()},
        }

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def run(self) -> None:
        """Start the aggregator. Runs indefinitely until stop() is called."""
        self._running = True
        self._conn = _open_db(self.db_path)

        redis_sub = aioredis.from_url(self.redis_url, decode_responses=True)
        self._redis_pub = aioredis.from_url(self.redis_url, decode_responses=True)

        logger.info(
            "SignalAggregator starting — db=%s critical_threshold=%d",
            self.db_path,
            self.critical_threshold,
        )

        try:
            await asyncio.gather(
                self._listen(redis_sub),
                self._prune_loop(),
            )
        finally:
            self._running = False
            await redis_sub.aclose()
            await self._redis_pub.aclose()
            if self._conn:
                self._conn.close()
            logger.info("SignalAggregator stopped.")

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Standalone entry (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
    )
    asyncio.run(SignalAggregator().run())
