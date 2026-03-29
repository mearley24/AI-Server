# Bob's Complete Training Manual
*Everything learned across all sessions with Computer. Read this before any action.*

## Identity
Bob is a Mac Mini M4 running as a 24/7 AI employee for Symphony Smart Homes. Bob runs Docker services, trades on Polymarket, monitors emails, handles client communications, and executes autonomous workflows.

## Owner
- Name: Matt Earley
- Phone: +19705193013
- Email: earleystream@gmail.com (Zoho Mail, NOT Gmail)
- Business: Symphony Smart Homes
- iMessage: Reply to phone number, NEVER to bob@symphonysh.com (causes loop)

## Critical Lessons (Ordered by Cost of Learning)

### 1. Both-Sides Buying Trap ($57 lost)
The copy-trader was buying BOTH Up and Down outcomes from different wallets on the same crypto market. Paying $1 total for a $1 payout = guaranteed loss.
**Rule:** ALWAYS check `_active_condition_ids` before any trade. Never hold opposite sides.

### 2. 161 Trades in 30 Minutes ($242 deployed at once)
Bot had no pacing. Bankroll wasn't decrementing. One wallet could fill unlimited positions. Blew through entire bankroll in one burst.
**Rule:** Max 10 trades/hour. Bankroll decrements immediately on order placement. Daily loss circuit breaker at $50 realized.

### 3. Docker Env Vars Override Code (8+ failed deploys)
Changed `max_positions` in Python from 20 to 35. Bot still showed 20. `docker-compose.yml` had `COPYTRADE_MAX_POSITIONS:-20` which overrides the code default. Wasted an entire morning on this.
**Rule:** ALWAYS check docker-compose.yml env vars when changing any config. The env var wins over code defaults.

### 4. Stale Positions Block All Trading (12+ hours stuck)
Resolved markets have no orderbook. `get_midpoint()` fails silently. Position stays in `_positions` forever. Bot showed 20/20 full with 5 dead positions.
**Rule:** If price lookup fails AND position age > category stale time, clean it up. Don't rely on price for cleanup.

### 5. FOK Sell Orders Need py-clob-client
Custom `client.place_order()` for sells gets "Invalid domain key: types". Buys worked because they used `self._clob_client.create_and_post_order()`.
**Rule:** Use `create_and_post_order(OrderArgs(...))` for ALL orders, buys and sells.

### 6. Kraken Market Making — Every Guard Was Too Tight
The Avellaneda MM had: max_inventory=10 (actual was 208 XRP), max_inventory_usdt=$250 (actual worth $295), max_total_exposure=$250, stale balance data, Hawkes adjustment pushing prices 14% from mid.
**Rule:** For any trading system, set limits relative to ACTUAL capital, not hardcoded conservative defaults. Sync real balances, not cached ones.

### 7. Wallet Win Rates Are Inflated by Crypto Coin Flips
A wallet with "100% win rate" on crypto 5-min markets is actually a market maker buying both sides. Their per-side win rate is ~50%.
**Rule:** Score wallets by P/L ratio, not just win rate. Filter out both-sides activity.

### 8. Category P/L Seeds Must Match Reality
Seeded crypto at -$57 from day 1 bugs. Actual resolved performance is +$65 after fixes. Stale seeds suppressed multiplier to 0.15x when it should be 1.2x.
**Rule:** Update seeds from RESOLVED positions only. Re-evaluate monthly.

### 9. iMessage Bridge — Port, Python Path, Permissions
- Must use `/opt/homebrew/bin/python3` (not system Python 3.9)
- Needs Full Disk Access for reading Messages.app database
- Use `PYTHONUNBUFFERED=1` for log visibility
- Use `SO_REUSEADDR` + `SO_REUSEPORT` for clean restarts
- Script auto-kills old process on port 8199 at startup
- REPLY_TO must be +19705193013, NOT bob@symphonysh.com

### 10. Credit Conservation
Don't iterate — test thoroughly before pushing. Each failed deploy + log check + redeploy = credits burned. The Kraken MM session burned ~15 deploys fixing guards one at a time when they should have been caught in one review.

## Architecture

### Docker Services (docker-compose.yml)
| Service | Port | Purpose |
|---|---|---|
| polymarket-bot | 8430 | Copy-trading bot + redeemer |
| mission-control | 8098 | Dashboard + service health |
| notification-hub | 8095 | Redis → iMessage dispatch |
| openwebui | 3000 | Open WebUI interface |
| remediator | 8090 | Service remediation |
| proposals | 8091 | Proposal engine |
| email-monitor | 8092 | Email monitoring |
| voice-receptionist | 8093 | Voice/phone handling |
| calendar-agent | 8094 | Calendar management |
| dtools-bridge | 8096 | D-Tools integration |
| clawwork | 8097 | ClawWork automation |
| openclaw | 8099 | OpenClaw AI agent |
| knowledge-scanner | 8100 | Knowledge ingestion |

### Native macOS Services (not Docker)
| Service | Port | How to Start |
|---|---|---|
| iMessage bridge | 8199 | `PYTHONUNBUFFERED=1 /opt/homebrew/bin/python3 scripts/imessage-server.py` |

### Key Wallet
- Address: `0xa791E3090312981A1E18ed93238e480a03E7C0d2`
- Network: Polygon
- Assets: USDC.e + POL for gas

## Trading Strategy (Current)

### Copy-Trade Flow
1. Scan wallets every 6 hours via Gamma API + leaderboard
2. Monitor top wallets every 30 seconds for new trades
3. Validate: price bounds (0.10-0.97), not duplicate, not both-sides
4. High conviction (90%+ WR, 20+ trades) → bypass all soft limits
5. Kelly sizing with category multiplier
6. METAR weather check for weather trades
7. Place GTC buy order via py-clob-client
8. Exit engine checks every 30 seconds: trailing stop, stop-loss, stale exit
9. FOK sell via py-clob-client for exits
10. Re-entry queue: watch for dip after profitable trailing stop

### Category Performance (Resolved as of 2026-03-28)
| Category | P/L | Trades | Avg Return | Multiplier |
|---|---|---|---|---|
| Crypto | +$65 | 8 | +105% | 1.2x |
| Sports | +$25 | 7 | +135% | 1.3x |
| Weather | +$11 | 2 | +31% | 1.0x |
| Politics | +$3 | — | — | 1.5x |
| Other | +$3 | — | — | 1.0x |

### Priority Copy Wallets
- `0xde9f7f4e77a1595623ceb58e469f776257ccd43c` — @tradecraft (tennis, 2139% ROI)
- `0x594edb9112f526fa6a80b8f858a6379c8a2c1c11` — @coldmath (weather, $89K)

## Deploy Procedures

### Polymarket Bot (code changes)
```bash
cd ~/AI-Server && git fetch origin && git reset --hard origin/main && docker compose build --no-cache polymarket-bot && docker compose up -d --force-recreate polymarket-bot
```

### Polymarket Bot (env var changes only)
```bash
cd ~/AI-Server && git fetch origin && git reset --hard origin/main && docker compose up -d --force-recreate polymarket-bot
```

### iMessage Bridge
```bash
lsof -ti :8199 | xargs kill -9 2>/dev/null; sleep 2
PYTHONUNBUFFERED=1 nohup /opt/homebrew/bin/python3 ~/AI-Server/scripts/imessage-server.py > /tmp/imessage-bridge.log 2>&1 &
```

### Watch Trading
```bash
docker logs polymarket-bot -f 2>&1 | grep --line-buffered "executed\|Cleaned\|Exit\|Re-entry\|Watching\|New Trade\|Halted\|bankroll_synced"
```

### Quick Status
```bash
curl -s http://localhost:8430/status | python3 -c "import sys,json; d=json.load(sys.stdin)['strategies']['copytrade']; print(f'Positions: {d[\"open_positions\"]} | Trades: {d[\"daily_trades\"]} | Bank: \${d[\"bankroll\"]:.0f}')"
```

## Anti-Patterns (Things That Wasted Credits/Money)
1. Pushing incremental fixes instead of batching — each deploy cycle costs credits
2. Not checking docker-compose.yml after changing code defaults
3. Guessing at issues instead of reading logs first
4. Setting limits too conservative then loosening one at a time
5. Not testing sell orders before deploying (the py-clob-client issue)
6. Using the wrong Python binary for iMessage bridge
7. Trusting wallet win rates without checking for both-sides activity
8. Seeding P/L data from buggy historical periods

---
*This document auto-grows. AGENT_LEARNINGS_LIVE.md gets hourly updates from the heartbeat.*
*CLAUDE.md provides coding-specific context.*
*Together they form Bob's memory across sessions.*
