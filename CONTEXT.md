# Symphony Smart Homes — Active Context
## Last Updated: 2026-04-03 08:58 MDT

## Active Project: Topletz — 84 Aspen Meadow
- Client: Steve Topletz (stopletz1@gmail.com)
- GC: RMGC (Rocky Mountain Construction Group) — David
- Proposal: V7 sent, $57,683.09, 18 switches
- Agreement addendum needed: client-supplied equipment warranty, TV install terms, 90-day support, third-party driver disclaimer
- Ceiling mount issue: Peerless PLCM-2 doesn't fit Hisense 100" U8 (VESA 800x400, 137 lbs). Researching alternatives.
- TV exclusion language added in V7
- Lighting walkthrough with RMGC/David still needs scheduling (SYM-37)

## Polymarket Bot
- Wallet: $217 USDC.e, $784 positions value, +$19 P/L
- Strategy filters deployed: entry price caps (weather 25¢, sports 75¢), temp clustering, crypto binary filter, category blacklist
- Paper trader running but had issues (duplicate entries fixed, resolution tracking added)
- Exit engine: sell haircut 0.995 fix deployed, original thresholds kept
- Multi-strategy architecture built: weather cheap brackets, filtered copytrade, spread/arb scanner
- Video transcriber wired to iMessage bridge — working but slow on long videos
- Redis static IP: 172.18.0.100

## Bob Infrastructure
- Auto-responder: import path fixed, Zoho creds added, needs end-to-end test
- Email routing: 21+ domain routes, auto-learn detects moves but folder search needs work
- iCloud SymphonySH folder: empty on Bob, needs re-sync
- iMessage bridge: running on port 8199, video transcription wired in
- Notification hub: Redis pub/sub working

## Standards (Bob & Team)
- Version numbers internal only — client sees "Updated proposal"
- Hyperlink every product/doc in client emails
- Strong VersaBox recommended at every TV location
- Client-supplied equipment = client's warranty responsibility
- Config changes = docker compose up -d --build (not restart)
- File naming: "Symphony Smart Homes — [Address] — [Type].pdf"

## Cursor Prompts Ready
1. Polymarket strategy fixes (highest priority)
2. RBI pipeline (research → backtest → implement)
3. Bob autonomy (auto-responder + email routing)
4. iCloud sync + file watcher
5. X video transcription reliability
