# Polymarket Bot — Capital Safety Audit
**Generated:** 2026-04-27T14:23:48Z  
**Auditor:** Claude Code (read-only — no trades placed, no live mode enabled, no secrets exposed)  
**Bot container:** `polymarket-bot` — Up 2 days (healthy)  
**Wallet:** `0xa791E3090312981A1E18ed93238e480a03E7C0d2`  
**Current mode:** `POLY_DRY_RUN=false` — **LIVE MODE IS ACTIVE**

---

## Executive Summary

The bot has a solid safety architecture (sandbox, kill switch, daily loss limit, exit engine, Kelly sizing) but has **4 blocking issues** that must be resolved before capital is loaded. The most important finding: **the bot is already in LIVE mode and is actively attempting to place real orders every 5 minutes**. A signer bug is currently acting as an accidental brake — when that bug is fixed, orders will flow immediately.

**SAFE TO FUND: NO**

Readiness score: **51 / 100**

---

## Section 1 — Current Live State

### Bot is in LIVE mode with a broken signer

```
POLY_DRY_RUN=false  (confirmed inside container)
dry_run: false      (config.yaml)
```

Strategies actively running: `sports_arb`, `flash_crash`, `stink_bid`, `cvd_arb`, `mean_reversion`, `presolution_scalp`, `liquidity_provider`, `kraken_mm` (8 strategies live).

**Active errors (every 5 minutes, same token IDs):**
```
{"error": "invalid literal for int() with base 10: '0x535a...'", "event": "place_order_error"}
{"error": "invalid literal for int() with base 10: '0x6626...'", "event": "place_order_error"}
{"error": "invalid literal for int() with base 10: '0xe31a...'", "event": "place_order_error"}
```

The `OrderSigner.build_and_sign()` is calling `int(token_id)` on a hex string instead of `int(token_id, 16)`. Every strategy that finds a market to trade hits this error on the first order attempt. The bot recovers (exception caught) and retries on the next scan cycle. **This bug is the only thing currently preventing live orders from being placed.**

### Historical trade record

The PnL CSV loaded on startup shows 477 historical copytrade trades with a net P&L of **-$3.17** (win rate 50%). These represent real past trades. The strategy manager shows 0 trades in this session since the signer broke.

---

## Section 2 — Core Logic

### Entry logic (copytrade — primary active strategy)
- Fetches trades from top-25 scored wallets every 30s
- Wallet qualifying criteria: win_rate ≥ 0.60, min 20 resolved trades
- Kelly sizing: quarter-Kelly against bankroll, hard cap $10/position
- Dedup guards: seen trade IDs, event-level slug dedup, temperature cluster regex
- Daily loss circuit breaker: $30 net loss halts copytrade

### Exit logic (exit_engine.py)
- Stop-loss: category-specific, 35-60% of entry (e.g., sports 35%, weather 60%)
- Deep value entries (<30c): stop-loss widens to 70%, trailing stop disabled
- Trailing stop: activates at +50% gain for non-deep-value entries
- Time-based exit: 6-48h depending on category
- Stale positions: hard exit after 14 days

### Position sizing
- Default copytrade size: $3/trade
- Kelly calculates against on-chain USDC.e balance, falls back to `COPYTRADE_BANKROLL` env var
- Hard cap: $10/position (KellySizer.HARD_CAP_USD)
- Max bankroll %: 5% per trade

### Order execution path (copytrade)
1. Wallet scan detects new trade
2. Dedup checks (seen IDs, event slug, temperature cluster)
3. Daily loss check → halt if exceeded
4. Max positions check → skip if ≥ limit
5. Sandbox.check_trade() → validate size and daily volume
6. If dry_run: paper log only. If live: PolymarketClient.place_order()
7. Sandbox.record_trade() → update daily counters
8. AuditTrail.log_trade_decision()

### API endpoints used
- CLOB: `https://clob.polymarket.com/order`, `/orders`, `/positions`, `/book`, `/price`
- Gamma: `https://gamma-api.polymarket.com/markets`
- WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`

---

## Section 3 — Risk Findings

### CRITICAL (4)

---

#### RISK-1: Signer bug causes active retry loop in live mode
**Severity: CRITICAL**  
**File:** `polymarket-bot/src/signer.py` (suspected line: hex→int conversion)

The `build_and_sign()` method fails with `invalid literal for int() with base 10: '0x...'` on every token ID presented by the scan strategies. This happens every scan cycle (every 5 minutes for presolution_scalp, more frequently for flash_crash/stink_bid). The loop structure is:

```
while True:
    try:
        await strategy.tick()   # finds market → place_order → signer fails
    except Exception:
        pass                    # catches error, sleeps, retries
```

The same token IDs appear in the error log every 5 minutes. This is not exponential backoff — it's a fixed-rate retry loop. No dead-letter queue, no circuit breaker for repeated signer failures on the same token.

**Risk when fixed:** All 8 live strategies will begin placing real orders immediately. No additional confirmation or safety review will be triggered.

**Fix required:**
```python
# In signer.py, wherever token_id is converted to int:
# WRONG:
token_id_int = int(token_id)
# CORRECT:
token_id_int = int(token_id, 16) if token_id.startswith("0x") else int(token_id)
```

---

#### RISK-2: Sandbox.check_trade() NOT called for 4 strategies
**Severity: CRITICAL**  
**Files:** `strategies/stink_bid.py`, `strategies/flash_crash.py`, `strategies/presolution_scalp.py`, `strategies/sports_arb.py`

These strategies use `self._client.place_order()` directly after a `dry_run` check, completely bypassing the ExecutionSandbox. They have NO:
- Single-trade size enforcement
- Daily volume limit enforcement
- Kill switch respect
- Rate-limit enforcement

Only `polymarket_copytrade.py` properly calls `sandbox.check_trade()` before each order.

**Evidence:**
```python
# stink_bid.py (line ~241):
if self._settings.dry_run:
    # paper trade
    return
# Falls through directly to:
await self._client.place_order(token_id, price, size, side)
# No sandbox check anywhere

# presolution_scalp.py (line ~298):
await self._client.place_order(token_id, price, size, side, ORDER_TYPE_GTC)
# No sandbox check
```

**Fix required:** All 4 strategies must call `sandbox.check_trade()` before any live order:
```python
if self._sandbox:
    allowed, reason = await self._sandbox.check_trade(size=size_usd, price=price)
    if not allowed:
        logger.warning("sandbox_blocked", reason=reason)
        return
```

And the sandbox must be passed into each strategy's `__init__()` from `main.py`.

---

#### RISK-3: docker-compose COPYTRADE_MAX_POSITIONS=100 contradicts all documentation
**Severity: CRITICAL**  
**File:** `docker-compose.yml`

```yaml
COPYTRADE_MAX_POSITIONS=${COPYTRADE_MAX_POSITIONS:-100}
```

Every source of documentation says max positions is 30:
- `config.py` default: 30
- `SAFETY_CHECKLIST.md`: 30
- `config.yaml` comment: "Max concurrent copied positions — concentrated, not spray-and-pray"

The docker-compose default overrides config.py at runtime, resulting in 100 max positions. At $3/trade, 100 positions = $300 at risk simultaneously. With `MAX_POSITIONS_PER_CATEGORY=50`, the bot could put $150 into a single category.

**Fix required:**
```yaml
COPYTRADE_MAX_POSITIONS=${COPYTRADE_MAX_POSITIONS:-30}
MAX_POSITIONS_PER_CATEGORY=${MAX_POSITIONS_PER_CATEGORY:-15}
```

---

#### RISK-4: No idempotency key on order placement — timeout = duplicate order risk
**Severity: CRITICAL**  
**File:** `polymarket-bot/src/client.py`

`PolymarketClient.place_order()` has a 30s timeout (`httpx.AsyncClient(timeout=30.0)`). If the network drops AFTER the CLOB server accepted the order but BEFORE the response arrives:
1. The client raises `httpx.TimeoutException`
2. The strategy catches the generic exception and logs `place_order_error`
3. On the next tick, the strategy may try to place the same order again
4. The order was already placed — a duplicate is now live

No idempotency key or order ID pre-generation is used. The CLOB API supports a `clientOrderId` field that could be used here.

**Fix required:**
```python
import uuid
async def place_order(self, token_id, price, size, side, order_type=..., **kwargs):
    client_order_id = kwargs.pop("client_order_id", str(uuid.uuid4()))
    payload = {
        "order": order,
        "signature": signature,
        "orderType": order_type,
        "clientOrderId": client_order_id,  # idempotency key
    }
```

And strategies should cache the `client_order_id` per market position to prevent retry duplicates.

---

### MEDIUM (3)

---

#### RISK-5: Kill switch fires AFTER one extra trade on daily loss
**Severity: MEDIUM**  
**File:** `polymarket-bot/src/security/sandbox.py`

Simulation confirms: the `record_trade()` / `record_pnl()` methods use `asyncio.ensure_future()` to activate the kill switch. This means:

1. Trade 10 at -$3.10 is PLACED (check_trade passes, daily_pnl = -27.90 < $30 limit)
2. `record_trade()` updates daily_pnl to -$31.00
3. `asyncio.ensure_future(_activate_kill_switch(...))` is scheduled but not awaited
4. Before the future runs, trade 11's `check_trade()` may pass if called before the future executes

**Simulation result:** With $30 daily loss limit and 10 × $3.10 trades, all 10 placed before kill switch activated. Kill switch fires asynchronously after trade 10.

**Fix required:**
```python
def record_trade(self, notional: float, pnl: float = 0.0) -> None:
    self._maybe_reset_daily()
    self._daily_volume += abs(notional)
    self._daily_pnl += pnl
    self._trade_count_today += 1
    # Check SYNCHRONOUSLY before returning — don't use ensure_future
    if self._daily_pnl < -self._max_daily_loss and self._kill_switch_enabled:
        self._killed = True  # Set flag synchronously
        self._kill_reason = f"auto: daily_loss_exceeded ({self._daily_pnl:.2f})"
        asyncio.ensure_future(self._activate_kill_switch(self._kill_reason))
```

---

#### RISK-6: Sandbox limits (config.yaml) are sized for a $50K+ account
**Severity: MEDIUM**  
**File:** `polymarket-bot/config.yaml` (security section)

```yaml
security:
  max_single_trade: 10000.0   # $10,000 per trade
  max_daily_volume: 50000.0   # $50,000 daily volume
  max_daily_loss: 2500.0      # $2,500 daily loss before kill switch
```

For a test account with a few hundred dollars, these limits offer zero protection. The bot could lose its entire balance many times over before the global sandbox kill switch fires.

The sandbox config should be account-sized, not formula-sized. For a $500 account:
```yaml
security:
  max_single_trade: 10.0      # $10 max per trade
  max_daily_volume: 100.0     # $100 daily volume
  max_daily_loss: 50.0        # 10% of account per day
```

---

#### RISK-7: Deep value stop-loss is 70% — $7 loss on a $10 position
**Severity: MEDIUM**  
**File:** `polymarket-bot/strategies/exit_engine.py`

For entries below $0.30 (called "deep value"), the stop-loss is widened:
```python
effective_sl_used = max(effective_sl, 0.70) if deep_value_entry else effective_sl
```

This means a position entered at $0.20 will only exit if price falls to $0.06. On a $10 position that's a $7 loss before the exit fires. Combined with the copytrade strategy having up to 100 positions (RISK-3), this creates large loss potential.

**Fix required:** Cap deep_value_sl at 60% maximum:
```python
DEEP_VALUE_SL_CAP = 0.60  # never let deep value blow 60%
effective_sl_used = min(max(effective_sl, 0.70) if deep_value_entry else effective_sl, DEEP_VALUE_SL_CAP)
```

---

### LOW (3)

---

#### RISK-8: Kalshi is in production mode with dry_run=false
**Severity: LOW**  
**File:** `polymarket-bot/config.yaml`

```yaml
kalshi:
  environment: production
  dry_run: false
```

Kalshi strategies (weather, fed/economics) are also live. Not part of this audit's focus but worth noting: if Kalshi credentials are present, the Kalshi strategies can place real contracts.

---

#### RISK-9: sports_arb config.yaml override ($5000/side) contradicts live value
**Severity: LOW**  
**File:** `polymarket-bot/config.yaml`

```yaml
sports_arb:
  max_position_per_side: 5000.0   # $5,000 per side
```

Status endpoint shows the live value is `10.0` — the docker-compose env var `COPYTRADE_MAX_POSITIONS` overrode the yaml. The config.yaml value is wrong and could cause confusion when values are interpreted. Should be cleaned up to match actual intended value.

---

#### RISK-10: Unrealized losses do not trigger daily loss circuit breaker
**Severity: LOW**  
**File:** `polymarket-bot/src/security/sandbox.py`

`record_pnl()` and `record_trade()` only track realized P&L. If 20 positions are all underwater by 40% simultaneously, the daily loss circuit breaker sees $0 in losses (no positions closed yet). The account value could drop by $80 before any circuit breaker fires.

The copytrade strategy's per-position stop-loss (35-60%) provides some protection, but there's no portfolio-level unrealized loss monitor.

---

## Section 4 — DRY_RUN Mode Verification

DRY_RUN mode **EXISTS and is properly implemented** in the copytrade path:

```python
# polymarket_copytrade.py line 2284:
if self._dry_run:
    order_id = f"paper-{position_id}"
    # logs paper trade, NO order placed
    return

# Live path only reached when dry_run=False:
if self._sandbox:
    _allowed, _reason = await self._sandbox.check_trade(...)
order_resp = await self._client.place_order(...)
```

**Gap:** stink_bid, flash_crash, presolution_scalp, sports_arb also have dry_run checks, but they check `self._settings.dry_run` directly without going through the unified `PolymarketPlatformClient.place_order()` adapter (which has its own `is_dry_run` guard). This means if the settings object is wrong at construction time, both checks fail independently. The copytrade path through the platform adapter is safer.

---

## Section 5 — Required Protections Checklist

| Protection | Status | Notes |
|---|---|---|
| `MAX_POSITION_PER_TRADE` | ✅ Exists | Kelly hard cap $10, copytrade_size_usd $3 |
| `MAX_DAILY_LOSS` | ⚠️ Partial | Exists in sandbox ($2500) and copytrade ($30), but fires AFTER last overshoot (RISK-5). Config values too high for small account (RISK-6) |
| `MAX_OPEN_POSITIONS` | ⚠️ Broken | Config says 30, docker-compose defaults to 100 (RISK-3) |
| `COOLDOWN_SECONDS` | ✅ Exists | Copytrade: 30s `_min_trade_gap`. Flash crash: 60s per-token. Others: scan interval |
| `DUPLICATE_ORDER_PREVENTION` | ⚠️ Partial | Copytrade: dedup by trade ID, event slug, temperature cluster. But no idempotency key on network timeout (RISK-4) |
| `API_FAILSAFE` | ⚠️ Partial | Sandbox checks approved endpoints. Timeouts handled by catching exceptions. No circuit breaker for repeated API failures to same endpoint |
| Stop-loss | ✅ Exists | ExitEngine with category-specific SL (35-60%) |
| Kill switch | ✅ Exists | Fires on daily loss exceeded, single trade exceeded, daily volume exceeded |
| Audit trail | ✅ Complete | AuditTrail writes daily JSONL files, 90-day retention |
| Rate limiter | ✅ Exists | Token bucket, 10 orders/min (sandbox config) |

---

## Section 6 — Trade Decision Logging Audit

Every copytrade order goes through `audit_trail.log_trade_decision()`:
- `timestamp` ✅ (`_ts` field auto-added)
- `market` ✅ (market question logged)
- `price` ✅ (price logged)
- `reason` ✅ (strategy + debate_result if >$25)
- `size` ✅ (size_usd logged)
- `outcome` ⚠️ Missing — `fill_status` is logged at entry time but there's no closure log when the position is exited. The audit trail has no "exit" event type.

**Fix required:** Add `audit_trail.log_trade_decision()` call in exit handler with `fill_status="closed"` and final P&L.

For strategies that bypass sandbox (stink_bid, flash_crash, presolution_scalp, sports_arb): **no audit log exists at all** — these strategies do not call AuditTrail.

---

## Section 7 — Simulation Results

### Simulation 1: Losing streak — circuit breaker test
```
Settings: max_daily_loss=$30, size=$3.10/trade
Trade 1: placed, daily_pnl=-3.10   ✓
Trade 2: placed, daily_pnl=-6.20   ✓
...
Trade 10: placed, daily_pnl=-31.00  ← OVERSHOOT (trade went through at -27.90 check)
Kill switch activated: auto:daily_loss_exceeded(-31.00)
```
**Result: Kill switch fires, but 1 extra trade overshoot confirmed (RISK-5)**

### Simulation 2: Rate limiter test
```
Settings: max_orders_per_minute=3
6 rapid orders → 3 allowed, 3 blocked by rate limit ✓
```
**Result: Rate limiter works correctly**

### Simulation 3: Single trade size limit
```
Settings: max_single_trade=$50
$100 trade: BLOCKED, kill_switch fires ✓
$25 trade after: BLOCKED by kill_switch (correct — reset needed)
```
**Result: Single trade limit works, kill switch latches correctly**

### Simulation 4: Daily volume ceiling
```
Settings: max_daily_volume=$25
Trade 1 ($10): allowed, vol=10 ✓
Trade 2 ($10): allowed, vol=20 ✓
Trade 3 ($10): BLOCKED, kill_switch fires ✓
Trade 4 ($10): BLOCKED (kill_switch latched) ✓
```
**Result: Volume ceiling works correctly**

### Simulation 5: Kelly sizing — price spike (no-trade zone)
```
Win rate=0.65, price=$0.90: size=$2.00 (negative EV → min_size) ✓
Win rate=0.65, price=$0.40: size=$10.00 (hits hard cap) ✓
Win rate=0.45, price=$0.40: size=$6.25 (still trades — filtered by min_win_rate guard)
```
**Result: Kelly correctly avoids negative EV at high prices. Hard cap enforced.**

### Simulation 6: Bot does NOT spiral
The bot cannot spiral because:
1. Kill switch latches — once fired, all subsequent `check_trade()` calls return `(False, "kill_switch_active")` until manual revive
2. Volume ceiling prevents volume runaway
3. Kelly max_bankroll_pct=5% prevents size runaway
4. Hard cap $10 prevents single-position blowup

**Result: No spiral risk in copytrade path. Spiral possible in stink_bid/flash_crash/presolution_scalp because they bypass sandbox (RISK-2)**

---

## Section 8 — Required Fixes (Priority Order)

### P0 — Must fix before any live trading

**FIX-1: Fix the signer hex conversion bug** (`signer.py`)  
The bot is in live mode and will immediately start placing orders when fixed. Before fixing, verify all P1/P2 items below are addressed.  
```python
# Find int(token_id) calls in signer.py and replace with:
int(token_id, 16) if isinstance(token_id, str) and token_id.startswith("0x") else int(token_id)
```

**FIX-2: Wire sandbox into stink_bid, flash_crash, presolution_scalp, sports_arb** (`strategies/`)  
Pass `sandbox` parameter through `main.py` initialization for each strategy.
Add `await sandbox.check_trade(size, price)` before each `client.place_order()` call.

**FIX-3: Fix docker-compose COPYTRADE_MAX_POSITIONS default**  
Change `100` → `30`. Change `MAX_POSITIONS_PER_CATEGORY` from `50` → `15`.

**FIX-4: Reduce sandbox security limits to account-appropriate values**  
For initial deployment (assume ≤$500 account):
```yaml
security:
  max_single_trade: 10.0
  max_daily_volume: 100.0
  max_daily_loss: 50.0
  max_orders_per_minute: 5
```

### P1 — Fix before scaling capital

**FIX-5: Add idempotency key to place_order()** (`client.py`)  
Generate a UUID per order, store in strategy state before the call, pass as `clientOrderId` in the payload. Do not retry with a new UUID on timeout — retry with the same UUID.

**FIX-6: Add audit logging to non-copytrade strategies and exit events**  
Ensure all 8 live strategies write to AuditTrail on every trade attempt (paper and live).
Add `log_trade_decision(fill_status="closed", ...)` on every exit.

### P2 — Fix before scaling capital above $1,000

**FIX-7: Synchronize kill switch activation in record_trade()**  
Set `self._killed = True` synchronously before returning from `record_trade()`. Use `asyncio.ensure_future()` only for the callback notifications, not for the kill flag itself.

**FIX-8: Cap deep value stop-loss at 60%**  
Change the override in `exit_engine.py` from `max(..., 0.70)` to `min(max(..., 0.60), 0.65)`.

---

## Section 9 — Readiness Score

| Category | Weight | Score | Notes |
|---|---|---|---|
| DRY_RUN mode implemented | 10 | 9 | Works in copytrade; gaps in 4 other strategies |
| Max position size | 10 | 7 | Hard cap $10 works; docker-compose max_positions wrong |
| Max daily loss | 10 | 6 | Exists but fires after overshoot; limits too high for small account |
| Stop-loss | 10 | 8 | Category-specific, exit engine solid. Deep value SL too wide |
| Cooldown | 5 | 8 | Good in copytrade and flash_crash |
| Duplicate order prevention | 10 | 5 | Dedup exists but no idempotency key on timeout |
| API failsafe | 10 | 5 | Approved endpoint list exists; no retry circuit breaker; signer bug creates retry loop |
| Audit/logging | 10 | 5 | Copytrade well-logged; 4 strategies not logged; no exit events |
| Sandbox coverage | 15 | 4 | Only copytrade checks sandbox; 4 strategies completely bypass it |
| Configuration consistency | 10 | 4 | docker-compose contradicts config.py defaults; yaml security limits wrong |

**Total: 51 / 100**

---

## Section 10 — Conclusion

**SAFE TO FUND: NO**

The bot is architecturally sound. The sandbox, kill switch, exit engine, Kelly sizing, and copytrade dedup are all well-implemented. **However**, four blocking issues prevent safe live deployment:

1. **Signer bug (RISK-1):** Orders are failing right now. When fixed without addressing FIX-2 through FIX-4 first, 8 live strategies will start trading with no sandbox protection on most of them.

2. **Sandbox coverage gap (RISK-2):** 4 of 8 live strategies can blow through the daily loss limit, ignore the kill switch, and ignore trade size caps because they never call `sandbox.check_trade()`.

3. **Position limit contradiction (RISK-3):** docker-compose defaults to 100 max positions while every other config source says 30.

4. **Sandbox limits too high (RISK-6):** $2,500/day loss limit is meaningless for a $300-$500 test account.

**Recommended path to funding:**
1. Fix FIX-2 (sandbox wiring for all strategies) — 2-3 hours
2. Fix FIX-3 (docker-compose position limit) — 5 minutes
3. Fix FIX-4 (account-appropriate security limits) — 5 minutes
4. Fix FIX-1 (signer hex bug) — 30 minutes
5. Restart bot in dry_run=true for 24h to verify no unexpected behavior
6. Fund $200 test account and monitor for 48h before raising limits

After FIX-1 through FIX-4, estimated readiness score: **78 / 100**. After P1 fixes: **88 / 100**.
