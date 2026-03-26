"""Generate a concise trading briefing focused on Polymarket copy-trader."""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


class BriefingGenerator:
    """Generates human-readable briefings about copy-trader status."""

    async def generate(self, report: dict) -> str:
        """Generate a concise briefing from the heartbeat review."""
        strategies = report.get("strategies", [])

        # Find the copytrade review
        copytrade = None
        for s in strategies:
            if s.get("name") == "copytrade":
                copytrade = s
                break

        if not copytrade:
            return "Copy-trader status unavailable."

        lines = []

        # Status line
        status = copytrade.get("status", "unknown")
        pnl = copytrade.get("pnl", 0)
        lines.append(f"Copy-Trader: {status.upper()}")
        lines.append("")

        # Open positions
        open_count = copytrade.get("open_positions", 0)
        open_value = copytrade.get("open_value", 0)
        if open_count > 0:
            lines.append(f"Open positions: {open_count} (${open_value:.2f})")
            details = copytrade.get("position_details", [])
            for d in details:
                title = d.get("title", "")
                outcome = d.get("outcome", "")
                value = d.get("value", 0)
                current = d.get("current", 0)
                entry = d.get("entry", 0)
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
                lines.append(f"  {outcome} {title} ${value:.2f} ({pnl_pct:+.0f}%)")
        else:
            lines.append("No open positions.")

        lines.append("")

        # Win/loss record
        won = copytrade.get("won_count", 0)
        won_val = copytrade.get("won_value", 0)
        lost = copytrade.get("lost_count", 0)
        lost_val = copytrade.get("lost_value", 0)
        lines.append(f"Results: {won}W/{lost}L")
        if won > 0:
            lines.append(f"  Won: ${won_val:.2f}")
        if lost > 0:
            lines.append(f"  Lost: ${lost_val:.2f}")
        lines.append(f"  Net: ${pnl:+.2f}")

        # Health
        health = report.get("health", {})
        platforms = health.get("platforms", {})
        if platforms:
            connected = sum(1 for p in platforms.values() if p.get("status") == "connected")
            lines.append(f"\nPlatforms: {connected}/{len(platforms)} connected")

        return "\n".join(lines)
