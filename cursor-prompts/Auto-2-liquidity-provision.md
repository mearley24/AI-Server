# Auto-2: Liquidity Provision Strategy

## Context Files to Read First
- polymarket-bot/strategies/liquidity_provider.py

## Prompt

Upgrade the liquidity provider to implement the @defiance_cr market making strategy:
1. Find new or illiquid Polymarket markets (spread > 5% between best bid and ask)
2. Place both a bid and an ask, collecting the spread
3. Position sizing: max $50 per side per market
4. Auto-cancel orders if the market moves >3% against you
5. Track daily P/L from spreads collected
6. Only provide liquidity in categories we understand: weather, sports, crypto
7. Avoid providing liquidity in politics/geopolitics (efficient markets, no edge)

The LP should run every 2 minutes scanning for opportunities.
Log every order placed and cancelled.
Notify via Redis when daily P/L crosses $50 or -$25.

Commit and push.
