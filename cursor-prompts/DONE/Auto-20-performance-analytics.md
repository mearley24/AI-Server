# Auto-20: Performance Analytics — Trading Strategy Backtester

## Context Files to Read First
- polymarket-bot/paper_runner.py
- polymarket-bot/src/pnl_tracker.py
- polymarket-bot/strategies/strategy_manager.py
- polymarket-bot/heartbeat/strategy_review.py
- polymarket-bot/AGENT_LEARNINGS.md

## Prompt

Build a proper analytics and backtesting system so we can measure what's actually working:

1. **Trade database** (`polymarket-bot/analytics/trade_db.py`):
   - SQLite database recording every trade: entry time, exit time, strategy, market, entry price, exit price, shares, fees, P/L, outcome
   - Migrate existing trade history from Redis/logs into this database
   - Auto-record all new trades (hook into each strategy's execute method)

2. **Strategy analytics** (`polymarket-bot/analytics/strategy_stats.py`):
   - Per-strategy metrics: win rate, avg P/L per trade, Sharpe ratio, max drawdown, avg hold time, best/worst trade
   - Rolling 7-day and 30-day performance windows
   - Strategy correlation: are two strategies betting on the same markets?
   - Category breakdown: P/L by market category (weather, sports, crypto, etc.)

3. **Backtester** (`polymarket-bot/analytics/backtester.py`):
   - Replay historical market data through a strategy to estimate performance
   - Use saved Gamma API snapshots (start saving hourly snapshots of active markets)
   - Backtest a new strategy before deploying live
   - Output: simulated P/L curve, trade count, win rate, drawdown
   - CLI: `python3 backtester.py --strategy mean_reversion --days 7`

4. **Weekly report** (auto-generated every Sunday):
   - Full performance breakdown by strategy
   - Best and worst performing markets
   - Bankroll growth chart (text-based ASCII)
   - Recommendations: which strategies to scale up/down based on recent performance
   - Send via iMessage to Matt

5. **Self-tuning** (`polymarket-bot/heartbeat/parameter_tuner.py` — expand):
   - Analyze last 30 days of trade data
   - If a strategy's win rate drops below 45%, recommend pausing
   - If a strategy's avg P/L is negative for 7 consecutive days, auto-pause and alert
   - If entry price caps are leaving money on the table (consistent wins near the cap), suggest raising
   - Log all recommendations to AGENT_LEARNINGS.md

6. **Market data snapshots**: Save hourly snapshot of all active Polymarket markets (price, volume, orderbook depth) to `polymarket-bot/data/snapshots/`. Retain 30 days. This powers the backtester.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
