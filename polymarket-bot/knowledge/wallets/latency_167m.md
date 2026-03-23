# Latency Whale — $1.67M BTC Momentum Wallet

> Type: wallet
> Tags: whale, latency, BTC, momentum, Polymarket, timing
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
A $1.67M wallet that consistently enters Polymarket BTC 5m/15m markets within the 9-16 second window after BTC moves >0.11% on Binance. This wallet's pattern is the basis for our latency detector strategy.

## Key Facts
- Total observed volume: $1.67M across BTC 5m/15m up/down markets
- Entry timing: consistently within 9-16 seconds after BTC >0.11% move on Binance
- Targets: Polymarket 5m and 15m BTC up/down binary markets
- Pattern is highly consistent — suggests automated execution
- Win rate appears high based on market resolution data
- Wallet was identified through on-chain Polymarket (Polygon) transaction analysis

## Numbers
- **total_volume**: $1.67M
- **entry_delay**: 9-16 seconds post BTC move
- **momentum_threshold**: BTC >0.11% on Binance
- **target_markets**: BTC 5m up/down, BTC 15m up/down
- **confidence**: High (multiple independent observations)

## Links
- Strategy: [[strategies/latency_patterns.md]]
- Market: [[markets/polymarket_markets.md]]

## Raw Notes
This wallet was the original inspiration for the latency detector strategy. Key observations:
1. Never enters before 9 seconds — likely a deliberate delay to confirm the move
2. Rarely enters after 16 seconds — the window closes as other participants reprice
3. Position sizes are relatively large ($1K-10K per trade) suggesting high confidence
4. The pattern has been consistent over weeks of observation
5. Similar pattern adapted for crypto spot trading in btc_correlation.py
