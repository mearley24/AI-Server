# Wave 0-2: Foundation Hardening + Gap Verification

**Priority:** CRITICAL — everything else is built on top of these. Verify before moving forward.
**Status:** Waves 0-2 were "substantially shipped" across three Cursor prompts (ship-everything-april5.md, high-impact-wave2-april5.md, final-opus-april5.md). But "shipped" ≠ "verified working." This prompt closes every remaining gap.

---

## Context Files to Read First

Read ALL of these before writing code — understand what was already built and what's still broken:

- `docker-compose.yml` — health checks, startup deps, port bindings, network config
- `scripts/startup.sh` — if it exists, check it actually works
- `scripts/healthcheck.sh` — if it exists, check it catches real failures
- `.env` — current secrets (DO NOT commit this file)
- `polymarket-bot/src/main.py` — main trading loop, strategy initialization
- `polymarket-bot/strategies/strategy_manager.py` — multi-strategy coordinator, `STRATEGY_ALLOCATIONS`, `SharedPositionRegistry`
- `polymarket-bot/strategies/polymarket_copytrade.py` — copytrade strategy
- `polymarket-bot/strategies/weather_trader.py` — weather strategy (price enrichment was deployed, needs verification)
- `polymarket-bot/strategies/sports_arb.py` — found 13 arbs at 161%, didn't execute
- `polymarket-bot/strategies/spread_arb.py` — sizing issues with ~$50 balance
- `polymarket-bot/strategies/exit_engine.py` — exit logic
- `polymarket-bot/strategies/kelly_sizing.py` — `fetch_onchain_bankroll()`
- `polymarket-bot/strategies/wallet_scoring.py` — whale scoring
- `polymarket-bot/strategies/rbi_pipeline.py` — RBI pipeline
- `polymarket-bot/strategies/cvd_detector.py` — CVD signal producer
- `polymarket-bot/src/position_syncer.py` — position reconciliation
- `polymarket-bot/src/pnl_tracker.py` — P/L tracking
- `polymarket-bot/src/redeemer.py` — token redemption
- `polymarket-bot/paper_runner.py` — paper trading
- `integrations/intel_feeds/runner.py` — intel feed runner
- `integrations/intel_feeds/signal_aggregator.py` — signal scoring
- `orchestrator/core/bob_orchestrator.py` — 91-line action dispatcher
- `openclaw/orchestrator.py` — higher-level orchestrator
- `openclaw/auto_responder.py` — email draft builder
- `email-monitor/router.py` — email categorization
- `email-monitor/monitor.py` — polling loop
- `email-monitor/bid_triage.py` — bid analysis
- `polymarket-bot/src/security/vault.py` — secrets management
- `polymarket-bot/src/security/audit.py` — audit logging
- `polymarket-bot/tests/` — existing test files
- `cursor-prompts/DONE/Auto-5-docker-health-startup.md` — full spec
- `cursor-prompts/DONE/Auto-8-risk-management-hardening.md` — full spec
- `cursor-prompts/DONE/Auto-21-position-reconciliation.md` — full spec (~6KB)
- `cursor-prompts/DONE/API-1-self-improving-trading-bot.md` — full spec (~7KB)
- `cursor-prompts/DONE/API-2-bob-business-operator.md` — full spec (~7KB)
- `cursor-prompts/DONE/Auto-10-intel-feeds-deploy.md` — full spec
- `cursor-prompts/DONE/Auto-13-test-suite.md` — full spec
- `cursor-prompts/DONE/Auto-19-security-hardening.md` — full spec

---

## WAVE 0 — Auto-5: Docker Health & Startup Orchestration

### Verify Existing Implementation

Check if these were built during the ship-everything session:

1. **Health checks in docker-compose.yml**: Every service should have a `healthcheck:` block.
   - Redis: `redis-cli -a $REDIS_PASSWORD ping` every 10s, 3 retries
   - Polymarket bot: `/health` endpoint or heartbeat file check
   - Email monitor: IMAP connection alive check
   - Paper trader: heartbeat file check
   - All other services: appropriate checks
   - **If missing**: Add them now. Read the spec.

2. **Startup dependencies**: `depends_on` with `condition: service_healthy`
   - Redis starts first, everything else waits
   - **If missing**: Add them now.

3. **`scripts/startup.sh`**: Starts iMessage bridge first (host process), waits for port 8199, then `docker compose up -d --build`, tails logs 30s, sends iMessage confirming all healthy.
   - **If missing**: Create it per the spec.
   - **If exists**: Verify it actually works — check iMessage bridge start command, port wait logic, compose invocation.

4. **`scripts/healthcheck.sh`**: Checks all container health + iMessage bridge. Restarts unhealthy services. Notifies Matt.
   - **If missing**: Create it.
   - **If exists**: Verify it detects real failures.

5. **Restart policy**: All services should have `restart: unless-stopped`.

6. **Port binding**: ALL ports must bind `127.0.0.1:XXXX:XXXX` except Mission Control (8098 can bind `0.0.0.0` for Tailscale access).
   - Audit docker-compose.yml. Fix any that bind `0.0.0.0`.

---

## WAVE 1 — Safety & Reconciliation

### Auto-8: Risk Management Hardening — Verify All 5 Items

Check each was actually implemented. If missing, build it:

1. **Minimum market volume filter** in `polymarket_copytrade.py`:
   - Does `_should_copy_trade()` check market volume from Gamma API?
   - Does it block entry on <$10k volume?
   - Env var `MIN_MARKET_VOLUME_USD` present?
   - **Test**: `grep -n "volume" polymarket-bot/strategies/polymarket_copytrade.py`

2. **Whale wallet 30-day rolling gate** in `wallet_scoring.py`:
   - Does it track rolling 30-day WR per priority wallet?
   - Demote if WR <60%? Re-promote at 65% for 14 days?
   - Redis hash `wallet:rolling:{address}` used?
   - Daily recalculation in heartbeat?
   - **Test**: `grep -n "rolling" polymarket-bot/strategies/wallet_scoring.py`

3. **Bankroll sync** in `pnl_tracker.py`:
   - Hourly on-chain USDC.e balance query via Polygon RPC?
   - Sums estimated position market value?
   - Drift >10% → iMessage alert?
   - **Test**: `grep -n "drift\|on.chain\|polygon" polymarket-bot/src/pnl_tracker.py`

4. **Redemption audit** in `redeemer.py`:
   - Heartbeat timestamp to Redis?
   - Alert if winning shares unredeemed >10 minutes?
   - `/redeem_status` API endpoint?
   - **Test**: `grep -n "heartbeat\|redeem_status\|alert" polymarket-bot/src/redeemer.py`

5. **Category blacklist exceptions** in `polymarket_copytrade.py`:
   - Political markets at ≥92¢ with LLM confidence ≥0.70 allowed with $5 cap?
   - Logged as `category_exception`?
   - **Test**: `grep -n "category_exception\|0.92\|blacklist" polymarket-bot/strategies/polymarket_copytrade.py`

**For each missing item**: Implement it per the spec in `cursor-prompts/DONE/Auto-8-risk-management-hardening.md`.

### Auto-21: Position Reconciliation — Verify Full Implementation

This is the MOST CRITICAL piece — it's the single source of truth for the entire trading stack.

1. **Position Syncer** (`polymarket-bot/src/position_syncer.py`):
   - Does it exist?
   - Does it call `client.get_positions()` every 5 minutes?
   - Does it fetch current market prices from Gamma API?
   - Does it produce a `PositionSnapshot` dataclass with: `usdc_balance`, `positions`, `total_position_value`, `total_portfolio_value`, `unrealized_pnl`?
   - Does it save to Redis `portfolio:snapshot` and `portfolio:history`?
   - Does it save to `data/portfolio_snapshots.json`?

2. **Reconciliation with internal state**:
   - Compares syncer results with `pnl_tracker._open_positions`?
   - Discovers positions on-chain but not in tracker → logs `position_discovered`?
   - Removes positions from tracker if not on-chain → logs `position_vanished`?
   - Rebuilds `_active_condition_ids` and `_active_event_slugs` from on-chain?
   - Syncs `SharedPositionRegistry`?

3. **True bankroll calculation**:
   - `available_bankroll` = on-chain USDC.e only?
   - `total_portfolio_value` = USDC.e + position market value?
   - Kelly sizer uses `available_bankroll` for new trade sizing?
   - Strategy allocations based on `total_portfolio_value`?

4. **Startup recovery**:
   - On bot startup: sync runs BEFORE any strategy starts?
   - Populates `_active_condition_ids`, `_active_event_slugs`, `_open_positions` from on-chain?
   - Logs "Recovered X positions worth $Y"?

5. **Notifications**: All notifications show Available + Positions + Portfolio?

6. **Drift alerting**: >10% change in 5 min → alert. Portfolio <$500 → alert. USDC <$50 → alert.

7. **Redis keys**: `portfolio:snapshot`, `portfolio:history`, `portfolio:positions`, `portfolio:alerts` all populated?

8. **API**: `GET /api/portfolio` returns PositionSnapshot?

9. **Persistence**: On SIGTERM → dumps to `data/position_state.json`? On startup → loads as initial state?

**If anything is missing or broken**: Implement per `cursor-prompts/DONE/Auto-21-position-reconciliation.md`.

---

## WAVE 2 — Core Trading Substrate

### API-1: Self-Improving Trading Bot (RBI + CVD Wiring)

1. **Import health check** — run these, fix any failures:
   ```bash
   cd polymarket-bot && python -c "from strategies.rbi_pipeline import RBIPipeline; print('RBI OK')"
   cd polymarket-bot && python -c "from strategies.cvd_detector import CVDDetector; print('CVD OK')"
   cd polymarket-bot && python -c "from strategies.strategy_manager import StrategyManager; print('SM OK')"
   ```

2. **RBI wired into main loop**: Is `rbi_pipeline.run_cycle()` called every 30 minutes from `src/main.py`? If not, wire it in as an async background task.

3. **CVD detector connected**: Does it connect to Polymarket CLOB WebSocket? Does it produce signals? Are signals consumed by strategy_manager via `set_cvd_signal()` or Redis keys `cvd:signal:{condition_id}`?

4. **Strategy Manager orchestration**: Does it start all strategies with correct allocations (weather 40%, copytrade 35%, CVD/arb 25%)? Are there broken imports?

5. **Intel feeds → ideas.txt**: Do high-scoring signals (>80) auto-create entries in `ideas.txt`? Does RBI pick them up?

### API-2: Bob Business Operator (Email → Orchestrator → Action)

1. **email-monitor → bob_orchestrator wired**: When router.py categorizes an actionable email, does it call bob_orchestrator or publish to `email:actionable` Redis channel?

2. **bob_orchestrator handle_email_event**: Does it dispatch based on category → action (draft_response, triage_bid, escalate)?

3. **auto_responder wired**: Does it draft responses into Zoho as DRAFTS (not auto-send)?

4. **bid_triage → iMessage**: Does bid analysis summary go to Matt via iMessage?

5. **Decision matrix**: Does `agents/bob_conductor.yml` exist with routing table?

6. **Test**: Publish a mock email event to `email:actionable`, verify bob_orchestrator logs a response action.

### Auto-10: Intel Feeds — Verify Deployment

1. **Docker service**: Is `intel-feeds` in docker-compose.yml? Is it running?
2. **Monitors functional**: Reddit (old.reddit.com JSON), news (RSS), Polymarket (Gamma API volume spikes)?
3. **Signal aggregator**: Dedup across sources? Score 0-100? >80 → auto-create in ideas.txt?
4. **Runner**: Async loop, correct intervals (Reddit 15min, news 10min, Polymarket 5min)?
5. **Notification**: High-scoring signals → Redis `notifications:trading`?

### Auto-13: Test Suite — Verify Coverage

1. **Tests exist**: `polymarket-bot/tests/` populated with test files?
2. **Key test files**: `test_weather_trader.py`, `test_copytrade.py`, `test_exit_engine.py`, `test_strategy_manager.py`?
3. **Test infrastructure**: `conftest.py` with fixtures? `pytest.ini`?
4. **Run**: `cd polymarket-bot && pytest -v --tb=short 2>&1 | tail -30` — how many pass/fail?
5. **If minimal coverage**: Build tests per the spec in `cursor-prompts/DONE/Auto-13-test-suite.md`.

### Auto-19: Security Hardening — Verify Core Items

1. **Secrets**: `vault.py` wired as single source? Private keys NOT in `.env`?
2. **API auth**: Internal APIs have API key auth? Mission Control has basic auth?
3. **Audit logging**: `audit.py` logging trades, emails sent, proposals generated?
4. **Port binding**: All ports `127.0.0.1` except Mission Control?
5. **Wallet safety**: Max single trade $25 hardcoded? Daily loss limit -$50 → auto-pause?

---

## Bonus: Strategy Execution Verification

These issues were found during the high-impact-wave2 session. Verify they were fixed:

### Sports Arb Not Executing

- Found 13 arbs at 161% spread but executed 0
- Check `strategies/sports_arb.py` for the execution path
- Is `_execute_arb()` actually called after detection?
- Is there a paper_mode flag blocking it?
- Log at every decision point: found → skipped (why?) or → executed

### Weather Trader Empty Positions

- Price enrichment was added in final-opus-april5 (CLOB midpoint fetch)
- Verify: does `_enrich_with_prices()` actually populate `tokens[].price`?
- After enrichment: are brackets found at ≤25¢? If all brackets are expensive → lower threshold to 35¢ or add more cities
- Check `docker logs polymarket-bot 2>&1 | grep weather` for recent activity

### Spread Arb Low Balance

- ~$50 free wallet balance causes sizing failures
- Check minimum order size requirements in `strategies/spread_arb.py`
- Add a "low-balance mode": if available USDC < $100, reduce min position to $2, skip strategies that need >$10/side
- Log clearly when a trade is skipped due to insufficient balance (don't silently fail)

### Copytrade Exit Errors

- Exit engine had balance mismatch errors (7% haircut was deployed)
- Verify: does the 7% haircut in `exit_engine.py` prevent sell-for-more-than-balance errors?
- Check `docker logs polymarket-bot 2>&1 | grep "exit\|sell\|balance"` for recent errors

---

## Execution Notes

- **Build order**: Wave 0 (Auto-5) → Wave 1 (Auto-8, Auto-21) → Wave 2 (API-1, API-2, Auto-10, Auto-13, Auto-19) → Bonus verifications
- **This is primarily a VERIFICATION prompt** — most code exists. Check if it works. Fix what doesn't.
- **For each check**: If the feature exists and works → log PASS. If it exists but is broken → fix it. If it doesn't exist → build it per the spec.
- **Commit each wave separately**: `verify: wave 0 — docker health checks confirmed`, `fix: wave 1 — position syncer startup recovery missing`, etc.
- **Redis password**: `d1fff1065992d132b000c01d6012fa52` (the actual password on Bob — there was a mismatch fixed earlier)
- Redis at `redis://172.18.0.100:6379` inside Docker. Polymarket-bot uses `host.docker.internal` (VPN network).
- Use standard logging throughout (NO structlog)
- Push to origin main when done
