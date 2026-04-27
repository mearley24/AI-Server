# Cortex Dashboard Data Source Audit v3

**Date:** 2026-04-27T18:56:41Z  
**Auditor:** Claude (automated)  
**Method:** Live curl of all endpoints + source code inspection  
**Cortex base URL:** http://localhost:8102

---

## Summary

| Category | Count |
|---|---|
| Live & accurate | 12 |
| Stale / misleading | 5 |
| Failing / broken | 5 |
| Synthetic / paper (unlabelled) | 2 |
| Debug-only (already gated) | 1 |
| **Total audited** | **25** |

---

## Full Audit Table

| Card | Tab | Source Endpoint | Count | Freshness | Problem | Recommendation | Priority |
|---|---|---|---|---|---|---|---|
| Today / Needs Attention | Today | Composite (watchdog, followups, xi, emails, exposure, audit) | Derived | Live | No problems | Working as designed | — |
| Service Health | Today | `/api/services` | 13 svcs | Live (healthy) | Docker shows degraded from recovery event 0.2h ago; OK services last seen 66-75h | Watchdog cleanup: filter stale-ok entries >48h | P2 |
| Watchdog | Today | `/api/watchdog/status` | 7 entries | updated_at=12:54 MT | Docker "degraded" is a false alarm (recovery event). Polymarket Bot / VPN / Tailscale / X Alpha Collector all "ok" but last seen 66-75h ago | Add stale threshold: hide "ok" entries not seen in >48h from main view | P1 |
| Tool Access | Today | `/api/tools?tab=overview` | 4 tools | Live | Working | — | — |
| Follow-ups | Today | `/api/followups` | 0 (error) | — | **DB not mounted** — returns `{"error":"unable to open database file"}` | Fix data volume mount for follow_ups.db | P1 |
| Emails | Today | `/api/emails` | Live | 2026-04-27 | Working — MakerFlo promo at top | Filter vendor/promo from summary count? (separate issue) | P3 |
| Calendar | Today | `/api/calendar` | 0 events | — | Returns empty — calendar agent may be idle or no events | Empty state is accurate ("no upcoming events") | — |
| X Intake (overview widget) | Today | `/api/x-intake/stats` + `/api/x-intake/queue` | 70 total, 0 pending | Live | Working | — | — |
| Calls / Voice | Today | `/api/symphony/voice-receptionist` | 0 calls | — | Planned — service offline, correct empty state shown | — | — |
| Safe-to-Fund | Money | Static + `/api/polymarket/exposure` | Static | Static | Working — 4 blockers correctly listed | — | — |
| Polymarket Exposure | Money | `/api/polymarket/exposure` | 78 positions, $397 | Live | Working | — | — |
| Wallet | Money | `/api/wallet` | usdc=0, active=0 | — | **BROKEN** — Redis key `portfolio:snapshot` never pushed. Real on-chain balance is $3.72 (from redeemer). Shows zeros. | Label as broken in UI; real balance is in redeemer card | P1 |
| Positions | Money | `/api/positions` | 13 positions | No timestamps | **UNLABELLED PAPER TRADES** — all 13 have `order_id: paper-*` from cvd_arb strategy. No timestamps. Shown as real positions without any paper badge. | Add PAPER badge; add empty state note | P1 |
| P&L | Money | `/api/wallet` + `/api/pnl-summary` | $-1112 realized | — | wallet returns zeros (broken). pnl-summary works: 2450 trades, $-1112 realized. These are paper/simulation trades. | Mark pnl as paper simulation data | P1 |
| P&L Series | Money | `/api/pnl-series` | 0 | — | **BROKEN** — returns `[]`. Redis key `portfolio:pnl_series` never populated. | Mark as unavailable; remove from default view | P1 |
| Redeemer | Money | `/api/redeemer` | 530 redeemed, $3.72 USDC | Live | Working — $3.72 USDC, 78 pending, 60 POL gas | — | — |
| Decisions | Debug | `/api/decisions/recent?limit=20` | 100 journal, 0 cortex | Newest: 2026-04-25 | **100% automation noise** — 77% D-Tools sync entries (`jobs` category), 23% email events. Zero human decisions. `employee=bob` for all (bot-generated). | Filter `category=jobs` (D-Tools noise) in normal mode | P1 |
| Meetings | Debug | `/api/meetings/recent?limit=20` | 5 rows | 2024-07-19 – 2024-08-14 | **ALL 2024** — source_dates are July/Aug 2024, empty summaries. 2 years old. The v2 7-day filter should already hide these. | Already filtered by v2 freshness; verify filter is working | P2 |
| Activity | Debug | `/api/activity` | 50 events | 18:30–18:50 | **Dominated by `health.checked` noise** — 10/50 are `health.checked` system pings. 15 have no channel. Data is fresh but low signal. | Filter `health.checked` events in normal mode (already cap 10) | P2 |
| Dashboard Audit | Debug | `/api/dashboard/audit-summary` | Static | 2026-04-27 | Working | Update to reflect new findings | P3 |
| Memory | Debug | `/health` + `/memories` | 100,816 total | Live | Working — 41k trading_strategy, 28k risk_management | — | — |
| Goals | Debug | `/goals` | 5 goals | No timestamps | Goals have NO `updated_at`. Trading goals (profit/win rate) may be stale. Status shows needs_attention for profit (10%) + edge discovery (0%). | Add timestamp to goals endpoint | P3 |
| Daily Digest | Debug | `/digest/today` | Empty | — | Returns `{summary:null, headline:""}` — digest not generated today | Empty state correct | — |
| Trading Intel | Symphony | `/api/trading/intel` | 0 signals | — | **BROKEN** — all zeros (active_signals:0, market_boosts:0, top_authors:[]) | Mark as UNAVAILABLE; endpoint returns live-shape but dead data | P2 |
| Vault | Vault | `/api/vault/secrets` | 1 (prod), hidden TEST_ | Live | Already gated behind CORTEX_DEBUG — correct | — | — |

---

## Positions Detail (Paper Trades)

All 13 positions from `/api/positions` are paper simulation trades:

| order_id prefix | strategy | market |
|---|---|---|
| paper-* (13 positions) | cvd_arb | "CVD signal 0x..." (synthetic market IDs) |

These are NOT real Polymarket positions. Real positions (78 legacy) are tracked by `/api/polymarket/exposure`.

---

## Decisions Journal Detail

100 entries audited:
- **D-Tools automation (jobs):** 77 entries — all "D-Tools sync: created=0, linked=0"
- **Email events:** 23 entries  
- **Human decisions:** 0 entries

The `employee` field is `bob` for ALL entries — these are bot-generated records, not human decisions.

The `cortex` array is empty (0 items). The Decisions card is showing 100% automation noise.

---

## Watchdog Detail

Services and their actual last-seen age:

| Service | State | Last seen | Age |
|---|---|---|---|
| Docker engine | **degraded** | 2026-04-27T18:45 | 0.2h (false alarm — recovery event) |
| OpenClaw | ok | 2026-04-27T17:29 | 1.4h |
| Containers | ok | 2026-04-26T21:59 | 20.9h |
| Tailscale | ok | 2026-04-25T00:32 | 66.4h |
| VPN | ok | 2026-04-24T18:18 | 72.6h |
| X Alpha Collector | ok | 2026-04-24T20:11 | 70.7h |
| Polymarket Bot | ok | 2026-04-24T16:08 | 74.8h |

The 4 "ok" services with 66-75h stale data are shown as healthy but their state is actually unknown/stale.

---

## Top 15 Stale/Misleading Data Sources

1. **Positions** — 13 paper trades shown without PAPER label (P1)
2. **Follow-ups** — DB not mounted, 0 results shown as "none" not "error" (P1)
3. **Decisions journal** — 77% D-Tools automation, 0% human decisions (P1)
4. **Wallet** — Returns all zeros; real balance in redeemer ($3.72) (P1)
5. **Watchdog stale-ok** — Tailscale/VPN/Bot/X-Alpha last seen 66-75h but shown green (P1)
6. **P&L Series** — Endpoint returns [] but shown as "unavailable" not "not configured" (P1)
7. **Trading Intel** — Returns valid JSON with all zeros; not marked as broken (P2)
8. **Activity feed** — health.checked events dominate; noise:signal ratio ~50% (P2)
9. **Meetings** — All 2024-era data (2 years old, empty summaries). Should be archive-hidden. (P2)
10. **Goals** — No timestamps; can't verify freshness; trading goals may be stale (P2)
11. **Daily Digest** — Returns empty/null but no empty state message (P3)
12. **X-API Items** — 0 items; unclear if pipeline is idle or broken (P2)
13. **X-API Insights** — 0 items; same (P2)
14. **Reply Inbox** — 404 endpoint in `loadReplyInbox()` (P2)
15. **PnL Summary** — $-1112 realized shown without noting it's from paper simulation trades (P2)

---

## Immediate Safe Fixes (applied in this commit)

1. **Positions PAPER badge** — `renderPositions()`: if `order_id` starts with `paper-` or all orders are paper, show a yellow PAPER badge. Does not hide data.
2. **Activity: filter health.checked noise** — `renderActivity()`: in normal mode, filter out events with `payload.type === 'health.checked'` before the 10-item cap.
3. **Decisions: filter D-Tools category** — `renderDecisions()`: in normal mode, also filter out `category === 'jobs'` entries (D-Tools automation). They'll still show in debug mode.
4. **Follow-ups error state** — `renderFollowups()`: if `data.error` is set, show explicit error state instead of "0 active".
5. **`GET /api/dashboard/data-source-audit`** — New endpoint returning the structured findings.
6. **Update `GET /api/dashboard/audit-summary`** — Add positions/follow-ups/reply-inbox to the stale/failing sections.

---

## Fixes Needing Approval (do NOT apply without review)

- **Watchdog stale-ok filter**: Removing ok entries not seen in >48h requires understanding of watchdog's polling model — a service might genuinely not need checking often.
- **Follow-ups DB mount**: Infrastructure change to docker-compose.yml volumes.
- **Reply inbox endpoint**: Need to verify correct endpoint URL in `loadReplyInbox()`.
- **Wallet Redis key**: Bot must push `portfolio:snapshot` Redis key — code change in polymarket-bot.
- **Goals timestamps**: Need to add `updated_at` to the goals endpoint — database migration.

---

## Recommended Next Cleanup Batch (v4)

1. Watchdog: add "stale-ok" warning badge for services not seen >48h
2. Goals: add `updated_at` to goal objects
3. Follow-ups: fix volume mount or add explicit "DB unavailable" error card
4. Reply inbox: audit `loadReplyInbox()` endpoint URL — appears to be 404
5. PnL/Positions: distinguish paper vs live clearly in Money tab header
6. Trading Intel: mark as UNAVAILABLE with reason in the card
