# Sports Arb Whale — $619K Binary Sports Wallet

> Type: wallet
> Tags: whale, sports, arbitrage, binary, Polymarket
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
A $619K wallet exploiting binary sports market arbitrage on Polymarket, buying both sides when YES+YES < $0.98 for a guaranteed profit. Executes ~21 trades per day with mechanical consistency.

## Key Facts
- Total observed volume: $619K across binary sports markets
- Pattern: buys both YES tokens when combined price < $0.98 (guaranteed >$0.02 profit per pair)
- Trade frequency: ~21 trades per day — highly consistent
- Markets: NBA, NFL, MLB, and soccer match outcome binaries
- Execution appears fully automated — mechanical timing and sizing
- This wallet's pattern is the basis for our sports_arb.py strategy

## Numbers
- **total_volume**: $619K
- **trades_per_day**: ~21
- **arb_threshold**: YES+YES < $0.98
- **min_profit_per_trade**: $0.02 per contract pair
- **target_sports**: NBA, NFL, MLB, soccer

## Links
- Strategy: [[strategies/sports_patterns.md]]
- Market: [[markets/polymarket_markets.md]]

## Raw Notes
This wallet demonstrates that consistent, small-edge arbitrage can be highly profitable at scale:
1. $0.02+ profit per trade * 21 trades/day * many contracts per trade = significant daily income
2. Risk is minimal — if both sides are bought, profit is guaranteed upon resolution
3. The main risk is resolution disputes (very rare on Polymarket)
4. Competition from other arb bots may be narrowing the available spread
5. The wallet's consistent ~21 trades/day suggests it has found a sustainable niche
