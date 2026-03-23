# Fed Calendar — Economic Release Trading

> Type: strategy
> Tags: fed, FOMC, CPI, GDP, economics, Kalshi, rates
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
FOMC meetings, CPI releases, and GDP reports create predictable trading windows on Kalshi economic contracts. Positioning before releases and trading divergence from consensus are the primary edges.

## Key Facts
- FOMC meeting dates are published well in advance — 8 meetings per year
- CPI release schedule is fixed (BLS publishes annually) — markets move sharply on surprises
- GDP preliminary/revised reports create multiple trading windows per quarter
- Kalshi has dedicated series: KXCPI (monthly CPI), KXCPIYOY (year-over-year CPI)
- Pre-release positioning: markets tend to drift toward consensus in the 24h before releases
- Post-release: fastest repricing happens in first 30 seconds after data hits
- Implemented in `kalshi_fed.py` strategy

## Numbers
- **fomc_meetings_per_year**: 8
- **cpi_release_day**: Usually second Tuesday of the month, 8:30 AM ET
- **gdp_release_day**: Last Thursday of the month, 8:30 AM ET
- **kalshi_cpi_series**: KXCPI, KXCPIYOY
- **pre_release_window**: 24 hours before release
- **post_release_window**: 30 seconds for fastest repricing

## Links
- Market: [[markets/kalshi_markets.md]]

## Raw Notes
Economic indicator trading on Kalshi is relatively new but offers significant edges because:
1. Kalshi markets are CFTC-regulated with $1.00 binary payouts — clear risk/reward
2. Market participants are often retail and slower to incorporate consensus data
3. The economic release calendar is deterministic — no surprises about WHEN data comes
4. The surprise component (actual vs. consensus) drives immediate repricing

Strategy approach:
- Track Bloomberg/Reuters consensus estimates leading up to releases
- Position in the 24h before when markets haven't fully priced in consensus
- After release, trade any gap between actual data and current contract prices

## Action Items
- [ ] Build FOMC date calendar into strategy config
- [ ] Automate CPI consensus tracking from public sources
- [ ] Track Kalshi contract liquidity around economic releases
