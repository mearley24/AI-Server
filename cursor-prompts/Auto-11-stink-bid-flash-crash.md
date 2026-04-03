# Auto-11: Stink Bid + Flash Crash Strategies — Production Wire-Up

## Context Files to Read First
- polymarket-bot/strategies/stink_bid.py
- polymarket-bot/strategies/flash_crash.py
- polymarket-bot/strategies/strategy_manager.py
- polymarket-bot/src/websocket_client.py
- polymarket-bot/paper_runner.py
- polymarket-bot/docs/multi_strategy_architecture.md

## Prompt

The StinkBidStrategy and FlashCrashStrategy classes exist but aren't wired into the running system. Make them operational:

1. **Stink Bid** (`strategies/stink_bid.py`):
   - Review the existing class, fix any issues (it uses structlog — convert to standard logging)
   - Wire into the paper trader first: publish all stink bid placements and fills to Redis `signals:stink_bid`
   - Stink bids should be placed on crypto 5m/15m markets where the current price is >60¢
   - Place limit buy at 40¢ (or 20¢ below current), hoping to catch a flash dip
   - Take profit: +15¢ from fill price. Stop loss: -10¢ from fill price
   - Max 5 concurrent stink bids. Cancel unfilled orders after 30 minutes.
   - Max $3 per bid (small size, high frequency)

2. **Flash Crash** (`strategies/flash_crash.py`):
   - Review existing class, fix structlog → standard logging
   - Wire into paper trader: publish to Redis `signals:flash_crash`
   - Monitor via WebSocket orderbook feed for sudden drops (≥30¢ in 10 seconds)
   - On detection: buy immediately at market, target 50% reversion
   - Stop loss: if price drops another 10¢ after entry, cut
   - Max $10 per flash crash buy
   - Only trigger on markets with >$50k volume (liquid enough to exit)

3. **Sports Arb** (`strategies/sports_arb.py`):
   - Review existing class (reverse-engineered from $619K wallet), fix structlog
   - Wire into paper trader: publish to Redis `signals:sports_arb`
   - Scan binary sports markets for combined YES+NO price < $0.98
   - Execute simultaneous buys on both sides for guaranteed profit
   - Size based on available liquidity (min 100 shares on each side)

4. **Integration**:
   - Add all three as sub-strategies under strategy_manager.py
   - Stink Bid + Flash Crash share the CVD/arb 25% bankroll allocation
   - Sports Arb gets a carved-out 5% of total bankroll (low frequency, guaranteed wins)
   - All three must register positions in SharedPositionRegistry

5. **Paper trading period**: Run all three in paper-only mode for 48 hours before considering live.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
