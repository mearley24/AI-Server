# API-1: Self-Improving Trading Bot — Wire Up RBI + CVD

## The Problem

The RBI (Research-Backtest-Implement) pipeline and CVD (Cumulative Volume Delta) detector have both been built but exist in isolation. The RBI pipeline has a shim at `polymarket-bot/rbi_pipeline.py` and a full implementation at `polymarket-bot/strategies/rbi_pipeline.py`, but it is not wired into the main trading loop — the bot never actually calls it on a schedule. The CVD detector at `polymarket-bot/strategies/cvd_detector.py` connects to a WebSocket and produces signals, but those signals are not consumed by any strategy. The `strategy_manager.py` coordinates multiple strategies but may have broken imports after previous Cursor passes. The goal is not to rewrite anything — it is to wire these existing pieces together so they actually run.

## Context Files to Read First

- `polymarket-bot/rbi_pipeline.py` (top-level shim — entry point)
- `polymarket-bot/strategies/rbi_pipeline.py` (full RBI implementation)
- `polymarket-bot/strategies/strategy_manager.py` (multi-strategy coordinator)
- `polymarket-bot/strategies/cvd_detector.py` (WebSocket-based volume signal producer)
- `polymarket-bot/src/main.py` (main trading loop — where the wiring goes)
- `polymarket-bot/strategies/weather_trader.py` (example of a strategy that consumes signals — use as pattern)
- `polymarket-bot/src/client.py` (PolymarketClient — already instantiated in main.py)

## Prompt

Read the existing code first — understand the RBI pipeline implementation, the CVD detector signal format, how strategy_manager coordinates strategies, and how main.py currently runs its async loop. Do not rewrite anything that already works. Wire the existing pieces together.

### 1. Verify Import Health

Before making any changes, do a dry-run import check:

```bash
cd polymarket-bot && python -c "from strategies.rbi_pipeline import RBIPipeline; print('RBI OK')"
cd polymarket-bot && python -c "from strategies.cvd_detector import CVDDetector; print('CVD OK')"
cd polymarket-bot && python -c "from strategies.strategy_manager import StrategyManager; print('SM OK')"
```

- Fix any `ImportError` or `ModuleNotFoundError` you find — missing packages go in `requirements.txt`, missing local imports get corrected at the source
- Do NOT restructure modules to fix imports — fix the import paths or add the missing dependency
- Log every fix you make and why

### 2. Wire RBI Into the Main Trading Loop

In `polymarket-bot/src/main.py`:

- Locate the main async loop (likely a `while True` or `asyncio.gather` block)
- Import `RBIPipeline` from `strategies.rbi_pipeline` (or use the shim at `rbi_pipeline.py` if it is the correct entry point — read both and determine which one main.py should call)
- Add a scheduled task that runs `rbi_pipeline.run_cycle()` (or equivalent method) every 30 minutes
- Use `asyncio` — add it as a background task, not a blocking call:

```python
async def rbi_scheduler(rbi: RBIPipeline):
    while True:
        try:
            await rbi.run_cycle()
        except Exception as e:
            logger.error(f"RBI cycle error: {e}")
        await asyncio.sleep(30 * 60)  # 30 minutes
```

- Initialize `RBIPipeline` with whatever arguments its `__init__` already expects — read the constructor, do not change its signature
- Pass the existing `client` instance if RBI needs it
- Log at startup: `"RBI pipeline scheduled — running every 30 minutes"`

### 3. Verify CVD Detector Connects and Produces Signals

Read `cvd_detector.py` fully:

- Identify what WebSocket endpoint it connects to (likely Polymarket's CLOB WS)
- Identify the signal format it produces (likely a dict with `condition_id`, `cvd_value`, `direction`, `timestamp`)
- Confirm it has a start method and a way to read the latest signal (a queue, a callback, or a shared dict)
- If it has a broken connection (wrong URL, missing auth), fix it using the same credentials already in `src/client.py` or `.env`
- Do not rewrite the detector — only fix connection parameters if broken

### 4. Wire CVD Signals Into StrategyManager

In `strategy_manager.py`:

- Add a `set_cvd_signal(condition_id: str, signal: dict)` method (or use whatever signal-passing mechanism already exists — read the file first)
- Each strategy registered in the manager should be able to call `self.get_cvd_signal(condition_id)` to read the latest CVD value for any market
- The CVD detector should call `strategy_manager.set_cvd_signal(...)` whenever a new signal is produced
- Wire this in `main.py`: start the CVD detector, pass it a reference to strategy_manager (or use a shared Redis key `cvd:signals:{condition_id}` if that is the existing pattern)

In `main.py`:

```python
cvd = CVDDetector(...)
cvd.on_signal(lambda cid, sig: strategy_manager.set_cvd_signal(cid, sig))
asyncio.create_task(cvd.start())
```

Adjust the lambda/callback pattern to match whatever `CVDDetector` already exposes. Do not add a callback if it already uses a queue — use the existing interface.

### 5. Fix Broken Imports in strategy_manager.py

Read `strategy_manager.py` line by line for:

- Imports of files that no longer exist at the expected path
- References to class names that were renamed in previous Cursor passes
- Missing `__init__.py` files in subdirectories

Fix each one. If a referenced file truly does not exist (not just renamed), add a `# TODO: missing dependency` comment and a no-op stub so the file at least imports cleanly. Do not silently swallow ImportErrors — let them surface at startup.

### 6. Integration Test

After wiring, verify the system works end-to-end:

```bash
cd polymarket-bot && timeout 300 python src/main.py 2>&1 | tee /tmp/bot_test.log
```

Check `/tmp/bot_test.log` for:

- `"RBI pipeline scheduled"` — confirms RBI is wired
- Any log line from `rbi_pipeline` showing it evaluated at least one idea from `ideas.txt` (or logged "no pending ideas" — either is valid)
- Any log line from `cvd_detector` showing a WebSocket message received and a signal produced
- No `ImportError`, `AttributeError`, or `KeyError` at startup

If the bot cannot connect to Polymarket (network/API key issue), that is not a wiring bug — note it and stop. The wiring test passes if the modules initialize without errors.

### 7. Redis Signal Keys (Standardize)

Use these Redis keys for CVD signals so all consumers agree on the format:

- `cvd:signal:{condition_id}` — latest CVD signal as JSON: `{"cvd": float, "direction": "buy"|"sell"|"neutral", "strength": float, "timestamp": float}`
- `cvd:history:{condition_id}` — list of last 100 signals (LPUSH + LTRIM)
- `rbi:last_run` — timestamp of last RBI cycle
- `rbi:results` — list of last 10 RBI evaluations with outcome

If CVD detector already writes to Redis, confirm the keys match. If it uses a different key scheme, add a bridge that writes to the standard keys above — do not change the detector itself.
