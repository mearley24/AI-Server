"""X Intel Processor — converts X intake signals into live trading influence.

Maintains a rolling window of high-relevance X intel signals that strategies
can query to boost/suppress confidence on specific markets.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

IDEAS_FILE = Path(__file__).parent.parent / "ideas.txt"
SIGNAL_WINDOW_SEC = 7200  # 2 hours
MIN_RELEVANCE = 50  # minimum relevance to influence trading


class XIntelProcessor:
    """Processes X intake signals into live trading intelligence."""

    def __init__(self, market_scanner=None):
        self.market_scanner = market_scanner
        self._last_processed: dict[str, float] = {}
        self._active_signals: list[dict[str, Any]] = []  # rolling window
        self._market_boosts: dict[str, dict[str, Any]] = {}  # keyword -> boost info

    async def on_intel_signal(self, signal) -> None:
        """Handle an intel signal from the signal bus."""
        data = signal.data
        source = data.get("source", "")

        if source != "x_intake":
            return

        url = data.get("url", "")
        now = time.time()

        # Dedup
        if url in self._last_processed and (now - self._last_processed[url]) < 300:
            return
        self._last_processed[url] = now
        self._last_processed = {k: v for k, v in self._last_processed.items() if v > now - 3600}

        relevance = data.get("relevance", 0)
        signals = data.get("signals", [])
        market_keywords = data.get("market_keywords", [])
        alpha_insights = data.get("alpha_insights", [])
        risk_warnings = data.get("risk_warnings", [])
        author = data.get("author", "unknown")
        summary = data.get("summary", "")

        logger.info(
            "x_intel_processing",
            author=author,
            relevance=relevance,
            signal_count=len(signals),
            keyword_count=len(market_keywords),
        )

        # Store in rolling window
        entry = {
            "timestamp": now,
            "author": author,
            "url": url,
            "relevance": relevance,
            "signals": signals,
            "keywords": market_keywords,
            "alpha": alpha_insights,
            "risk": risk_warnings,
            "summary": summary[:500],
        }
        self._active_signals.append(entry)

        # Prune old signals
        cutoff = now - SIGNAL_WINDOW_SEC
        self._active_signals = [s for s in self._active_signals if s["timestamp"] > cutoff]

        # Process trading signals into market boosts
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            confidence = sig.get("confidence", 0)
            if confidence < 0.4:
                continue

            keyword = sig.get("market_keyword", "").lower()
            direction = sig.get("direction", "")
            reasoning = sig.get("reasoning", "")

            if keyword:
                self._market_boosts[keyword] = {
                    "direction": direction,
                    "confidence": confidence,
                    "author": author,
                    "reasoning": reasoning[:200],
                    "timestamp": now,
                    "relevance": relevance,
                }

        # Prune old boosts
        self._market_boosts = {
            k: v for k, v in self._market_boosts.items()
            if v["timestamp"] > cutoff
        }

        # Publish boost to Redis for strategies that subscribe
        if signals and relevance >= MIN_RELEVANCE:
            self._publish_boost(entry)

        # Still write to ideas.txt for audit trail
        ideas = []
        for sig in signals:
            if not isinstance(sig, dict) or sig.get("confidence", 0) < 0.4:
                continue
            ideas.append(
                f"[X-INTEL] @{author} | Market: {sig.get('market_keyword', '')} | "
                f"Direction: {sig.get('direction', '')} | Confidence: {sig.get('confidence', 0):.0%} | "
                f"Reasoning: {sig.get('reasoning', '')[:120]}"
            )
        for insight in alpha_insights:
            ideas.append(f"[X-ALPHA] @{author} | {insight[:200]}")
        for warning in risk_warnings:
            ideas.append(f"[X-RISK] @{author} | {warning[:200]}")

        if ideas:
            self._append_ideas(ideas)
            logger.info("x_intel_ideas_logged", count=len(ideas), author=author)

    def get_active_signals(self) -> list[dict[str, Any]]:
        """Return signals from the last 2 hours for strategy queries."""
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC
        return [s for s in self._active_signals if s["timestamp"] > cutoff]

    def get_market_boost(self, market_title: str) -> dict[str, Any] | None:
        """Check if X intel suggests a boost/suppress for a market keyword.

        Returns the boost info if any keyword matches the market title,
        or None if no active intel applies.
        """
        title_lower = market_title.lower()
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC

        for keyword, boost in self._market_boosts.items():
            if boost["timestamp"] < cutoff:
                continue
            if keyword in title_lower:
                return boost
        return None

    def get_signal_summary(self) -> dict[str, Any]:
        """Dashboard-friendly summary of current intel state."""
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC
        active = [s for s in self._active_signals if s["timestamp"] > cutoff]
        return {
            "active_signals": len(active),
            "market_boosts": len(self._market_boosts),
            "top_authors": list({s["author"] for s in active})[:5],
            "boost_keywords": list(self._market_boosts.keys())[:10],
        }

    def _publish_boost(self, entry: dict[str, Any]) -> None:
        """Publish high-relevance signal to Redis for live strategies."""
        try:
            import redis
            url = os.environ.get("REDIS_URL", "redis://redis:6379").strip()
            r = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            r.publish("polymarket:x_strategy_boost", json.dumps({
                "author": entry["author"],
                "relevance": entry["relevance"],
                "keywords": entry["keywords"],
                "signals": entry["signals"],
                "summary": entry["summary"],
                "timestamp": entry["timestamp"],
            }, default=str))
        except Exception as exc:
            logger.warning("x_boost_publish_failed", error=str(exc)[:100])

    def _append_ideas(self, ideas: list[str]) -> None:
        """Append ideas to ideas.txt with timestamp."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"\n--- X Intel [{timestamp}] ---"]
        lines.extend(ideas)
        lines.append("")
        try:
            with open(IDEAS_FILE, "a") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.warning("ideas_write_failed", error=str(exc)[:100])
