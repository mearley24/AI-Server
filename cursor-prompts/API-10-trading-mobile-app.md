# API-10: Trading Mobile App — iOS Integration

## Context Files to Read First
- ios-app/SymphonyTrading/README.md
- api/trading_api.py
- api/mobile_api.py
- docs/TRADING_API_CONTRACT.md
- docs/APP_FLOW_STATE_BLUEPRINT.md
- polymarket-bot/api/routes.py

## Prompt

Wire the iOS trading app to the live Polymarket bot API:

1. **Trading API** (`api/trading_api.py` — expand):
   - `GET /api/portfolio` — current positions, P/L, bankroll, unrealized gains
   - `GET /api/trades` — recent trades with entry/exit prices, strategy source, outcome
   - `GET /api/strategies` — status of each strategy (running/paused, bankroll allocation, recent P/L)
   - `GET /api/markets/active` — markets we're currently positioned in
   - `POST /api/strategy/{name}/pause` — pause a strategy (owner auth required)
   - `POST /api/strategy/{name}/resume` — resume a strategy (owner auth required)
   - `GET /api/pnl/daily` — daily P/L for last 30 days (for charting)
   - `GET /api/pnl/by-strategy` — P/L breakdown by strategy
   - `GET /api/paper` — paper trading positions and results
   - Authentication: simple API key in header (`X-API-Key`) — no OAuth needed for personal use

2. **WebSocket** (`/ws/trades`):
   - Real-time trade notifications (same data as iMessage notifications but structured JSON)
   - Position updates when prices change
   - Strategy status changes

3. **Data formatting**:
   - All monetary values in USD with 2 decimal places
   - All percentages as decimals (0.15 not 15%)
   - Timestamps in ISO 8601 UTC
   - Consistent error format: `{"error": "message", "code": "ERROR_CODE"}`

4. **CORS**: Allow requests from `localhost:*` and the Tailscale IP range (100.x.x.x).

5. **Docker**: Add port 8421 mapping to the polymarket-bot service in docker-compose.yml.

6. **Health**: `GET /api/health` returns bot uptime, last trade time, Redis connectivity, VPN status.

Use standard logging.
