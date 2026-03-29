# AI-Server — Claude Code Instructions

## Project Overview
Polymarket copy-trading bot running on a Mac Mini ("Bob"). Copies high win-rate wallets, manages positions with smart exits, and learns from every trade. Part of a broader AI employee system (Symphony Smart Homes).

## Architecture
- **polymarket-bot/** — Main trading bot (Docker, port 8430)
- **mission_control/** — Dashboard (Docker, port 8098)
- **notification-hub/** — Redis → iMessage notifications (Docker, port 8095)
- **scripts/imessage-server.py** — Native macOS iMessage bridge (port 8199)
- **Wallet:** `0xa791E3090312981A1E18ed93238e480a03E7C0d2` (Polygon/Polymarket)

## Trading Lessons (CRITICAL — Read Before Any Trading Code Change)

### Lesson 1: Both-Sides Buying Trap
The bot copied wallets that took opposite sides of the same market (Buy Up AND Buy Down). Combined cost = $1.00 for a $1.00 payout = guaranteed loss after fees.
**FIX:** Opposite-side detection before every trade. Check `_active_condition_ids`.

### Lesson 2: Stale Positions Block Everything
Resolved markets have no orderbook. Price lookups fail silently. The position stays in `_positions` forever, blocking new trades.
**FIX:** If `get_midpoint()` fails AND position is older than category stale time, clean it up. Don't rely on price checks for cleanup.

### Lesson 3: Docker Env Vars Override Code Defaults
`docker-compose.yml` environment variables take precedence over Python defaults. Changed a value in code? Check docker-compose.yml too — it might be overriding you.

### Lesson 4: Sell Orders Must Use py-clob-client
The custom `client.place_order()` gets "Invalid domain key: types" from the CLOB API. Always use `self._clob_client.create_and_post_order()` with `OrderArgs` for both buys AND sells.

### Lesson 5: Category P/L Seed Data Must Reflect Reality
Old P/L seeds from day 1 (with bugs) suppressed profitable categories. Crypto was seeded at -$57 when actual resolved trades show +$65. Update seeds from RESOLVED positions, not from buggy historical data.

### Lesson 6: High Win-Rate Wallets Are the Entire Edge
Wallets with 90%+ WR on 20+ resolved trades bypass all soft limits. Don't throttle proven winners with correlation limits, category caps, or LLM validation.

### Lesson 7: FOK for Exits, GTC for Entries
Buy orders use GTC (sit on book at wallet's price). Sell orders need instant execution — use FOK with 5% slippage tolerance.

### Lesson 8: Bankroll Must Sync from Chain
Internal bankroll tracking drifts from reality (doesn't account for redemptions). Fetch real USDC.e balance from Polygon every 5 minutes.

### Lesson 9: Position Limits Must Be Generous
We've been burned by max_positions too low (20, then 35). Currently 100. The real constraint is bankroll, not arbitrary position counts.

### Lesson 10: iMessage Bridge Needs Specific Python Path
Must use `/opt/homebrew/bin/python3` with Full Disk Access. The system Python 3.9 doesn't have permission. Use `PYTHONUNBUFFERED=1` for log visibility.

## Code Conventions
- All notifications via `_notify(title, body)` — keep short (2-3 lines max for iMessage readability)
- Log with structlog: `logger.info("event_name", key=value)`
- Positions persisted to `/data/copytrade_positions.json`
- Category detection in `strategies/correlation_tracker.py` — keyword matching
- Exit params in `strategies/exit_engine.py` — per-category SL/trailing/stale timers

## Current Strategy Parameters (as of 2026-03-28)
- Max positions: 100
- Per-category cap: 50
- Correlation limit: 50% of bankroll per category
- High conviction bypass: WR >= 90% AND resolved >= 20
- Entry price range: $0.10 - $0.97
- Min source trade: $0.50
- Category multipliers: crypto 1.2x, sports 1.3x, weather 1.0x, politics 1.5x
- Re-entry: after trailing stop exit, watch for 10% dip or 2% momentum continuation

## Resolved Performance (17/17 wins, +$139)
- Crypto: +$65 (8 wins, avg 105% return)
- Sports: +$25 (7 wins, avg 135% return — best ROI)
- Weather: +$11 (2 wins)
- Politics: +$3 (profitable, small sample)

## Deploy Commands
```bash
# Bot
cd ~/AI-Server && git fetch origin && git reset --hard origin/main && docker compose build --no-cache polymarket-bot && docker compose up -d --force-recreate polymarket-bot

# iMessage bridge
PYTHONUNBUFFERED=1 nohup /opt/homebrew/bin/python3 ~/AI-Server/scripts/imessage-server.py > /tmp/imessage-bridge.log 2>&1 &
```
