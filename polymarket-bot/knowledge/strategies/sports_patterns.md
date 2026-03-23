# Sports Arbitrage Patterns — Binary Market Inefficiencies

> Type: strategy
> Tags: sports, arbitrage, binary, Polymarket, odds
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Binary sports markets on Polymarket frequently have YES+YES pricing below $0.98 on complementary outcomes, creating risk-free arbitrage. A $619K wallet exploits this pattern with ~21 trades per day.

## Key Facts
- YES+YES < $0.98 on binary sports markets = guaranteed profit opportunity
- $619K wallet trades this pattern ~21 times per day (source: on-chain analysis)
- Binary markets: exactly two outcomes, one must resolve YES, combined should equal $1.00
- Spread below $0.98 means buying both sides locks in >$0.02 per contract
- Most common in: NBA, NFL, MLB, and soccer match outcomes
- Speed matters — inefficiencies close within minutes as arb bots converge
- Implemented in `sports_arb.py` strategy

## Numbers
- **whale_wallet_size**: $619K total volume observed
- **trades_per_day**: ~21 trades
- **arb_threshold**: YES+YES < $0.98
- **guaranteed_profit_per_trade**: >$0.02 per contract pair
- **typical_close_time**: Minutes (fast-moving arb)

## Links
- Related: [[wallets/sports_619k.md]]
- Market: [[markets/polymarket_markets.md]]

## Raw Notes
Sports arbitrage on prediction markets works differently than traditional sports betting arb:
1. Binary markets have only YES/NO — if YES+YES for both outcomes < $1.00, it's a guaranteed profit
2. Polymarket uses USDC settlement — no withdrawal delays
3. The $619K wallet shows a consistent, mechanical approach — likely automated
4. Key risk: market resolution disputes (rare but possible on Polymarket)

The `sports_arb.py` strategy scans for binary sports markets and calculates the combined YES price.
When below threshold, it places limit orders on both sides.

## Action Items
- [ ] Track arb window duration (how long does the spread persist?)
- [ ] Monitor wallet competition — are more bots entering this space?
- [ ] Consider extending to non-sports binary markets
