# Cline Prompt Z4 — Live Trading Dashboard + X-Intel Strategy Loop

## Context
The Cortex dashboard (port 8102) shows "unavailable" for Wallet, Positions, and P&L because `position_syncer.py` only publishes to Redis once at startup. There is no periodic sync loop. The bot is actively trading (100 open positions worth $465, 2500+ trades executed) but the dashboard cannot see any of it.

Additionally, x-intake intelligence signals are routed to `ideas.txt` but never actually influence live trading decisions. The intelligence pipeline is write-only — no strategy reads it in real time.

This prompt fixes both problems.

## Files to modify:
- `polymarket-bot/src/main.py` — add periodic position sync background task
- `polymarket-bot/src/position_syncer.py` — add Polymarket data-API direct fetch as fallback
- `cortex/dashboard.py` — add Polymarket data-API direct fallback for wallet/positions when Redis and bot are both stale
- `polymarket-bot/strategies/x_intel_processor.py` — upgrade from ideas.txt logger to live strategy influencer

---

## Part 1: Periodic Position Sync Loop

### 1A. Add background sync task in `polymarket-bot/src/main.py`

Find the startup section where `sync_positions` is called once (around line 520-534). After the one-time startup sync, add a background task that runs every 5 minutes:

```python
    # Periodic position sync — publish fresh data to Redis every 5 minutes
    async def _position_sync_loop():
        """Keep Redis portfolio snapshot fresh for the dashboard."""
        from src.position_syncer import sync_positions as _sync_fn, persist_snapshot_redis
        await asyncio.sleep(60)  # wait 1 min after startup before first periodic sync
        while True:
            try:
                snap = await _sync_fn(client)
                persist_snapshot_redis(snap)
                log.info(
                    "periodic_position_sync",
                    positions=len(snap.positions),
                    total_value=round(snap.total_position_value, 2),
                    usdc=round(snap.usdc_balance, 2),
                )
            except Exception as exc:
                log.warning("periodic_position_sync_error", error=str(exc)[:200])
            await asyncio.sleep(300)  # 5 minutes

    asyncio.create_task(_position_sync_loop())
    log.info("position_sync_loop_started", interval_sec=300)
```

Place this right after the one-time startup sync block (after line ~534) and before the StrategyManager startup.

### 1B. Add TTL to Redis snapshot in `position_syncer.py`

In `persist_snapshot_redis()`, add a TTL to the snapshot key so stale data expires rather than showing forever:

Find:
```python
        r.set("portfolio:snapshot", payload)
```

Change to:
```python
        r.set("portfolio:snapshot", payload, ex=600)  # expire after 10 min (2x sync interval)
```

This way if the sync loop dies, the dashboard shows "unavailable" instead of hours-old numbers.

## Part 2: Dashboard Direct-API Fallback

### 2A. Add Polymarket data-API fallback in `cortex/dashboard.py`

The wallet endpoint currently tries Redis then the bot's `/status`. When both fail, it returns "unavailable". Add a third fallback that queries the public Polymarket data API directly.

Find the `api_wallet()` function. After the `_safe_get(TRADING_BOT_URL/status)` fallback block (around line 383), add before `return empty`:

```python
        # Third fallback — query Polymarket data API directly (public, no auth)
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        positions_data = await _safe_get(
            f"https://data-api.polymarket.com/positions?user={poly_wallet}&sizeThreshold=0",
            timeout=10.0,
        )
        if positions_data and isinstance(positions_data, list):
            try:
                total_value = sum(float(p.get("currentValue", 0)) for p in positions_data)
                total_initial = sum(float(p.get("initialValue", 0) or 0) for p in positions_data)
                active_value = sum(
                    float(p.get("currentValue", 0))
                    for p in positions_data
                    if 0.05 < float(p.get("curPrice", p.get("currentPrice", 0)) or 0) < 0.95
                )
                return {
                    "usdc_balance": 0.0,  # can't get USDC from data API
                    "position_value": round(total_value, 2),
                    "active_value": round(active_value, 2),
                    "redeemable_value": 0.0,
                    "redeemable_count": 0,
                    "lost_count": 0,
                    "dust_count": sum(1 for p in positions_data if float(p.get("currentValue", 0)) < 0.50),
                    "daily_pnl": 0.0,
                    "weekly_pnl": 0.0,
                    "source": "polymarket_data_api",
                    "position_count": len(positions_data),
                    "unrealized_pnl": round(total_value - total_initial, 2),
                }
            except (TypeError, ValueError):
                pass
```

Also add the same `POLY_WALLET_ADDRESS` env var to the `cortex` service block in `docker-compose.yml`:
```yaml
    environment:
      - POLY_WALLET_ADDRESS=0xa791E3090312981A1E18ed93238e480a03E7C0d2
```

### 2B. Add similar fallback for `/api/positions`

In `api_positions()`, after the `_safe_get(TRADING_BOT_URL/positions)` fallback, add:

```python
        # Third fallback — Polymarket data API
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        positions_data = await _safe_get(
            f"https://data-api.polymarket.com/positions?user={poly_wallet}&sizeThreshold=0",
            timeout=10.0,
        )
        if positions_data and isinstance(positions_data, list):
            return [
                {
                    "title": p.get("title", "?"),
                    "outcome": p.get("outcome", "?"),
                    "size": float(p.get("size", 0)),
                    "currentValue": float(p.get("currentValue", 0)),
                    "curPrice": float(p.get("curPrice", p.get("currentPrice", 0)) or 0),
                    "source": "polymarket_data_api",
                }
                for p in sorted(positions_data, key=lambda x: float(x.get("currentValue", 0)), reverse=True)
                if float(p.get("currentValue", 0)) > 0.01
            ]
```

### 2C. Add P&L endpoint using Polymarket activity API

Add a new endpoint in `cortex/dashboard.py` (or update the existing `/api/pnl-series` endpoint) that queries the public activity API:

```python
    @app.get("/api/pnl-summary")
    async def api_pnl_summary():
        """Realized P&L from Polymarket activity API (public, no auth needed)."""
        poly_wallet = os.environ.get("POLY_WALLET_ADDRESS", "0xa791E3090312981A1E18ed93238e480a03E7C0d2")
        try:
            all_activity = []
            for offset in range(0, 5001, 500):
                data = await _safe_get(
                    f"https://data-api.polymarket.com/activity?user={poly_wallet}&limit=500&offset={offset}",
                    timeout=15.0,
                )
                if not data or not isinstance(data, list) or len(data) == 0:
                    break
                all_activity.extend(data)
                if len(data) < 500:
                    break

            total_spent = sum(float(a.get("usdcSize", 0)) for a in all_activity if a.get("type") in ("TRADE", "BUY"))
            total_redeemed = sum(float(a.get("usdcSize", 0)) for a in all_activity if a.get("type") == "REDEEM")
            trade_count = sum(1 for a in all_activity if a.get("type") in ("TRADE", "BUY"))
            redeem_count = sum(1 for a in all_activity if a.get("type") == "REDEEM")

            return {
                "total_spent": round(total_spent, 2),
                "total_redeemed": round(total_redeemed, 2),
                "realized_pnl": round(total_redeemed - total_spent, 2),
                "trade_count": trade_count,
                "redeem_count": redeem_count,
                "activity_count": len(all_activity),
            }
        except Exception as exc:
            return {"error": str(exc)[:200]}
```

### 2D. Update the dashboard HTML P&L tile

In `cortex/static/index.html`, find the P&L rendering section. Update it to fetch from `/api/pnl-summary` and display realized P&L:

Find the P&L render function (the one that updates the `pnl` div). Replace its fetch logic so it calls `/api/pnl-summary` instead of (or in addition to) `/api/pnl-series`. Display:
- **TODAY**: realized P&L from today's redeems minus today's trades (filter by timestamp)
- **ALL-TIME**: total realized P&L

The P&L values should use `pnl-positive` class (green) when positive and `pnl-negative` class (red) when negative.

## Part 3: X-Intel Live Strategy Influence

### 3A. Upgrade `x_intel_processor.py`

Replace the current `_append_ideas()` approach with a direct influence on the copytrade strategy's decision-making. The processor should:

1. Keep a rolling window of high-relevance signals (last 2 hours)
2. Expose a `get_active_signals()` method that strategies can query
3. Publish actionable signals to Redis `polymarket:x_strategy_boost` channel

Replace the entire file with:

```python
"""X Intel Processor — converts X intake signals into live trading influence.

Maintains a rolling window of high-relevance X intel signals that strategies
can query to boost/suppress confidence on specific markets.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

IDEAS_FILE = Path(__file__).parent.parent / "ideas.txt"
SIGNAL_WINDOW_SEC = 7200  # 2 hours
MIN_RELEVANCE = 50  # minimum relevance to influence trading


class XIntelProcessor:
    """Processes X intake signals into live trading intelligence."""

    def __init__(self, market_scanner=None):
        self.market_scanner = market_scanner
        self._last_processed: dict[str, float] = {}
        self._active_signals: list[dict[str, Any]] = []  # rolling window
        self._market_boosts: dict[str, dict[str, Any]] = {}  # keyword -> boost info

    async def on_intel_signal(self, signal) -> None:
        """Handle an intel signal from the signal bus."""
        data = signal.data
        source = data.get("source", "")

        if source != "x_intake":
            return

        url = data.get("url", "")
        now = time.time()

        # Dedup
        if url in self._last_processed and (now - self._last_processed[url]) < 300:
            return
        self._last_processed[url] = now
        self._last_processed = {k: v for k, v in self._last_processed.items() if v > now - 3600}

        relevance = data.get("relevance", 0)
        signals = data.get("signals", [])
        market_keywords = data.get("market_keywords", [])
        alpha_insights = data.get("alpha_insights", [])
        risk_warnings = data.get("risk_warnings", [])
        author = data.get("author", "unknown")
        summary = data.get("summary", "")

        logger.info(
            "x_intel_processing",
            author=author,
            relevance=relevance,
            signal_count=len(signals),
            keyword_count=len(market_keywords),
        )

        # Store in rolling window
        entry = {
            "timestamp": now,
            "author": author,
            "url": url,
            "relevance": relevance,
            "signals": signals,
            "keywords": market_keywords,
            "alpha": alpha_insights,
            "risk": risk_warnings,
            "summary": summary[:500],
        }
        self._active_signals.append(entry)

        # Prune old signals
        cutoff = now - SIGNAL_WINDOW_SEC
        self._active_signals = [s for s in self._active_signals if s["timestamp"] > cutoff]

        # Process trading signals into market boosts
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            confidence = sig.get("confidence", 0)
            if confidence < 0.4:
                continue

            keyword = sig.get("market_keyword", "").lower()
            direction = sig.get("direction", "")
            reasoning = sig.get("reasoning", "")

            if keyword:
                self._market_boosts[keyword] = {
                    "direction": direction,
                    "confidence": confidence,
                    "author": author,
                    "reasoning": reasoning[:200],
                    "timestamp": now,
                    "relevance": relevance,
                }

        # Prune old boosts
        self._market_boosts = {
            k: v for k, v in self._market_boosts.items()
            if v["timestamp"] > cutoff
        }

        # Publish boost to Redis for strategies that subscribe
        if signals and relevance >= MIN_RELEVANCE:
            self._publish_boost(entry)

        # Still write to ideas.txt for audit trail
        ideas = []
        for sig in signals:
            if not isinstance(sig, dict) or sig.get("confidence", 0) < 0.4:
                continue
            ideas.append(
                f"[X-INTEL] @{author} | Market: {sig.get('market_keyword', '')} | "
                f"Direction: {sig.get('direction', '')} | Confidence: {sig.get('confidence', 0):.0%} | "
                f"Reasoning: {sig.get('reasoning', '')[:120]}"
            )
        for insight in alpha_insights:
            ideas.append(f"[X-ALPHA] @{author} | {insight[:200]}")
        for warning in risk_warnings:
            ideas.append(f"[X-RISK] @{author} | {warning[:200]}")

        if ideas:
            self._append_ideas(ideas)
            logger.info("x_intel_ideas_logged", count=len(ideas), author=author)

    def get_active_signals(self) -> list[dict[str, Any]]:
        """Return signals from the last 2 hours for strategy queries."""
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC
        return [s for s in self._active_signals if s["timestamp"] > cutoff]

    def get_market_boost(self, market_title: str) -> dict[str, Any] | None:
        """Check if X intel suggests a boost/suppress for a market keyword.

        Returns the boost info if any keyword matches the market title,
        or None if no active intel applies.
        """
        title_lower = market_title.lower()
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC

        for keyword, boost in self._market_boosts.items():
            if boost["timestamp"] < cutoff:
                continue
            if keyword in title_lower:
                return boost
        return None

    def get_signal_summary(self) -> dict[str, Any]:
        """Dashboard-friendly summary of current intel state."""
        now = time.time()
        cutoff = now - SIGNAL_WINDOW_SEC
        active = [s for s in self._active_signals if s["timestamp"] > cutoff]
        return {
            "active_signals": len(active),
            "market_boosts": len(self._market_boosts),
            "top_authors": list({s["author"] for s in active})[:5],
            "boost_keywords": list(self._market_boosts.keys())[:10],
        }

    def _publish_boost(self, entry: dict[str, Any]) -> None:
        """Publish high-relevance signal to Redis for live strategies."""
        try:
            import redis
            url = os.environ.get("REDIS_URL", "redis://redis:6379").strip()
            r = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            r.publish("polymarket:x_strategy_boost", json.dumps({
                "author": entry["author"],
                "relevance": entry["relevance"],
                "keywords": entry["keywords"],
                "signals": entry["signals"],
                "summary": entry["summary"],
                "timestamp": entry["timestamp"],
            }, default=str))
        except Exception as exc:
            logger.warning("x_boost_publish_failed", error=str(exc)[:100])

    def _append_ideas(self, ideas: list[str]) -> None:
        """Append ideas to ideas.txt with timestamp."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"\n--- X Intel [{timestamp}] ---"]
        lines.extend(ideas)
        lines.append("")
        try:
            with open(IDEAS_FILE, "a") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.warning("ideas_write_failed", error=str(exc)[:100])
```

### 3B. Wire x_intel into main.py deps

In `main.py`, after the `XIntelProcessor` is created (around line 492-497), store it in deps so strategies can access it:

Find:
```python
        x_intel = XIntelProcessor()
        signal_bus.subscribe(SignalType.MARKET_DATA, x_intel.on_intel_signal)
```

Add after:
```python
        deps.x_intel = x_intel
```

### 3C. Add x-intel status to dashboard

In `cortex/dashboard.py`, add a new endpoint:

```python
    @app.get("/api/trading/intel")
    async def api_trading_intel():
        """X-intel signal summary from the bot."""
        data = await _safe_get(f"{TRADING_BOT_URL}/x-intel/status", timeout=5.0)
        if data:
            return data
        return {"active_signals": 0, "market_boosts": 0, "status": "unavailable"}
```

And in `polymarket-bot/api/routes.py`, add:

```python
@router.get("/x-intel/status")
async def x_intel_status() -> dict[str, Any]:
    """Get current X intelligence signal state."""
    x_intel = getattr(deps, "x_intel", None)
    if not x_intel:
        return {"status": "not_initialized"}
    return x_intel.get_signal_summary()


@router.get("/x-intel/signals")
async def x_intel_signals() -> dict[str, Any]:
    """Get active X intel signals (last 2 hours)."""
    x_intel = getattr(deps, "x_intel", None)
    if not x_intel:
        return {"signals": [], "count": 0}
    signals = x_intel.get_active_signals()
    return {"signals": signals, "count": len(signals)}
```

## Part 4: Verify and Commit

```zsh
python3 -c "import ast; ast.parse(open('cortex/dashboard.py').read()); print('dashboard OK')"
python3 -c "import ast; ast.parse(open('polymarket-bot/src/main.py').read()); print('main OK')"
python3 -c "import ast; ast.parse(open('polymarket-bot/src/position_syncer.py').read()); print('syncer OK')"
python3 -c "import ast; ast.parse(open('polymarket-bot/strategies/x_intel_processor.py').read()); print('intel OK')"
python3 -c "import ast; ast.parse(open('polymarket-bot/api/routes.py').read()); print('routes OK')"
```

All must print OK. Then:

```zsh
git add -A
git commit -m "feat: live trading dashboard + periodic sync + x-intel strategy loop"
git push origin main
```

## Post-deploy on Bob

After pulling and rebuilding:
```zsh
docker compose up -d --build polymarket-bot cortex
```

Verify:
- Dashboard Wallet tile should show real position values (not "unavailable")
- Dashboard Positions tile should list top positions by value
- Dashboard P&L tile should show realized P&L numbers
- `/api/trading/intel` should return signal summary

## DO NOT:
- Change any trading parameters, thresholds, or bankroll settings
- Modify the copytrade, weather, or sports arb strategy logic
- Touch the redeemer code
- Change any environment variable values
- Add new pip dependencies (use only stdlib + what's already installed)
