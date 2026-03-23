# Polymarket Markets — Polygon/USDC Prediction Market

> Type: market
> Tags: Polymarket, Polygon, USDC, CLOB, prediction-market, crypto
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Polymarket is a Polygon/USDC-based prediction market with a CLOB API. Offers 5m/15m BTC/ETH/SOL up/down markets plus sports, politics, and event markets. User is on US waitlist — currently in observer mode.

## Key Facts
- Blockchain: Polygon (MATIC) with USDC settlement
- API: CLOB (Central Limit Order Book) with EIP-712 order signing
- Crypto markets: 5m and 15m BTC/ETH/SOL up/down binary markets
- Sports: binary outcome markets (win/lose) for major leagues
- Politics: election and policy outcome markets
- User is currently on US waitlist — observer mode active, paper trading only
- Gamma API for market discovery and metadata
- WebSocket feed for real-time orderbook data

## Numbers
- **settlement_token**: USDC on Polygon
- **crypto_timeframes**: 5m, 15m
- **crypto_assets**: BTC, ETH, SOL
- **signing_method**: EIP-712
- **api_type**: CLOB (REST + WebSocket)

## Active Strategy Coverage
- `stink_bid` — Low-ball limit orders on crypto 5m/15m markets
- `flash_crash` — Orderbook drops >30% in 10 seconds
- `weather_trader` — Weather event markets
- `sports_arb` — Binary sports outcome arbitrage
- `latency_detector` — BTC momentum repricing window

## Links
- Related: [[strategies/latency_patterns.md]]
- Related: [[strategies/sports_patterns.md]]
- Related: [[wallets/latency_167m.md]]

## Raw Notes
Polymarket offers the deepest liquidity for prediction markets globally. Key differences from Kalshi:
1. Not CFTC-regulated — offshore platform, US access is restricted
2. USDC settlement — requires crypto wallet (not bank transfer)
3. Deeper liquidity on most markets compared to Kalshi
4. More market categories and higher volume

Observer mode limitations:
- Can read all market data, orderbooks, and trade history
- Cannot place real orders (paper trading via paper_ledger.py)
- Full strategy evaluation and signal generation still works
- When US access opens, switch by setting POLY_DRY_RUN=false

## Action Items
- [ ] Monitor US waitlist status for Polymarket access
- [ ] Track paper trade P&L to validate strategies before going live
- [ ] Compare Polymarket vs Kalshi liquidity for overlapping markets
