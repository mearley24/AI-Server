"""Trade Firehose Monitor — polls the Polymarket trades endpoint for new activity."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
TRADES_URL = "https://data-api.polymarket.com/trades"
POLL_INTERVAL = 30  # seconds between polls
WINDOW_SECONDS = 7200  # 2-hour rolling window
TRADES_LIMIT = 200  # max trades per poll


@dataclass
class ParsedTrade:
    """A normalized trade from the firehose."""

    trade_id: str
    wallet: str
    condition_id: str
    token_id: str
    side: str  # BUY or SELL
    price: float
    size: float  # shares
    usdc_value: float  # size * price
    timestamp: float  # epoch
    market_slug: str = ""
    market_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "wallet": self.wallet,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "usdc_value": self.usdc_value,
            "timestamp": self.timestamp,
            "market_slug": self.market_slug,
            "market_title": self.market_title,
        }


class TradeMonitor:
    """Polls the Polymarket trade firehose and maintains a rolling window."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._seen_ids: set[str] = set()
        self._last_timestamp: float = 0.0
        self._trades: deque[ParsedTrade] = deque()
        self._total_polled: int = 0
        self._last_poll_time: float = 0.0
        self._poll_count: int = 0

    async def poll(self) -> list[ParsedTrade]:
        """Fetch new trades from the firehose. Returns only unseen trades."""
        now = time.time()
        self._last_poll_time = now
        self._poll_count += 1

        try:
            resp = await self._http.get(
                TRADES_URL,
                params={"limit": TRADES_LIMIT},
                timeout=15.0,
            )
            resp.raise_for_status()
            raw_trades = resp.json()
        except Exception as exc:
            logger.warning("trade_monitor_poll_error", error=str(exc)[:120])
            return []

        new_trades: list[ParsedTrade] = []

        for raw in raw_trades:
            trade_id = raw.get("id", raw.get("transactionHash", ""))
            if not trade_id or trade_id in self._seen_ids:
                continue

            self._seen_ids.add(trade_id)

            price = float(raw.get("price", 0))
            size = float(raw.get("size", 0))
            usdc_value = size * price

            ts = raw.get("timestamp", raw.get("matchTime", 0))
            if isinstance(ts, str):
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = now

            parsed = ParsedTrade(
                trade_id=trade_id,
                wallet=raw.get("maker", raw.get("taker", raw.get("user", ""))).lower(),
                condition_id=raw.get("market", raw.get("conditionId", "")),
                token_id=raw.get("asset", raw.get("asset_id", raw.get("tokenId", ""))),
                side=raw.get("side", "").upper(),
                price=price,
                size=size,
                usdc_value=usdc_value,
                timestamp=float(ts) if ts else now,
                market_slug=raw.get("slug", raw.get("event_slug", "")),
                market_title=raw.get("title", raw.get("market_question", raw.get("question", ""))),
            )

            new_trades.append(parsed)
            self._trades.append(parsed)

        self._total_polled += len(new_trades)

        # Trim rolling window
        cutoff = now - WINDOW_SECONDS
        while self._trades and self._trades[0].timestamp < cutoff:
            old = self._trades.popleft()
            self._seen_ids.discard(old.trade_id)

        if new_trades:
            logger.debug(
                "trade_monitor_polled",
                new=len(new_trades),
                window_size=len(self._trades),
                total_polled=self._total_polled,
            )

        return new_trades

    def get_recent_trades(self, seconds: int = WINDOW_SECONDS) -> list[ParsedTrade]:
        """Return trades from the rolling window within the last N seconds."""
        cutoff = time.time() - seconds
        return [t for t in self._trades if t.timestamp >= cutoff]

    def get_stats(self) -> dict[str, Any]:
        """Return monitor statistics."""
        return {
            "last_poll_time": self._last_poll_time,
            "poll_count": self._poll_count,
            "total_polled": self._total_polled,
            "window_size": len(self._trades),
            "seen_ids_count": len(self._seen_ids),
        }
