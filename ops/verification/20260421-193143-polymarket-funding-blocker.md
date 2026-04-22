# Stage 4 — Polymarket Funding Blocker Verification
Timestamp: 2026-04-21T19:31:43 MDT
Runner: Claude Code claude-sonnet-4-6[1m], direct Priority 1 run

## What was checked (read-only — no transfers initiated)

1. `docker compose ps` — container health
2. `docker logs polymarket-bot --tail N` — key structured log events
3. `docker exec polymarket-bot python3 -c "..."` — config values (no secrets printed)
4. Latest heartbeat report: `/app/heartbeat_reports/review_20260421_184018.json`
5. STATUS_REPORT.md — prior funding history

## Results

### Container health
```
polymarket-bot  Up 8 hours (healthy)  — runs via WireGuard VPN
```
Container is up and healthcheck passes.

### Internal balance (from structured logs)
```json
{"internal": 500.0, "onchain_usdc": 500.0, "drift": 0.0,
 "note": "informational only — internal tracker is source of truth",
 "event": "bankroll_onchain_check"}
```
Internal tracker reports 500.0 USDC. Note: this is the bot's local position tracker,
not a live on-chain read. The `onchain_usdc: 500.0` value is a fallback/cached figure,
because on-chain verification failed (see DNS blocker below).

Last STATUS_REPORT entry (2026-04-17) recorded actual wallet balance at **$1.94 USDC**
(`[NEEDS_MATT]` item: fund wallet to $50+ to unblock strategies). The discrepancy
between the internal 500.0 and the prior $1.94 on-chain figure is unresolved pending
DNS fix.

### MATIC gas balance
```json
{"matic_balance": 0.0, "event": "redeemer_low_gas", "level": "warning"}
```
No MATIC/POL gas. All on-chain transactions (redemptions, approvals) are blocked until
gas is added.

### Strategy status
```
copytrade: IDLE — 0 signals, 0 trades, 0 open positions
Platforms: 0/2 connected (polymarket: error, kraken: error)
```

### Configuration (no secrets)
```
dry_run: False
wallet_configured: True  (private key present)
```

## Identified blockers (in priority order)

### Blocker 1 — DNS failure from VPN container (CRITICAL)
```
bankroll_onchain_error: "[Errno -3] Temporary failure in name resolution"
position_sync_clob_failed: "[Errno -3] Temporary failure in name resolution"
trade_monitor_poll_error: "[Errno -3] Temporary failure in name resolution"
kraken GET https://api.kraken.com/0/public/Assets: connection error
```
The `polymarket-bot` container routes through the `vpn` WireGuard container.
DNS is not resolving external hostnames from inside. This blocks:
- Polymarket CLOB API calls (market data, order placement)
- Polygon RPC calls (on-chain balance reads, transaction submission)
- Kraken API calls (market making)
- Cortex/notification-hub internal links (Redis at `redis:6379` also failing from bot)

**Minimal next step:** Check WireGuard DNS config in `docker-compose.yml` under `vpn` service.
Confirm `DNS =` is set in the WireGuard config and that the `polymarket-bot` container's
`dns:` setting resolves correctly. Alternatively, check if the VPN recently changed its
DNS endpoint. Running `docker exec polymarket-bot nslookup api.polymarket.com` will confirm.

### Blocker 2 — MATIC/POL gas = 0
Even if DNS were fixed, on-chain transactions (redeem winning positions, approve USDC
spend) will fail without gas. The redeemer fires every 180s and logs `redeemer_low_gas`
on every tick.

**Minimal next step:** Send ~0.5 MATIC/POL to wallet `0xa791E3090312981A1E18ed93238e480a03E7C0d2`
on Polygon mainnet. Requires Matt action (transfer from Kraken or bridge). High-risk gate applies.

### Blocker 3 — Wallet underfunded (may be resolved if on-chain balance is actually higher)
Prior STATUS_REPORT: wallet held $1.94 USDC as of 2026-04-17. Strategies require $50+ USDC
(configured bankroll 500 USDC). All strategies skip with `copytrade_skip: low_bankroll`.
The bot's internal tracker shows 500.0 USDC, but this cannot be verified on-chain until
DNS is fixed. If the actual on-chain balance is still $1.94, Matt must deposit.

**Minimal next step:** Once DNS is fixed, confirm on-chain USDC balance. If < $50, deposit
USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. This requires approval
(financial action, high-risk tier).

## Pass/Fail per check

| Check | Result |
|---|---|
| Container up and healthy | ✅ PASS |
| Read-only status check completed | ✅ PASS |
| On-chain balance visible | ❌ FAIL — DNS prevents on-chain reads |
| MATIC gas balance | ❌ FAIL — 0.0 MATIC |
| Strategies active | ❌ FAIL — 0/2 platforms connected, all idle |
| Last funding attempt status | ⚠️ PARTIAL — internal tracker shows 500.0 but unverified |
| Overall | ❌ FAIL (3 active blockers) |

## Next steps (in order)

1. **Fix VPN DNS** (no approval needed — infrastructure change): Investigate the WireGuard
   DNS config under the `vpn` service. Run `docker exec polymarket-bot nslookup api.polymarket.com`
   to confirm. If WireGuard DNS is mis-configured, update `docker-compose.yml` or the WireGuard
   config and restart the vpn + polymarket-bot containers.
2. **After DNS fixed, verify on-chain USDC balance** — read-only, no approval.
3. **If balance < $50, request Matt to deposit USDC** — `[NEEDS_MATT]` — high-risk gate.
4. **Top up MATIC gas** — `[NEEDS_MATT]` — ~0.5 POL/MATIC to same wallet — high-risk gate.
