"""Pre-resolution scalp — Auto-7. Buys cheap side 1–3h before resolution."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import redis

from src.client import ORDER_TYPE_GTC
from src.signer import SIDE_BUY
from strategies.base import BaseStrategy, OpenOrder
from strategies.llm_completion import completion as llm_complete

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434").strip()
OLLAMA_VALIDATE_MODEL = os.getenv("OLLAMA_VALIDATE_MODEL", os.getenv("OLLAMA_KNOWLEDGE_MODEL", "qwen3:8b"))


def _parse_approve_from_llm_text(text: str) -> bool:
    """Return True if model approves entry (cheap side OK). Default permissive."""
    s = (text or "").strip()
    if not s:
        return True
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "approve" in obj:
            return bool(obj.get("approve"))
    except json.JSONDecodeError:
        pass
    sl = s.lower()
    if '"approve": true' in sl or "'approve': true" in sl:
        return True
    if '"approve": false' in sl or "'approve': false" in sl:
        return False
    return "true" in sl



MAX_ENTRY_PRICE = float(os.environ.get("PS_MAX_ENTRY", "0.08"))
MIN_AVAILABLE_SHARES = float(os.environ.get("PS_MIN_SHARES", "100"))
POSITION_SIZE_USD = float(os.environ.get("PS_POSITION_USD", "3.0"))
MAX_POSITIONS = int(os.environ.get("PS_MAX_POSITIONS", "20"))
MAX_TOTAL_EXPOSURE = float(os.environ.get("PS_MAX_EXPOSURE", "100.0"))
TICK_INTERVAL_SECONDS = float(os.environ.get("PS_TICK_SECONDS", "300"))
MIN_MARKET_VOLUME = float(os.environ.get("PS_MIN_VOLUME", "10000"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
STATS_KEY = "signals:presolution_scalp:stats"
HISTORY_KEY = "signals:presolution_scalp:history"


@dataclass
class PresolutionPosition:
    condition_id: str
    market_question: str
    token_id: str
    side: str
    entry_price: float
    shares: float
    cost_basis: float
    resolution_time: datetime
    entered_at: float
    outcome: str | None = None
    pnl: float | None = None
    resolved_at: float | None = None


@dataclass
class ScalpStats:
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    total_wagered: float = 0.0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_bets if self.total_bets > 0 else 0.0


class PresolutionScalpStrategy(BaseStrategy):
    name = "presolution_scalp"
    description = "Cheap-side scalps near resolution"

    def __init__(self, client, settings, scanner, orderbook, pnl_tracker) -> None:
        super().__init__(client, settings, scanner, orderbook, pnl_tracker)
        self._tick_interval = TICK_INTERVAL_SECONDS
        self._presolution_positions: dict[str, PresolutionPosition] = {}
        self._active_condition_ids: set[str] = set()
        self._llm_cache: dict[str, bool] = {}
        self._stats = ScalpStats()
        self._registry = None
        self._bankroll = float(os.environ.get("COPYTRADE_BANKROLL", "1000"))
        self._redis = None
        try:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        except Exception:
            self._redis = None

    def set_position_registry(self, registry: Any) -> None:
        self._registry = registry

    def set_bankroll(self, bankroll: float) -> None:
        self._bankroll = float(bankroll)

    @property
    def _available_bankroll(self) -> float:
        return self._bankroll

    def _passes_safety_checks(self) -> bool:
        if len(self._presolution_positions) >= MAX_POSITIONS:
            logger.warning("presolution_scalp.max_positions_reached count=%s", len(self._presolution_positions))
            return False
        total_exposure = sum(p.cost_basis for p in self._presolution_positions.values())
        if total_exposure + POSITION_SIZE_USD > MAX_TOTAL_EXPOSURE:
            logger.warning("presolution_scalp.exposure_cap total=%.2f", total_exposure)
            return False
        if self._available_bankroll < POSITION_SIZE_USD * 2:
            logger.warning("presolution_scalp.low_bankroll bankroll=%.2f", self._available_bankroll)
            return False
        return True

    async def on_tick(self) -> None:
        await self._check_resolutions()
        now_utc = datetime.now(timezone.utc)
        markets = await self._scan_presolution_window()
        logger.info("presolution_scalp.scan_complete candidates=%s", len(markets))
        for m in markets:
            await self._evaluate_market(m, now_utc)

    async def _scan_presolution_window(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"active": "true", "closed": "false", "limit": 300},
                )
                if r.status_code != 200:
                    return []
                markets = r.json()
        except Exception as exc:
            logger.warning("presolution_scalp.gamma_error: %s", str(exc)[:120])
            return []

        now = datetime.now(timezone.utc)
        for m in markets:
            if not isinstance(m, dict):
                continue
            cid = str(m.get("conditionId") or "")
            if cid in self._active_condition_ids:
                continue
            vol = float(m.get("volume") or m.get("volumeNum") or 0)
            if vol < MIN_MARKET_VOLUME:
                continue
            end_iso = m.get("endDateIso") or m.get("end_date_iso")
            if not end_iso:
                continue
            try:
                end_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            minutes = (end_dt - now).total_seconds() / 60.0
            if 60 <= minutes <= 180:
                out.append(m)
        return out

    async def _evaluate_market(self, market: dict[str, Any], now_utc: datetime) -> None:
        cheap = await self._find_cheap_side(market)
        if not cheap:
            return
        token_id, price, side = cheap
        cid = str(market.get("conditionId") or "")
        if self._registry and self._registry.is_claimed(token_id):
            return
        if not self._passes_safety_checks():
            return
        ok = await self._validate_with_llm(market, side, price)
        if not ok:
            logger.info("presolution_scalp.llm_rejected %s", (market.get("question") or "")[:60])
            return
        await self._enter_position(market, token_id, price, side)

    async def _find_cheap_side(self, market: dict[str, Any]) -> tuple[str, float, str] | None:
        clobs = market.get("clobTokenIds")
        if isinstance(clobs, str):
            try:
                clobs = json.loads(clobs)
            except json.JSONDecodeError:
                clobs = []
        if not isinstance(clobs, list) or len(clobs) < 2:
            return None
        yes_tid, no_tid = str(clobs[0]), str(clobs[1])
        try:
            y_mid = await self._client.get_midpoint(yes_tid)
            n_mid = await self._client.get_midpoint(no_tid)
        except Exception:
            return None
        cheap_tid = ""
        cheap_price = 0.0
        side = ""
        if y_mid <= MAX_ENTRY_PRICE and y_mid <= n_mid:
            cheap_tid, cheap_price, side = yes_tid, y_mid, "YES"
        elif n_mid <= MAX_ENTRY_PRICE and n_mid <= y_mid:
            cheap_tid, cheap_price, side = no_tid, n_mid, "NO"
        else:
            return None
        try:
            book = await self._client.get_orderbook(cheap_tid)
            asks = book.get("asks") or []
            avail = sum(float(a.get("size", 0)) for a in asks[:5])
        except Exception:
            avail = 0.0
        if avail < MIN_AVAILABLE_SHARES:
            return None
        return cheap_tid, cheap_price, side

    async def _validate_with_llm(self, market: dict[str, Any], cheap_side: str, price: float) -> bool:
        cid = str(market.get("conditionId") or "")
        if cid in self._llm_cache:
            return self._llm_cache[cid]
        q = market.get("question") or ""
        prompt = (
            f"Market: {q}\nCheap side {cheap_side} at {price:.3f}. "
            "Is the opposite outcome virtually certain (>90%)? "
            'Reply JSON {{"approve": true}} or {{"approve": false}} only.'
        )
        try:
            result = await llm_complete(
                prompt=prompt,
                complexity="medium",
                max_tokens=512,
                temperature=0.2,
            )
            text = result.get("content", result.get("text", ""))
            approve = _parse_approve_from_llm_text(text)
        except Exception as exc:
            logger.warning("presolution_scalp.llm_validate_skip: %s", str(exc)[:100])
            approve = False  # REJECT when LLM fails
        self._llm_cache[cid] = approve
        return approve

    async def _enter_position(self, market: dict[str, Any], token_id: str, price: float, side: str) -> None:
        shares = POSITION_SIZE_USD / max(price, 0.01)
        end_iso = market.get("endDateIso") or market.get("end_date_iso") or ""
        try:
            res_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
            if res_dt.tzinfo is None:
                res_dt = res_dt.replace(tzinfo=timezone.utc)
        except Exception:
            res_dt = datetime.now(timezone.utc)
        cid = str(market.get("conditionId") or "")
        pos = PresolutionPosition(
            condition_id=cid,
            market_question=market.get("question") or "",
            token_id=token_id,
            side=side,
            entry_price=price,
            shares=shares,
            cost_basis=POSITION_SIZE_USD,
            resolution_time=res_dt,
            entered_at=time.time(),
        )
        payload = {
            "strategy": self.name,
            "condition_id": cid,
            "token_id": token_id,
            "side": side,
            "price": price,
            "shares": shares,
            "cost": POSITION_SIZE_USD,
            "question": pos.market_question[:120],
        }
        if self._redis:
            try:
                self._redis.publish("signals:presolution_scalp", json.dumps(payload, default=str))
            except Exception:
                pass

        # All order placement goes through the guarded execution path.
        # _place_market_order handles dry_run, sandbox limits, and recording.
        order: OpenOrder | None = await self._place_market_order(
            token_id=token_id,
            market=pos.market_question,
            price=price,
            size=shares,
            side=SIDE_BUY,
            order_type=ORDER_TYPE_GTC,
        )
        if order is None:
            logger.warning("presolution_scalp.order_blocked_or_failed market=%s", pos.market_question[:60])
            return

        self._presolution_positions[cid] = pos
        self._active_condition_ids.add(cid)
        if self._registry:
            await self._registry.claim(token_id, self.name, price, shares, market_question=pos.market_question)
        logger.info(
            "presolution_scalp.entered%s %s",
            "_paper" if self._settings.dry_run else "",
            pos.market_question[:60],
        )

    async def _check_resolutions(self) -> None:
        for cid, pos in list(self._presolution_positions.items()):
            try:
                m = await self._client.get_market(cid)
            except Exception:
                continue
            if not m.get("closed"):
                continue
            won = False
            try:
                raw = m.get("outcomePrices")
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if isinstance(raw, list) and len(raw) >= 2:
                    y = float(raw[0])
                    n = float(raw[1])
                    if y > 0.99:
                        winning = "YES"
                    elif n > 0.99:
                        winning = "NO"
                    else:
                        winning = ""
                    won = bool(winning) and pos.side.upper() == winning
            except Exception:
                win_raw = str(m.get("winningOutcome") or m.get("winning_outcome") or "")
                won = pos.side.upper() in win_raw.upper()
            if won:
                pnl = pos.shares * (1.0 - pos.entry_price)
                pos.outcome = "WIN"
            else:
                pnl = -pos.cost_basis
                pos.outcome = "LOSS"
            pos.pnl = pnl
            pos.resolved_at = time.time()
            self._record_resolution(pos)
            del self._presolution_positions[cid]
            self._active_condition_ids.discard(cid)
            if self._registry:
                await self._registry.release(pos.token_id, exit_price=1.0 if won else 0.0)
            logger.info(
                "presolution_scalp.resolved market=%s outcome=%s pnl=%.2f",
                pos.market_question[:60],
                pos.outcome,
                pnl,
            )

    def _record_resolution(self, pos: PresolutionPosition) -> None:
        self._stats.total_bets += 1
        self._stats.total_wagered += pos.cost_basis
        if pos.outcome == "WIN":
            self._stats.wins += 1
        else:
            self._stats.losses += 1
        self._stats.total_pnl += float(pos.pnl or 0)
        if not self._redis:
            return
        try:
            self._redis.set(STATS_KEY, json.dumps(asdict(self._stats), default=str))
            self._redis.lpush(HISTORY_KEY, json.dumps(asdict(pos), default=str))
            self._redis.ltrim(HISTORY_KEY, 0, 499)
        except Exception:
            pass

PresolutionScalp = PresolutionScalpStrategy
