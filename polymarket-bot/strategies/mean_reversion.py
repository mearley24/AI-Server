"""Mean reversion / fade strategy — Auto-6.

Fades sharp short-term moves on thin volume in binary markets (Gamma API).
Paper signals: Redis channel `signals:mean_reversion`.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import redis

from src.signer import SIDE_BUY, SIDE_SELL
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
SIGNAL_KEY = "signals:mean_reversion"

MOVE_THRESHOLD = float(os.environ.get("MR_MOVE_THRESHOLD", "0.30"))
MAX_VOLUME_24H = float(os.environ.get("MR_MAX_VOLUME_24H", "1000"))
MIN_RESOLUTION_HOURS = float(os.environ.get("MR_MIN_RESOLUTION_HOURS", "24"))
MAX_ENTRY_PRICE = float(os.environ.get("MR_MAX_ENTRY_PRICE", "0.25"))
TP_REVERSION_PCT = float(os.environ.get("MR_TP_REVERSION_PCT", "0.50"))
SL_PCT = float(os.environ.get("MR_SL_PCT", "0.40"))
MAX_HOLD_SEC = float(os.environ.get("MR_MAX_HOLD_SEC", str(6 * 3600)))
TICK_INTERVAL = float(os.environ.get("MR_TICK_INTERVAL", "300"))
MAX_SPREAD = float(os.environ.get("MR_MAX_SPREAD", "0.05"))


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return []


def _yes_no_prices(market: dict[str, Any]) -> tuple[float, float] | None:
    raw = market.get("outcomePrices")
    prices = _parse_json_list(raw)
    if len(prices) < 2:
        return None
    try:
        return float(prices[0]), float(prices[1])
    except (TypeError, ValueError):
        return None


def _weather_market(question: str) -> bool:
    q = (question or "").lower()
    keys = ("temperature", "rain", "snow", "noaa", "weather", "°f", "°c", "hurricane", "precip")
    return any(k in q for k in keys)


class MeanReversionStrategy(BaseStrategy):
    """Fade sharp moves on thin volume; uses arb / CVD bankroll slice."""

    name = "mean_reversion"
    description = "Mean reversion fade on binary Polymarket markets"

    def __init__(self, client, settings, scanner, orderbook, pnl_tracker) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = TICK_INTERVAL
        self._registry = None
        self._bankroll = float(os.environ.get("COPYTRADE_BANKROLL", "1000")) * 0.10
        self._redis = None
        self._positions: dict[str, dict[str, Any]] = {}
        try:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        except Exception:
            self._redis = None

    def set_position_registry(self, registry: Any) -> None:
        self._registry = registry

    def set_bankroll(self, bankroll: float) -> None:
        self._bankroll = float(bankroll)

    def _publish_paper(self, payload: dict[str, Any]) -> None:
        if not self._redis:
            return
        try:
            self._redis.publish(SIGNAL_KEY, json.dumps(payload, default=str))
        except Exception as exc:
            logger.debug("mean_reversion_redis_publish_failed: %s", str(exc)[:120])

    async def on_tick(self) -> None:
        markets = await self._fetch_gamma_markets()
        now = time.time()
        await self._check_exits(now)

        for m in markets:
            if not self._passes_filters(m):
                continue
            fade = self._fade_candidate(m)
            if not fade:
                continue
            token_id, side_label, entry_price, question, move_sz = fade
            if self._registry and self._registry.is_claimed(token_id):
                continue
            if entry_price > MAX_ENTRY_PRICE:
                continue
            if not await self._liquidity_ok(token_id):
                continue
            if await self._copytrade_agrees(m, side_label):
                continue

            size_usd = min(25.0, max(5.0, self._bankroll * 0.02))
            shares = size_usd / max(entry_price, 0.01)

            payload = {
                "strategy": self.name,
                "condition_id": m.get("conditionId", ""),
                "token_id": token_id,
                "side": "BUY",
                "price": entry_price,
                "shares": shares,
                "market": (question or "")[:120],
                "timestamp": now,
            }
            self._publish_paper(payload)

            if self._settings.dry_run:
                logger.info(
                    "mean_reversion_paper: %s fade=%s entry=%.3f",
                    (question or "")[:60],
                    side_label,
                    entry_price,
                )
                if self._registry:
                    await self._registry.claim(
                        token_id,
                        self.name,
                        entry_price,
                        shares,
                        market_question=question or "",
                    )
                self._positions[token_id] = {
                    "entry": entry_price,
                    "side": side_label,
                    "opened_at": now,
                    "question": question,
                    "move": move_sz,
                    "shares": shares,
                }
                continue

            try:
                await self._client.place_order(
                    token_id=token_id,
                    price=entry_price,
                    size=shares,
                    side=SIDE_BUY,
                )
                if self._registry:
                    await self._registry.claim(
                        token_id,
                        self.name,
                        entry_price,
                        shares,
                        market_question=question or "",
                    )
                self._positions[token_id] = {
                    "entry": entry_price,
                    "side": side_label,
                    "opened_at": now,
                    "question": question,
                    "move": move_sz,
                    "shares": shares,
                }
                logger.info(
                    "mean_reversion_entered: %s price=%.3f shares=%.2f",
                    (question or "")[:80],
                    entry_price,
                    shares,
                )
            except Exception as exc:
                logger.warning("mean_reversion_order_failed: %s", str(exc)[:160])

    async def _fetch_gamma_markets(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": 200,
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                if r.status_code != 200:
                    return []
                data = r.json()
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("mean_reversion_gamma_error: %s", str(exc)[:120])
            return []

    def _passes_filters(self, m: dict[str, Any]) -> bool:
        q = m.get("question") or ""
        if _weather_market(q):
            return False
        if m.get("closed"):
            return False
        prices = _yes_no_prices(m)
        if not prices:
            return False
        end_iso = m.get("endDateIso") or m.get("end_date_iso")
        if end_iso:
            try:
                end_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
                hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours < MIN_RESOLUTION_HOURS:
                    return False
            except Exception:
                pass
        vol = float(m.get("volume24hr") or m.get("volume") or 0)
        if vol > MAX_VOLUME_24H:
            return False
        return True

    def _fade_candidate(self, m: dict[str, Any]) -> tuple[str, str, float, str, float] | None:
        prices = _yes_no_prices(m)
        if not prices:
            return None
        yes_p, no_p = prices
        move = float(m.get("oneDayPriceChange") or 0.0)
        if abs(move) < MOVE_THRESHOLD:
            return None

        clobs = _parse_json_list(m.get("clobTokenIds"))
        if len(clobs) < 2:
            return None
        yes_tid, no_tid = str(clobs[0]), str(clobs[1])

        if move > 0:
            token_id = no_tid
            side_label = "NO"
            entry_price = no_p
        else:
            token_id = yes_tid
            side_label = "YES"
            entry_price = yes_p

        return (token_id, side_label, float(entry_price), m.get("question") or "", abs(move))

    async def _liquidity_ok(self, token_id: str) -> bool:
        try:
            book = await self._client.get_orderbook(token_id)
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            if not bids or not asks:
                return False
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            if best_ask <= 0 or best_bid <= 0:
                return False
            spread = best_ask - best_bid
            return spread <= MAX_SPREAD
        except Exception:
            return False

    async def _copytrade_agrees(self, market: dict[str, Any], fade_side: str) -> bool:
        return False

    async def _check_exits(self, now: float) -> None:
        for token_id, pos in list(self._positions.items()):
            age = now - float(pos.get("opened_at", now))
            if age > MAX_HOLD_SEC:
                await self._maybe_exit(token_id, pos, reason="time_stop")
                continue
            try:
                mid = await self._client.get_midpoint(token_id)
            except Exception:
                continue
            entry = float(pos.get("entry", 0))
            move = float(pos.get("move", MOVE_THRESHOLD))
            target = max(0.01, entry + TP_REVERSION_PCT * (0.5 * move))
            if mid >= target:
                await self._maybe_exit(token_id, pos, reason="tp", exit_price=mid)
            elif mid <= entry * (1 - SL_PCT):
                await self._maybe_exit(token_id, pos, reason="sl", exit_price=mid)

    async def _maybe_exit(
        self,
        token_id: str,
        pos: dict[str, Any],
        reason: str,
        exit_price: float | None = None,
    ) -> None:
        price = exit_price or await self._client.get_midpoint(token_id)
        size = float(pos.get("shares", 0)) or 0.0
        if size <= 0:
            entry = float(pos.get("entry", 0.01))
            size = 10.0 / max(entry, 0.01)
        if self._settings.dry_run:
            self._positions.pop(token_id, None)
            if self._registry:
                await self._registry.release(token_id, exit_price=price)
            logger.info("mean_reversion_exit_paper: token=%s reason=%s", token_id[:12], reason)
            return
        try:
            await self._client.place_order(
                token_id=token_id,
                price=max(0.01, min(0.99, price)),
                size=size,
                side=SIDE_SELL,
            )
            self._positions.pop(token_id, None)
            if self._registry:
                await self._registry.release(token_id, exit_price=price)
            logger.info("mean_reversion_exit: token=%s reason=%s", token_id[:12], reason)
        except Exception as exc:
            logger.warning("mean_reversion_exit_failed: %s", str(exc)[:120])

# Alias for import checks (Auto-6/7)
MeanReversion = MeanReversionStrategy
