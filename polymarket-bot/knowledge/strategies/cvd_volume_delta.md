# CVD (Cumulative Volume Delta) Strategy

> Type: strategy
> Tags: crypto, volume, divergence, reversal
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: medium
> Status: active

## Summary
CVD measures net buying vs selling pressure. When price and volume delta diverge, it signals a potential reversal. Bearish divergence = price up but sellers dominating. Bullish divergence = price down but buyers accumulating.

## Key Facts
- Tracks buy vs sell volume from recent trades (last 500 trades)
- Normalized delta ranges from -1 (all sells) to +1 (all buys)
- Divergence threshold: 2% between price change and delta
- Confidence scales with divergence magnitude
- Works best on higher-volume tokens (XRP, HBAR)
- XCN may have insufficient volume for reliable signals

## Parameters
- lookback_trades: 500
- divergence_threshold: 0.02 (2%)
- poll_interval: 120 seconds
- trade_amount_usd: $50

## Related Strategies
- [[strategies/mean_reversion_params.md]] — RSI/BB complement CVD signals
- [[strategies/crypto_correlations.md]] — BTC correlation can confirm CVD signals
