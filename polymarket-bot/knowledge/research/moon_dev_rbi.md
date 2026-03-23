# Moon Dev RBI Framework — Research Backtest Implement

> Type: research
> Tags: framework, methodology, RBI, backtest, Moon-Dev, Polymarket
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: high
> Status: active

## Summary
Research-Backtest-Implement (RBI) framework from Moon Dev's Polymarket bot tutorial. A systematic methodology for developing trading strategies: research the pattern, backtest with historical data, then implement only proven edges.

## Key Facts
- RBI = Research → Backtest → Implement — strict sequential pipeline
- Research phase: gather data, identify patterns, formulate hypotheses
- Backtest phase: validate patterns against historical data before any live trading
- Implement phase: only code and deploy strategies with proven backtested edges
- Source: Moon Dev's Polymarket trading bot tutorial series
- This framework influenced our development workflow (Research → Spec → Build → Test → PR)
- Key principle: never implement a strategy that hasn't been validated through backtesting

## Links
- Related: [[strategies/latency_patterns.md]]
- Related: [[strategies/sports_patterns.md]]

## Raw Notes
The RBI framework is a disciplined approach to strategy development that prevents the common
mistake of implementing strategies based on intuition alone. Key takeaways:

1. Research is not just reading — it means gathering quantitative data
2. Backtesting must use out-of-sample data to avoid overfitting
3. Implementation should be the smallest part of the process — most time in R and B
4. Failed backtests are valuable — they prevent losing real money
5. The framework applies to any trading strategy, not just prediction markets

Our adaptation adds Spec and PR steps between Backtest and Implement for code quality and review.

## Action Items
- [ ] Set up historical data pipeline for backtesting new strategies
- [ ] Create backtesting harness using paper_ledger historical data
