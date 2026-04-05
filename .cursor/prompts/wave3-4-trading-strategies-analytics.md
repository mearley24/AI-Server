# Wave 3-4: Trading Strategies + Performance Analytics

**Priority:** HIGH — these are the revenue-generating strategies that justify the entire stack.
**Dependencies:** Waves 0-2 are shipped (Auto-5 health, Auto-8 risk, Auto-21 position syncer, API-1 RBI/CVD, Auto-10 intel feeds). All prerequisites are met.

---

## Context Files to Read First

Read these before writing ANY code — understand patterns, data shapes, and integration points:

- `polymarket-bot/strategies/base.py` — BaseStrategy ABC, `on_tick()` contract, `OpenOrder` dataclass
- `polymarket-bot/strategies/strategy_manager.py` — `STRATEGY_ALLOCATIONS`, `SharedPositionRegistry`, how strategies are registered and run
- `polymarket-bot/strategies/llm_validator.py` — `ValidationResult`, `validate_trade()`, the `approved`/`reasoning` fields
- `polymarket-bot/strategies/polymarket_copytrade.py` — patterns for Gamma API scanning, placing limit orders, deduplicating with `_active_condition_ids`
- `polymarket-bot/strategies/spread_arb.py` — existing arb scanner patterns
- `polymarket-bot/strategies/stink_bid.py` — exists but NOT wired into strategy_manager
- `polymarket-bot/strategies/flash_crash.py` — exists but NOT wired
- `polymarket-bot/src/client.py` — `get_markets()`, `place_order()`, `get_positions()`, `ORDER_TYPE_GTC`
- `polymarket-bot/src/websocket_client.py` — orderbook feed
- `polymarket-bot/paper_runner.py` — paper trading infrastructure
- `polymarket-bot/heartbeat/strategy_review.py` — parameter tuning
- `polymarket-bot/AGENT_LEARNINGS.md` — prior strategy insights
- `polymarket-bot/ideas.txt` — MeanReversion and PresolutionScalp entries
- `polymarket-bot/docs/multi_strategy_architecture.md` — architecture overview
- `cursor-prompts/DONE/Auto-6-mean-reversion-strategy.md` — full spec
- `cursor-prompts/DONE/Auto-7-presolution-scalp.md` — full spec (very detailed, ~12KB)
- `cursor-prompts/DONE/Auto-1-cross-platform-arb.md` — full spec
- `cursor-prompts/DONE/Auto-2-liquidity-provision.md` — full spec
- `cursor-prompts/DONE/Auto-11-stink-bid-flash-crash.md` — full spec
- `cursor-prompts/DONE/Auto-20-performance-analytics.md` — full spec
- `cursor-prompts/DONE/Auto-14-network-guard-deploy.md` — full spec
- `cursor-prompts/DONE/Auto-15-ollama-maestro-setup.md` — full spec

---

## Part 1: Auto-6 — Mean Reversion Strategy

**New file: `polymarket-bot/strategies/mean_reversion.py`**

Build a `MeanReversion` strategy class subclassing `BaseStrategy`:

1. **Core logic**: Monitor active markets via Gamma API for 24h price change. When a market moves >30¢ in <12 hours on volume <1,000 shares → fade candidate. Buy the opposite side. Target: reversion to 50% of the move.

2. **Entry filters**:
   - Only binary YES/NO markets (no multi-outcome)
   - Min time to resolution: 24 hours
   - Skip weather markets (real moves, not manipulation)
   - Skip markets already in SharedPositionRegistry
   - Max entry price: 25¢ on the fade side

3. **Exit rules**:
   - Take profit at 50% reversion (configurable)
   - Stop loss at -40%
   - Time stop: 6 hours max hold

4. **Validation**: Cross-reference copytrade data — if multiple high-quality wallets (>70% WR) entered same direction, skip (real movement). Check orderbook depth — spread >5¢ → skip (illiquid).

5. Wire into `strategy_manager.py` under the spread/arb bankroll allocation (25%).

6. Paper trading: publish signals to Redis `signals:mean_reversion` for `paper_runner.py`.

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.

---

## Part 2: Auto-7 — Pre-Resolution Scalp Strategy

**New file: `polymarket-bot/strategies/presolution_scalp.py`**

This is the highest-detail spec — read `cursor-prompts/DONE/Auto-7-presolution-scalp.md` end to end. It contains complete code for every method. Build EXACTLY what's specified there. Key points:

1. **Edge**: Near-certain markets misprice the losing side at 3-8¢. Buy cheap side, hold through resolution. 20:1 payoff. ~5% win rate is profitable.

2. **Scanner**: Run every 5 minutes (`TICK_INTERVAL_SECONDS = 300`). Fetch markets resolving within 1-3 hours. Min volume $10,000.

3. **Cheap side detection**: One side ≤8¢ (`MAX_ENTRY_PRICE = 0.08`). Min 100 shares available at ask.

4. **LLM validation**: Ask gpt-4o-mini "is the expensive side virtually certain?" — 5-second timeout. Cache per condition_id. Default to approved if LLM unavailable.

5. **Constants**: `POSITION_SIZE_USD = 3.00`, `MAX_POSITIONS = 20`, `MAX_TOTAL_EXPOSURE = 100.00`.

6. **Safety guards**: Position count limit, exposure cap, bankroll check.

7. **Exit**: Hold through resolution — no active exit. Detect resolution via `market["closed"]`, compute PNL, track `ScalpStats`.

8. **Tracking**: Persist stats to Redis `signals:presolution_scalp:stats` and history to `signals:presolution_scalp:history`.

9. **Registration**: Add to `STRATEGY_ALLOCATIONS` with `presolution_scalp: 0.15`. Adjust weather_trader down to 0.35.

10. **`PresolutionPosition` dataclass**: See spec for exact fields.

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.

---

## Part 3: Auto-11 — Stink Bid + Flash Crash + Sports Arb Wire-Up

The `StinkBidStrategy` and `FlashCrashStrategy` classes exist but are NOT wired into strategy_manager. Make them operational:

1. **Stink Bid** (`strategies/stink_bid.py`):
   - Review existing class, fix any structlog → standard logging
   - Wire into paper trader: publish to Redis `signals:stink_bid`
   - Crypto 5m/15m markets where current price >60¢
   - Place limit buy at 40¢ (or 20¢ below current), catch flash dips
   - TP: +15¢ from fill. SL: -10¢ from fill
   - Max 5 concurrent stink bids. Cancel unfilled after 30 min. Max $3/bid.

2. **Flash Crash** (`strategies/flash_crash.py`):
   - Review existing class, fix structlog → standard logging
   - Wire into paper trader: publish to Redis `signals:flash_crash`
   - Monitor WebSocket orderbook for sudden drops (≥30¢ in 10 seconds)
   - Buy immediately at market, target 50% reversion
   - SL: if price drops another 10¢ post-entry, cut
   - Max $10 per flash crash buy. Only on markets with >$50k volume.

3. **Sports Arb** (`strategies/sports_arb.py`):
   - Review existing class, fix structlog
   - Wire into paper trader: publish to Redis `signals:sports_arb`
   - Scan binary sports markets for combined YES+NO price < $0.98
   - Simultaneous buys on both sides for guaranteed profit
   - Size based on available liquidity (min 100 shares each side)

4. **Integration**:
   - Add all three as sub-strategies under strategy_manager.py
   - Stink Bid + Flash Crash share CVD/arb 25% allocation
   - Sports Arb: carved-out 5% of total bankroll
   - All three register positions in SharedPositionRegistry
   - ALL run in paper-only mode for 48 hours before live

---

## Part 4: Auto-2 — Liquidity Provision Upgrade

**File: `polymarket-bot/strategies/liquidity_provider.py`** (expand existing)

Upgrade the liquidity provider to implement market making:

1. Find illiquid Polymarket markets (spread > 5% between best bid/ask)
2. Place both a bid and an ask, collecting the spread
3. Max $50 per side per market
4. Auto-cancel if market moves >3% against you
5. Track daily P/L from spreads collected
6. Only provide liquidity in: weather, sports, crypto (skip politics/geopolitics)
7. Run every 2 minutes scanning for opportunities
8. Notify via Redis when daily P/L crosses $50 or -$25

---

## Part 5: Auto-1 — Cross-Platform Arbitrage Scanner

**File: `polymarket-bot/strategies/spread_arb.py`** (add method)

Add `_scan_cross_platform()` to spread_arb.py:

1. Fetch active markets from Polymarket (gamma-api) and Kalshi
2. Match markets by title/slug similarity (fuzzy match on question)
3. When same event priced differently (>3% spread) → flag as arb
4. Buy low on one platform, sell high on the other
5. Account for fees on both platforms
6. If Kalshi API code doesn't exist → create `polymarket-bot/strategies/kalshi_client.py` with public Kalshi API (GET `https://api.elections.kalshi.com/trade-api/v2/markets`)
7. Add `_scan_cross_platform` to `scan_once()` method

---

## Part 6: Auto-20 — Performance Analytics & Backtester

Build a proper analytics system so we can measure what's working:

1. **Trade database** (`polymarket-bot/analytics/trade_db.py`):
   - SQLite recording every trade: entry/exit time, strategy, market, prices, shares, fees, P/L, outcome
   - Migrate existing Redis/log trade history into this DB
   - Auto-record all new trades via hooks in each strategy's execute method

2. **Strategy analytics** (`polymarket-bot/analytics/strategy_stats.py`):
   - Per-strategy: win rate, avg P/L per trade, Sharpe ratio, max drawdown, avg hold time, best/worst trade
   - Rolling 7-day and 30-day windows
   - Strategy correlation analysis
   - Category breakdown: P/L by market category

3. **Backtester** (`polymarket-bot/analytics/backtester.py`):
   - Replay historical market data through a strategy
   - Use saved Gamma API snapshots (start saving hourly snapshots)
   - CLI: `python3 backtester.py --strategy mean_reversion --days 7`
   - Output: simulated P/L curve, trade count, win rate, drawdown

4. **Weekly report** (auto-generated every Sunday):
   - Full performance breakdown by strategy
   - Best/worst markets, bankroll growth
   - Recommendations: which strategies to scale up/down
   - Send via iMessage to Matt

5. **Self-tuning** (`polymarket-bot/heartbeat/parameter_tuner.py` — expand):
   - If win rate <45% → recommend pause
   - If avg P/L negative 7 consecutive days → auto-pause and alert
   - Log recommendations to AGENT_LEARNINGS.md

6. **Market data snapshots**: Save hourly snapshot of all active markets to `polymarket-bot/data/snapshots/`. Retain 30 days.

---

## Part 7: Auto-14 — Network Guard Daemon

Deploy network monitoring on Bob (runs on HOST, not Docker):

1. **Fix and deploy** (`tools/network_guard_daemon.py`):
   - Gateway ping + packet loss + jitter checks (macOS compatible)
   - Control4 controller reachability (ping configured IP)
   - Cooldown: max 1 alert per endpoint per 15 min
   - On drop: create task board incident, iMessage Matt. On recover: resolve + notify.

2. **Docker network checks**:
   - Verify all containers reach Redis at 172.18.0.100
   - Verify VPN container has internet (ping 1.1.1.1 from inside VPN)
   - VPN down → immediate alert (bot can't trade without VPN)

3. **Launchd service** (`setup/launchd/com.symphony.network-guard.plist`):
   - Run every 5 min, log to `/tmp/network-guard.log`, auto-start on boot

4. **Mission Control integration**: Publish network status to Redis `system:network` every check.

---

## Part 8: Auto-15 — Ollama on Maestro (64GB iMac)

Set up local LLM inference on Maestro:

1. **Setup script** (`setup/ollama_worker/setup_maestro.sh`):
   - Install Ollama, pull `llama3.1:8b`, `codellama:13b`, `nomic-embed-text`
   - Configure `OLLAMA_HOST=0.0.0.0:11434`
   - Create launchd service for auto-start

2. **Bob → Maestro routing** (`setup/ollama_worker/ollama_router.py`):
   - FastAPI proxy on Bob (port 11435) routing to Maestro
   - Health check every 30s; if offline → fall back to OpenAI
   - Load balancing: queue > 3 → overflow to OpenAI
   - Track tokens: local vs OpenAI (cost savings metric)

3. **Integration**: Replace OpenAI calls where possible:
   - `email-monitor/analyzer.py`: switch to llama3.1:8b for triage
   - `polymarket-bot/strategies/llm_validator.py`: local pre-screening, escalate uncertain to GPT-4o
   - Keep GPT-4o/Claude for: complex reasoning, proposals, client comms

4. **Embeddings**: Use `nomic-embed-text` on Maestro for all vector ops. ChromaDB points to Maestro's embedding endpoint.

5. **Monitoring**: Maestro health in Mission Control, daily cost savings report, alert if offline >10 min.

---

## Execution Notes

- **Build order within this prompt**: Auto-6 → Auto-7 → Auto-11 → Auto-2 → Auto-1 → Auto-20 → Auto-14 → Auto-15
- **All new strategies start in paper-only mode** — publish to `signals:` Redis channels, run through `paper_runner.py`
- **Commit each part separately** with descriptive messages (e.g., `feat: add mean reversion strategy (Auto-6)`)
- **Test each strategy imports cleanly**: `python -c "from strategies.mean_reversion import MeanReversion; print('OK')"`
- Redis at `redis://172.18.0.100:6379` inside Docker
- Use standard logging throughout (NO structlog)
- Push to origin main when done
