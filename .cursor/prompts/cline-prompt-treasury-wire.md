---
description: Wire the existing Treasury system into the polymarket-bot main loop
---

# Treasury Integration — Wire Profit Reinvestment into the Trading Loop

## Context

The file `openclaw/treasury.py` (444 lines) contains a complete `TreasuryManager` class with:
- Profit allocation (split between reinvestment and operating reserve)
- Bankroll scaling (auto-scale position sizes based on trailing weekly P&L)
- Monthly P&L tracking (trading + business revenue - expenses)
- Alert system (low reserve, low runway, flywheel active, bankroll growth)
- Weekly financial report (Sunday 8am UTC via iMessage)

**None of this is wired into the running system.** The polymarket-bot has no import or reference to treasury. This prompt connects them.

The openclaw directory is already volume-mounted into the polymarket-bot container at `/app/openclaw`, so `from openclaw.treasury import TreasuryManager` works.

## Instructions

### Step 1: Initialize TreasuryManager in polymarket-bot lifespan

In `polymarket-bot/src/main.py`, inside the `lifespan()` function:

1. **After** the `strategy_manager` is started (around line 585), add treasury initialization:

```python
# ── Treasury system — profit reinvestment + bankroll scaling ──────────
treasury_manager = None
try:
    from openclaw.treasury import TreasuryManager
    treasury_manager = TreasuryManager()
    await treasury_manager.update_state()
    deps.treasury_manager = treasury_manager
    log.info("treasury_manager_initialized")
except Exception as exc:
    log.warning("treasury_init_failed", error=str(exc)[:200])
```

2. **Start a treasury loop task** right after the initialization:

```python
# Treasury periodic loop — update state, evaluate alerts, check bankroll scaling
async def _treasury_loop():
    """Run treasury state update, alerts, bankroll scaling, and weekly report every 15 minutes."""
    await asyncio.sleep(120)  # wait 2 min after startup
    while True:
        try:
            if treasury_manager:
                state = await treasury_manager.update_state()
                await treasury_manager.evaluate_alerts(state)
                decision = await treasury_manager.evaluate_bankroll_scaling()
                if decision.action != "hold":
                    log.info(
                        "treasury_bankroll_scaled",
                        action=decision.action,
                        new_pct=decision.new_max_position_pct,
                        reason=decision.reason,
                    )
                report = await treasury_manager.maybe_publish_weekly_report()
                if report:
                    log.info("treasury_weekly_report_sent")
        except Exception as exc:
            log.warning("treasury_loop_error", error=str(exc)[:200])
        await asyncio.sleep(900)  # every 15 minutes

if treasury_manager:
    asyncio.create_task(_treasury_loop())
    log.info("treasury_loop_started", interval_sec=900)
```

3. **In the shutdown section** of lifespan (the `finally:` block or after `yield`), add:

```python
if treasury_manager:
    await treasury_manager.close()
```

### Step 2: Feed trade P&L into Treasury

In `polymarket-bot/strategies/strategy_manager.py`, in the `record_close()` method:

1. After the existing P&L ledger update (after `self._pnl[strategy].record_close(trade)`), add treasury P&L recording:

```python
# Feed realized P&L into Treasury for profit allocation
try:
    import redis as redis_sync
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url and pnl != 0:
        rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=2)
        rc.publish("treasury:trade_pnl", json.dumps({
            "strategy": strategy,
            "pnl": round(pnl, 4),
            "token_id": token_id,
            "market": market_question[:60] if market_question else "",
            "timestamp": time.time(),
        }))
        rc.close()
except Exception:
    pass
```

2. In `polymarket-bot/src/main.py`, add a Redis subscriber in the treasury loop that processes these events. OR simpler approach — have the treasury loop read the PnL tracker directly. The simpler approach:

In the `_treasury_loop` function, after `update_state()`, add this to feed cumulative daily P&L:

```python
# Feed daily realized P&L from PnL tracker into treasury
try:
    if pnl_tracker and hasattr(pnl_tracker, 'daily_pnl'):
        daily = pnl_tracker.daily_pnl()
        if daily != 0:
            await treasury_manager.record_trading_pnl(daily)
except Exception:
    pass
```

**IMPORTANT**: The `record_trading_pnl` method is cumulative (it adds to monthly totals), so you need to track what has already been recorded. Add a simple delta tracker:

```python
_last_treasury_pnl = 0.0  # track cumulative to only send deltas

# Inside the loop:
try:
    if pnl_tracker:
        current_total = sum(p.total_pnl for p in (deps.strategy_manager._pnl.values() if deps.strategy_manager else []))
        delta = current_total - _last_treasury_pnl
        if abs(delta) > 0.01:
            await treasury_manager.record_trading_pnl(delta)
            _last_treasury_pnl = current_total
except Exception:
    pass
```

### Step 3: Add Treasury API endpoint

In `polymarket-bot/api/routes.py`, add a treasury status endpoint:

```python
@router.get("/treasury")
async def get_treasury():
    """Current treasury state — balances, runway, monthly P&L."""
    if not hasattr(deps, 'treasury_manager') or deps.treasury_manager is None:
        return {"error": "Treasury not initialized"}
    try:
        state = await deps.treasury_manager.get_current_state()
        from dataclasses import asdict
        return asdict(state)
    except Exception as exc:
        return {"error": str(exc)}

@router.get("/treasury/monthly")
async def get_treasury_monthly():
    """Monthly financial breakdown."""
    if not hasattr(deps, 'treasury_manager') or deps.treasury_manager is None:
        return {"error": "Treasury not initialized"}
    try:
        monthly = await deps.treasury_manager._get_monthly_hash()
        return monthly
    except Exception as exc:
        return {"error": str(exc)}
```

### Step 4: Wire bankroll scaling into position sizing

The `BankrollScaler` writes `treasury:max_position_pct` to Redis. The copytrade strategy should read this value.

In `polymarket-bot/strategies/polymarket_copytrade.py`, find where position size is calculated (look for `kelly` or `position_size` or `bankroll`). Add a check:

```python
# Check if treasury has set a dynamic max position percentage
try:
    import redis as redis_sync
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        rc = redis_sync.from_url(redis_url, decode_responses=True, socket_timeout=1)
        treasury_max_pct = rc.get("treasury:max_position_pct")
        rc.close()
        if treasury_max_pct:
            max_position = float(treasury_max_pct) * bankroll
            position_size = min(position_size, max_position)
except Exception:
    pass
```

Find the right spot in the copytrade code where `position_size` is finalized, just before the order is placed. This caps any single position at the treasury-approved percentage.

### Step 5: Add env vars to docker-compose.yml

In the `polymarket-bot` service environment section, add:

```yaml
- TREASURY_REINVEST_PCT=${TREASURY_REINVEST_PCT:-0.50}
```

This controls the profit split: 50% reinvested to bankroll, 50% to operating reserve (until reserve hits target of 2x monthly burn).

### Step 6: Wire weekly P&L into Treasury

At the end of each week (or when the treasury loop detects a new week), record the weekly aggregate. In the `_treasury_loop`:

```python
# Record weekly P&L for bankroll scaling decisions (Sunday rollover)
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
_last_weekly_day = getattr(_treasury_loop, '_last_weekly_day', -1)
if now.weekday() == 6 and _last_weekly_day != now.day:
    _treasury_loop._last_weekly_day = now.day
    try:
        weekly_pnl = current_total  # use the running total delta for the week
        await treasury_manager.record_weekly_pnl(weekly_pnl)
        log.info("treasury_weekly_pnl_recorded", pnl=round(weekly_pnl, 2))
    except Exception:
        pass
```

### Step 7: Add deps attribute

In `polymarket-bot/api/routes.py`, in the `deps` class/namespace, add:

```python
treasury_manager = None
```

### Verification

After all changes:

1. `cd polymarket-bot && python -c "from openclaw.treasury import TreasuryManager; print('OK')"` — must print OK
2. `grep -n "treasury" src/main.py` — should show initialization, loop, and shutdown
3. `grep -n "treasury" api/routes.py` — should show the two endpoints
4. The bot should start cleanly with treasury logging: `treasury_manager_initialized` and `treasury_loop_started`

### What This Enables

- Every trade close feeds P&L into the treasury
- Treasury auto-splits profits: 50% reinvested, 50% to reserve (until reserve is healthy)
- Bankroll scaling: 3 winning weeks = scale up position sizes, 2 losing weeks = scale down
- Low reserve alerts via iMessage
- Weekly financial report every Sunday morning
- `/treasury` API endpoint for monitoring
- Position sizes capped by treasury-approved maximum percentage

Commit message: `feat: wire treasury into trading loop — profit reinvestment, bankroll scaling, weekly reports`
