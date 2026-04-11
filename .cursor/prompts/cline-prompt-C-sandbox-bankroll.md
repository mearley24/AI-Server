# Cline Prompt C: ExecutionSandbox Enforcement + Bankroll Timing

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push at the end.

## 1. Wire ExecutionSandbox into copytrade trade execution

`ExecutionSandbox` exists at `polymarket-bot/src/security/sandbox.py` and is instantiated in `src/main.py` (line ~178), stored on `deps.sandbox`. But `polymarket_copytrade.py` bypasses it entirely — orders go straight to the CLOB client.

### Step 1: Accept sandbox in copytrade constructor
In `polymarket-bot/strategies/polymarket_copytrade.py`, find the `__init__` method. Add `sandbox=None` parameter and store it:
```python
self._sandbox = sandbox
```

### Step 2: Find where sandbox is NOT passed
In `src/main.py`, search for where `CopytradeStrategy` (or whatever the copytrade class is named) is instantiated. Pass `sandbox=sandbox` to it.

### Step 3: Gate trade execution through sandbox
Find all places in `polymarket_copytrade.py` where `self._clob_client.create_and_post_order(...)` is called (search for `create_and_post_order`). Before each call, add a sandbox check:

```python
if self._sandbox:
    allowed, reason = self._sandbox.check_order(
        size_usd=size_usd,
        side="BUY",
    )
    if not allowed:
        logger.warning("sandbox_blocked_trade", reason=reason, market=market_question[:40], size=size_usd)
        return
```

Look at the actual `ExecutionSandbox.check_order()` method signature in `sandbox.py` first — adapt the arguments to match what it expects. If it doesn't have a `check_order` method, look for whatever validation method it exposes (maybe `validate`, `pre_trade_check`, etc.).

If the sandbox has a `record_trade()` or `post_trade()` method, call it AFTER successful order execution too.

## 2. Fix bankroll refresh timing

In `polymarket_copytrade.py`, the bankroll refresh happens mid-tick (around line 626):
```python
if now - self._last_bankroll_refresh >= self._bankroll_refresh_interval:
```

This can cause the bankroll to change between when a trade is evaluated and when it's executed. Fix:

### Move refresh to start of tick only
Find the `on_tick` method (the main loop entry point). Ensure bankroll refresh happens at the very START before any trade decisions:
```python
async def on_tick(self):
    # Refresh bankroll FIRST, before any trade decisions
    await self._maybe_refresh_bankroll()
    # ... rest of tick logic
```

Create `_maybe_refresh_bankroll()` as an extracted method if the bankroll refresh code isn't already isolated. The key rule: bankroll should NOT change during trade evaluation.

Add a flag to prevent mid-tick refreshes:
```python
self._tick_in_progress = False
```

In the refresh logic, skip if a tick is in progress:
```python
if self._tick_in_progress:
    return  # Never refresh bankroll mid-tick
```

Set `self._tick_in_progress = True` at the start of `on_tick()` and `False` at the end (in a finally block).

## Verify and commit
```bash
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py && echo "copytrade OK"
python3 -m py_compile polymarket-bot/src/main.py && echo "main OK"
grep "sandbox" polymarket-bot/strategies/polymarket_copytrade.py | head -5
echo "Sandbox should be referenced"
grep "_tick_in_progress\|_maybe_refresh_bankroll" polymarket-bot/strategies/polymarket_copytrade.py | head -5
echo "Bankroll timing guard should be present"
git add -A && git commit -m "fix: wire ExecutionSandbox into copytrade, fix bankroll refresh timing"
git push origin main
```
