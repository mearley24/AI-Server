"""Multi-Strategy Orchestrator — StrategyManager.

Manages three independent strategies (weather, copytrade, arb) with:
- Per-strategy bankroll allocation (weather: 40%, copytrade: 35%, arb: 25%)
- Shared position registry — zero market overlap between strategies
- Independent P/L tracking per strategy
- Cross-strategy correlation monitoring (alert if > 0.3)
- Hourly comparative P/L dashboard logged to structlog
- iMessage alerts for significant events (correlation spikes, big wins/losses, crashes)
- Producer-consumer ideas queue via ideas.txt

Architecture inspired by @zostaff's competing Claude bots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from strategies.base import BaseStrategy, StrategyState

logger = structlog.get_logger(__name__)

# ── Bankroll splits ────────────────────────────────────────────────────────────

STRATEGY_ALLOCATIONS: dict[str, float] = {
    "weather_trader": 0.35,   # reduced for presolution (Auto-7)
    "copytrade": 0.30,
    "cvd_arb": 0.15,          # CVD + spread/arb scanner
    "mean_reversion": 0.05,   # Auto-6 fade (uses arb slice)
    "presolution_scalp": 0.15,
}

# ── Correlation alert threshold ────────────────────────────────────────────────

CORRELATION_ALERT_THRESHOLD = 0.3
CORRELATION_WINDOW = 20  # number of recent closed trades used per strategy


# ── Shared Position Registry ───────────────────────────────────────────────────


@dataclass
class RegistryEntry:
    """A position claimed by one strategy in the shared registry."""

    token_id: str
    strategy: str
    entry_price: float
    entry_time: float
    size: float
    market_question: str = ""
    closed: bool = False
    exit_price: float = 0.0
    exit_time: float = 0.0


class SharedPositionRegistry:
    """Prevents any market from being entered by more than one strategy.

    Thread-safe via asyncio.Lock — always await claim() and release().
    """

    def __init__(self) -> None:
        self._positions: dict[str, RegistryEntry] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        token_id: str,
        strategy: str,
        entry_price: float,
        size: float,
        market_question: str = "",
    ) -> bool:
        """Claim a market position for a strategy.

        Returns True if claimed successfully, False if already taken.
        """
        async with self._lock:
            if token_id in self._positions and not self._positions[token_id].closed:
                existing = self._positions[token_id]
                logger.debug(
                    "registry_claim_blocked",
                    token_id=token_id[:20],
                    requested_by=strategy,
                    owned_by=existing.strategy,
                )
                return False

            self._positions[token_id] = RegistryEntry(
                token_id=token_id,
                strategy=strategy,
                entry_price=entry_price,
                entry_time=time.time(),
                size=size,
                market_question=market_question,
            )
            logger.info(
                "registry_claimed",
                token_id=token_id[:20],
                strategy=strategy,
                price=entry_price,
                size=size,
            )
            return True

    async def release(
        self,
        token_id: str,
        exit_price: float = 0.0,
    ) -> RegistryEntry | None:
        """Release a position from the registry (mark as closed).

        Returns the entry for P/L calculation, or None if not found.
        """
        async with self._lock:
            entry = self._positions.get(token_id)
            if not entry:
                return None

            entry.closed = True
            entry.exit_price = exit_price
            entry.exit_time = time.time()

            logger.info(
                "registry_released",
                token_id=token_id[:20],
                strategy=entry.strategy,
                entry_price=entry.entry_price,
                exit_price=exit_price,
            )
            return entry

    def is_claimed(self, token_id: str) -> bool:
        """Check if a market is currently held by any strategy (non-async fast path)."""
        entry = self._positions.get(token_id)
        return entry is not None and not entry.closed

    def get_owner(self, token_id: str) -> str | None:
        """Return the strategy name that owns this position, or None."""
        entry = self._positions.get(token_id)
        if entry and not entry.closed:
            return entry.strategy
        return None

    def get_open_positions(self, strategy: str | None = None) -> list[RegistryEntry]:
        """List open positions, optionally filtered by strategy."""
        result = [e for e in self._positions.values() if not e.closed]
        if strategy:
            result = [e for e in result if e.strategy == strategy]
        return result

    def summary(self) -> dict[str, Any]:
        """Return a registry summary for dashboards."""
        open_positions = [e for e in self._positions.values() if not e.closed]
        by_strategy: dict[str, int] = defaultdict(int)
        for e in open_positions:
            by_strategy[e.strategy] += 1

        return {
            "total_open": len(open_positions),
            "total_closed": sum(1 for e in self._positions.values() if e.closed),
            "by_strategy": dict(by_strategy),
        }


# ── Per-Strategy P/L Tracker ──────────────────────────────────────────────────


@dataclass
class ClosedTrade:
    """A completed trade used for correlation and P/L analysis."""

    strategy: str
    token_id: str
    market_question: str
    entry_price: float
    exit_price: float
    size: float
    entry_time: float
    exit_time: float
    reason: str = ""

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.size

    @property
    def pnl_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0


class StrategyPnL:
    """Independent P/L ledger for one strategy."""

    def __init__(self, strategy: str, bankroll: float) -> None:
        self.strategy = strategy
        self.bankroll = bankroll
        self.realized_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.total_trades: int = 0
        self.wins: int = 0
        self.losses: int = 0
        self._closed_trades: deque[ClosedTrade] = deque(maxlen=200)  # keep last 200

    def record_close(self, trade: ClosedTrade) -> None:
        """Record a closed trade and update P/L."""
        self._closed_trades.append(trade)
        self.realized_pnl += trade.pnl
        self.total_trades += 1
        if trade.pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1

    def set_unrealized(self, pnl: float) -> None:
        """Update unrealized P/L from strategy's open positions."""
        self.unrealized_pnl = pnl

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def recent_returns(self) -> list[float]:
        """Return the last CORRELATION_WINDOW trade P/L percentages."""
        trades = list(self._closed_trades)[-CORRELATION_WINDOW:]
        return [t.pnl_pct for t in trades]

    def snapshot(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "bankroll": round(self.bankroll, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate * 100, 1),
        }


# ── Correlation Math ──────────────────────────────────────────────────────────


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation between two return series (same length)."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0  # Not enough data to be meaningful

    x = x[-n:]
    y = y[-n:]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
    std_x = (sum((xi - mean_x) ** 2 for xi in x) / n) ** 0.5
    std_y = (sum((yi - mean_y) ** 2 for yi in y) / n) ** 0.5

    if std_x == 0 or std_y == 0:
        return 0.0

    return cov / (std_x * std_y)


# ── iMessage Alert System ──────────────────────────────────────────────────────


def send_imessage(message: str, recipient: str | None = None) -> bool:
    """Send an iMessage via osascript (macOS only).

    Set IMESSAGE_RECIPIENT env var to phone number or Apple ID email.
    Returns True if sent successfully.
    """
    if recipient is None:
        recipient = os.environ.get("IMESSAGE_RECIPIENT", "")

    if not recipient:
        logger.debug("imessage_no_recipient_configured")
        return False

    # Only works on macOS
    if os.name != "posix" or not Path("/usr/bin/osascript").exists():
        logger.debug("imessage_not_macos", platform=os.name)
        return False

    script = f'''
tell application "Messages"
    set targetService to 1st service whose service type is iMessage
    set targetBuddy to buddy "{recipient}" of targetService
    send "{message}" to targetBuddy
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info("imessage_sent", recipient=recipient[:12], length=len(message))
            return True
        else:
            logger.warning("imessage_failed", error=result.stderr[:100])
            return False
    except Exception as exc:
        logger.error("imessage_error", error=str(exc))
        return False


# ── Ideas Queue (Producer-Consumer / RBI System) ───────────────────────────────


class IdeasQueue:
    """Reads and writes strategy ideas from ideas.txt.

    Format: plain text blocks separated by '---', each with key: value pairs.
    STATUS values: pending | researching | backtesting | implementing | live | rejected
    """

    DEFAULT_PATH = Path("/home/user/workspace/AI-Server/polymarket-bot/ideas.txt")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.DEFAULT_PATH

    def get_pending(self) -> list[dict[str, str]]:
        """Return all ideas with STATUS: pending."""
        ideas = self._parse_all()
        return [i for i in ideas if i.get("STATUS", "").lower() == "pending"]

    def add_idea(
        self,
        title: str,
        description: str,
        hypothesis: str,
        notes: str = "",
    ) -> None:
        """Append a new idea to the queue file."""
        entry = (
            f"\nIDEA: {title}\n"
            f"DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"DESCRIPTION: {description}\n"
            f"HYPOTHESIS: {hypothesis}\n"
            f"STATUS: pending\n"
            f"NOTES: {notes}\n"
            "---\n"
        )
        with open(self.path, "a") as f:
            f.write(entry)
        logger.info("idea_added", title=title)

    def update_status(self, title: str, status: str, notes: str = "") -> bool:
        """Update the status of an idea by title. Returns True if found."""
        if not self.path.exists():
            return False

        content = self.path.read_text()
        blocks = content.split("---")
        updated = False

        new_blocks = []
        for block in blocks:
            if f"IDEA: {title}" in block:
                # Update STATUS line
                lines = block.split("\n")
                new_lines = []
                for line in lines:
                    if line.startswith("STATUS:"):
                        new_lines.append(f"STATUS: {status}")
                    elif line.startswith("NOTES:") and notes:
                        new_lines.append(f"NOTES: {notes}")
                    else:
                        new_lines.append(line)
                block = "\n".join(new_lines)
                updated = True
            new_blocks.append(block)

        if updated:
            self.path.write_text("---".join(new_blocks))
            logger.info("idea_status_updated", title=title, status=status)

        return updated

    def _parse_all(self) -> list[dict[str, str]]:
        """Parse all ideas from the file."""
        if not self.path.exists():
            return []

        content = self.path.read_text()
        ideas = []
        for block in content.split("---"):
            block = block.strip()
            if not block:
                continue
            idea: dict[str, str] = {}
            for line in block.split("\n"):
                if ": " in line:
                    key, _, value = line.partition(": ")
                    idea[key.strip()] = value.strip()
            if "IDEA" in idea:
                ideas.append(idea)
        return ideas


# ── Strategy Manager ──────────────────────────────────────────────────────────


class StrategyManager:
    """Orchestrates all trading strategies with shared infrastructure.

    Responsibilities:
    - Starts/stops strategies
    - Manages bankroll splits
    - Enforces shared position registry (no overlap)
    - Tracks per-strategy P/L independently
    - Monitors cross-strategy return correlation
    - Sends iMessage alerts for high correlation, crashes, big wins/losses
    - Logs hourly comparative P/L dashboard
    - Manages the ideas.txt RBI queue

    Usage::

        manager = StrategyManager(total_bankroll=1000.0)
        manager.register_strategy("weather_trader", weather_strategy)
        manager.register_strategy("copytrade", copytrade_strategy)

        await manager.start()
        # ... runs indefinitely ...
        await manager.stop()
    """

    def __init__(
        self,
        total_bankroll: float = 1000.0,
        allocations: dict[str, float] | None = None,
        correlation_threshold: float = CORRELATION_ALERT_THRESHOLD,
        imessage_recipient: str | None = None,
        dry_run: bool = False,
        ideas_path: Path | None = None,
    ) -> None:
        self.total_bankroll = total_bankroll
        self.allocations = allocations or STRATEGY_ALLOCATIONS
        self.correlation_threshold = correlation_threshold
        self.imessage_recipient = imessage_recipient or os.environ.get("IMESSAGE_RECIPIENT", "")
        self.dry_run = dry_run

        # Core infrastructure
        self.registry = SharedPositionRegistry()
        self.ideas = IdeasQueue(ideas_path)

        # Strategy registry
        self._strategies: dict[str, BaseStrategy] = {}
        self._pnl: dict[str, StrategyPnL] = {}

        # Monitoring tasks
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._started_at: float = 0.0

        # Correlation history: strategy_name → deque of hourly correlation snapshots
        self._correlation_history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=48)
        )
        self._last_correlation_check: float = 0.0
        self._last_dashboard_log: float = 0.0

        logger.info(
            "strategy_manager_init",
            total_bankroll=total_bankroll,
            allocations=self.allocations,
            dry_run=dry_run,
        )

    # ── Strategy Registration ─────────────────────────────────────────────────

    def register_strategy(self, name: str, strategy: BaseStrategy) -> None:
        """Register a strategy and initialize its P/L tracker."""
        if name in self._strategies:
            raise ValueError(f"Strategy '{name}' already registered")

        allocation_pct = self.allocations.get(name, 0.0)
        bankroll = self.total_bankroll * allocation_pct

        self._strategies[name] = strategy
        self._pnl[name] = StrategyPnL(strategy=name, bankroll=bankroll)
        if hasattr(strategy, "set_bankroll"):
            try:
                strategy.set_bankroll(bankroll)
            except Exception:
                pass

        logger.info(
            "strategy_registered",
            name=name,
            bankroll=round(bankroll, 2),
            allocation_pct=allocation_pct,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all registered strategies and monitoring loops."""
        if self._running:
            logger.warning("strategy_manager_already_running")
            return

        self._running = True
        self._started_at = time.time()

        # Inject shared registry into strategies that support it
        for name, strategy in self._strategies.items():
            if hasattr(strategy, "set_position_registry"):
                strategy.set_position_registry(self.registry)
            if hasattr(strategy, "set_strategy_pnl"):
                strategy.set_strategy_pnl(self._pnl[name])

        # Start all strategies
        for name, strategy in self._strategies.items():
            try:
                await strategy.start()
                logger.info("strategy_started", name=name)
            except Exception as exc:
                logger.error("strategy_start_error", name=name, error=str(exc))
                self._alert(f"[CRASH] Strategy '{name}' failed to start: {exc}", priority="HIGH")

        # Start monitoring tasks
        self._tasks = [
            asyncio.create_task(self._correlation_monitor_loop()),
            asyncio.create_task(self._dashboard_loop()),
            asyncio.create_task(self._ideas_queue_monitor_loop()),
            asyncio.create_task(self._strategy_health_monitor_loop()),
        ]

        prefix = "[PAPER] " if self.dry_run else ""
        self._alert(
            f"{prefix}PolyBot STARTED — {len(self._strategies)} strategies, "
            f"bankroll ${self.total_bankroll:.0f}",
            priority="LOW",
        )
        logger.info(
            "strategy_manager_started",
            strategies=list(self._strategies.keys()),
            total_bankroll=self.total_bankroll,
        )

    async def stop(self) -> None:
        """Stop all strategies and monitoring tasks cleanly."""
        if not self._running:
            return

        self._running = False

        # Stop all strategies
        for name, strategy in self._strategies.items():
            try:
                await strategy.stop()
            except Exception as exc:
                logger.error("strategy_stop_error", name=name, error=str(exc))

        # Cancel monitoring tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Log final dashboard
        self._log_dashboard()

        uptime = time.time() - self._started_at
        self._alert(
            f"PolyBot STOPPED — uptime {uptime/3600:.1f}h — "
            f"total P/L: ${self._total_pnl():+.2f}",
            priority="MEDIUM",
        )
        logger.info("strategy_manager_stopped", uptime_hours=round(uptime / 3600, 2))

    # ── P/L Management ────────────────────────────────────────────────────────

    def record_close(
        self,
        strategy: str,
        token_id: str,
        exit_price: float,
        market_question: str = "",
        reason: str = "",
    ) -> ClosedTrade | None:
        """Record a trade close — called by strategies when they exit a position.

        Updates P/L ledger, releases from registry, fires alerts for big moves.
        """
        # Release from registry
        registry_entry = self.registry._positions.get(token_id)
        if not registry_entry:
            logger.warning("close_not_in_registry", token_id=token_id[:20], strategy=strategy)
            return None

        trade = ClosedTrade(
            strategy=strategy,
            token_id=token_id,
            market_question=market_question or registry_entry.market_question,
            entry_price=registry_entry.entry_price,
            exit_price=exit_price,
            size=registry_entry.size,
            entry_time=registry_entry.entry_time,
            exit_time=time.time(),
            reason=reason,
        )

        # Update registry
        registry_entry.closed = True
        registry_entry.exit_price = exit_price
        registry_entry.exit_time = trade.exit_time

        # Update P/L ledger
        if strategy in self._pnl:
            self._pnl[strategy].record_close(trade)

        # Alert on big wins / losses
        pnl = trade.pnl
        pnl_pct = trade.pnl_pct * 100

        if pnl >= 20.0:
            self._alert(
                f"BIG WIN [{strategy}] {market_question[:40]}\n"
                f"Entry: ${registry_entry.entry_price:.3f} → Exit: ${exit_price:.3f}\n"
                f"P/L: +${pnl:.2f} (+{pnl_pct:.0f}%)",
                priority="MEDIUM",
            )
        elif pnl <= -15.0:
            self._alert(
                f"BIG LOSS [{strategy}] {market_question[:40]}\n"
                f"Entry: ${registry_entry.entry_price:.3f} → Exit: ${exit_price:.3f}\n"
                f"P/L: -${abs(pnl):.2f} ({pnl_pct:.0f}%)",
                priority="MEDIUM",
            )

        logger.info(
            "manager_trade_closed",
            strategy=strategy,
            market=market_question[:50],
            entry=registry_entry.entry_price,
            exit=exit_price,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 1),
            reason=reason,
        )

        # 8d. Publish trade outcome to cortex for learning
        try:
            import redis as redis_sync
            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=2)
                won = pnl >= 0
                category_guess = ""
                for kw in ("crypto", "weather", "esports", "tennis", "sports", "politics"):
                    if kw in (market_question or "").lower():
                        category_guess = kw
                        break
                rc.publish("cortex:learn", json.dumps({
                    "category": "trading_rule",
                    "title": f"Trade outcome: {(market_question or 'unknown')[:60]}",
                    "content": (
                        f"Strategy: {strategy}, "
                        f"Entry: {registry_entry.entry_price:.3f}, "
                        f"Exit: {exit_price:.3f}, "
                        f"Size: ${registry_entry.size:.2f}, "
                        f"Outcome: {'WIN' if won else 'LOSS'}, "
                        f"P/L: ${pnl:.2f}, "
                        f"Reason: {reason}"
                    ),
                    "source": "trade_outcome",
                    "confidence": 1.0,
                    "importance": 8,
                    "tags": [strategy, "win" if won else "loss", category_guess],
                }))
                rc.close()
        except Exception as _cortex_exc:
            logger.debug("cortex_trade_outcome_error", error=str(_cortex_exc))

        return trade

    def get_strategy_bankroll(self, strategy: str) -> float:
        """Return the effective bankroll for a strategy (initial allocation + realized P/L)."""
        if strategy not in self._pnl:
            return self.total_bankroll * self.allocations.get(strategy, 0.0)
        pnl_tracker = self._pnl[strategy]
        return max(pnl_tracker.bankroll + pnl_tracker.realized_pnl, 10.0)

    def _total_pnl(self) -> float:
        return sum(p.total_pnl for p in self._pnl.values())

    # ── Cortex Consultation (8b) ──────────────────────────────────────────────

    async def _consult_cortex(
        self,
        market: str,
        strategy_name: str,
        entry_price: float,
        size: float,
    ) -> None:
        """Ask the cortex if this trade aligns with learned rules (non-blocking).

        Cortex failures must NEVER block or delay trade execution.
        Future: make this blocking with a short timeout to act as a pre-trade gate.
        """
        try:
            import uuid
            redis_url = os.environ.get("REDIS_URL", "")
            if not redis_url:
                return
            import redis as redis_sync
            request_id = str(uuid.uuid4())[:8]
            rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=1)
            rc.publish("cortex:query", json.dumps({
                "request_id": request_id,
                "question": (
                    f"Should I enter '{market}' at {entry_price:.3f} "
                    f"for ${size:.2f} via {strategy_name}?"
                ),
                "context": {
                    "market": market,
                    "strategy": strategy_name,
                    "entry_price": entry_price,
                    "size": size,
                },
            }))
            rc.close()
            logger.debug(
                "cortex_consulted",
                market=market[:40],
                strategy=strategy_name,
                entry_price=entry_price,
                request_id=request_id,
            )
        except Exception as exc:
            # Cortex down must never block trading
            logger.debug("cortex_consult_skipped", error=str(exc))

    # ── Monitoring Loops ──────────────────────────────────────────────────────

    async def _correlation_monitor_loop(self) -> None:
        """Check cross-strategy return correlation every 15 minutes."""
        while self._running:
            await asyncio.sleep(900)  # 15 minutes
            try:
                self._check_correlation()
            except Exception as exc:
                logger.error("correlation_monitor_error", error=str(exc))

    def _check_correlation(self) -> None:
        """Compute pairwise Pearson correlation of strategy returns. Alert if > threshold."""
        strategy_names = list(self._pnl.keys())
        if len(strategy_names) < 2:
            return

        correlations: dict[tuple[str, str], float] = {}
        for i, name_a in enumerate(strategy_names):
            for name_b in strategy_names[i + 1:]:
                returns_a = self._pnl[name_a].recent_returns
                returns_b = self._pnl[name_b].recent_returns

                corr = _pearson_correlation(returns_a, returns_b)
                key = (name_a, name_b)
                correlations[key] = corr
                self._correlation_history[key].append(corr)

                logger.info(
                    "strategy_correlation",
                    strategies=f"{name_a} × {name_b}",
                    correlation=round(corr, 3),
                    threshold=self.correlation_threshold,
                )

                if corr > self.correlation_threshold:
                    self._alert(
                        f"HIGH CORRELATION ALERT\n"
                        f"{name_a} × {name_b}: r={corr:.2f} (threshold={self.correlation_threshold})\n"
                        f"Strategies may be trading same markets — review position registry",
                        priority="HIGH",
                    )

        self._last_correlation_check = time.time()

    async def _dashboard_loop(self) -> None:
        """Log the hourly P/L dashboard."""
        while self._running:
            await asyncio.sleep(3600)  # every hour
            try:
                self._log_dashboard()
            except Exception as exc:
                logger.error("dashboard_loop_error", error=str(exc))

    def _log_dashboard(self) -> None:
        """Log a formatted P/L dashboard across all strategies."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        prefix = "[PAPER] " if self.dry_run else ""

        lines = [
            "═" * 54,
            f"{prefix}POLYMARKET BOT — P/L SNAPSHOT",
            f"{now}",
            "═" * 54,
            f"{'Strategy':<16} {'Bankroll':>9} {'Trades':>7} {'Win%':>6} {'P/L':>10}",
            "─" * 54,
        ]

        for name, pnl in self._pnl.items():
            snap = pnl.snapshot()
            bankroll = self.get_strategy_bankroll(name)
            lines.append(
                f"{name:<16} ${bankroll:>8.0f} "
                f"{snap['total_trades']:>7} "
                f"{snap['win_rate']:>5.0f}% "
                f"${snap['total_pnl']:>+9.2f}"
            )

        lines.append("─" * 54)
        total = self._total_pnl()
        total_trades = sum(p.total_trades for p in self._pnl.values())
        lines.append(f"{'TOTAL':<16} ${self.total_bankroll:>8.0f} {total_trades:>7}       ${total:>+9.2f}")
        lines.append("")

        # Correlation matrix
        strategy_names = list(self._pnl.keys())
        if len(strategy_names) >= 2:
            lines.append("Correlation Matrix (last 20 trades):")
            for i, name_a in enumerate(strategy_names):
                for name_b in strategy_names[i + 1:]:
                    history = self._correlation_history.get((name_a, name_b), deque())
                    corr = history[-1] if history else 0.0
                    status = " ← HIGH" if corr > self.correlation_threshold else ""
                    lines.append(f"  {name_a} × {name_b}: {corr:+.2f}{status}")

        lines.append("")
        lines.append(f"Registry: {self.registry.summary()}")
        lines.append("═" * 54)

        dashboard_text = "\n".join(lines)
        logger.info("hourly_dashboard", dashboard=dashboard_text)
        print(dashboard_text)

        self._last_dashboard_log = time.time()

        # Also log as structured event for monitoring systems
        dashboard_data = {
            "strategies": {name: pnl.snapshot() for name, pnl in self._pnl.items()},
            "total_pnl": round(total, 2),
            "total_trades": total_trades,
            "registry": self.registry.summary(),
            "dry_run": self.dry_run,
        }
        logger.info("pnl_snapshot", **dashboard_data)

        # Publish to Redis for Mission Control and other consumers
        try:
            import redis as redis_sync

            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=2)
                rc.publish(
                    "events:trading",
                    json.dumps({"type": "strategy_dashboard", "data": dashboard_data}),
                )
                rc.close()
        except Exception as exc:
            logger.debug("dashboard_redis_publish_error", error=str(exc))

    async def _ideas_queue_monitor_loop(self) -> None:
        """Check ideas.txt every 6 hours. Alert if 3+ pending ideas ready for review."""
        while self._running:
            await asyncio.sleep(21600)  # 6 hours
            try:
                pending = self.ideas.get_pending()
                if len(pending) >= 3:
                    titles = ", ".join(i.get("IDEA", "?") for i in pending[:3])
                    self._alert(
                        f"IDEAS QUEUE: {len(pending)} pending ideas ready for research\n"
                        f"Top 3: {titles}",
                        priority="LOW",
                    )
                    logger.info("ideas_queue_alert", pending_count=len(pending))
            except Exception as exc:
                logger.error("ideas_monitor_error", error=str(exc))

    async def _strategy_health_monitor_loop(self) -> None:
        """Check strategy health every 5 minutes. Alert on crashes."""
        while self._running:
            await asyncio.sleep(300)  # 5 minutes
            try:
                for name, strategy in self._strategies.items():
                    strategy_state = getattr(strategy, "state", None)
                    if strategy_state == StrategyState.ERROR:
                        self._alert(
                            f"[CRASH] Strategy '{name}' is in ERROR state — needs restart",
                            priority="HIGH",
                        )
                        logger.error("strategy_health_crash", name=name)
                    elif strategy_state == StrategyState.IDLE and self._running:
                        logger.warning("strategy_unexpected_idle", name=name)
            except Exception as exc:
                logger.error("health_monitor_error", error=str(exc))

    # ── Alert System ──────────────────────────────────────────────────────────

    def _alert(self, message: str, priority: str = "MEDIUM") -> None:
        """Send an alert via iMessage and log it.

        Priority levels: HIGH, MEDIUM, LOW
        LOW priority alerts are skipped if recipient not configured.
        """
        prefix = "[PAPER] " if self.dry_run else ""
        full_message = f"{prefix}[{priority}] {message}"

        logger.info(
            "alert_fired",
            priority=priority,
            message=message[:100],
            dry_run=self.dry_run,
        )

        # HIGH alerts always attempt iMessage
        # MEDIUM and LOW only if recipient configured
        if priority == "HIGH" or (priority in ("MEDIUM", "LOW") and self.imessage_recipient):
            send_imessage(full_message, self.imessage_recipient)

    # ── Status / Info ─────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return full system status for API endpoints."""
        return {
            "running": self._running,
            "dry_run": self.dry_run,
            "uptime_seconds": round(time.time() - self._started_at) if self._started_at else 0,
            "total_bankroll": self.total_bankroll,
            "total_pnl": round(self._total_pnl(), 2),
            "strategies": {
                name: {
                    "state": strategy.state.value,
                    "pnl": self._pnl[name].snapshot(),
                    "bankroll": round(self.get_strategy_bankroll(name), 2),
                    "open_positions": len(self.registry.get_open_positions(name)),
                }
                for name, strategy in self._strategies.items()
            },
            "registry": self.registry.summary(),
            "pending_ideas": len(self.ideas.get_pending()),
            "last_correlation_check": self._last_correlation_check,
            "last_dashboard_log": self._last_dashboard_log,
        }

    def __repr__(self) -> str:
        strategies = list(self._strategies.keys())
        return (
            f"StrategyManager(strategies={strategies}, "
            f"bankroll=${self.total_bankroll:.0f}, "
            f"running={self._running})"
        )
