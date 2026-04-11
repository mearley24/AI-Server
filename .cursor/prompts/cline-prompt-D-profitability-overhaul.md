# Cline Prompt D: Maximize Bot Profitability — Data-Driven Tuning

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push when done.

## Context — What the wallet data tells us

Live wallet scan (April 11, 2026):
- 100 open positions, $468 total cost, $462 current value (-1.3% overall)
- **10-25c entry bracket: +38.3% ROI** — the sweet spot
- **25-50c bracket: +7.2% ROI** — solid
- **Sub-10c bracket: -48% ROI** — losing badly, mostly penny esports/soccer lottery tickets
- **75c+ bracket: -1.4% ROI** — tying up capital for almost no return
- **50-75c bracket: -4.7% ROI** — mediocre
- Best performers: DHS shutdown (+337%), India politics (+188%), NBA rookie (+128%) — all contrarian macro/political at 10-30c entry
- Worst performers: soccer day-of bets (-95%), chess longshots at 69c (-89%), sports at penny prices

The bot has $304 liquid USDC.e and $462 in positions. Every dollar matters.

## Changes to make in `polymarket-bot/strategies/polymarket_copytrade.py`:

### 1. Raise minimum entry price — kill penny lottery tickets

The sub-5c positions are hemorrhaging money. Find `CATEGORY_MIN_ENTRY` dict (around line 1762). Change ALL minimums:

```python
CATEGORY_MIN_ENTRY = {
    "weather": 0.05,
    "us_sports": 0.08,
    "sports": 0.08,
    "esports": 0.08,
    "tennis": 0.08,
    "crypto": 0.05,
    "crypto_updown": 0.05,
    "economics": 0.05,
    "science": 0.08,
    "other": 0.05,
    "politics": 0.05,
    "geopolitics": 0.05,
}
```

### 2. Lower maximum entry prices — stop buying expensive positions

Positions bought at 90c+ are terrible risk/reward ($9 risk for $1 upside). Find `CATEGORY_MAX_ENTRY` dict. Change to:

```python
CATEGORY_MAX_ENTRY = {
    "weather": 0.15,
    "us_sports": 0.30,
    "sports": 0.30,
    "esports": 0.30,
    "tennis": 0.30,
    "crypto": 0.30,
    "crypto_updown": 0.30,
    "economics": 0.30,
    "science": 0.30,
    "other": 0.30,
    "politics": 0.25,
    "geopolitics": 0.25,
}
```

### 3. Rethink category tiers based on ACTUAL performance

The current blacklist kills categories that are actually profitable. The wallet data shows politics (+$12 DHS, +$7 Peru) and sports (+$5 NBA rookie, +$5 esports) CAN be profitable when bought cheap. The problem isn't the category — it's the entry price.

Find `CATEGORY_TIERS` dict (around line 282). Change to:

```python
CATEGORY_TIERS: dict[str, str] = {
    "weather": "whitelist",
    "crypto": "whitelist",
    "crypto_updown": "whitelist",
    "economics": "whitelist",
    "politics": "graylist",       # was blacklist — profitable at cheap entries
    "geopolitics": "graylist",    # was blacklist — long-dated macro bets work
    "other": "graylist",
    "esports": "graylist",
    "science": "graylist",        # was blacklist
    "entertainment": "blacklist", # keep blacklisted — pure noise
    "us_sports": "graylist",      # was blacklist — NBA/NHL have edge at cheap prices
    "sports": "graylist",         # was blacklist — but only at cheap entries
    "tennis": "blacklist",        # keep — no edge
    "soccer_intl": "blacklist",   # keep — no edge
    "f1": "graylist",             # was blacklist — motorsport has info edge
    "motorsport": "graylist",     # was blacklist
}
```

### 4. Increase position size for the profitable bracket

In `polymarket-bot/src/config.py`, find `copytrade_size_usd`. It's currently $2.00. The 10-25c bracket is crushing it but positions are tiny. Bump to $3:

```python
copytrade_size_usd: float = Field(default=3.0, description="USD per copied trade — tiered by wallet quality and entry price bracket")
```

### 5. Add entry-price-based size scaling

In `polymarket_copytrade.py`, find where `size_usd` is calculated for a trade (search for `size_usd` assignment, likely near where the order is built). Add scaling logic AFTER the base size is determined but BEFORE the order is placed:

```python
# Scale position size by entry price bracket — more capital in the profitable zone
if 0.08 <= price <= 0.25:
    size_usd *= 1.5  # 50% boost for the sweet spot (10-25c bracket is +38% ROI)
    logger.info("copytrade_size_boost", reason="sweet_spot_bracket", price=price, boosted_size=round(size_usd, 2))
elif price >= 0.60:
    size_usd *= 0.5  # Halve size for expensive entries (75c+ is -1.4% ROI)
    logger.info("copytrade_size_reduce", reason="expensive_bracket", price=price, reduced_size=round(size_usd, 2))
```

### 6. Raise daily loss limit

With 24/7 trading and more positions, $15 is too tight — it'll halt the bot mid-day on a bad streak and miss recovery. In `polymarket-bot/src/config.py`:

```python
copytrade_daily_loss_limit: float = Field(default=30.0, description="Max net daily loss before halting trades")
```

### 7. Increase max positions

With $767 total portfolio and $3 per trade, 30 positions = $90 deployed max. We have $462 already deployed across 100 positions. Raise the cap:

```python
copytrade_max_positions: int = Field(default=60, description="Max concurrent copied positions")
```

### 8. Fix remaining neg_risk TODOs

Search for `TODO: wire neg_risk from market data` in `polymarket_copytrade.py`. There should be 3 occurrences. For each one, look at what variables are in scope. The trade context typically has a `market_data` or `mkt_data` dict. Replace each:

```python
neg_risk=False,  # TODO: wire neg_risk from market data
```

With the best available market data lookup. If `mkt_data` is in scope:
```python
neg_risk=bool(mkt_data.get("neg_risk", mkt_data.get("negativeRisk", False))) if isinstance(mkt_data, dict) else False,
```

If only `trade` dict is in scope:
```python
neg_risk=bool(trade.get("neg_risk", trade.get("negativeRisk", False))),
```

Search the surrounding context for each occurrence and use whatever market/trade dict is available.

### 9. Remove the dead quiet hours code path

The `_is_quiet_hours` method now returns False always. Find every call site where `_is_quiet_hours()` is checked (search for `quiet_hours` in the file). Remove the `if self._is_quiet_hours():` blocks entirely — they're dead code. There should be about 3 call sites. Delete the method itself too.

## Verify and commit
```bash
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py && python3 -m py_compile polymarket-bot/src/config.py && echo "COMPILE OK"
grep "quiet_hours" polymarket-bot/strategies/polymarket_copytrade.py | wc -l
echo "Should be 0 (quiet hours removed)"
grep "TODO.*neg_risk" polymarket-bot/strategies/polymarket_copytrade.py | wc -l
echo "Should be 0 (all neg_risk wired)"
grep "copytrade_size_usd.*3.0" polymarket-bot/src/config.py && echo "Size at $3"
grep "daily_loss_limit.*30" polymarket-bot/src/config.py && echo "Daily loss at $30"
grep "max_positions.*60" polymarket-bot/src/config.py && echo "Max positions at 60"
grep "0.08" polymarket-bot/strategies/polymarket_copytrade.py | head -3
echo "Min entry raised"
git add -A && git commit -m "feat: profitability overhaul — data-driven brackets, 24/7 trading, kill penny bets, boost sweet spot"
git push origin main
```
