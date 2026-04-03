# API-10: Trading Mobile App — iOS + API Integration

## The Vision

A native iOS app where Matt can monitor the Polymarket trading bot in real time — live portfolio value, open positions, recent trades, per-strategy P/L breakdown — all from his iPhone. The API backend and iOS app shells exist. Wire the API to real Redis data and verify the iOS project is structurally clean.

Read the existing code first.

## Context Files to Read First

- `api/mobile_api.py`
- `api/trading_api.py`
- `ios-app/SymphonyTrading/` (directory structure — read all Swift files)
- `build_trading_simulator.sh`

## Prompt

### 1. Understand the Existing API Surface

Read `api/mobile_api.py` and `api/trading_api.py` end to end:
- What routes are already defined? What's missing?
- What data sources do they currently read from?
- Are any routes returning placeholder data instead of real Redis data?
- What auth mechanism (if any) is already wired?

Map every existing route to its Redis key pattern. This mapping is the foundation for everything below.

### 2. Wire Mobile API to Real Redis Portfolio Data

`mobile_api.py` must consume live `portfolio:snapshot` data written by Auto-21 (position reconciliation):

```python
# Redis key: portfolio:snapshot → JSON hash with full portfolio state
# Written by Auto-21 every 60 seconds

GET /api/mobile/portfolio
# Returns: {total_value, available_usdc, unrealized_pnl, daily_pnl, positions_count, last_updated}

GET /api/mobile/positions
# Returns: list of open positions from portfolio:snapshot.positions
# Each position: {market, position_id, side, size, avg_price, current_price, unrealized_pnl, strategy}

GET /api/mobile/trades/recent
# Returns: last 50 trades from Redis list: trades:recent
# Each trade: {trade_id, market, side, size, price, timestamp, strategy, outcome}

POST /api/mobile/alert-settings
# Body: {min_trade_size, alert_on_loss, alert_on_win, loss_threshold, win_threshold}
# Stored in Redis hash: mobile:alert_settings
# Returns: {success: true, settings: {...}}
```

If `portfolio:snapshot` does not exist in Redis (bot not running), return a structured error:
```json
{"error": "Portfolio data unavailable — trading bot may be offline", "code": "BOT_OFFLINE"}
```

### 3. Wire Trading API Routes

Read `trading_api.py` — verify these routes are registered and return real data:

```python
GET /api/portfolio           # Same as mobile portfolio but more detailed (for web)
GET /api/trades              # Full trade history (paginated: ?page=1&limit=50)
GET /api/strategies          # All strategies: name, status, bankroll_allocation, recent_pnl
GET /api/markets/active      # Markets currently positioned in
GET /api/pnl/daily           # Daily P/L for last 30 days (from Redis sorted set: pnl:daily)
GET /api/pnl/by-strategy     # P/L breakdown per strategy

POST /api/strategy/{name}/pause   # Auth required — pause a running strategy
POST /api/strategy/{name}/resume  # Auth required — resume a paused strategy

GET /api/paper               # Paper trading positions and results
GET /api/health              # Bot uptime, last trade time, Redis connectivity, VPN status
```

For pause/resume: verify the strategy name exists before acting. Write `strategy:{name}:paused = true` to Redis. The strategy runner must check this flag.

### 4. Authentication

Simple API key auth — no OAuth, no JWT, this is a personal tool:

```python
# All /api/* routes require: X-API-Key header
# Key stored in env var: TRADING_API_KEY
# On missing/wrong key: 401 {"error": "Unauthorized", "code": "INVALID_API_KEY"}
# Exception: /api/health — no auth required (for monitoring)
```

Add a middleware that checks the header on every request. Do not use per-route decorators.

### 5. Data Formatting Standards

Apply consistently across all endpoints:
- All monetary values: USD with 2 decimal places (float, not string — let the client format)
- All percentages: decimals (0.15 not 15.0)
- All timestamps: ISO 8601 UTC (`2026-04-03T16:24:35Z`)
- Consistent error format: `{"error": "Human readable message", "code": "SCREAMING_SNAKE_CASE"}`
- Null values for missing data — never omit fields

### 6. WebSocket: Real-Time Trade Feed

```python
WebSocket /ws/trades
# On connect: send current portfolio snapshot
# Subscribe to Redis pub/sub channel: trades:live
# Forward every trade event as JSON to connected WebSocket clients
# On disconnect: unsubscribe cleanly

# Trade event format:
{
  "event": "trade_executed",
  "market": "Will Trump tweet before 5pm?",
  "side": "YES",
  "size": 10.0,
  "price": 0.09,
  "strategy": "weather_arb",
  "timestamp": "2026-04-03T16:24:35Z"
}
```

Also forward position update events (when prices change significantly) and strategy status changes.

### 7. CORS Configuration

```python
# Allow:
# - localhost on any port (development)
# - 100.x.x.x range (Tailscale VPN — Matt's iPhone on VPN)
# Block all other origins

allowed_origins = [
    r"http://localhost:.*",
    r"http://100\.\d+\.\d+\.\d+:.*"
]
```

### 8. Docker Port Mapping

Add port 8421 to the `polymarket-bot` service in `docker-compose.yml`:

```yaml
polymarket-bot:
  ports:
    - "8421:8421"  # Trading API (mobile + web)
```

The trading API server starts inside the polymarket-bot container. If it runs as a separate process, add a supervisor entry or a secondary CMD.

### 9. iOS App Verification

Read all Swift files in `ios-app/SymphonyTrading/`:

- Verify the project structure is standard Xcode layout (Sources, Resources, Info.plist)
- Check that API base URL is configured via a constant or environment (not hardcoded to localhost)
- Verify each view model maps to the API endpoints defined above
- Flag any obvious Swift errors: force unwraps on optionals that could be nil, missing error handling on network calls, incorrect Codable conformance
- If `build_trading_simulator.sh` exists and Xcode CLI tools are available, run it and check for compile errors

Do not rewrite the iOS app. Just identify and fix structural issues.

### 10. Test: Verify All Endpoints

```bash
export API_KEY="your-key-here"

# Portfolio snapshot
curl -H "X-API-Key: $API_KEY" http://localhost:8421/api/mobile/portfolio

# Positions
curl -H "X-API-Key: $API_KEY" http://localhost:8421/api/mobile/positions

# Recent trades
curl -H "X-API-Key: $API_KEY" http://localhost:8421/api/mobile/trades/recent

# Alert settings
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"min_trade_size": 5.0, "alert_on_win": true, "win_threshold": 10.0}' \
  http://localhost:8421/api/mobile/alert-settings

# Health (no auth)
curl http://localhost:8421/api/health

# Strategies
curl -H "X-API-Key: $API_KEY" http://localhost:8421/api/strategies
```

Every response must be valid JSON with real data from Redis. No placeholder values.

Use standard logging. All log messages prefixed with `[trading-api]`.
