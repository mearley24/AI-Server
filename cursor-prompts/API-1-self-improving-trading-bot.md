# API-1: Self-Improving Trading Bot — Full Stack

## Context Files to Read First
- polymarket-bot/docs/multi_strategy_architecture.md
- polymarket-bot/strategies/strategy_manager.py
- polymarket-bot/strategies/spread_arb.py
- polymarket-bot/strategies/weather_trader.py
- polymarket-bot/paper_runner.py
- polymarket-bot/ideas.txt

## Prompt

Build the complete self-improving trading system:

1. RBI Pipeline (polymarket-bot/strategies/rbi_pipeline.py):
   - Monitor ideas.txt for "pending" entries
   - For each: run 4-hour paper backtest using paper_runner infrastructure
   - If positive P/L after fees ($0.05 gas, 2% winner tax, 0.5% slippage): mark "validated", notify via Redis notifications:trading
   - If negative: mark "rejected" with data
   - Auto-promote: if an idea validates 3 times consecutively, add it to live strategies
   - Async loop, checks every 30 min
   - CLI: python rbi_pipeline.py --idea "name" --hours 4

2. Order Flow / CVD Divergence Detector (polymarket-bot/strategies/cvd_detector.py):
   - Inspired by @zostaff's CVD bot: price goes up but money flows out = sell, price drops but money flows in = buy
   - Monitor Polymarket CLOB orderbook for volume/price divergence
   - Track cumulative volume delta per market over 15-min windows
   - When divergence exceeds threshold (price moved >5% but CVD is opposite sign): generate signal
   - Log signals, publish to Redis for paper trader to act on
   - This is strategy #3 in the multi-strategy architecture

3. Wire strategy_manager.py to actually start all 3 strategies:
   - Weather cheap bracket (40% bankroll)
   - Filtered copytrade (35% bankroll)
   - CVD/arb combined (25% bankroll)
   - SharedPositionRegistry prevents overlap
   - Correlation monitoring every 15 min
   - Hourly P/L dashboard via iMessage
   - Update polymarket-bot/src/main.py to initialize StrategyManager and start all strategies

4. Intel feeds auto-feeding ideas:
   - When integrations/intel_feeds/signal_aggregator.py detects a high-relevance signal (score >80), auto-create an entry in ideas.txt with status "pending"
   - The RBI pipeline picks it up automatically
   - Complete the loop: intel finds idea → paper tests it → winner goes live

Use standard logging (not structlog) for anything called from imessage-server.py. Redis at redis://172.18.0.100:6379 inside Docker, redis://localhost:6379 on host.

Commit each major piece separately. Push to origin main.
