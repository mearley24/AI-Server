"""Subscribe to Redis events:* channels and score decision_journal outcomes."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from decision_journal import DecisionJournal, get_journal

logger = logging.getLogger("openclaw.outcome_listener")

EVENT_CHANNELS = (
    "events:email",
    "events:trading",
    "events:jobs",
    "events:clients",
    "events:system",
)


class OutcomeListener:
    """Background task: map external outcomes to journal rows via Redis pub/sub."""

    def __init__(self, journal: DecisionJournal, redis_url: str):
        self._journal = journal
        self._redis_url = redis_url

    async def run(self) -> None:
        if not self._redis_url:
            logger.warning("outcome_listener: no REDIS_URL — skipping")
            return
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning("outcome_listener: redis.asyncio unavailable")
            return

        r = aioredis.from_url(self._redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(*EVENT_CHANNELS)
        logger.info("outcome_listener subscribed: %s", EVENT_CHANNELS)

        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if not raw:
                    continue
                try:
                    event = json.loads(raw) if isinstance(raw, str) else json.loads(str(raw))
                    await self._process_event(event)
                except Exception as e:
                    logger.debug("outcome_listener parse/process: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("outcome_listener loop error: %s", e)
        finally:
            try:
                await pubsub.unsubscribe()
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
                if callable(close):
                    res = close()
                    if asyncio.iscoroutine(res):
                        await res
                aclose = getattr(r, "aclose", None)
                if callable(aclose):
                    await aclose()
                else:
                    r.close()
            except Exception:
                pass

    async def _process_event(self, event: dict[str, Any]) -> None:
        etype = str(event.get("type", ""))
        data = event.get("data") or {}

        if etype == "email.client_reply":
            client = str(data.get("client_name", "")).strip()
            if not client:
                return
            sentiment = str(data.get("sentiment", "neutral")).lower()
            score = 0.8 if sentiment != "negative" else 0.2
            for cat in ("followup", "email"):
                rows = self._journal.search_recent(
                    cat, client, hours=336, limit=5, only_unscored=True
                )
                for d in rows:
                    if d.get("outcome"):
                        continue
                    self._journal.update_outcome(int(d["id"]), "client_responded", score)
                    logger.info("outcome_listener scored id=%s client_reply", d["id"])
                    return

        elif etype in ("trade.redeemed", "trade.exited"):
            pnl = float(data.get("pnl", 0) or 0)
            needle = str(data.get("position_id", "") or data.get("market", "") or data.get("condition_id", ""))[:200]
            score = max(-1.0, min(1.0, pnl / 10.0))
            if needle:
                rows = self._journal.search_recent(
                    "trading", needle, hours=720, limit=5, only_unscored=True
                )
                for d in rows:
                    if d.get("outcome"):
                        continue
                    self._journal.update_outcome(int(d["id"]), f"pnl_{pnl:+.2f}", score)
                    logger.info("outcome_listener scored id=%s trade", d["id"])
                    return
            self._journal.log_decision(
                "trading",
                "betty",
                f"Resolved trade pnl={pnl:+.2f}",
                {
                    "position_id": data.get("position_id", ""),
                    "market": (data.get("market") or "")[:400],
                    "condition_id": data.get("condition_id", ""),
                    "pnl": pnl,
                },
                confidence=55.0,
                outcome=f"pnl_{pnl:+.2f}",
                outcome_score=score,
            )
            logger.info("outcome_listener logged external trade resolution pnl=%s", pnl)
            return

        elif etype == "job.payment_received":
            jid = str(data.get("job_id", ""))
            if not jid:
                return
            rows = self._journal.search_recent("jobs", jid, hours=2160, limit=5, only_unscored=True)
            for d in rows:
                if d.get("outcome"):
                    continue
                self._journal.update_outcome(int(d["id"]), "payment_received", 1.0)
                logger.info("outcome_listener scored id=%s payment", d["id"])
                return

        elif etype == "email.escalated":
            subj = str(data.get("subject", ""))[:300]
            if not subj:
                return
            rows = self._journal.search_recent("email", subj, hours=168, limit=5, only_unscored=True)
            for d in rows:
                act = (d.get("action") or "").lower()
                if d.get("outcome"):
                    continue
                if "low" in act or "general" in act:
                    self._journal.update_outcome(int(d["id"]), "misclassified_escalated", -0.8)
                    logger.info("outcome_listener scored id=%s escalated", d["id"])
                    return

        elif etype in ("approval.granted", "approval.denied"):
            from approval_bridge import resolve_async

            raw_id = data.get("decision_id")
            if raw_id is None:
                return
            try:
                decision_id = int(raw_id)
            except (TypeError, ValueError):
                return
            granted = etype == "approval.granted"
            edit_note = str(data.get("edit_note", "") or "")
            await resolve_async(decision_id, granted, edit_note)


async def run_outcome_listener(data_dir: Path, redis_url: str) -> None:
    """Entry point for OpenClaw startup."""
    if not redis_url:
        logger.warning("run_outcome_listener: empty REDIS_URL")
        return
    journal = get_journal(data_dir)
    listener = OutcomeListener(journal, redis_url)
    await listener.run()
