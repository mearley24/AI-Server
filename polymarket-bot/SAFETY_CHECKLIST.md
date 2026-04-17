# polymarket-bot Safety Checklist

Every active trading strategy has multiple guardrails. This page lists
them in one place so an agent responding to a trading incident can
find the full set of brakes.

## Global

- **dry_run** (config.yaml, env `POLY_DRY_RUN`) — if true, all
  platforms skip real orders and only log. Default: false (LIVE).
- **paper_ledger** — `paper_ledger.enabled: true` in config.yaml.
  Runs in parallel with live. `score_resolved_markets: true` scores
  hypothetical trades against on-chain resolution.
- **Bankroll gate** — strategies skip with `low_bankroll` when the
  on-chain USDC balance falls below thresholds. Re-read every 5 min.
- **VPN** — polymarket-bot only reaches Polymarket via the WireGuard
  container. If VPN container is down the bot is isolated.

## Per-strategy / embedded

| Strategy | Guardrail | Value |
|---|---|---|
| polymarket_copytrade | daily_loss_limit | $30 |
| polymarket_copytrade | max_positions | 30 |
| polymarket_copytrade | min_win_rate (wallet) | 0.6 |
| polymarket_copytrade | min_trades (wallet) | 20 |
| polymarket_copytrade | size_usd | $3 |
| polymarket_copytrade | correlation cap per category | 50% of bankroll |
| polymarket_copytrade | halted (runtime bool) | start-up state false |
| polymarket_copytrade | Kelly sizing | `kelly_enabled: true` |
| polymarket_copytrade | LLM validation | `llm_validation_enabled: true` |
| stink_bid | drop_threshold / take_profit / stop_loss | 0.08 / 0.10 / 0.08 |
| flash_crash | drop_threshold / window | 0.15 / 10s |
| flash_crash | take_profit / stop_loss | 0.15 / 0.10 |
| sports_arb | arb_threshold | 0.97 |
| sports_arb | max_position_per_side | $10 |
| kraken_mm | max_position_usdt | 500 |
| kraken_mm | max_daily_loss | -$50 |
| kraken_mm | spread_floor_bps | 10 |
| kraken_mm | consecutive_failures pause | on 3 fails |
| liquidity_provider | halted | true if no markets to quote |

## How to kill all trading, fast

1. Set global dry-run:
   ```
   bash scripts/set-env.sh POLY_DRY_RUN true
   docker compose restart polymarket-bot
   ```
2. Or stop the container:
   ```
   docker compose stop polymarket-bot
   ```
3. Or halt the VPN container (hardest shutdown — also cuts the
   redeemer):
   ```
   docker compose stop vpn
   ```

Option 1 keeps the redeemer running and lets strategies observe
without trading. Prefer this.

## Post-incident capture

```
bash scripts/trading-status-snapshot.sh
```

Writes a timestamped JSON + text dump to `ops/verification/<stamp>-
trading-status-snapshot.txt`.

## Related

- `STRATEGY_MAP.md` — status of every strategy file.
- `ops/MESSAGING_ALERTS.md` — what trading failures SHOULD alert
  Matt.
- `STATUS_REPORT.md` Trading State section — baseline blockers
  (bankroll funding, KRAKEN_SECRET, Kalshi demo).
