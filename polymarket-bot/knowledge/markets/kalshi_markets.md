# Kalshi Markets — CFTC-Regulated Prediction Market

> Type: market
> Tags: Kalshi, CFTC, prediction-market, binary, regulated
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Kalshi is a CFTC-regulated prediction market with binary contracts paying $1.00. Covers weather, economics, politics, sports, and crypto categories. Maker fees are ~4x lower than taker — always use limit orders.

## Key Facts
- CFTC-regulated exchange — legal for US residents
- Binary contracts: $1.00 payout on YES resolution, $0.00 on NO
- Categories: weather, economics (CPI/GDP/Fed), politics, sports, crypto price
- Maker fees ~4x lower than taker fees — always use limit orders
- RSA-PSS authentication for API access
- Demo environment available for testing (demo.kalshi.com)
- API supports market discovery, order placement, position tracking
- Settlement is deterministic — based on official data sources (NOAA, BLS, etc.)

## Numbers
- **max_payout**: $1.00 per contract
- **maker_fee_ratio**: ~4x lower than taker
- **api_environments**: demo, production
- **auth_method**: RSA-PSS
- **cpi_series**: KXCPI, KXCPIYOY
- **scan_interval**: Configurable via `kalshi_scan_interval`

## Key Contract Series
- **KXCPI** — Monthly CPI print contracts
- **KXCPIYOY** — Year-over-year CPI contracts
- **Weather** — Temperature ranges, precipitation, hurricane categories
- **Fed** — Federal funds rate target ranges
- **GDP** — Quarterly GDP growth rate ranges

## Links
- Related: [[strategies/fed_calendar.md]]
- Related: [[strategies/weather_edges.md]]

## Raw Notes
Kalshi's competitive advantage is regulatory clarity. As a CFTC-designated contract market (DCM),
it offers legal certainty that Polymarket (offshore) cannot. This means:
1. US bank transfers for funding (no crypto required)
2. Tax reporting is straightforward (1099 forms)
3. Contract settlement is based on official government data sources
4. Dispute resolution follows CFTC rules

For our bot, Kalshi is the primary platform for weather and economic indicator trading.
Polymarket remains the primary for crypto price and sports markets due to deeper liquidity.

## Action Items
- [ ] Map all active Kalshi contract series and their settlement sources
- [ ] Compare liquidity between Kalshi and Polymarket for overlapping markets
- [ ] Track maker vs taker fill rates on Kalshi
