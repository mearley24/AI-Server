# Latency Patterns — BTC Momentum Repricing Window

> Type: strategy
> Tags: latency, BTC, momentum, timing, Binance, Polymarket, crypto
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
A proven 9-16 second repricing window exists after BTC moves >0.11% on Binance. Prediction markets and altcoins lag behind, creating a brief arbitrage window exploited by at least one $1.67M wallet.

## Key Facts
- BTC >0.11% move on Binance triggers a 9-16 second repricing window on Polymarket and altcoins
- $1.67M wallet consistently enters positions within this window (source: on-chain analysis)
- Window applies to both Polymarket 5m/15m BTC markets and crypto spot (XRP, HBAR on Kraken)
- Implemented in `latency_detector.py` for Polymarket and adapted in `btc_correlation.py` for crypto spot
- Binance WebSocket feed is the reference price source
- Entry after 9s, exit target by 16s — tighter windows show lower fill rates
- Pattern holds across different BTC volatility regimes

## Numbers
- **momentum_threshold**: 0.11% BTC move on Binance
- **entry_delay_min**: 9 seconds
- **entry_delay_max**: 16 seconds
- **whale_wallet_size**: $1.67M total volume observed
- **confidence_level**: High — multiple independent observations

## Links
- Related: [[wallets/latency_167m.md]]
- Strategy: [[strategies/crypto_correlations.md]]
- Market: [[markets/polymarket_markets.md]]
- Market: [[markets/crypto_tokens.md]]

## Raw Notes
The latency pattern was first identified from on-chain Polymarket data showing a specific wallet
consistently entering 5m/15m BTC up/down markets within seconds of large Binance moves. Backtesting
confirmed the 9-16s window is statistically significant. The same principle applies to crypto spot
markets where altcoins lag BTC momentum — this is the basis of the `btc_correlation` crypto strategy.

## Action Items
- [ ] Track fill rate at different entry delays (9s, 12s, 16s) to optimize timing
- [ ] Monitor if window narrows as more bots discover this edge
- [ ] Test pattern on ETH and SOL Polymarket markets (not just BTC)
