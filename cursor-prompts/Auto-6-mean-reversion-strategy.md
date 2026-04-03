# Auto-6: Mean Reversion Strategy

## Context Files to Read First
- polymarket-bot/ideas.txt (MeanReversion entry)
- polymarket-bot/strategies/base.py
- polymarket-bot/strategies/spread_arb.py
- polymarket-bot/src/websocket_client.py
- polymarket-bot/docs/multi_strategy_architecture.md

## Prompt

Build the MeanReversion strategy as a new strategy class in `polymarket-bot/strategies/mean_reversion.py`:

1. Core logic:
   - Monitor all active markets via Gamma API for 24h price change
   - When a market moves >30¢ in <12 hours on volume <1,000 shares, flag it as a fade candidate
   - Buy the opposite side (if it spiked to 85¢, buy NO at 15¢)
   - Target: reversion to 50% of the move (spike to 85¢ → target 67¢ → sell YES at 67¢ or let NO appreciate)

2. Entry filters:
   - Only binary YES/NO markets (no multi-outcome)
   - Minimum time to resolution: 24 hours (don't fade moves near settlement)
   - Skip weather markets (those moves are real, not manipulation)
   - Skip markets already in our position registry
   - Max entry price: 25¢ on the fade side

3. Exit rules:
   - Take profit at 50% reversion (configurable)
   - Stop loss at -40% (the move extended further)
   - Time stop: 6 hours max hold (if no reversion, cut it)

4. Validation:
   - Cross-reference with copytrade data: if multiple high-quality wallets (>70% WR) also entered the same direction, skip the fade (it's real movement, not manipulation)
   - Check orderbook depth: if the spread is >5¢, skip (illiquid, hard to exit)

5. Wire into strategy_manager.py as a sub-strategy under the spread/arb umbrella (uses the 25% bankroll allocation).

6. Add paper trading support: publish signals to Redis `signals:mean_reversion` so paper_runner.py can track them before going live.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
