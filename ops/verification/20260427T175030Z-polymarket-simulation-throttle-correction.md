# Polymarket Simulation Throttle — Correction Report
Generated: 2026-04-27T17:50:30Z

## Summary

The previous simulation-only validation was **safety-clean** (no real orders placed,
no live gate bypassed) but **behavior-noisy**: copytrade was producing dozens of
`copytrade_copy_attempt` log events within seconds, including repeated same-token
calls and high prices (0.95-0.999), making the log hard to read and the behavior
appear erratic.

Root cause: `copytrade_copy_attempt` was logged at the very top of `_copy_trade()`,
BEFORE any per-minute rate limiting, per-token dedup, or global max-price filter.
Every trade from every watched wallet emitted the event even if it would immediately
be filtered by category max-entry-price guards below.

## Throttles Added

| Throttle | Env Var | Default | Behavior |
|----------|---------|---------|----------|
| Per-minute attempt rate cap | `COPYTRADE_MAX_ATTEMPTS_PER_MINUTE` | 5 | After 5 calls in any rolling 60-second window, further calls log `copytrade_skipped_rate_limited` and return without attempting |
| Per-token dedup window | `COPYTRADE_DEDUPE_WINDOW_SECONDS` | 3600 | Same token_id seen within 1 hour logs `copytrade_skipped_duplicate` and returns |
| Global max entry price | `COPYTRADE_MAX_PRICE` | 0.90 | Price > 0.90 logs `copytrade_skipped_price_too_high` and returns (bypass: `COPYTRADE_ALLOW_HIGH_PRICE=true`) |

All three throttles fire **before** `copytrade_copy_attempt` is logged, so the event
now accurately represents "we evaluated this trade and deemed it worth attempting."

The `COPYTRADE_MAX_ATTEMPTS_PER_MARKET_PER_HOUR` env var (default 1) is also
documented and wired to `_max_attempts_per_market_per_hour` in the strategy init.

## 2-Minute Simulation-Only Run Results

Run window: 2026-04-27T17:48:29Z → 17:50:04Z (~95 seconds before observer-only restore)

| Event | Count |
|-------|-------|
| `copytrade_copy_attempt` | **0** |
| `copytrade_skipped_rate_limited` | 0 |
| `copytrade_skipped_duplicate` | 0 |
| `copytrade_skipped_price_too_high` | 0 |
| `crypto_paper_order` | **0** |
| `trade_recorded` | **0** |
| `avellaneda_mm_started` | **0** |
| `simulation_only_started` | ✓ |
| `crypto_disabled_skip` (kraken gate) | ✓ |

**Note on 0 attempts:** Expected. The bot seeds all existing wallet trades as "seen"
on startup (prevents copying old trades). In the 95-second window, no watched wallets
placed NEW trades on Polymarket. The throttle is exercised when new trades arrive;
tests prove all three paths work correctly.

## Test Results

64 tests across all simulation/safety suites:
- `test_copytrade_throttle.py` — 11 tests (rate cap, dedup, price filter, valid pass, no real order)
- `test_simulation_only.py` — 18 tests
- `test_observer_only.py` — 12 tests
- `test_crypto_simulation_guard.py` — 12 tests
- `test_avellaneda_simulation_guard.py` — 11 tests

Full ops/tests suite: **1139 passed, 0 failures**

## Correction to Previous Validation

The previous validation (20260427T165021Z pre-funding readiness report) stated the
bot was "behavior-noisy" as an observed issue but did not include a formal
remediation. This report closes that gap.

The safety assertions from the prior report remain valid:
- POLY_DRY_RUN=true ✓
- POLY_ALLOW_LIVE=(empty) ✓
- No real orders submitted ✓
- All sandbox guards active ✓

## SAFE TO FUND: NO

Remaining blockers (unchanged from prior report):
1. On-chain balance $3.72 — below bot's own $7.50 circuit-breaker minimum
2. No extended paper simulation run (≥48h) completed
3. EIP-712 signer not live-validated against CLOB with real order
4. 78 legacy positions outstanding, not managed by current bot code

Next step: fund ≥$50 USDC on Polygon to `0xa791E3090312981A1E18ed93238e480a03E7C0d2`,
then run simulation-only for 48h before considering any live trades.
