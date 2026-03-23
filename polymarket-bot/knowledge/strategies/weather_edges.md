# Weather Trading Edges — Data Latency Arbitrage

> Type: strategy
> Tags: weather, NOAA, AccuWeather, Kalshi, Polymarket, temperature, precipitation, hurricane
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
NOAA and AccuWeather data updates lag behind Polymarket and Kalshi weather contract pricing, creating arbitrage windows. ColdMath wallet ($80K) has profited from rare weather events using this edge.

## Key Facts
- NOAA data updates on known schedules — weather contract markets often misprice during data releases
- AccuWeather and NOAA divergence signals are valuable — when sources disagree, markets often follow NOAA
- ColdMath wallet has $80K+ profit from rare weather events (extreme temp, hurricane landfalls)
- Target markets: temperature ranges, precipitation totals, hurricane categories on both Kalshi and Polymarket
- Kalshi has dedicated weather contract series with binary $1.00 payouts
- Implemented in `weather_trader.py` (Polymarket) and `kalshi_weather.py` (Kalshi)
- Seasonal patterns: hurricane season (June-Nov), winter storms, spring severe weather all have distinct edges

## Numbers
- **coldmath_profit**: $80,000+ on rare weather events
- **noaa_update_lag**: Minutes to hours before markets fully reprice
- **target_edge**: >5% divergence between data source and market price
- **kalshi_edge_threshold**: Configurable via `kalshi_edge_threshold` setting

## Links
- Related: [[wallets/coldmath_80k.md]]
- Market: [[markets/kalshi_markets.md]]
- Market: [[markets/polymarket_markets.md]]

## Raw Notes
Weather markets are unique because the underlying data (temperature, rainfall, wind speed) is
publicly available from government sources (NOAA) on known schedules. The edge comes from:
1. Processing NOAA data faster than other market participants
2. Recognizing when AccuWeather forecasts diverge from NOAA — NOAA is authoritative for settlement
3. Seasonal patterns where market makers misprice tail risk (e.g., hurricane category upgrades)

Both Kalshi and Polymarket offer weather contracts, so the same signal can trigger trades on both platforms via the signal bus.

## Action Items
- [ ] Build NOAA data polling automation for key stations
- [ ] Track AccuWeather vs NOAA divergence scores historically
- [ ] Map all active Kalshi weather contract series
