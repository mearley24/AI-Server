# Crypto Token Intel — XRP, HBAR, XCN, PI

> Type: market
> Tags: crypto, XRP, HBAR, XCN, PI, Kraken, Coinbase, tokens
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Four altcoins targeted for spot trading: XRP (commodity, fully legal), HBAR (Grayscale trust filed), XCN (ERC-20, best on Coinbase), PI (only Kraken, low liquidity). Each has distinct exchange availability and trading characteristics.

## Key Facts

### XRP
- Classified as commodity (March 2026) — fully legal to trade in the US
- Available on Kraken and Coinbase with deep liquidity
- Shows strong BTC correlation with measurable lag (9-16s window)
- High volume, tight spreads — ideal for momentum and mean reversion strategies

### HBAR
- Grayscale trust filing submitted — institutional interest growing
- Available on Kraken and Coinbase
- Requires memo field for deposits on some exchanges — critical for transfers
- Strong BTC correlation, slightly less liquid than XRP
- Good candidate for BTC correlation and mean reversion strategies

### XCN
- ERC-20 token — transferable via Ethereum or L2s
- Best liquidity on Coinbase for centralized exchange trading
- Can DEX trade via Uniswap V3 for better pricing on large orders
- Lower liquidity than XRP/HBAR — wider spreads, smaller position sizes recommended
- Moderate BTC correlation

### PI (Pi Network)
- Only available on Kraken among major exchanges
- Very low liquidity — wide spreads, slippage risk
- 90% below all-time high — potential deep value or continued decline
- Large token unlock schedule ahead — supply pressure risk
- Smallest position sizes recommended due to liquidity constraints

## Numbers
- **xrp_status**: Commodity (legal)
- **hbar_catalyst**: Grayscale trust filing
- **xcn_type**: ERC-20
- **xcn_dex**: Uniswap V3
- **pi_exchange**: Kraken only
- **pi_from_ath**: ~90% below
- **default_trade_size**: $50 per trade

## Links
- Related: [[strategies/crypto_correlations.md]]
- Related: [[strategies/mean_reversion_params.md]]

## Raw Notes
Token selection criteria for the trading bot:
1. Available on supported exchanges (Kraken, Coinbase via CCXT)
2. Sufficient liquidity for automated trading ($50-500 orders)
3. Measurable BTC correlation for the correlation strategy
4. Technical analysis viability for mean reversion and momentum strategies

Risk hierarchy: XRP (lowest risk, most liquid) > HBAR > XCN > PI (highest risk, least liquid)

## Action Items
- [ ] Monitor HBAR Grayscale trust approval timeline
- [ ] Track PI token unlock schedule and impact on price
- [ ] Evaluate adding SOL or ETH to the crypto strategy portfolio
