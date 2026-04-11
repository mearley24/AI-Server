"""X Intel Processor — converts X intake signals into market search + position review.

Listens for high-relevance X intel signals on the signal bus and:
1. Searches Polymarket for markets matching signal keywords
2. Cross-references with current positions
3. Logs actionable opportunities to ideas.txt
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

IDEAS_FILE = Path(__file__).parent.parent / "ideas.txt"


class XIntelProcessor:
    """Processes X intake signals into actionable Polymarket opportunities."""

    def __init__(self, market_scanner=None):
        self.market_scanner = market_scanner
        self._last_processed: dict[str, float] = {}  # url -> timestamp (dedup)

    async def on_intel_signal(self, signal) -> None:
        """Handle an intel signal from the signal bus."""
        data = signal.data
        source = data.get("source", "")

        if source != "x_intake":
            return  # Only process X intake signals

        url = data.get("url", "")

        # Dedup: skip if we processed this URL in the last 5 minutes
        now = time.time()
        if url in self._last_processed and (now - self._last_processed[url]) < 300:
            return
        self._last_processed[url] = now

        # Clean up old entries
        cutoff = now - 3600
        self._last_processed = {k: v for k, v in self._last_processed.items() if v > cutoff}

        relevance = data.get("relevance", 0)
        signals = data.get("signals", [])
        market_keywords = data.get("market_keywords", [])
        alpha_insights = data.get("alpha_insights", [])
        risk_warnings = data.get("risk_warnings", [])
        author = data.get("author", "unknown")

        logger.info(
            "x_intel_processing",
            author=author,
            relevance=relevance,
            signal_count=len(signals),
            keyword_count=len(market_keywords),
        )

        ideas = []

        # Process trading signals
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            confidence = sig.get("confidence", 0)
            if confidence < 0.4:
                continue

            keyword = sig.get("market_keyword", "")
            direction = sig.get("direction", "")
            reasoning = sig.get("reasoning", "")

            ideas.append(
                f"[X-INTEL] @{author} | Market: {keyword} | "
                f"Direction: {direction} | Confidence: {confidence:.0%} | "
                f"Reasoning: {reasoning[:120]}"
            )

        # Log alpha insights
        for insight in alpha_insights:
            ideas.append(f"[X-ALPHA] @{author} | {insight[:200]}")

        # Log risk warnings
        for warning in risk_warnings:
            ideas.append(f"[X-RISK] @{author} | {warning[:200]}")

        # Write to ideas.txt (strategy manager reads this)
        if ideas:
            self._append_ideas(ideas)
            logger.info("x_intel_ideas_logged", count=len(ideas), author=author)

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
