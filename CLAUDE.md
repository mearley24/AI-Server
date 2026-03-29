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

## Current Strategy Parameters (as of 2026-03-29)
- Max positions: 100
- Per-category cap: 50
- High conviction bypass: WR >= 90% AND resolved >= 30 (raised from 20)
- Entry price range: $0.40 - $0.97 (raised floor from $0.10 — sub-40¢ has 35% WR)
- Default position size: $3 (NOT $5 — small positions have 78% WR)
- Scale to $5 only for >80% WR wallets
- Scale to $10 only for >90% WR wallets with >30 resolved in category
- NEVER >$10 per position
- Quiet hours: suppress new buys 11pm-5am MDT (midnight = 29% WR)
- Min source trade: $0.50
- Category multipliers: crypto_updown 1.2x, esports 1.0x, tennis 1.3x, weather 0.5x, politics 1.5x, us_sports 0.3x, soccer_intl 0.2x
- Both-sides guard: check EVENT SLUG not just condition ID
- Re-entry: after trailing stop exit, watch for 10% dip or 2% momentum continuation

## Real Performance (206 markets, full activity history)
- **True P/L: -$229.54** (deposited $386.49, have $156.95 in 32 open positions)
- Crypto up/down: 45W/15L (75%), +$57 net — BEST category
- Esports: 5W/2L (71%), +$28 net — big swings, keep
- Tennis: 6W/2L (75%), +$18 net — consistent
- Weather: 9W/12L (43%), +$4 net — barely positive, reduce size
- US sports: 4W/6L (40%), -$15 net — LOSING money
- Soccer intl: 2W/3L (40%), -$8 net — LOSING money
- High entry (>80¢) = 83% WR. Low entry (<40¢) = 35% WR.

## Deploy Commands
```bash
# Bot
cd ~/AI-Server && git fetch origin && git reset --hard origin/main && docker compose build --no-cache polymarket-bot && docker compose up -d --force-recreate polymarket-bot

# iMessage bridge
PYTHONUNBUFFERED=1 nohup /opt/homebrew/bin/python3 ~/AI-Server/scripts/imessage-server.py > /tmp/imessage-bridge.log 2>&1 &
```
