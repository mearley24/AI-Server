# Crypto Correlations — BTC Momentum to Altcoin Delay

> Type: strategy
> Tags: crypto, BTC, correlation, XRP, HBAR, altcoin, momentum, timing
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
BTC momentum signals propagate to altcoins with a 9-16 second delay, especially visible on Kraken for XRP and HBAR. This is an adaptation of the Polymarket latency pattern applied to crypto spot markets.

## Key Facts
- BTC >0.11% move on Binance precedes altcoin repricing by 9-16 seconds
- XRP and HBAR show the strongest BTC correlation with measurable lag
- Adapted from the Polymarket latency detector pattern for crypto spot trading on Kraken
- CCXT library provides unified API across Kraken, Coinbase, Binance for execution
- XCN and PI show weaker but still tradable correlation
- Implemented in `btc_correlation.py` strategy via crypto platform client

## Numbers
- **btc_momentum_threshold**: 0.11% (same as latency detector)
- **delay_window**: 9-16 seconds
- **strongest_correlation**: XRP, HBAR
- **moderate_correlation**: XCN, PI
- **default_trade_size**: $50 per trade (configurable)

## Links
- Related: [[strategies/latency_patterns.md]]
- Related: [[markets/crypto_tokens.md]]

## Raw Notes
The BTC-to-altcoin delay is a well-known phenomenon in crypto markets, but the specific
9-16 second window optimized from the Polymarket latency detector research provides a more
precise entry signal than generic "BTC leads alts" strategies.

Key implementation details:
- Binance WebSocket for BTC price feed (lowest latency)
- Kraken REST API for altcoin order execution (via CCXT)
- Signal bus routes BTC momentum signals to both latency_detector and btc_correlation simultaneously
- Position sizing: $50 default, configurable via `crypto_trade_amount_usd`

## Action Items
- [ ] Measure exact lag per token (XRP vs HBAR vs XCN) to optimize per-token timing
- [ ] Test on Coinbase as alternative exchange for execution
- [ ] Track win rate by BTC move magnitude (0.11% vs 0.2% vs 0.5%)
