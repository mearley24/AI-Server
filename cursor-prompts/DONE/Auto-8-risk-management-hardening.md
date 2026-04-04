# Auto-8: Risk Management Hardening

## Context Files to Read First
- polymarket-bot/docs/polymarket_strategy_improvements.md (Risk Management Summary section, line ~973)
- polymarket-bot/strategies/polymarket_copytrade.py
- polymarket-bot/strategies/wallet_scoring.py
- polymarket-bot/strategies/exit_engine.py
- polymarket-bot/src/redeemer.py
- polymarket-bot/src/pnl_tracker.py

## Prompt

Implement the 5 risk management items flagged in the strategy spec but not yet built:

1. **Minimum market volume filter** (`polymarket_copytrade.py`):
   - In `_should_copy_trade()`, fetch market volume from Gamma API
   - Block entry on any market with <$10k total volume (wide spreads make exit impossible)
   - Log skipped markets with reason `insufficient_liquidity`
   - Env var: `MIN_MARKET_VOLUME_USD=10000`

2. **Whale wallet 30-day rolling gate** (`wallet_scoring.py`):
   - Track each priority wallet's last-30-day performance (WR and P/L)
   - If a priority wallet's rolling 30-day WR drops below 60%, demote to standard tracking
   - If it recovers above 65% WR for 14 consecutive days, re-promote
   - Store rolling stats in Redis hash `wallet:rolling:{address}`
   - Daily job to recalculate (add to heartbeat runner)

3. **Bankroll sync** (`pnl_tracker.py`):
   - Every hour, query on-chain USDC.e balance via Polygon RPC
   - Also sum estimated market value of all open positions (shares × current price)
   - Set internal bankroll = on-chain USDC + estimated position value
   - Log drift between internal tracker and on-chain reality
   - If drift >10%, send an iMessage alert ("Bankroll drift detected: internal $X vs on-chain $Y")

4. **Redemption audit** (`redeemer.py`):
   - Verify the redeemer loop is actually running (add a heartbeat timestamp to Redis)
   - After a market resolves, if we hold winning shares and they aren't redeemed within 10 minutes, send alert
   - Log all redemptions: market, shares, payout, timestamp
   - Add `/redeem_status` to the API routes showing pending redemptions

5. **Category blacklist exceptions** (`polymarket_copytrade.py`):
   - Political markets at ≥92¢ on the likely outcome have genuine edge (almost no tail risk)
   - If LLM categorizes as politics/geopolitics BUT price ≥0.92 AND LLM confidence ≥0.70, allow entry with $5 cap
   - Log these as `category_exception` entries

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
