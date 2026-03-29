"""Auto-update AGENT_LEARNINGS.md with trade outcomes.

Called after each heartbeat review cycle. Reads the strategy review data,
identifies new wins/losses, patterns, and appends to AGENT_LEARNINGS.md.

The file is read by Claude Code at the start of every session, creating
a self-improving feedback loop where the bot learns from its own mistakes.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

LEARNINGS_PATH = Path(os.environ.get("LEARNINGS_FILE", "/data/AGENT_LEARNINGS_LIVE.md"))


def update_learnings(strategy_data: dict[str, Any], category_pnl: dict[str, float] | None = None) -> None:
    """Append new trade insights to the learnings file.
    
    Called by the heartbeat runner after each review cycle.
    """
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        
        # Extract copytrade data
        copytrade = strategy_data.get("copytrade", {})
        if not copytrade:
            return
        
        positions = copytrade.get("open_positions", 0)
        daily_trades = copytrade.get("daily_trades", 0)
        daily_net = copytrade.get("daily_net", 0)
        bankroll = copytrade.get("bankroll", 0)
        daily_wins = copytrade.get("daily_wins", 0)
        daily_losses = copytrade.get("daily_realized_losses", 0)
        
        # Build the update entry
        lines = [
            f"\n## Heartbeat Update — {now}",
            f"- Positions: {positions} | Bankroll: ${bankroll:.2f}",
            f"- Daily: {daily_trades} trades, ${daily_net:+.2f} net",
        ]
        
        if daily_wins > 0:
            lines.append(f"- Wins today: ${daily_wins:.2f}")
        if daily_losses > 0:
            lines.append(f"- Losses today: ${daily_losses:.2f}")
        
        # Category P/L snapshot
        if category_pnl:
            winners = {k: v for k, v in category_pnl.items() if v > 0}
            losers = {k: v for k, v in category_pnl.items() if v < 0}
            if winners:
                top = max(winners, key=winners.get)
                lines.append(f"- Best category: {top} (${winners[top]:+.2f})")
            if losers:
                worst = min(losers, key=losers.get)
                lines.append(f"- Worst category: {worst} (${losers[worst]:+.2f})")
        
        # Check for concerning patterns
        if daily_losses > daily_wins and daily_trades > 3:
            lines.append(f"- ⚠️ LOSING DAY: losses exceed wins. Review trade quality.")
        
        if positions > 80:
            lines.append(f"- ⚠️ HIGH POSITION COUNT: {positions} positions open. Watch for stale ones.")
        
        if bankroll < 20:
            lines.append(f"- ⚠️ LOW BANKROLL: ${bankroll:.2f}. Positions resolving will replenish.")
        
        entry = "\n".join(lines) + "\n"
        
        # Append to file (create if doesn't exist)
        LEARNINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Keep file from growing forever — max 200 lines of updates
        if LEARNINGS_PATH.exists():
            existing = LEARNINGS_PATH.read_text()
            update_count = existing.count("## Heartbeat Update")
            if update_count > 200:
                # Keep only the last 100 updates
                parts = existing.split("## Heartbeat Update")
                header = parts[0]
                recent = parts[-100:]
                existing = header + "## Heartbeat Update".join(recent)
                LEARNINGS_PATH.write_text(existing)
        
        with open(LEARNINGS_PATH, "a") as f:
            f.write(entry)
        
        logger.info("learnings_updated", path=str(LEARNINGS_PATH), daily_net=round(daily_net, 2))
        
    except Exception as exc:
        logger.error("learnings_update_error", error=str(exc)[:120])
