"""
Trading learning — daily summary from trades.csv, weekly JSON, Redis publish.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("openclaw.trade_learner")


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/app/data"))


def _polymarket_dir() -> Path:
    return _data_dir() / "polymarket"


def _trades_path() -> Path:
    return _polymarket_dir() / "trades.csv"


def _category_for_market(market: str) -> str:
    m = (market or "").lower()
    if any(
        k in m
        for k in (
            "temperature",
            "°f",
            "weather",
            "rain",
            "snow",
            "hurricane",
            "storm",
            "degrees",
        )
    ):
        return "weather"
    if any(k in m for k in ("nfl", "nba", "mlb", "nhl", "vs ", " vs ", "championship", "tournament", "super bowl")):
        return "sports"
    if any(k in m for k in ("bitcoin", "btc", "eth", "ethereum", "crypto", "solana")):
        return "crypto"
    if any(k in m for k in ("trump", "biden", "election", "senate", "house", "president")):
        return "politics"
    return "other"


def _city_hint(market: str) -> str:
    m = market or ""
    for city in ("New York", "Seoul", "London", "Miami", "Chicago", "Denver", "Los Angeles", "Austin"):
        if city.lower() in m.lower():
            return city
    return "unknown"


def _parse_ts(row: dict) -> datetime | None:
    raw = (row.get("timestamp") or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _load_rows() -> list[dict[str, Any]]:
    path = _trades_path()
    if not path.is_file():
        logger.info("trade_learner: no trades file at %s", path)
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(dict(row))
    return rows


def _filter_window(rows: list[dict], start: datetime, end: datetime) -> list[dict]:
    out = []
    for row in rows:
        t = _parse_ts(row)
        if t is None:
            continue
        if start <= t.replace(tzinfo=t.tzinfo or timezone.utc) <= end:
            out.append(row)
    return out


def _stats_for_rows(rows: list[dict]) -> dict[str, Any]:
    by_cat: dict[str, list[float]] = defaultdict(list)
    by_wallet: dict[str, list[float]] = defaultdict(list)
    by_city: dict[str, list[float]] = defaultdict(list)
    by_hour: dict[int, list[float]] = defaultdict(list)
    by_entry: dict[str, list[float]] = defaultdict(list)

    wins = losses = 0
    pnls: list[float] = []
    best = (-1e9, "")
    worst = (1e9, "")

    # Sort by time for hold approximation (same market consecutive buy/sell)
    indexed = []
    for row in rows:
        t = _parse_ts(row)
        if t:
            indexed.append((t, row))
    indexed.sort(key=lambda x: x[0])

    for _, row in indexed:
        market = row.get("market") or ""
        cat = _category_for_market(market)
        try:
            pnl = float(row.get("pnl") or 0)
        except Exception:
            pnl = 0.0
        strat = (row.get("strategy") or "").lower()
        wallet = "copytrade" if "copy" in strat else (strat or "unknown")

        pnls.append(pnl)
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        by_cat[cat].append(pnl)
        by_wallet[wallet].append(pnl)
        by_city[_city_hint(market)].append(pnl)

        ts = _parse_ts(row)
        if ts:
            by_hour[ts.astimezone(timezone.utc).hour].append(pnl)

        try:
            price = float(row.get("price") or 0)
        except Exception:
            price = 0.0
        if price < 0.25:
            bucket = "0-0.25"
        elif price < 0.5:
            bucket = "0.25-0.5"
        elif price < 0.75:
            bucket = "0.5-0.75"
        else:
            bucket = "0.75-1"
        by_entry[bucket].append(pnl)

        if pnl > best[0]:
            best = (pnl, market[:80])
        if pnl < worst[0]:
            worst = (pnl, market[:80])

    def agg(name: str, xs: list[float]) -> dict[str, Any]:
        if not xs:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0}
        w = sum(1 for x in xs if x > 0)
        l = sum(1 for x in xs if x < 0)
        tot = sum(xs)
        return {
            "total_trades": len(xs),
            "wins": w,
            "losses": l,
            "win_rate": round(100.0 * w / max(1, w + l), 1),
            "total_pnl": round(tot, 4),
            "avg_pnl": round(tot / len(xs), 4),
        }

    out_cat = {k: agg(k, v) for k, v in by_cat.items()}
    out_wallet = {k: agg(k, v) for k, v in by_wallet.items()}
    out_city = {k: agg(k, v) for k, v in by_city.items() if k != "unknown"}
    out_hour = {str(k): agg(str(k), v) for k, v in sorted(by_hour.items())}
    out_entry = {k: agg(k, v) for k, v in by_entry.items()}

    total_trades = len(rows)
    total_pnl = round(sum(pnls), 4) if pnls else 0.0

    best_cat = max(out_cat.items(), key=lambda kv: kv[1]["total_pnl"])[0] if out_cat else "n/a"
    worst_cat = min(out_cat.items(), key=lambda kv: kv[1]["total_pnl"])[0] if out_cat else "n/a"

    recommendations: list[str] = []
    for c, s in sorted(out_cat.items(), key=lambda kv: kv[1]["total_pnl"], reverse=True):
        if s["total_trades"] >= 3 and s["win_rate"] >= 55 and s["total_pnl"] > 0:
            recommendations.append(f"Increase {c} allocation — {s['win_rate']:.0f}% WR, ${s['total_pnl']:.2f} P/L")
        if s["total_trades"] >= 5 and s["total_pnl"] < -5:
            recommendations.append(f"Review {c} — negative P/L (${s['total_pnl']:.2f}) over {s['total_trades']} trades")
    for w, s in out_wallet.items():
        if s["total_trades"] >= 8 and s["win_rate"] < 45:
            recommendations.append(f"Wallet/strategy {w} — {s['win_rate']:.0f}% WR, consider tightening filters")

    return {
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "wins": wins,
        "losses": losses,
        "by_category": out_cat,
        "by_wallet": out_wallet,
        "by_city": out_city,
        "by_hour_utc": out_hour,
        "by_entry_price": out_entry,
        "best_trade": {"pnl": best[0], "market": best[1]},
        "worst_trade": {"pnl": worst[0], "market": worst[1]},
        "best_category": best_cat,
        "worst_category": worst_cat,
        "recommendations": recommendations[:12],
        "hold_time_note": "Hold time requires matched open/close ids — not inferred in v1",
    }


def generate_trading_summary(redis_url: str | None = None) -> str:
    """Read trades, write weekly_learning.json, optional Redis publish, return briefing text."""
    rows = _load_rows()
    now = datetime.now(timezone.utc)
    week_end = now
    week_start = now - timedelta(days=7)
    prev_end = week_start
    prev_start = prev_end - timedelta(days=7)

    this_week = _filter_window(rows, week_start, week_end)
    last_week = _filter_window(rows, prev_start, prev_end)

    s_this = _stats_for_rows(this_week)
    s_last = _stats_for_rows(last_week)

    report: dict[str, Any] = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "period": f"{week_start.date().isoformat()} to {week_end.date().isoformat()}",
        "summary": {
            "total_trades": s_this["total_trades"],
            "total_pnl": s_this["total_pnl"],
            "best_category": s_this["best_category"],
            "worst_category": s_this["worst_category"],
        },
        "week_over_week": {
            "pnl_delta": round(s_this["total_pnl"] - s_last["total_pnl"], 4),
            "trades_delta": s_this["total_trades"] - s_last["total_trades"],
        },
        "by_category": s_this["by_category"],
        "by_wallet": s_this["by_wallet"],
        "by_city": s_this["by_city"],
        "recommendations": s_this["recommendations"],
        "patterns": {
            "best_entry_bucket": max(
                s_this["by_entry_price"].items(), key=lambda kv: kv[1].get("total_pnl", 0)
            )[0]
            if s_this["by_entry_price"]
            else None,
            "best_hour_utc": max(s_this["by_hour_utc"].items(), key=lambda kv: kv[1].get("total_pnl", 0))[0]
            if s_this["by_hour_utc"]
            else None,
        },
    }

    out_dir = _polymarket_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "weekly_learning.json"
    try:
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("trade_learner: could not write %s: %s", out_path, e)

    rurl = redis_url or os.environ.get("REDIS_URL", "")
    if rurl:
        try:
            import event_bus

            event_bus.publish_and_log(
                rurl,
                "events:trading",
                {"type": "weekly_learning", "data": report},
            )
        except Exception as e:
            logger.debug("trade_learner redis: %s", e)

    lines = [
        f"Rolling 7d: {s_this['total_trades']} trades, P/L ${s_this['total_pnl']:.2f} "
        f"(best: {s_this['best_category']}, worst: {s_this['worst_category']}).",
        f"WoW: ΔP/L ${report['week_over_week']['pnl_delta']:.2f}, Δtrades {report['week_over_week']['trades_delta']:+d}.",
    ]
    for rec in s_this["recommendations"][:5]:
        lines.append(f"  - {rec}")
    if not rows:
        lines = ["No trades.csv yet — learning report will populate as trades are logged."]
    return "\n".join(lines)


def run_weekly_deep_analysis(redis_url: str | None = None) -> dict[str, Any]:
    """Sunday extended pass — same artifact, flagged in Redis payload."""
    text = generate_trading_summary(redis_url=redis_url)
    rurl = redis_url or os.environ.get("REDIS_URL", "")
    if rurl:
        try:
            import event_bus

            event_bus.publish_and_log(
                rurl,
                "events:trading",
                {"type": "weekly_learning_deep", "data": {"summary_text": text}},
            )
        except Exception as e:
            logger.debug("weekly_deep redis: %s", e)
    return {"ok": True, "summary_lines": text}
