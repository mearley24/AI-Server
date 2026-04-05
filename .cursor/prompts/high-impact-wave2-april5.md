# High Impact Wave 2 — April 5, 2026

## CRITICAL: Commit Rules

**YOU MUST commit and push after completing each wave.** Cursor worktrees get deleted — uncommitted work is lost forever.

After finishing each wave, immediately run:
```bash
cd /Users/bob/AI-Server
git add -A
git commit -m "<wave>: <brief description>"
git push origin main
```

Work ONLY in /Users/bob/AI-Server/. Do NOT create worktrees. All file paths must be absolute.

## Context

The polymarket-bot has 7 strategies loaded but most aren't executing trades. The infrastructure is solid (18 Docker services, all healthy, Redis authed, watchdog running). Now we need to make the trading bot actually profitable.

Current state from `docker logs polymarket-bot`:
- `copytrade` — running, placing trades, but exit errors from balance mismatches (7% haircut just deployed)
- `weather_trader` — loaded, scanning NOAA stations, but `open_positions: 0` and `entered_this_tick: 0`
- `sports_arb` — loaded, found 13 arb opportunities (`arb_negative_risk_found: count=13, best_pct=161.54`), but NOT executing them
- `liquidity_provider` — loaded but unknown if placing orders
- `flash_crash` — loaded but unknown if detecting events
- `stink_bid` — loaded but unknown if placing orders
- `strategy_manager` — exists but may not be orchestrating properly
- `kraken_mm` — code exists, activation added, but no API key set yet

Redis URL for polymarket-bot: must use `host.docker.internal` (not `redis`) because it runs on `network_mode: service:vpn`. Current password in `.env` as `REDIS_PASSWORD`.

Intel-feeds service is running and finding signals (Reddit, news, Polymarket volume) but signals don't trigger trades.

---

## Wave 1: Make Existing Strategies Actually Execute

### W1-1: Fix Sports Arb Execution

The arb scanner found 13 opportunities at 161% but didn't execute. In `/Users/bob/AI-Server/polymarket-bot/strategies/sports_arb.py`:

1. Add detailed logging at every decision point:
   - Log when an arb is found: market, YES price, NO price, combined, spread, estimated profit
   - Log when an arb is SKIPPED and why (threshold, liquidity, max position, already held)
   - Log when an arb is EXECUTED: order IDs, sizes, prices
   - Log when an arb FAILS: error message, which side failed

2. Check the execution path — is `_execute_arb()` or equivalent actually being called after detection? If there's a condition that prevents execution (e.g., paper mode, insufficient balance, missing approval), log it clearly.

3. Verify the arb threshold makes sense. Current: `arb_threshold=0.995`. This means YES+NO must be < $0.995 to trigger. That's a 0.5% spread. With the 161% arb found in logs, something is off — either the threshold isn't being applied correctly, or the execution path is blocked.

4. Add a `/arb/status` endpoint to the bot's health API:
   ```json
   {"enabled": true, "arbs_found_today": 13, "arbs_executed_today": 0, "last_arb": {...}, "reason_not_executed": "..."}
   ```

### W1-2: Fix Weather Trader Execution

Weather trader scans 7 NOAA stations and 200 Polymarket markets but enters 0 positions. In `/Users/bob/AI-Server/polymarket-bot/strategies/weather_trader.py`:

1. Add logging at every filter step:
   - How many markets match a city+date
   - Forecast temperature from NOAA
   - Which brackets are available and at what prices
   - Which brackets pass the max 25¢ filter
   - Why candidates = 0 (price too high? Already held? No cheap brackets?)

2. Check if the weather trader has access to the CLOB client to actually place orders. If it's read-only, wire it to the shared `PolymarketClient`.

3. Verify position tracking integrates with the shared position registry (strategy_manager). If weather_trader tracks its own positions separately, sync it with position_syncer on startup.

4. If the issue is that ALL weather brackets are above 25¢ for the scanned cities, lower the threshold to 35¢ or add more cities with cheaper brackets.

### W1-3: Verify Liquidity Provider, Flash Crash, Stink Bid

For each of these three strategies in `/Users/bob/AI-Server/polymarket-bot/strategies/`:

1. Check `docker logs polymarket-bot` for any load errors or tick activity
2. Add a tick counter and last_tick_time to each strategy's health output
3. If a strategy is loaded but never ticking, find why (missing dependency, config, or error in the run loop)
4. Each strategy should log at least: `{strategy}_tick_complete` with a summary every cycle

### W1-4: Commit

```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "W1: fix arb execution, weather trader entry, strategy health logging" && git push origin main
```

After pushing, rebuild and check:
```bash
docker compose up -d --build polymarket-bot && sleep 30
docker logs polymarket-bot --tail 50 2>&1 | grep -E "arb_|weather_|lp_|flash_|stink_|strategy_"
```

---

## Wave 2: Wire Intel Feeds → Trading Signals

### W2-1: Intel Feeds Signal Publishing

The intel-feeds service (`/Users/bob/AI-Server/integrations/intel_feeds/`) monitors Reddit, news RSS, and Polymarket volume. It stores signals in `/data/intel_feeds/signals.db` and routes them to review.

What's missing: signals aren't published to Redis for the trading bot to consume.

In `/Users/bob/AI-Server/integrations/intel_feeds/aggregator.py` (or wherever signals are routed):

1. When a signal scores above `critical_threshold` (80), publish to Redis:
   ```python
   redis_client.publish("polymarket:intel_signals", json.dumps({
       "type": "intel_signal",
       "source": signal.source,  # "reddit", "news", "polymarket_volume"
       "relevance": signal.relevance_score,
       "summary": signal.summary,
       "markets": signal.related_markets,  # list of market slugs/IDs if identified
       "timestamp": datetime.utcnow().isoformat()
   }))
   ```

2. For Polymarket volume spikes (`volume_multiplier >= 2.0x`), also publish:
   ```python
   redis_client.publish("polymarket:volume_alerts", json.dumps({
       "type": "volume_spike",
       "market_id": market_id,
       "current_volume": current,
       "average_volume": average,
       "multiplier": multiplier
   }))
   ```

### W2-2: Trading Bot Signal Consumer

In `/Users/bob/AI-Server/polymarket-bot/src/main.py`, the Redis listener already subscribes to `polymarket:ta_signals`. Extend it:

1. Also subscribe to `polymarket:intel_signals` and `polymarket:volume_alerts`
2. When an intel signal arrives with relevance >= 80:
   - Log it: `intel_signal_received`
   - Forward to the signal bus as `SignalType.MARKET_DATA`
   - The copytrade strategy can use this to boost confidence on matching markets
3. When a volume spike arrives:
   - Log it: `volume_spike_received`
   - Forward to signal bus
   - The arb scanner should check this market immediately (volume spikes often precede price dislocations)

### W2-3: Commit

```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "W2: intel feeds -> redis signals -> trading bot consumer" && git push origin main
```

After pushing:
```bash
docker compose up -d --build polymarket-bot intel-feeds && sleep 20
docker logs intel-feeds --tail 10 2>&1 | grep "signal\|publish"
docker logs polymarket-bot --tail 10 2>&1 | grep "intel_signal\|volume_spike\|redis.*listener"
```

---

## Wave 3: Strategy Manager Orchestration + Bankroll

### W3-1: Verify Strategy Manager

In `/Users/bob/AI-Server/polymarket-bot/strategies/strategy_manager.py`:

1. Check if the strategy manager's `run()` or `tick()` method is actually being called from main.py
2. Verify bankroll allocation is working:
   - Weather: 40% of total bankroll
   - Copytrade: 35%
   - Arb: 25%
3. Verify the shared position registry prevents duplicate entries across strategies
4. Add a `/strategies/status` API endpoint that returns:
   ```json
   {
     "strategy_manager": "enabled",
     "total_bankroll": 215.52,
     "strategies": {
       "weather_trader": {"allocated": 86.21, "deployed": 0, "positions": 0, "last_tick": "..."},
       "copytrade": {"allocated": 75.43, "deployed": 150, "positions": 38, "last_tick": "..."},
       "sports_arb": {"allocated": 53.88, "deployed": 0, "positions": 0, "last_tick": "..."}
     }
   }
   ```

### W3-2: Cross-Strategy Correlation Monitor

In the strategy manager:

1. Verify the correlation monitor is running — it should alert if two strategies are holding opposing positions on the same market
2. Log hourly: `strategy_dashboard` with per-strategy P/L, position count, and win rate
3. Publish the dashboard to Redis: `events:trading` → `{"type": "strategy_dashboard", "data": {...}}`

### W3-3: Ideas Queue

The strategy manager supports a producer-consumer `ideas.txt` file. Wire it:

1. The iMessage bridge should write trading ideas to `/data/polymarket/ideas.txt` when Matt texts something like "look into [market]" or "bet on [topic]"
2. The strategy manager reads ideas.txt, evaluates them via LLM, and either executes or explains why not
3. Log: `idea_received`, `idea_evaluated`, `idea_executed` or `idea_rejected`

### W3-4: Commit

```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "W3: strategy manager orchestration, bankroll splits, ideas queue" && git push origin main
```

After pushing:
```bash
docker compose up -d --build polymarket-bot && sleep 30
curl -s http://127.0.0.1:8430/strategies/status 2>/dev/null | python3 -m json.tool
```

---

## Wave 4: Kraken + Dashboard

### W4-1: Kraken Status Check

The Kraken Avellaneda market maker code exists but needs API credentials. Don't configure credentials in this prompt — just verify:

1. The activation code in main.py handles missing API key gracefully (already done)
2. The `/kraken/status` endpoint works and returns `{"enabled": false, "reason": "KRAKEN_API_KEY not set"}`
3. When API key IS set, the Avellaneda MM should:
   - Connect to Kraken websocket
   - Fetch XRP/USD orderbook
   - Place bid/ask quotes around mid with Avellaneda spread
   - Log every tick: `kraken_mm_tick` with mid_price, spread, inventory, open_orders

4. Add safety guards:
   - Max position size (configurable, default $500)
   - Max daily loss circuit breaker (default -$50)
   - Spread floor (never tighter than 0.1%)
   - Kill switch: if 3 consecutive ticks fail, pause for 5 minutes

### W4-2: Mission Control Trading View

In `/Users/bob/AI-Server/mission_control/`, add a `/trading` dashboard page:

1. Pull data from polymarket-bot API endpoints:
   - `/status` — overall bot health
   - `/positions` — open positions
   - `/strategies/status` — per-strategy dashboard
   - `/kraken/status` — Kraken MM status
2. Display:
   - Total portfolio value (wallet cash + position value)
   - Per-strategy P/L chart (can be simple table for now)
   - Open positions list with current price, entry price, P/L %
   - Recent trades (last 20)
3. Auto-refresh every 30 seconds
4. Must include the auth token in all API calls (read from URL query param)

### W4-3: Commit

```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "W4: kraken safety guards, mission control trading dashboard" && git push origin main
```

---

## Verification

After all waves, run:

```bash
# 1. All strategies reporting
docker logs polymarket-bot --tail 100 2>&1 | grep -E "strategy_loaded|tick_complete" | sort -u

# 2. Arb scanner executing
docker logs polymarket-bot --tail 100 2>&1 | grep "arb_"

# 3. Weather trader entering
docker logs polymarket-bot --tail 100 2>&1 | grep "weather_"

# 4. Intel signals flowing
docker logs polymarket-bot --tail 100 2>&1 | grep "intel_signal\|volume_spike"

# 5. Strategy dashboard
curl -s http://127.0.0.1:8430/strategies/status | python3 -m json.tool

# 6. Trading view
curl -s "http://127.0.0.1:8098/trading?token=$(grep MISSION_CONTROL_TOKEN /Users/bob/AI-Server/.env | cut -d= -f2)" | head -20

# 7. No Redis errors
docker logs polymarket-bot --tail 50 2>&1 | grep -i "redis.*error\|NOAUTH" | head -3
```

## Files to Create/Modify

| File | Action | Wave |
|------|--------|------|
| `polymarket-bot/strategies/sports_arb.py` | MODIFY | W1 |
| `polymarket-bot/strategies/weather_trader.py` | MODIFY | W1 |
| `polymarket-bot/strategies/liquidity_provider.py` | MODIFY | W1 |
| `polymarket-bot/strategies/flash_crash.py` | MODIFY | W1 |
| `polymarket-bot/strategies/stink_bid.py` | MODIFY | W1 |
| `polymarket-bot/api/routes.py` | MODIFY | W1, W3 |
| `integrations/intel_feeds/aggregator.py` | MODIFY | W2 |
| `polymarket-bot/src/main.py` | MODIFY | W2 |
| `polymarket-bot/strategies/strategy_manager.py` | MODIFY | W3 |
| `scripts/imessage-server.py` | MODIFY | W3 (ideas queue) |
| `polymarket-bot/strategies/crypto/avellaneda_market_maker.py` | MODIFY | W4 |
| `mission_control/templates/trading.html` | CREATE | W4 |
| `mission_control/main.py` | MODIFY | W4 |

## Constraints

- Do NOT break existing copytrade strategy — it's actively trading
- All Redis URLs must use env var `REDIS_URL`, never hardcode
- polymarket-bot uses `host.docker.internal` for Redis, not `redis`
- All new API endpoints must work without auth (bot runs on localhost)
- Mission Control endpoints require the `MISSION_CONTROL_TOKEN`
- Rebuild polymarket-bot after each wave: `docker compose up -d --build polymarket-bot`
- Test each strategy independently — one broken strategy must not crash others
- Log everything with structlog — no print statements
