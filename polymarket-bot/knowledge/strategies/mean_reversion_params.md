# Mean Reversion Parameters — Bollinger Bands + RSI

> Type: strategy
> Tags: crypto, mean-reversion, RSI, Bollinger-Bands, technical-analysis
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: medium
> Status: active

## Summary
Bollinger Bands (20-period) combined with RSI (14-period) provide mean reversion signals for crypto spot trading. Oversold below RSI 30 / overbought above RSI 70 with BB penetration triggers entries.

## Key Facts
- Bollinger Bands: 20-period SMA with 2 standard deviation bands
- RSI: 14-period, oversold threshold at 30, overbought threshold at 70
- Combined signal: price touches lower BB + RSI < 30 = buy, upper BB + RSI > 70 = sell
- Default trade size: $50 per trade
- Applied to XRP, HBAR, XCN on Kraken via CCXT
- Implemented in `mean_reversion.py` strategy
- Best in ranging/choppy markets — performs poorly in strong trends

## Numbers
- **bb_period**: 20
- **bb_std_dev**: 2.0
- **rsi_period**: 14
- **rsi_oversold**: 30
- **rsi_overbought**: 70
- **default_trade_size**: $50
- **check_interval**: Configurable via `crypto_poll_interval_seconds`

## Links
- Related: [[markets/crypto_tokens.md]]

## Raw Notes
Mean reversion is a complementary strategy to momentum/correlation plays. While BTC correlation
and momentum strategies profit from trend continuation, mean reversion profits from extremes
reverting to the mean.

Key considerations:
- Works best on higher timeframes (1h+) for crypto — too much noise on shorter timeframes
- BB width indicates volatility regime — narrow bands suggest breakout incoming (avoid mean reversion)
- RSI divergence (price makes new low but RSI doesn't) is a stronger signal than RSI level alone
- Stop-loss placement: below the lower BB for longs, above upper BB for shorts

## Action Items
- [ ] Backtest optimal BB/RSI parameters per token
- [ ] Add BB width filter to avoid mean reversion during breakouts
- [ ] Track win rate by market regime (trending vs ranging)
