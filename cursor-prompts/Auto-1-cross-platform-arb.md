# Auto-1: Cross-Platform Arbitrage Scanner

## Context Files to Read First
- polymarket-bot/strategies/spread_arb.py
- polymarket-bot/strategies/kalshi/ (if exists)

## Prompt

Add Kalshi cross-platform arbitrage to the spread_arb scanner.

Build a new method _scan_cross_platform() in spread_arb.py that:
1. Fetches active markets from both Polymarket (gamma-api) and Kalshi
2. Matches markets by title/slug similarity (fuzzy match on market question)
3. When the same event is priced differently (>3% spread), flag as arbitrage opportunity
4. Buy low on one platform, sell high on the other
5. Account for fees on both platforms

If the Kalshi API code doesn't exist, create polymarket-bot/strategies/kalshi_client.py with the public Kalshi API integration (GET https://api.elections.kalshi.com/trade-api/v2/markets).

Add _scan_cross_platform to the scan_once() method. Commit and push.
