"""CVD Divergence detector strategy with spread/arb assist.

Detects order-flow divergence:
- Price up while CVD down -> bearish divergence (sell)
- Price down while CVD up -> bullish divergence (buy)

Also runs the existing spread/arb scanner and publishes candidate opportunities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import httpx
import redis

from src.signer import SIDE_BUY, SIDE_SELL
from strategies.base import BaseStrategy
from strategies.spread_arb import SpreadArbScanner

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://172.18.0.100:6379")
SIGNAL_CHANNEL = "signals:cvd"


@dataclass
class CvdPoint:
    ts: float
    price: float
    cvd: float


class CVDDetectorStrategy(BaseStrategy):
    """Strategy #3: CVD divergence + arb scanner."""

    name = "cvd_arb"
    description = "CVD divergence detector with spread/arb scanning"

    def __init__(self, client, settings, scanner, orderbook, pnl_tracker) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = float(os.environ.get("CVD_SCAN_INTERVAL_SECONDS", "300"))
        self._window_seconds = int(os.environ.get("CVD_WINDOW_SECONDS", "900"))  # 15 minutes
        self._price_move_threshold = float(os.environ.get("CVD_PRICE_MOVE_THRESHOLD", "0.05"))
        self._max_signals_per_tick = int(os.environ.get("CVD_MAX_SIGNALS_PER_TICK", "3"))
        self._signal_size_usd = float(os.environ.get("CVD_SIGNAL_SIZE_USD", "5"))
        self._history: dict[str, deque[CvdPoint]] = defaultdict(lambda: deque(maxlen=200))
        self._state_cache: dict[str, dict[str, float]] = {}
        self._arb = SpreadArbScanner(bankroll=float(os.environ.get("CVD_ARB_BANKROLL", "250")), dry_run=settings.dry_run)
        self._redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)

    async def on_tick(self) -> None:
        markets = await self._fetch_markets()
        now = time.time()
        self._update_cvd(markets, now)

        signals = self._detect_divergences(now)
        for signal in signals[: self._max_signals_per_tick]:
            self._publish_signal(signal)
            await self._execute_signal(signal)

        arb_opps = await self._arb.scan_once()
        for opp in arb_opps[:2]:
            self._publish_signal(
                {
                    "strategy": self.name,
                    "type": "arb_opportunity",
                    "market": opp.market_title,
                    "condition_id": opp.condition_id,
                    "expected_profit_pct": opp.expected_profit_pct,
                    "timestamp": now,
                }
            )

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": 250,
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                if resp.status_code != 200:
                    return []
                return resp.json()
        except Exception as exc:
            logger.warning("cvd_fetch_markets_error: %s", str(exc)[:200])
            return []

    def _extract_price(self, market: dict[str, Any]) -> float:
        raw = market.get("outcomePrices")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return 0.0
        if isinstance(raw, list) and raw:
            try:
                return float(raw[0])
            except Exception:
                return 0.0
        return 0.0

    def _extract_token_id(self, market: dict[str, Any]) -> str:
        tokens = market.get("tokens", [])
        if isinstance(tokens, list) and tokens:
            token_id = tokens[0].get("token_id")
            if token_id:
                return str(token_id)
        return str(market.get("conditionId", ""))

    def _update_cvd(self, markets: list[dict[str, Any]], now: float) -> None:
        for m in markets:
            cid = str(m.get("conditionId", ""))
            if not cid:
                continue
            price = self._extract_price(m)
            if price <= 0:
                continue
            volume = float(m.get("volume24hr", 0) or 0)
            prev = self._state_cache.get(cid, {"price": price, "volume": volume, "cvd": 0.0})

            delta_vol = max(0.0, volume - prev["volume"])
            cvd = prev["cvd"]
            if price > prev["price"]:
                cvd += delta_vol
            elif price < prev["price"]:
                cvd -= delta_vol

            self._state_cache[cid] = {"price": price, "volume": volume, "cvd": cvd}
            self._history[cid].append(CvdPoint(ts=now, price=price, cvd=cvd))

    def _detect_divergences(self, now: float) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for cid, points in self._history.items():
            if len(points) < 2:
                continue
            latest = points[-1]
            baseline = None
            for p in reversed(points):
                if latest.ts - p.ts >= self._window_seconds:
                    baseline = p
                    break
            if baseline is None:
                continue

            price_change = (latest.price - baseline.price) / baseline.price if baseline.price > 0 else 0.0
            cvd_change = latest.cvd - baseline.cvd
            if abs(price_change) < self._price_move_threshold:
                continue
            if price_change > 0 and cvd_change >= 0:
                continue
            if price_change < 0 and cvd_change <= 0:
                continue

            side = "buy" if price_change < 0 and cvd_change > 0 else "sell"
            signal = {
                "strategy": self.name,
                "type": "cvd_divergence",
                "condition_id": cid,
                "side": side,
                "price_change_pct": round(price_change * 100, 2),
                "cvd_change": round(cvd_change, 2),
                "price": latest.price,
                "timestamp": latest.ts,
            }
            signals.append(signal)
            logger.info("cvd_signal: %s", signal)
        return signals

    def _publish_signal(self, signal: dict[str, Any]) -> None:
        try:
            self._redis.publish(SIGNAL_CHANNEL, json.dumps(signal))
        except Exception as exc:
            logger.warning("cvd_publish_error: %s", str(exc)[:200])

    async def _execute_signal(self, signal: dict[str, Any]) -> None:
        token_id = signal.get("condition_id", "")
        if not token_id:
            return
        side = SIDE_BUY if signal.get("side") == "buy" else SIDE_SELL
        price = float(signal.get("price", 0.5))
        price = max(0.01, min(0.99, price))
        await self._place_limit_order(
            token_id=token_id,
            market=f"CVD signal {token_id[:12]}",
            price=price,
            size=self._signal_size_usd,
            side=side,
        )
