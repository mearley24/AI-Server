"""Priority-wallet 30-day rolling performance in Redis (Auto-8).

Hash per address: wallet:rolling:{address}
Fields: wr_30d, pl_30d, wins_30d, losses_30d, updated_ts, demoted, promo_streak, last_promo_eval_date
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PRIORITY_WALLET_ADDRESSES: tuple[str, ...] = (
    "0xde9f7f4e77a1595623ceb58e469f776257ccd43c",
    "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11",
)

_PRIORITY_SET = {a.lower() for a in PRIORITY_WALLET_ADDRESSES}

REDIS_URL_DEFAULT = "redis://172.18.0.100:6379"


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", REDIS_URL_DEFAULT).strip()


def _client():
    try:
        import redis
    except ImportError:
        return None
    url = _redis_url()
    if not url:
        return None
    try:
        return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
    except Exception as exc:
        logger.warning("wallet_rolling_redis_connect_failed: %s", exc)
        return None


def rolling_key(address: str) -> str:
    return f"wallet:rolling:{address.lower()}"


def is_priority_wallet_demoted(address: str) -> bool:
    """True if this priority wallet is demoted (must pass normal quality tiers)."""
    if address.lower() not in _PRIORITY_SET:
        return False
    r = _client()
    if r is None:
        return False
    try:
        return r.hget(rolling_key(address), "demoted") == "1"
    except Exception as exc:
        logger.debug("is_priority_wallet_demoted error: %s", exc)
        return False


def apply_rolling_policy(address: str, stats: dict) -> None:
    """Update Redis hash and demote/promote priority wallets from 30d stats."""
    addr = address.lower()
    if addr not in _PRIORITY_SET:
        return

    r = _client()
    if r is None:
        return

    wr = float(stats.get("wr", 0.0))
    pl = float(stats.get("pl", 0.0))
    wins = int(stats.get("wins", 0))
    losses = int(stats.get("losses", 0))
    total = int(stats.get("total_closed", 0))
    key = rolling_key(address)
    min_trades = int(os.environ.get("WALLET_ROLLING_MIN_TRADES", "5"))

    try:
        r.hset(
            key,
            mapping={
                "wr_30d": f"{wr:.6f}",
                "pl_30d": f"{pl:.4f}",
                "wins_30d": str(wins),
                "losses_30d": str(losses),
                "total_30d": str(total),
                "updated_ts": str(time.time()),
            },
        )

        was_demoted = r.hget(key, "demoted") == "1"

        if total >= min_trades and wr < 0.60:
            r.hset(key, mapping={"demoted": "1", "promo_streak": "0"})
            if not was_demoted:
                logger.warning(
                    "priority_wallet_demoted_30d_wr: addr=%s wr=%.3f trades=%d",
                    addr[:12],
                    wr,
                    total,
                )

        demoted = r.hget(key, "demoted") == "1"

        if demoted:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            last_day = r.hget(key, "last_promo_eval_date") or ""
            if last_day == today:
                return

            streak = int(r.hget(key, "promo_streak") or "0")
            if total >= min_trades and wr >= 0.65:
                streak += 1
            else:
                streak = 0

            r.hset(
                key,
                mapping={
                    "promo_streak": str(streak),
                    "last_promo_eval_date": today,
                },
            )

            if streak >= 14:
                r.hset(key, mapping={"demoted": "0", "promo_streak": "0"})
                logger.info(
                    "priority_wallet_repromoted: addr=%s after 14d wr>=0.65 streak",
                    addr[:12],
                )
    except Exception as exc:
        logger.warning("apply_rolling_policy error: %s", exc)
