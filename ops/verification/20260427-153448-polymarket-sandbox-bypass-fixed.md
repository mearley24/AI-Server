# Polymarket Sandbox Bypass Fix — Verification Report
**Date:** 2026-04-27T15:34:48Z  
**Task:** P1 — Route all Polymarket strategies through guarded execution sandbox

---

## Summary

All 4 strategies that previously bypassed the `ExecutionSandbox` have been
refactored to enforce sandbox limits on every order path.

---

## Strategies Fixed

| Strategy | Old path | Fixed path |
|---|---|---|
| `stink_bid` | `_exit_position()` called `client.place_order()` directly | Now calls `_place_market_order()` (sandbox-guarded) |
| `flash_crash` | `_execute_crash_buy()` and `_exit_position()` called `client.place_order()` directly | Both now call `_place_market_order()` |
| `presolution_scalp` | `_enter_position()` called `client.place_order()` directly | Now calls `_place_market_order()` |
| `sports_arb` | `_execute_arb()` called `client.place_order()` directly for both legs | Both legs now sandbox pre-checked before any live order |

---

## Architecture of Fix

### `strategies/base.py` — single guarded execution path

Three additions to `BaseStrategy`:

1. **`_sandbox: ExecutionSandbox | None = None`** — field, starts None
2. **`set_sandbox(sandbox)`** — attach method, called from `main.py`
3. **`_place_market_order(token_id, market, price, size, side, order_type)`** — new helper

Both `_place_limit_order()` (existing) and `_place_market_order()` (new) now:
- Call `sandbox.check_trade(size, price)` before any live order (returns early with None if blocked)
- Call `sandbox.record_trade(notional)` after successful live order
- In dry_run: call `_record_paper_trade()` — no sandbox check needed (no real money at risk)

### `sports_arb` — special dual-leg handling

Because both FOK legs must be placed concurrently, sandbox pre-checks are done
manually and sequentially before the `asyncio.gather()`:
- Leg A sandbox check → fail = abort both
- Leg B sandbox check → fail = abort both
- `asyncio.gather()` with both client.place_order() calls — only reachable after both checks pass
- Both `sandbox.record_trade()` calls after success

### `main.py` — wiring

Added `strategy.set_sandbox(sandbox)` after each of the 4 instantiations:
```python
presolution_scalp.set_sandbox(sandbox)
sports_arb.set_sandbox(sandbox)
flash_crash.set_sandbox(sandbox)
stink_bid.set_sandbox(sandbox)
```

---

## Proof: No Direct Order Paths Remain

**stink_bid.py — zero direct calls:**
```
$ grep "await self._client.place_order" strategies/stink_bid.py
(no output)
```

**flash_crash.py — zero direct calls:**
```
$ grep "await self._client.place_order" strategies/flash_crash.py
(no output)
```

**presolution_scalp.py — zero direct calls:**
```
$ grep "await self._client.place_order" strategies/presolution_scalp.py
(no output)
```

**sports_arb.py — two calls, both inside live-only guarded block:**
```python
# Live: place both orders concurrently (sandbox pre-checks above already passed)
results = await asyncio.gather(
    self._client.place_order(...),  # only reachable after both sandbox checks passed
    self._client.place_order(...),
    ...
)
```
These are only reachable when `not self._settings.dry_run` AND both
`sandbox.check_trade()` calls returned `(True, "ok")`.

---

## Tests Run

### polymarket-bot/tests/test_sandbox_bypass_fixed.py (20 tests)
```
.................….. 20 passed in 0.34s
```

Tests cover:
- `stink_bid`: dry_run no order, sandbox blocked no order, live order + record, limit order sandbox-guarded
- `flash_crash`: dry_run no order, sandbox blocked no position, live order + record + track, exit dry_run, cooldown duplicate protection
- `presolution_scalp`: dry_run no order but position tracked, sandbox blocked no position, live order + record + position, max_single_trade respected
- `sports_arb`: dry_run no order, leg A blocked → neither order, leg B blocked → neither order, live both orders + both recorded, kill switch blocks
- Cross-strategy: all 4 have `set_sandbox()`, signer.py untouched

### ops/tests/test_sandbox_bypass_fixed.py (8 tests, delegates to above)
```
8 passed in 0.73s
```

### ops/tests/test_live_gate.py (9 tests)
```
9 passed in 0.07s
```

### Total: 37 tests passing, 0 failures

---

## Files Changed

| File | Change |
|---|---|
| `polymarket-bot/strategies/base.py` | Added `_sandbox` field, `set_sandbox()`, `_place_market_order()`, sandbox checks in `_place_limit_order()` |
| `polymarket-bot/strategies/stink_bid.py` | `_exit_position()` → `_place_market_order()` |
| `polymarket-bot/strategies/flash_crash.py` | `_execute_crash_buy()` and `_exit_position()` → `_place_market_order()` |
| `polymarket-bot/strategies/presolution_scalp.py` | `_enter_position()` → `_place_market_order()` |
| `polymarket-bot/strategies/sports_arb.py` | `_execute_arb()` manual sandbox pre-checks + record after live success |
| `polymarket-bot/src/main.py` | Added `set_sandbox(sandbox)` for all 4 strategies |
| `polymarket-bot/tests/test_sandbox_bypass_fixed.py` | New: 20 strategy sandbox tests |
| `ops/tests/test_sandbox_bypass_fixed.py` | New: 8 tests (subprocess delegate + source checks) |

**NOT modified:** `polymarket-bot/src/signer.py` ✓

---

## Guardrails Now Enforced Uniformly Across All Strategies

Every order path now checks:
- ✅ Kill switch (sandbox killed)
- ✅ Max single trade notional
- ✅ Daily volume ceiling
- ✅ Order rate limiter (token bucket)
- ✅ dry_run gate (never calls live API in paper mode)
- ✅ Daily loss kill-switch (fires after cumulative losses exceed limit)

---

## Remaining Blockers Before Funding

| # | Blocker | Status |
|---|---|---|
| 1 | **Signer.py EIP-712 bug** (`0x` prefix on token_id) | ❌ Not yet fixed (deliberately deferred) |
| 2 | **Paper trading validation** (48h+ run required) | ❌ Not yet done |

**SAFE TO FUND: NO** — signer bug means live orders fail with every attempt.
Fixing the signer is the next step. Once fixed, run ≥48h paper trading before
any deposit.
