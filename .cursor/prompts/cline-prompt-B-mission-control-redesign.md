# Cline Prompt B: Mission Control — Trading-First Redesign

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push at the end.

## Goal
Redesign Mission Control from an ops dashboard into a trading dashboard. The current `/` shows email queue, calendar, AI employee cards. Trading should be the primary view.

## Backend — `mission_control/main.py`

Add these 4 API endpoints. Each should gracefully return empty/default data if the polymarket-bot is unreachable:

### `GET /api/wallet`
- Try to fetch from Redis key `portfolio:snapshot` first
- Fallback: HTTP GET to `http://polymarket-bot:8430/status`
- Return: `{ "usdc_balance": float, "position_value": float, "daily_pnl": float, "weekly_pnl": float }`
- On error: return `{ "usdc_balance": 0, "position_value": 0, "daily_pnl": 0, "weekly_pnl": 0, "error": "unavailable" }`

### `GET /api/positions`
- Try Redis key `portfolio:positions` or HTTP GET to `http://polymarket-bot:8430/positions`
- Return: `[{ "title": str, "category": str, "entry_price": float, "current_price": float, "pnl_pct": float, "value_usd": float, "hold_hours": float }]`
- On error: return `[]`

### `GET /api/pnl-series`
- Try Redis key `portfolio:pnl_series` (should be a JSON list of `{timestamp, cumulative_pnl}` entries)
- Return: `[{ "timestamp": str, "pnl": float }]`
- On error: return `[]`

### `GET /api/activity`
- Try Redis LRANGE on `events:trading` (last 50 entries)
- Fallback: read recent Docker logs from polymarket-bot
- Return: `[{ "timestamp": str, "type": str, "message": str }]`
- On error: return `[]`

For Redis access, use the existing Redis connection if mission_control already has one. Otherwise:
```python
import redis
_redis = None
def _get_redis():
    global _redis
    if _redis is None:
        try:
            _redis = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"), decode_responses=True, socket_timeout=2)
        except Exception:
            pass
    return _redis
```

For HTTP fallbacks to polymarket-bot, use `httpx` with a 3-second timeout.

## Frontend — `mission_control/static/index.html`

Replace the current content with a trading-first 3-column layout:

### Layout
- **Left column (250px fixed):** Portfolio summary card — USDC balance, total position value, daily P&L (green/red), 7-day P&L
- **Center column (flex):** Positions table (sortable by clicking headers: title, category, P&L%, value) + Chart.js line chart showing P&L over time
- **Right column (300px fixed):** Live activity feed showing recent trades, redemptions, strategy decisions. Auto-scrolls.

### Style
- Dark theme: body background `#000`, cards `#1c1c1e`, borders `#2c2c2e`
- Accent color: teal `#2dd4bf` for positive numbers, `#ef4444` for negative
- Font: `-apple-system, 'SF Pro Display', 'Inter', system-ui, sans-serif`
- Monospace for numbers: `'SF Mono', 'Fira Code', monospace`
- Cards with subtle border-radius (12px), padding 16px

### JavaScript
- Vanilla JS only (no frameworks)
- Include Chart.js from CDN: `https://cdn.jsdelivr.net/npm/chart.js`
- Auto-refresh all data every 30 seconds
- P&L chart: line chart, dark background, teal line, subtle grid
- Activity feed: poll `/api/activity` every 15 seconds, prepend new items
- Positions table: click column headers to sort
- Format currency with `$` prefix and 2 decimal places
- Format percentages with `%` suffix, color green/red based on sign

### Navigation
- Add a small nav bar at the top: "Trading" (active, bold) | "Ops" link
- "Ops" links to `/ops`

## Move existing ops content to `/ops`

In the backend:
- Add a route `GET /ops` that serves the OLD `index.html` content
- Rename current `mission_control/static/index.html` to `mission_control/static/ops.html` BEFORE creating the new index.html
- Wire `/ops` to serve `ops.html`

## Delete redundant files
- Check if `trading.html` or `dashboard.html` exist in `mission_control/static/` — if so, delete them since the new `index.html` replaces their purpose.

## Verify and commit
```bash
python3 -m py_compile mission_control/main.py && echo "COMPILE OK"
grep -c "api/wallet\|api/positions\|api/pnl-series\|api/activity" mission_control/main.py
echo "Should be 4+ (all endpoints present)"
test -f mission_control/static/ops.html && echo "ops.html exists"
test -f mission_control/static/index.html && echo "new index.html exists"
git add -A && git commit -m "feat: mission control — trading-first redesign with 3-column layout, ops moved to /ops"
git push origin main
```
