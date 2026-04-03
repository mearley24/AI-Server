# Auto-7: Pre-Resolution Scalp Strategy

## Context Files to Read First
- polymarket-bot/ideas.txt (PresolutionScalp entry)
- polymarket-bot/strategies/base.py
- polymarket-bot/strategies/weather_trader.py
- polymarket-bot/src/market_scanner.py

## Prompt

Build the PresolutionScalp strategy in `polymarket-bot/strategies/presolution_scalp.py`:

1. Core logic:
   - Scan all markets within 2 hours of resolution (use `end_date_iso` from Gamma API)
   - Find markets where one side is priced ≥95¢ (heavy favorite)
   - Buy the cheap side (≤5¢) for tail risk
   - Resolution is never 100% certain — smart contract bugs, oracle delays, ambiguous question wording all create 1-5% tail risk that markets underprice

2. Entry filters:
   - Only markets with clear resolution sources (price feeds, government data, weather — not panel judgment or subjective)
   - Parse the `resolution_source` field or market description to classify resolution type
   - Min market volume: $25k (ensures liquidity and the 95¢ side is well-traded)
   - Max position: $5 per scalp (many small bets, not one big one)
   - Skip any market we already hold a position in

3. Position management:
   - No stop loss needed (max loss is $5 per scalp)
   - Hold to resolution (these are <2 hour holds)
   - Expected hit rate: ~2-5% → need 800%+ payoff per hit to be profitable
   - At 3¢ entry, a win pays $0.97 profit per share (32x return)

4. Tracking:
   - Log every scalp: market, entry price, resolution outcome, P/L
   - Daily summary: total scalps, hits, misses, net P/L
   - Publish to Redis `signals:presolution_scalp`

5. Wire into strategy_manager.py under the spread/arb umbrella. This runs on a faster loop than other strategies — check every 5 minutes for markets entering the 2-hour window.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
