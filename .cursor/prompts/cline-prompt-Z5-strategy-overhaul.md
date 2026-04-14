# Cline Prompt Z5 — Strategy Overhaul: Kill the Bleeders, Double Down on Winners

## Context
Full P&L analysis across 3,500 trades and $4,703 spent reveals the bot is hemorrhaging money:
- **Sports**: -$618 (23% win rate, $1,514 spent) — random match betting with zero edge
- **Crypto**: -$185 (31% win rate) — spray-and-pray on price brackets
- **Weather**: -$163 (48% win rate, $1,071 spent) — exact-temp coin flips at high cost
- **GTA VI memes + Genius token**: -$222 dead money in unresolved markets

**What works**: Bitcoin price bracket bets with conviction (+$178 single winner), esports with high confidence (+$67), cheap "No" bets on absurd long-duration events.

**Goal**: Stop the bleeding, concentrate capital on proven edges, implement minimum ROI thresholds.

## Files to modify:
- `strategies/polymarket_copytrade.py` — tighten category controls
- `strategies/weather_trader.py` — restrict to high-confidence only
- `strategies/sports_arb.py` — raise arb threshold
- `src/config.py` — update defaults

---

## Part 1: Copytrade Category Overhaul

### 1A. Update category multipliers based on REAL P&L data

In `polymarket_copytrade.py`, replace the `_DEFAULT_CATEGORY_MULTIPLIERS` dict (around line 731) with data-driven values from the actual -$1,764 loss analysis:

```python
    # Data-driven multipliers from 3,500-trade analysis (2026-04-13)
    # Categories sorted by ROI: only positive-ROI categories get >= 1.0x
    _DEFAULT_CATEGORY_MULTIPLIERS: dict[str, float] = {
        "crypto_updown": 1.5,   # BTC brackets are the #1 winner (+$178 single trade)
        "crypto": 1.5,          # alias — crypto price brackets have real edge
        "esports": 0.8,         # -$32 but has big individual winners (+$67 BLG/JDG)
        "tennis": 0.3,          # demote — not enough data to justify 1.3x
        "politics": 0.3,        # -$31 across 18 losses — no proven edge
        "us_sports": 0.0,       # DISABLED — 23% win rate, -$618, zero edge
        "soccer_intl": 0.0,     # DISABLED — part of sports -$618 disaster
        "sports": 0.0,          # DISABLED — generic sports is pure gambling
        "weather": 0.0,         # DISABLED from copytrade — weather_trader handles its own
        "other": 0.2,           # -$476 from "other" — nearly all losers
        "geopolitics": 0.2,     # -$31, 0% win rate on world politics
        "economics": 0.5,       # fed rates have some structure
        "science": 0.3,         # low sample
        "entertainment": 0.3,   # +$8, mixed results
        "f1": 0.0,              # DISABLED — part of sports
        "motorsport": 0.0,      # DISABLED — part of sports
    }
```

### 1B. Lower category loss limits to stop bleeding faster

Replace the `_CATEGORY_LOSS_LIMITS` dict (around line 350) with much tighter limits:

```python
        self._CATEGORY_LOSS_LIMITS: dict[str, float] = {
            "crypto_updown": 15.0,   # highest conviction — allow more room
            "crypto": 15.0,
            "crypto_binary": 0.0,    # still blocked
            "esports": 5.0,          # cut from 10 to 5
            "tennis": 3.0,
            "sports": 0.0,           # ZERO — no sports losses allowed
            "us_sports": 0.0,        # ZERO
            "soccer_intl": 0.0,      # ZERO
            "weather": 0.0,          # ZERO from copytrade (weather_trader is separate)
            "politics": 3.0,         # cut from 10 to 3
            "geopolitics": 2.0,      # cut from 5 to 2
            "science": 2.0,
            "entertainment": 2.0,    # cut from 5 to 2
            "other": 5.0,            # cut from 15 to 5
            "economics": 5.0,
            "f1": 0.0,               # ZERO
            "motorsport": 0.0,       # ZERO
        }
```

### 1C. Add minimum expected ROI filter

In the copytrade `_should_copy_trade()` or `_evaluate_signal()` method (wherever the buy decision is made), add this check before executing a trade:

Find where the entry price is evaluated. Add this filter — reject any trade where the entry price is above 0.85 (only 18% max return) or where the expected ROI is too thin:

```python
        # Minimum ROI filter — don't risk capital for tiny returns
        if entry_price > 0.80:
            logger.info("copytrade_skip_low_roi", price=entry_price, market=market_title[:50])
            return False
```

This prevents the bot from buying shares at 85-95 cents for a measly 5-15% potential return. The big winners (BTC +$178, esports +$67) were all bought at low prices with high potential multiples.

### 1D. Reduce max concurrent positions

The bot has 100 open positions right now — that's too spread thin. In `config.py`, change:

```python
    copytrade_max_positions: int = Field(default=30, description="Max concurrent copied positions — concentrated, not spray-and-pray")
```

## Part 2: Disable Weather Trader

The weather strategy has spent $1,071 with a 48% win rate. That's worse than a coin flip after fees. The wins are mostly $1-5 and the losses go up to $72. Disable it entirely.

### 2A. In `src/config.py`, change the default:

```python
    weather_trader_enabled: bool = Field(default=False, description="DISABLED — 48% win rate, -$163 P&L across 200 markets. Re-enable only with improved NOAA model.")
```

### 2B. In `src/main.py`, add an explicit log when weather is disabled:

Find the weather_trader initialization block (around line 300). After the `if` check for `settings.weather_trader_enabled`, add in the `else`:

```python
    else:
        log.warning("weather_trader_disabled", reason="Strategy lost $163 across 200 markets at 48% win rate. Set WEATHER_TRADER_ENABLED=true to re-enable.")
```

### 2C. IMPORTANT — Also disable it in Bob's .env

After running this prompt, Matt needs to add to `.env`:
```
WEATHER_TRADER_ENABLED=false
```

## Part 3: Sports Arb Tightening

The sports_arb strategy is supposed to find arbitrage opportunities, but the data shows 23% win rate on sports. The arb threshold may be too loose, taking "almost-arb" positions that aren't really risk-free.

### 3A. In `config.py`, tighten the arb threshold:

```python
    sports_arb_arb_threshold: float = Field(default=0.97, description="Max combined price for arbitrage — tightened from 0.995 to require genuine arb")
    sports_arb_max_position_per_side: float = Field(default=10.0, description="Max position per side — reduced from 5000 to 10")
```

The old 0.995 threshold means combined prices up to 99.5 cents were considered "arb" — that's only 0.5% margin, which evaporates with slippage and fees. 0.97 requires a 3% true arb.

### 3B. In `sports_arb.py`, add a minimum arb profit check:

Find where the arb is evaluated. Add:

```python
        # Skip arbs with less than $0.50 expected profit
        expected_profit = position_size * (1.0 - combined_price)
        if expected_profit < 0.50:
            self._arbs_skipped_today += 1
            self._last_skip_reason = "profit_too_small"
            return
```

## Part 4: GTA VI / Long-Duration Position Cleanup

The bot has $83 in GTA VI meme positions and $139 in Genius token positions. These won't resolve for months/years. That capital is dead.

Add an explicit position age check in the copytrade exit engine. In `strategies/exit_engine.py`, find where positions are checked for exit. Add:

```python
        # Auto-exit positions older than 14 days at current market price
        # Dead money in long-duration markets should be recycled
        position_age_days = (time.time() - entry_timestamp) / 86400
        if position_age_days > 14:
            return ExitSignal(
                reason="stale_position",
                message=f"Position {position_age_days:.0f} days old — recycling capital",
            )
```

## Part 5: Add Strategy Performance Logging

Add a daily summary that logs P&L by category to Cortex so we can track whether these changes work.

In `polymarket_copytrade.py`, add a method that runs once per day (or call it from the existing daily reset at line ~880):

```python
    def _log_daily_category_summary(self) -> None:
        """Log daily P&L by category to Cortex for tracking."""
        try:
            import redis
            import json
            url = os.environ.get("REDIS_URL", "")
            if not url:
                return
            r = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            summary = {
                "type": "trading_daily_summary",
                "category_pnl": dict(self._category_pnl),
                "category_multipliers": dict(self._CATEGORY_MULTIPLIERS),
                "halted_categories": list(self._halted_categories),
                "total_positions": len(self._positions),
            }
            r.publish("ops:trading_summary", json.dumps(summary, default=str))
        except Exception:
            pass
```

Call this from the daily reset block (around line 880 where `_daily_category_losses` is reset).

## Part 6: Verify and Commit

```zsh
python3 -c "import ast; ast.parse(open('strategies/polymarket_copytrade.py').read()); print('copytrade OK')"
python3 -c "import ast; ast.parse(open('strategies/weather_trader.py').read()); print('weather OK')"
python3 -c "import ast; ast.parse(open('strategies/sports_arb.py').read()); print('arb OK')"
python3 -c "import ast; ast.parse(open('src/config.py').read()); print('config OK')"
python3 -c "import ast; ast.parse(open('src/main.py').read()); print('main OK')"
```

All must print OK. Then:

```zsh
git add -A
git commit -m "feat: strategy overhaul — kill sports/weather bleeders, concentrate on crypto/esports winners"
git push origin main
```

## Post-Deploy

After pulling on Bob:
```zsh
docker compose up -d --build polymarket-bot
```

Also add to Bob's `.env`:
```
WEATHER_TRADER_ENABLED=false
COPYTRADE_MAX_POSITIONS=30
```

## DO NOT:
- Change wallet addresses or private keys
- Modify the redeemer code
- Change Redis connection settings
- Add new pip dependencies
- Touch Cortex/dashboard code (that's Z4's job)
