# Tracked Whale Wallets — Master Registry

> Type: wallet
> Tags: wallets, whales, tracking, registry
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Master index of tracked whale wallets whose trading patterns inform our strategies. Each wallet has a dedicated knowledge file with detailed pattern analysis.

## Tracked Wallets

| Wallet | Volume | Primary Pattern | Strategy Link |
|--------|--------|-----------------|---------------|
| [[wallets/latency_167m.md\|Latency $1.67M]] | $1.67M | 9-16s BTC momentum window | latency_detector, btc_correlation |
| [[wallets/sports_619k.md\|Sports $619K]] | $619K | YES+YES < $0.98 sports arb | sports_arb |
| [[wallets/coldmath_80k.md\|ColdMath $80K]] | $80K | Rare weather events via NOAA | weather_trader, kalshi_weather |

## Key Facts
- Three wallets currently tracked — all show consistent, repeatable patterns
- Wallet analysis informs strategy parameters (timing, thresholds, position sizing)
- On-chain data from Polymarket (Polygon) is the primary data source
- Wallet patterns are validated against our own paper trade results

## Action Items
- [ ] Add automated wallet tracking via Polygon blockchain scanning
- [ ] Identify new whale wallets for pattern analysis
- [ ] Track wallet activity frequency to detect strategy changes
