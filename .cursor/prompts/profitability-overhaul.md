# Polymarket Bot Profitability Overhaul — Cursor Prompt

Work ONLY in `/Users/bob/AI-Server/`. Do NOT create worktrees.

After completing ALL changes, run:
```bash
cd /Users/bob/AI-Server && python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py && python3 -m py_compile polymarket-bot/strategies/exit_engine.py && python3 -m py_compile polymarket-bot/src/config.py && python3 -m py_compile polymarket-bot/strategies/spread_arb.py && python3 -m py_compile polymarket-bot/strategies/weather_trader.py && echo "ALL COMPILATIONS PASSED" && git add -A && git commit -m "fix: profitability overhaul — tighten entry caps, fix exits, kill losing categories" && git push origin main
```

---

## CONTEXT — WHY THESE CHANGES

12 days of live trading data (2,036 trades, March 25 – April 6, 2026) shows a net loss of **-$1,322 (-25.3% ROI)**. Root cause analysis:

| Problem | Impact |
|---|---|
| Entry prices too high (65¢+ = -11.9% ROI) | -$197 lost on expensive entries alone |
| Only profitable bucket is 5¢–35¢ (5¢-10¢ = +72% ROI, 20¢-35¢ = +36.8% ROI) | The bot's edge ONLY exists below 35¢ |
| Both-sides betting on 49 conditions | $389 wasted on positions that cancel out |
| Sports category bleeding (-37.7% ROI overall; NBA -53.6%, Tennis -48.7%, F1 -70.6%) | -$443 total |
| Politics (-77.1% ROI) | -$52 total |
| 68% of sells are at a loss vs entry; average sell price is 29¢ | Bot sells winners too early, losers too late |
| Burst trading (525 trades within 5 seconds of each other) | Apr 1-2 lost $870 in 2 days |
| Weather is closest to profitable (-15.7%) but events with 3+ trades/city lose money | Temp clustering needs stricter enforcement |

**The ONLY profitable pattern**: cheap bracket entries (5¢–35¢), especially weather. The biggest winners all bought below 25¢.

---

## CHANGES — IMPLEMENT EACH ONE IN ORDER

### 1. Tighten Entry Price Caps (polymarket_copytrade.py ~line 1778)

Find `CATEGORY_MAX_ENTRY` dict and replace with:

```python
CATEGORY_MAX_ENTRY = {
    "weather": 0.25,      # KEEP — cheap brackets only (proven profitable)
    "us_sports": 0.35,    # WAS 0.75 — data shows sports only works below 35¢
    "sports": 0.35,       # WAS implicit 0.70 — same as above
    "esports": 0.35,      # NEW — same logic
    "tennis": 0.35,       # NEW — tennis was -48.7% ROI
    "crypto": 0.35,       # WAS 0.60 — only cheap crypto bets work
    "crypto_updown": 0.35,# NEW — crypto up/down was -10% ROI at current caps
    "economics": 0.35,    # NEW
    "science": 0.35,      # WAS 0.60
    "other": 0.35,        # WAS 0.70
    "politics": 0.30,     # WAS 0.50 — tighten further (still blacklisted anyway)
    "geopolitics": 0.30,  # WAS 0.50
}
```

Also in the same function, update `CATEGORY_MIN_ENTRY` — set a floor of 0.02 for weather (sub-penny bets are noise) and 0.03 for everything else:

```python
CATEGORY_MIN_ENTRY = {
    "weather": 0.02,
    "us_sports": 0.03,
    "sports": 0.03,
    "esports": 0.03,
    "tennis": 0.03,
    "crypto": 0.03,
    "crypto_updown": 0.03,
    "economics": 0.03,
    "science": 0.03,
    "other": 0.03,
    "politics": 0.03,
    "geopolitics": 0.03,
}
```

### 2. Expand Category Blacklist (polymarket_copytrade.py ~line 281)

Find `CATEGORY_TIERS` dict and replace with:

```python
CATEGORY_TIERS: dict[str, str] = {
    "weather": "whitelist",       # KEEP — closest to profitable
    "crypto": "graylist",         # KEEP — moderate filter
    "crypto_updown": "graylist",  # KEEP
    "economics": "graylist",      # KEEP
    "other": "graylist",          # KEEP
    "esports": "graylist",        # WAS whitelist — needs LLM gate, data inconclusive
    "us_sports": "blacklist",     # WAS whitelist — NBA -53.6%, overall -37.7% ROI
    "sports": "blacklist",        # WAS whitelist — massive losses
    "tennis": "blacklist",        # WAS whitelist — -48.7% ROI
    "politics": "blacklist",      # KEEP
    "geopolitics": "blacklist",   # KEEP
    "science": "blacklist",       # KEEP
    "entertainment": "blacklist", # KEEP
    "soccer_intl": "blacklist",   # KEEP
    "f1": "blacklist",            # NEW — F1 was -70.6% ROI
    "motorsport": "blacklist",    # NEW
}
```

### 3. Tighten Per-Category Loss Limits (polymarket_copytrade.py ~line 338)

Find `_CATEGORY_LOSS_LIMITS` dict and replace with:

```python
self._CATEGORY_LOSS_LIMITS: dict[str, float] = {
    "crypto_updown": 5.0,    # WAS 10 — halve it
    "crypto_binary": 0.0,    # KEEP — blocked
    "sports": 0.0,           # WAS 30 — now blacklisted, but zero tolerance if it sneaks through
    "us_sports": 0.0,        # WAS implicit — blocked
    "tennis": 0.0,           # NEW — blocked
    "weather": 25.0,         # WAS 50 — tighten, this is our main strategy
    "politics": 0.0,         # WAS 5 — zero, fully blocked
    "geopolitics": 0.0,      # WAS 5 — zero
    "science": 0.0,          # WAS 10 — zero, blacklisted
    "entertainment": 0.0,    # NEW — blocked
    "other": 15.0,           # WAS 25 — tighten
    "esports": 10.0,         # NEW
    "economics": 10.0,       # NEW
}
```

### 4. Reduce Hourly and Daily Trade Caps (polymarket_copytrade.py ~line 408-413)

Change the defaults:

```python
self._max_trades_per_hour: int = int(os.environ.get("MAX_TRADES_PER_HOUR", "8"))     # WAS 20
self._max_trades_per_wallet_per_day: int = int(os.environ.get("MAX_TRADES_PER_WALLET_PER_DAY", "2"))  # WAS 3
```

### 5. Reduce Max Concurrent Positions (polymarket_copytrade.py ~line 310)

Change:
```python
self._max_positions: int = getattr(settings, "copytrade_max_positions", 30)  # WAS 100
```

And per-category cap (~line 417):
```python
self._max_positions_per_category: int = int(os.environ.get("MAX_POSITIONS_PER_CATEGORY", "15"))  # WAS 50
```

### 6. Tighten Daily Loss Circuit Breaker (polymarket_copytrade.py ~line 318)

Change:
```python
self._daily_loss_limit: float = getattr(settings, "copytrade_daily_loss_limit", 25.0)  # WAS 50
```

Also in `src/config.py` ~line 198, update the default:
```python
copytrade_daily_loss_limit: float = Field(default=25.0, description="Max net daily loss before halting trades")
```

And in `src/config.py` ~line 193, update max positions default:
```python
copytrade_max_positions: int = Field(default=30, description="Max concurrent copied positions")
```

### 7. Fix the Exit Engine (strategies/exit_engine.py)

The current exit engine sells at a 29¢ average — 68% of sells are at a loss. The problem: the stop-loss triggers too slowly (50% drop) and the trailing stop never activates for cheap entries (30% gain on a 10¢ entry means price only went to 13¢).

Replace the `CATEGORY_EXIT_PARAMS` dict at the top of the file:

```python
CATEGORY_EXIT_PARAMS: dict[str, dict[str, float]] = {
    "crypto_updown": {"sl": 0.40, "time_hours": 6, "trailing": 0.08},    # Tighter time (was 12h)
    "sports": {"sl": 0.35, "time_hours": 12, "trailing": 0.10},          # Tighter SL (was 0.40)
    "weather": {"sl": 0.60, "time_hours": 48, "trailing": 0.12},         # Wider SL for weather — let cheap brackets ride to resolution
    "politics": {"sl": 0.40, "time_hours": 48, "trailing": 0.15},        # Tighter SL (was 0.50)
    "geopolitics": {"sl": 0.40, "time_hours": 48, "trailing": 0.15},     
    "other": {"sl": 0.45, "time_hours": 36, "trailing": 0.12},           # Tighter (was 72h)
    "esports": {"sl": 0.35, "time_hours": 12, "trailing": 0.10},         # NEW
    "economics": {"sl": 0.45, "time_hours": 48, "trailing": 0.15},       # NEW
}
```

In the `ExitEngine.__init__` method, change defaults:

```python
def __init__(
    self,
    take_profit_1_pct: float = 0.50,    # WAS 0.30 — activate trailing later, let winners run more
    take_profit_2_pct: float = 9.99,    # KEEP disabled
    stop_loss_pct: float = 0.45,        # WAS 0.50 — slightly tighter default
    trailing_stop_pct: float = 0.12,    # WAS 0.15 — trail closer to peak
    time_exit_hours: float = 36.0,      # WAS 48 — don't hold stale positions as long
    time_exit_min_move_pct: float = 0.05,
) -> None:
```

**Critical addition**: In the `evaluate()` method, add a new rule **BEFORE** the stop-loss check (before the `if pnl_pct <= -effective_sl:` block). This prevents selling cheap bracket buys at a loss when they still have time to resolve:

```python
# 0. HOLD RULE: For cheap entries (< 35¢), do NOT stop-loss within first 6 hours.
# Cheap brackets are volatile but resolve to $0 or $1. Early exits destroy the strategy.
cheap_entry = entry < 0.35
if cheap_entry and hold_hours < 6.0 and pnl_pct > -0.80:
    # Only emergency exit if down 80%+ — otherwise hold
    return None
```

Also, in the near-resolution take-profit section (~line 182), make it more aggressive at locking in gains:

```python
# 3b. Near-resolution take profit: lock gains near $1 outcomes
# If price is 85¢+ and we bought below 50¢, take 75% profit
near_resolution_price = 0.85   # WAS 0.92
if current_price >= near_resolution_price and entry < 0.50:  # WAS entry < 0.80
    return ExitSignal(
        position_id=position_id,
        reason="near_resolution_takeprofit",
        sell_fraction=0.75,
        current_price=current_price,
        entry_price=entry,
        pnl_pct=pnl_pct,
        hold_time_hours=hold_hours,
        peak_price=tracker.peak_price,
    )
```

### 8. Add Global Both-Sides Prevention (polymarket_copytrade.py)

The existing event slug guard (~line 1817-1827) is correct but we also need condition-level dedup. Find the guard section and verify that BOTH of these are present and working:

1. **Condition-level**: `if market and market in self._active_condition_ids:` (~line 1807) — this exists, verify it's not bypassed by any high-conviction override.
2. **Event-level**: the `_active_event_slugs` check (~line 1820) — this exists.

Additionally, add a **complementary outcome guard**. After the event-slug check, add:

```python
# Guard: complementary outcome detection — if we hold "Up", don't buy "Down" on same event
trade_outcome = trade.get("outcome", "")
if trade_event_slug:
    for pos in self._positions.values():
        if hasattr(pos, 'event_slug') and pos.event_slug == trade_event_slug:
            if pos.outcome != trade_outcome:
                logger.info(
                    "copytrade_skip",
                    reason="complementary_outcome_blocked",
                    held_outcome=pos.outcome,
                    new_outcome=trade_outcome,
                    event_slug=trade_event_slug,
                )
                return False
```

Make sure the `CopiedPosition` dataclass has `event_slug` and `outcome` fields. Check the existing dataclass (~line 196+) and add them if missing.

### 9. Widen the Anti-Spam Gap (polymarket_copytrade.py ~line 406)

The current min trade gap is 10 seconds. With 525 trades within 5 seconds of each other, this isn't working or isn't being enforced. Change:

```python
self._min_trade_gap: float = 30.0  # WAS 10.0 — 30 seconds minimum between any two trades
```

### 10. Temperature Cluster: Enforce Max 2 Brackets Strictly

The temp clustering logic exists (~line 1507+) but 61 weather events had 3+ trades per city-event anyway. Find `_check_temperature_cluster` method and verify:

1. The check runs BEFORE any bypass (high-conviction wallets should NOT bypass temp clustering).
2. `self._temp_cluster_max_brackets` defaults to 2 (line 445 — verified, but make sure the env var isn't overriding it).

In the `_should_copy_trade` method, find the high-conviction bypass section (~line 1862-1865). Make sure the temp cluster check (~line 1850) happens BEFORE this block and is NOT skipped by high conviction. The current code already does this correctly — just verify the ordering is:
1. Resolution window check
2. Temperature cluster check  
3. THEN high-conviction bypass (which should only skip correlation limits, NOT temp clustering)

### 11. Config Defaults (src/config.py)

Update these defaults to match the changes above:

```python
copytrade_size_usd: float = Field(default=3.0, description="...")           # KEEP
copytrade_max_positions: int = Field(default=30, description="...")          # WAS 20
copytrade_min_win_rate: float = Field(default=0.60, description="...")      # WAS 0.55 — higher bar
copytrade_daily_loss_limit: float = Field(default=25.0, description="...")  # WAS 50
```

---

## VERIFICATION CHECKLIST

After making all changes, verify with these commands:

```bash
# Compile all modified files
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py
python3 -m py_compile polymarket-bot/strategies/exit_engine.py
python3 -m py_compile polymarket-bot/src/config.py

# Verify the key values are set
grep "CATEGORY_MAX_ENTRY" polymarket-bot/strategies/polymarket_copytrade.py | head -1
grep "us_sports.*0.35" polymarket-bot/strategies/polymarket_copytrade.py | head -1
grep "sports.*blacklist" polymarket-bot/strategies/polymarket_copytrade.py | head -3
grep "daily_loss_limit.*25" polymarket-bot/src/config.py
grep "max_positions.*30" polymarket-bot/src/config.py
grep "MAX_TRADES_PER_HOUR.*8" polymarket-bot/strategies/polymarket_copytrade.py
grep "cheap_entry" polymarket-bot/strategies/exit_engine.py
grep "near_resolution_price = 0.85" polymarket-bot/strategies/exit_engine.py
grep "min_trade_gap.*30" polymarket-bot/strategies/polymarket_copytrade.py
```

Every grep above should return at least one match. If any doesn't, the change wasn't applied correctly.

---

## DEPLOY

After commit + push:
```bash
cd ~/AI-Server && git pull origin main && docker compose up -d --build polymarket-bot
```

Then verify filters are active:
```bash
sleep 30 && docker logs polymarket-bot --tail 50 2>&1 | grep -i "skip\|blacklist\|above_max\|cheap_entry\|complementary"
```
