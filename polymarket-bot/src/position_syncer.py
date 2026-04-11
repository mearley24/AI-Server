"""On-chain position sync — single source of truth for portfolio (Auto-21)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from strategies.kelly_sizing import fetch_onchain_bankroll

logger = structlog.get_logger(__name__)
_log = logging.getLogger(__name__)

REDIS_URL_DEFAULT = os.environ.get("REDIS_URL", "redis://redis:6379")
SNAPSHOT_INTERVAL_SEC = float(os.environ.get("PORTFOLIO_SYNC_INTERVAL_SEC", "300"))
HISTORY_MAX = 1000


@dataclass
class Position:
    """One held outcome position (normalized from CLOB / Data API)."""

    token_id: str
    condition_id: str
    market_title: str
    outcome_side: str
    shares: float
    avg_entry_price: float
    current_price: float
    market_value_usd: float
    unrealized_pnl: float
    market_status: str = ""
    source: str = "clob"


@dataclass
class PositionSnapshot:
    timestamp: float
    usdc_balance: float
    positions: list[Position]
    total_position_value: float
    total_portfolio_value: float
    unrealized_pnl: float
    raw_count: int = 0
    # Categorized breakdown — prevents stale/misleading aggregates
    active_value: float = 0.0       # Only tradeable positions (0.05 < price < 0.95)
    redeemable_value: float = 0.0   # Resolved wins not yet redeemed (free money)
    redeemable_count: int = 0
    lost_cost: float = 0.0          # Sunk cost from resolved losses
    lost_count: int = 0
    dust_count: int = 0             # Positions < $0.50 value

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "usdc_balance": round(self.usdc_balance, 2),
            "total_position_value": round(self.total_position_value, 2),
            "total_portfolio_value": round(self.total_portfolio_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "positions": [asdict(p) for p in self.positions],
            "position_count": len(self.positions),
            "active_value": round(self.active_value, 2),
            "redeemable_value": round(self.redeemable_value, 2),
            "redeemable_count": self.redeemable_count,
            "lost_cost": round(self.lost_cost, 2),
            "lost_count": self.lost_count,
            "dust_count": self.dust_count,
        }


def format_portfolio_line(snapshot: PositionSnapshot | None) -> str:
    """iMessage / briefing one-liner with categorized breakdown."""
    if snapshot is None:
        return "Portfolio: (sync pending)"
    a = snapshot.usdc_balance
    active = snapshot.active_value
    redeem = snapshot.redeemable_value
    u = snapshot.unrealized_pnl
    sign = "+" if u >= 0 else ""
    total_real = a + active + redeem
    parts = [f"Liquid: ${a:,.0f}", f"Active: ${active:,.0f}"]
    if redeem > 0:
        parts.append(f"Redeemable: ${redeem:,.0f} ({snapshot.redeemable_count})")
    parts.append(f"Total: ${total_real:,.0f}")
    parts.append(f"P/L: {sign}${u:,.2f}")
    return " | ".join(parts)


def _parse_clob_row(row: dict[str, Any]) -> dict[str, Any]:
    tid = row.get("asset") or row.get("token_id") or row.get("tokenId") or ""
    if isinstance(tid, dict):
        tid = tid.get("token_id") or tid.get("tokenId") or ""
    tid = str(tid).strip()
    cid = str(row.get("conditionId") or row.get("condition_id") or "").strip()
    title = str(row.get("title") or row.get("question") or row.get("market") or "")
    outcome = str(row.get("outcome") or row.get("outcomeName") or "")
    size = float(row.get("size", 0) or 0)
    avg = float(row.get("avgPrice", row.get("avg_price", 0)) or 0)
    cur = float(row.get("curPrice", row.get("currentPrice", row.get("price", 0))) or 0)
    cv = float(row.get("currentValue", row.get("current_value", 0)) or 0)
    upnl = float(row.get("unrealizedPnl", row.get("unrealized_pnl", 0)) or 0)
    status = str(row.get("marketStatus", row.get("status", "")) or "")
    if not tid:
        return {}
    if cv <= 0 and size > 0 and cur > 0:
        cv = size * cur
    side = "YES" if outcome else ""
    return {
        "token_id": tid,
        "condition_id": cid,
        "title": title,
        "outcome": side or outcome or "?",
        "shares": size,
        "avg": avg,
        "cur": cur,
        "cv": cv,
        "upnl": upnl,
        "status": status,
    }


async def _enrich_price(client: Any, token_id: str, cur: float) -> float:
    if cur > 0:
        return cur
    try:
        return await client.get_midpoint(token_id)
    except Exception:
        return 0.0


async def sync_positions(client: Any) -> PositionSnapshot:
    """Fetch CLOB positions + on-chain USDC; enrich prices; build snapshot."""
    wallet = getattr(client, "wallet_address", "") or ""
    raw_list: list[dict[str, Any]] = []
    try:
        raw_list = await client.get_positions()
    except Exception as exc:
        logger.warning("position_sync_clob_failed", error=str(exc)[:120])
    if not isinstance(raw_list, list):
        raw_list = []

    usdc = 0.0
    if wallet:
        try:
            usdc = await fetch_onchain_bankroll(wallet)
        except Exception:
            usdc = 0.0
    if usdc <= 0:
        try:
            bal = await client.get_balance()
            if isinstance(bal, dict):
                usdc = float(bal.get("balance", bal.get("available", 0)) or 0)
        except Exception:
            pass

    positions: list[Position] = []
    total_pv = 0.0
    total_upnl = 0.0

    # Categorized accumulators
    active_value = 0.0
    redeemable_value = 0.0
    redeemable_count = 0
    lost_cost = 0.0
    lost_count = 0
    dust_count = 0

    for row in raw_list:
        p = _parse_clob_row(row if isinstance(row, dict) else {})
        if not p:
            continue
        cur = await _enrich_price(client, p["token_id"], p["cur"])
        cv = p["cv"]
        if cv <= 0 and p["shares"] > 0 and cur > 0:
            cv = p["shares"] * cur
        upnl = p["upnl"]
        if upnl == 0 and p["avg"] > 0 and p["shares"] > 0 and cur > 0:
            upnl = (cur - p["avg"]) * p["shares"]

        # Categorize: active vs resolved-win vs resolved-loss vs dust
        shares = p["shares"]
        if cv < 0.50:
            dust_count += 1
            status_tag = "dust"
        elif cur >= 0.95:
            # Resolved win — redeemable for ~$1/share
            redeemable_value += shares  # payout = shares * $1
            redeemable_count += 1
            status_tag = "redeemable"
        elif cur <= 0.05:
            # Resolved loss — worth ~$0, track cost for P&L
            lost_cost += shares * p["avg"]
            lost_count += 1
            status_tag = "lost"
        else:
            # Active — tradeable position
            active_value += cv
            status_tag = "active"

        positions.append(
            Position(
                token_id=p["token_id"],
                condition_id=p["condition_id"],
                market_title=p["title"][:500],
                outcome_side=str(p["outcome"])[:32],
                shares=round(shares, 6),
                avg_entry_price=round(p["avg"], 6),
                current_price=round(cur, 6),
                market_value_usd=round(cv, 4),
                unrealized_pnl=round(upnl, 4),
                market_status=status_tag,
            )
        )
        total_pv += cv
        total_upnl += upnl

    ts = time.time()
    snap = PositionSnapshot(
        timestamp=ts,
        usdc_balance=usdc,
        positions=positions,
        total_position_value=round(total_pv, 2),
        total_portfolio_value=round(usdc + total_pv, 2),
        unrealized_pnl=round(total_upnl, 2),
        raw_count=len(raw_list),
        active_value=round(active_value, 2),
        redeemable_value=round(redeemable_value, 2),
        redeemable_count=redeemable_count,
        lost_cost=round(lost_cost, 2),
        lost_count=lost_count,
        dust_count=dust_count,
    )

    by_strategy: dict[str, int] = {}
    for p in positions:
        src = p.source or "unknown"
        by_strategy[src] = by_strategy.get(src, 0) + 1
    logger.info(
        "position_sync_summary",
        total=len(positions),
        total_value=round(total_pv, 2),
        usdc=round(usdc, 2),
        by_strategy=by_strategy,
    )

    return snap


def _redis():
    try:
        import redis
    except ImportError:
        return None
    url = os.environ.get("REDIS_URL", REDIS_URL_DEFAULT).strip()
    if not url:
        return None
    try:
        return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
    except Exception:
        return None


def persist_snapshot_redis(snap: PositionSnapshot) -> None:
    r = _redis()
    if not r:
        return
    try:
        payload = json.dumps(snap.to_api_dict(), default=str)
        r.set("portfolio:snapshot", payload)
        r.lpush("portfolio:history", payload)
        r.ltrim("portfolio:history", 0, HISTORY_MAX - 1)
        for p in snap.positions:
            key = p.condition_id or p.token_id
            if key:
                r.hset("portfolio:positions", key, json.dumps(asdict(p), default=str))
        chain_keys = {p.condition_id or p.token_id for p in snap.positions if (p.condition_id or p.token_id)}
        if chain_keys:
            existing = r.hkeys("portfolio:positions")
            for ek in existing or []:
                if ek not in chain_keys:
                    r.hdel("portfolio:positions", ek)
    except Exception as exc:
        logger.warning("portfolio_redis_persist_error", error=str(exc)[:80])


def append_snapshot_json_file(snap: PositionSnapshot, data_dir: str) -> None:
    """Append one JSON line; rotate to dated file at UTC midnight."""
    base = Path(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = base / f"portfolio_snapshots_{day}.jsonl"
    try:
        with path.open("a") as f:
            f.write(json.dumps(snap.to_api_dict(), default=str) + "\n")
    except OSError as exc:
        _log.warning("portfolio_snapshots_file_error: %s", exc)


def load_position_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_position_state(
    path: Path,
    *,
    active_condition_ids: list[str],
    active_event_slugs: list[str],
    pnl_open_positions: dict[str, Any],
    available_bankroll: float,
    total_portfolio_value: float,
) -> None:
    data = {
        "saved_at": time.time(),
        "active_condition_ids": active_condition_ids,
        "active_event_slugs": active_event_slugs,
        "pnl_open_positions": pnl_open_positions,
        "available_bankroll": available_bankroll,
        "total_portfolio_value": total_portfolio_value,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def reconcile_pnl_tracker_open(pnl: Any, snap: PositionSnapshot) -> None:
    """Merge PnLTracker open positions with on-chain snapshot."""
    chain_tokens = {p.token_id for p in snap.positions if p.token_id}
    internal = pnl.open_positions
    internal_ids = set(internal.keys())

    for p in snap.positions:
        if not p.token_id:
            continue
        if p.token_id not in internal_ids:
            internal[p.token_id] = {
                "token_id": p.token_id,
                "market": p.market_title,
                "strategy": "manual_or_pre_restart",
                "entry_price": p.avg_entry_price if p.avg_entry_price > 0 else -1.0,
                "size": p.shares,
                "side": "LONG",
                "realized_pnl": 0.0,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "source": "position_sync",
            }
            logger.info(
                "position_discovered",
                token_id=p.token_id[:20],
                market=p.market_title[:50],
            )
        else:
            row = internal[p.token_id]
            row["current_price"] = p.current_price
            if p.avg_entry_price > 0:
                row["entry_price"] = p.avg_entry_price
            row["size"] = p.shares
            row["unrealized_pnl"] = p.unrealized_pnl

    vanished = internal_ids - chain_tokens
    for tid in vanished:
        logger.info("position_vanished", token_id=tid[:20])
        del internal[tid]


def check_portfolio_alerts(
    snap: PositionSnapshot,
    prev_total: float | None,
    *,
    notify_fn: Any = None,
) -> float:
    """Drift and floor alerts; returns snap.total_portfolio_value for next call."""
    total = snap.total_portfolio_value
    avail = snap.usdc_balance

    def _notify(title: str, body: str) -> None:
        if notify_fn:
            try:
                notify_fn(title, body)
            except Exception:
                pass

    if prev_total is not None and prev_total > 50:
        chg = abs(total - prev_total) / prev_total
        if chg > 0.10:
            msg = f"Before ${prev_total:,.2f} → after ${total:,.2f} ({chg*100:.1f}%)"
            _notify("Portfolio moved >10% in 5m", msg)
            r = _redis()
            if r:
                try:
                    r.lpush(
                        "portfolio:alerts",
                        json.dumps(
                            {"ts": time.time(), "type": "pct_move", "body": msg},
                            default=str,
                        ),
                    )
                    r.ltrim("portfolio:alerts", 0, 99)
                except Exception:
                    pass

    if total < 500:
        _notify("Portfolio below $500", f"Total portfolio ${total:,.2f}")

    if avail < 50:
        _notify("Low USDC (trading capital)", f"Available ${avail:,.2f}")

    return total
