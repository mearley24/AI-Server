# polymarket-bot Strategy Map

Generated 2026-04-17 (Category 8 campaign pass). Snapshot of every
strategy file in `strategies/` with status, purpose, and known params.

## Legend

- **active** — Registered with the strategy manager and confirmed
  ticking in `/status` at audit time.
- **partial** — Source present but not observed ticking (yet) or
  skipped by a guard (e.g. low_bankroll).
- **infra** — Support module, not a trading strategy itself.
- **unknown** — No clear caller. Candidate for removal.

## Tickers + snapshot values (2026-04-17 /status)

| Strategy | Status | Tick count / signals | Notes |
|---|---|---|---|
| `polymarket_copytrade.py` | active | 33 scored wallets, 56 whale signals active | Primary. Kelly + LLM validation. $30 daily-loss. |
| `stink_bid.py` | active | 813 ticks | Place bid 0.08 below price, 0.10 take-profit, 0.08 stop. |
| `flash_crash.py` | active | 544 ticks | 0.15 drop trigger, 10s window. |
| `sports_arb.py` | active | 177 ticks | arb_threshold 0.97, FOK orders. |
| `liquidity_provider.py` | active | running, 0 markets quoted (bankroll) | halted=false. |
| `kraken_mm` (embedded) | active | 357 ticks | XRP/USD, max_position 500 USDT, loss limit -50. |
| `cvd_detector.py` | active | 28 ticks | Cumulative-volume-delta arb. |
| `mean_reversion.py` | active | 29 ticks | Classic mean-reversion. |
| `presolution_scalp.py` | active | 29 ticks | Scalp pre-resolution markets. |
| `spread_arb.py` | partial | not in /status snapshot | Prompt G completed. |
| `weather_trader.py` | active | — (weather flow) | Accuracy scored on redeem. |
| `kalshi_client.py` + `kalshi/` | partial | DEMO mode | `KALSHI_DRY_RUN=true`, `KALSHI_ENVIRONMENT=demo`. |

## Support / infra modules

| File | Role |
|---|---|
| `base.py` | Base class for strategies. |
| `strategy_manager.py` | Registers + ticks strategies. |
| `ws_manager.py` | WebSocket lifecycle. |
| `exit_engine.py` | Exit/haircut logic (Lesson #17 target). |
| `correlation_tracker.py` | Correlation exposure cap (50% per category). |
| `kelly_sizing.py` | Kelly criterion position sizing. |
| `llm_completion.py`, `llm_validator.py` | LLM-driven strategy idea + validation. |
| `rbi_pipeline.py` | Research-Backtest-Implement meta-loop. |
| `sentiment_engine.py` | Sentiment scoring input. |
| `wallet_rolling_redis.py`, `wallet_scoring.py` | Copytrade wallet analytics. |
| `x_intel_processor.py` | Consumes `polymarket:intel_signals`. |
| `weather_accuracy.py` | Weather-market accuracy scoring. |

## Where to look first

- Live: `curl http://127.0.0.1:8430/status | python3 -m json.tool`
- Paper ledger: `polymarket-bot/data/paper_trades.jsonl`
- Redeemer summary: `data/polymarket/redeemer_summary.json`
- Config: `polymarket-bot/config.yaml`

## Before editing a strategy

1. Check `SAFETY_CHECKLIST.md` to confirm halted/loss guards are in
   place for the intended change.
2. Run a paper-mode pass (`dry_run: true` in config.yaml) before
   re-enabling live.
3. After code change, `docker compose up -d --build polymarket-bot`
   — `restart` is not enough (lesson #16).
