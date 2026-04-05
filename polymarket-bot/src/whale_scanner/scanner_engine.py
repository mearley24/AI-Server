"""Scanner Engine — orchestrates all whale scanner components as an async background task."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import httpx
import structlog

from src.whale_scanner.trade_monitor import TradeMonitor, POLL_INTERVAL
from src.whale_scanner.whale_detector import WhaleDetector, WhaleSignal
from src.whale_scanner.fresh_wallet_detector import FreshWalletDetector, InsiderSignal
from src.whale_scanner.cluster_detector import ClusterDetector, ClusterSignal

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
SIGNAL_ACTIVE_HOURS = 4  # signals expire after this many hours
SIGNAL_DEDUP_SECONDS = 3600  # same wallet + same market within 1 hour = one signal
SIGNALS_FILE = "/data/whale_signals.json"
MAX_PERSISTED_SIGNALS = 500  # cap persisted signal history


AnySignal = Union[WhaleSignal, InsiderSignal, ClusterSignal]


@dataclass
class SignalRecord:
    """A unified signal record for storage and querying."""

    signal_type: str  # "whale", "insider", "cluster"
    condition_id: str
    market_title: str
    market_slug: str
    wallet: str  # primary wallet (or first in cluster)
    trade_size: float
    confidence_score: float
    timestamp: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "condition_id": self.condition_id,
            "market_title": self.market_title,
            "market_slug": self.market_slug,
            "wallet": self.wallet,
            "trade_size": self.trade_size,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class ScannerEngine:
    """Orchestrates the whale signal scanner as an async background task."""

    def __init__(self, data_dir: str = "/data") -> None:
        self._data_dir = data_dir
        self._signals_path = Path(data_dir) / "whale_signals.json"
        self._running = False
        self._task: asyncio.Task | None = None

        # Components (initialized on start)
        self._http: httpx.AsyncClient | None = None
        self._trade_monitor: TradeMonitor | None = None
        self._whale_detector: WhaleDetector | None = None
        self._fresh_wallet_detector: FreshWalletDetector | None = None
        self._cluster_detector: ClusterDetector | None = None

        # Signal storage
        self._active_signals: list[SignalRecord] = []
        self._all_signals: list[SignalRecord] = []  # persisted history
        self._dedup_keys: set[str] = set()

        # Stats
        self._start_time: float = 0.0
        self._signals_today: int = 0
        self._last_daily_reset: float = 0.0

        # Load persisted signals
        self._load_signals()

    async def start(self) -> None:
        """Start the scanner engine background task."""
        if self._running:
            return
        self._running = True
        self._start_time = time.time()

        self._http = httpx.AsyncClient(timeout=30.0)
        self._trade_monitor = TradeMonitor(self._http)
        self._whale_detector = WhaleDetector(self._http)
        self._fresh_wallet_detector = FreshWalletDetector(self._whale_detector)
        self._cluster_detector = ClusterDetector()

        self._task = asyncio.create_task(self._run_loop())
        logger.info("whale_scanner_started")

    async def stop(self) -> None:
        """Stop the scanner engine."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        self._save_signals()
        logger.info("whale_scanner_stopped", total_signals=len(self._all_signals))

    async def _run_loop(self) -> None:
        """Main scanner loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("whale_scanner_loop_error", error=str(exc)[:200])

            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """Single tick: poll trades, run detectors, collect signals."""
        assert self._trade_monitor is not None
        assert self._whale_detector is not None
        assert self._fresh_wallet_detector is not None
        assert self._cluster_detector is not None

        now = time.time()

        # Reset daily counter at midnight UTC
        current_day = int(now // 86400)
        if current_day != int(self._last_daily_reset // 86400):
            self._signals_today = 0
            self._last_daily_reset = now

        # 1. Poll trade firehose
        new_trades = await self._trade_monitor.poll()
        if not new_trades:
            return

        # 2. Run whale detector
        whale_signals = await self._whale_detector.check_trades(new_trades)

        # 3. Run fresh wallet detector on whale signals
        insider_signals = self._fresh_wallet_detector.check_whale_signals(whale_signals)

        # 4. Run cluster detector on all trades
        cluster_signals = self._cluster_detector.ingest_trades(new_trades)

        # 5. Collect and deduplicate all signals
        all_new: list[AnySignal] = []
        all_new.extend(whale_signals)
        all_new.extend(insider_signals)
        all_new.extend(cluster_signals)

        for signal in all_new:
            record = self._to_record(signal)
            if record and self._dedup(record):
                self._active_signals.append(record)
                self._all_signals.append(record)
                self._signals_today += 1

                # Whale signals are now tagged on [NEW TRADE] cards instead of
                # separate notifications. Only notify for extreme signals (90+).
                if record.confidence_score >= 90:
                    self._notify_signal(record)

        # 6. Expire old active signals
        cutoff = now - (SIGNAL_ACTIVE_HOURS * 3600)
        self._active_signals = [s for s in self._active_signals if s.timestamp >= cutoff]

        # Clean up dedup keys older than the dedup window
        dedup_cutoff = now - SIGNAL_DEDUP_SECONDS
        self._dedup_keys = {
            k for k in self._dedup_keys
            if any(s.timestamp >= dedup_cutoff for s in self._active_signals
                   if self._make_dedup_key(s) == k)
        }

        # 7. Persist signals periodically (every 10 ticks ≈ 5 minutes)
        if self._trade_monitor._poll_count % 10 == 0:
            self._save_signals()

    def _to_record(self, signal: AnySignal) -> SignalRecord | None:
        """Convert any signal to a unified SignalRecord."""
        if isinstance(signal, WhaleSignal):
            return SignalRecord(
                signal_type="whale",
                condition_id=signal.condition_id,
                market_title=signal.market_title,
                market_slug=signal.market_slug,
                wallet=signal.wallet,
                trade_size=signal.trade_size,
                confidence_score=signal.confidence_score,
                timestamp=signal.timestamp,
                details=signal.to_dict(),
            )
        elif isinstance(signal, InsiderSignal):
            return SignalRecord(
                signal_type="insider",
                condition_id=signal.condition_id,
                market_title=signal.market_title,
                market_slug=signal.market_slug,
                wallet=signal.wallet,
                trade_size=signal.trade_size,
                confidence_score=signal.confidence_score,
                timestamp=signal.timestamp,
                details=signal.to_dict(),
            )
        elif isinstance(signal, ClusterSignal):
            return SignalRecord(
                signal_type="cluster",
                condition_id=signal.condition_id,
                market_title=signal.market_title,
                market_slug=signal.market_slug,
                wallet=signal.wallets_involved[0] if signal.wallets_involved else "",
                trade_size=signal.total_cluster_volume,
                confidence_score=signal.confidence_score,
                timestamp=signal.timestamp,
                details=signal.to_dict(),
            )
        return None

    def _make_dedup_key(self, record: SignalRecord) -> str:
        """Create a dedup key: wallet + condition_id."""
        return f"{record.wallet}:{record.condition_id}"

    def _dedup(self, record: SignalRecord) -> bool:
        """Return True if this signal is new (not a duplicate)."""
        key = self._make_dedup_key(record)
        if key in self._dedup_keys:
            return False
        self._dedup_keys.add(key)
        return True

    def _notify_signal(self, record: SignalRecord) -> None:
        """Send notification for a signal via Redis."""
        try:
            import redis as _redis
            import os
            url = os.environ.get("REDIS_URL", "redis://:d19c9b0faebeee9927555eb8d6b28ec9@host.docker.internal:6379")
            r = _redis.from_url(url, decode_responses=True, socket_timeout=2)

            wallet_short = record.wallet[:6] + "..." + record.wallet[-4:] if len(record.wallet) > 10 else record.wallet
            market = record.market_title[:60] if record.market_title else record.condition_id[:20]

            if record.signal_type == "insider":
                title = "Whale Scanner"
                body = f"\U0001f525 Fresh wallet: ${record.trade_size:.0f} on {market} — insider pattern"
            elif record.signal_type == "cluster":
                wallet_count = record.details.get("wallet_count", len(record.details.get("wallets_involved", [])))
                body = f"\U0001f3af Cluster: {wallet_count} wallets, ${record.trade_size:.0f} total on {market}"
                title = "Whale Scanner"
            else:
                title = "Whale Scanner"
                body = f"\U0001f40b Whale: ${record.trade_size:.0f} on {market} by {wallet_short}"

            r.publish("notifications:trading", json.dumps({"title": title, "body": body}))
        except Exception:
            pass  # never block on notification failure

    # ── Public API ────────────────────────────────────────────────────────

    def get_active_signals(self) -> list[SignalRecord]:
        """Return all active signals from the last SIGNAL_ACTIVE_HOURS hours."""
        cutoff = time.time() - (SIGNAL_ACTIVE_HOURS * 3600)
        return [s for s in self._active_signals if s.timestamp >= cutoff]

    def get_signal_for_market(self, condition_id: str) -> list[SignalRecord]:
        """Check if there's whale activity on a specific market."""
        cutoff = time.time() - (SIGNAL_ACTIVE_HOURS * 3600)
        return [
            s for s in self._active_signals
            if s.condition_id == condition_id and s.timestamp >= cutoff
        ]

    def get_status(self) -> dict[str, Any]:
        """Return scanner status for health endpoint."""
        now = time.time()
        monitor_stats = self._trade_monitor.get_stats() if self._trade_monitor else {}

        # Trades scanned in last hour
        trades_last_hour = 0
        if self._trade_monitor:
            trades_last_hour = len(self._trade_monitor.get_recent_trades(3600))

        return {
            "running": self._running,
            "last_poll_time": monitor_stats.get("last_poll_time", 0),
            "last_poll_age_seconds": round(now - monitor_stats.get("last_poll_time", now), 1),
            "trades_scanned_last_hour": trades_last_hour,
            "trades_in_window": monitor_stats.get("window_size", 0),
            "total_trades_polled": monitor_stats.get("total_polled", 0),
            "active_signals": len(self.get_active_signals()),
            "signals_today": self._signals_today,
            "total_signals_ever": len(self._all_signals),
            "signal_breakdown": {
                "whale": sum(1 for s in self.get_active_signals() if s.signal_type == "whale"),
                "insider": sum(1 for s in self.get_active_signals() if s.signal_type == "insider"),
                "cluster": sum(1 for s in self.get_active_signals() if s.signal_type == "cluster"),
            },
            "uptime_hours": round((now - self._start_time) / 3600, 1) if self._start_time else 0,
        }

    # ── Persistence ───────────────────────────────────────────────────────

    def _save_signals(self) -> None:
        """Persist signals to disk."""
        try:
            Path(self._data_dir).mkdir(parents=True, exist_ok=True)
            # Keep only the most recent signals
            to_save = self._all_signals[-MAX_PERSISTED_SIGNALS:]
            data = [s.to_dict() for s in to_save]
            self._signals_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.debug("whale_signals_save_error", error=str(exc)[:100])

    def _load_signals(self) -> None:
        """Load persisted signals from disk."""
        try:
            if self._signals_path.exists():
                data = json.loads(self._signals_path.read_text())
                for item in data:
                    record = SignalRecord(
                        signal_type=item.get("signal_type", ""),
                        condition_id=item.get("condition_id", ""),
                        market_title=item.get("market_title", ""),
                        market_slug=item.get("market_slug", ""),
                        wallet=item.get("wallet", ""),
                        trade_size=item.get("trade_size", 0),
                        confidence_score=item.get("confidence_score", 0),
                        timestamp=item.get("timestamp", 0),
                        details=item.get("details", {}),
                    )
                    self._all_signals.append(record)

                # Restore active signals (within the active window)
                cutoff = time.time() - (SIGNAL_ACTIVE_HOURS * 3600)
                self._active_signals = [s for s in self._all_signals if s.timestamp >= cutoff]

                if self._all_signals:
                    logger.info(
                        "whale_signals_loaded",
                        total=len(self._all_signals),
                        active=len(self._active_signals),
                    )
        except Exception as exc:
            logger.debug("whale_signals_load_error", error=str(exc)[:100])
