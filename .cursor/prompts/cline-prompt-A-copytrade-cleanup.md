# Cline Prompt A: Copytrade Cleanup — Kill Fake Data + Fix neg_risk

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. ONE commit at the end.

## 1. Remove hardcoded category P&L seeds

In `polymarket-bot/strategies/polymarket_copytrade.py` around line 537, there's a block:
```python
if not self._category_pnl:
    self._category_pnl = {
        "crypto": 65.48,
        ...
    }
    logger.info("copytrade_category_pnl_seeded", categories=self._category_pnl)
```

Replace that entire `if not self._category_pnl:` block (including the dict and the logger line) with:
```python
# Start from zero — let real data accumulate (old seeds were stale)
# P&L will populate from Redis persistence or live trade tracking
```

The `self._category_pnl` is already initialized as `{}` on line 494. The seeds reset real performance tracking on every restart, which is wrong.

## 2. Remove fabricated priority wallet stats

Around line 1181, there's a block that injects fake stats for priority wallets:
```python
# Inject priority wallets (proven profitable from research)
priority_added = 0
for pw_addr in self._PRIORITY_WALLETS:
    pw_lower = pw_addr.lower()
    if pw_lower not in wallet_stats:
        wallet_stats[pw_lower] = {
            "wins": 50, "losses": 5, "total_volume": 100000,
            "avg_win_pnl": 10.0, "avg_loss_pnl": -3.0,
        }
        priority_added += 1
if priority_added:
    logger.info("copytrade_priority_wallets_injected", count=priority_added)
```

Delete that entire block (the `priority_added = 0`, the for loop, and the if/logger). Priority wallets should compete on REAL data, not fabricated 91% win rates.

## 3. Fix neg_risk in copy orders

Search the entire file for `neg_risk=False` in order creation. There are at least 4 occurrences (around lines 2187, 2928, 3115, 3251). Each one hardcodes `neg_risk=False` instead of reading from market data.

For each occurrence, find where the market data is available in the surrounding context. Look for a variable like `market_data`, `market`, `m`, or `market_info` in scope. Replace:
```python
neg_risk=False,
```
With:
```python
neg_risk=bool(market_data.get("neg_risk", market_data.get("negativeRisk", False))),
```

Adapt the variable name to whatever is in scope at each location. If no market data dict is accessible, look up the call chain to find where it's available and thread it through. If you truly cannot determine neg_risk from context, leave it as `False` but add a `TODO: wire neg_risk from market data` comment.

## 4. Extend quiet hours

Find the `_is_quiet_hours` static method (around line 743). It currently blocks 23:00-05:00 MDT. Extend it to also block 00:00-06:00 UTC (which is 18:00-00:00 MDT). The goal is to block the low-liquidity overnight window.

Change the return line to:
```python
return now_mdt.hour >= 18 or now_mdt.hour < 5
```

Update the docstring to reflect the new window (18:00 - 05:00 MDT).

## Verify and commit
```bash
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py && echo "COMPILE OK"
grep -c "65.48\|copytrade_category_pnl_seeded" polymarket-bot/strategies/polymarket_copytrade.py
echo "Should be 0 (seeds removed)"
grep -c "priority_wallets_injected\|wins.*50.*losses.*5" polymarket-bot/strategies/polymarket_copytrade.py
echo "Should be 0 (fake stats removed)"
grep "neg_risk" polymarket-bot/strategies/polymarket_copytrade.py | head -10
echo "Check neg_risk is reading from market data"
git add -A && git commit -m "fix: copytrade — remove fake P&L seeds, kill fabricated wallet stats, fix neg_risk, extend quiet hours"
git push origin main
```
