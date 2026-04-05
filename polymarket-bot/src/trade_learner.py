"""Trading learning analytics.

Canonical implementation lives in the OpenClaw service at ``openclaw/trade_learner.py``
(``generate_trading_summary``, ``run_weekly_deep_analysis``), which reads
``DATA_DIR/polymarket/trades.csv`` and writes ``weekly_learning.json``.

This stub exists so repo layout matches the bot/orchestrator split; import from
OpenClaw when running tooling on the host with ``PYTHONPATH`` including ``openclaw``.
"""
