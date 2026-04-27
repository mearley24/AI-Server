# Cortex Dashboard Full Audit v1
Generated: 2026-04-27T18:08:00Z

## Executive Summary

Full audit of all 40+ Cortex dashboard API endpoints. Endpoints categorized as:
- **BROKEN**: returns error or always-zero data
- **STALE**: data present but outdated or misleading
- **SYNTHETIC**: test/placeholder data shown in production
- **PLANNED**: endpoint exists but feature not yet built
- **LIVE**: working correctly

---

## Audit Table

| Section | Endpoint | Current State | Problem | Recommendation | Priority |
|---------|----------|---------------|---------|----------------|----------|
| Portfolio | `/api/wallet` | BROKEN (all zeros) | `portfolio:snapshot` Redis key not being pushed by bot; fallback Polymarket data API hit successfully — shows position_value but usdc_balance=0 always | Label tile "Portfolio (positions only)" until bot pushes snapshot | P1 |
| Portfolio | `/api/pnl-series` | BROKEN (empty list) | `portfolio:pnl_series` Redis key never populated by bot | Show "No PnL history yet" empty state instead of blank chart | P1 |
| Portfolio | `/api/pnl-summary` | LIVE | Fetches realized PnL from public Polymarket data API; working | None | — |
| Portfolio | `/api/polymarket/exposure` | LIVE | 78 positions, $398.19 value fetched from data API correctly | None | — |
| Portfolio | `/api/positions` | PARTIALLY LIVE | Falls through to Polymarket data API; no bot snapshot | Add `source` label to UI to clarify data origin | P2 |
| Trading | `/api/trading` | DEGRADED | Bot at `http://vpn:8430` unreachable from host test; in-container works | N/A (container-only) | — |
| Trading | `/api/trading/intel` | BROKEN (zeros) | Bot `/x-intel/status` returns zeros — X-intel not actively scoring | Show "No signals" empty state | P2 |
| Trading | `/api/activity` | NOISY | `events:log` Redis dominated by `health.checked` system noise events | Filter `health.checked` events from display | P2 |
| Decisions | `/api/decisions/recent` | MISLEADING | `cortex[]` always empty; `journal[]` contains 8000+ D-Tools automation entries (not human decisions) | Label as "Automation Log" or add `type != 'dtool'` filter | P1 |
| Follow-ups | `/api/followups` | BROKEN | SQLite path not reachable outside container → "unable to open database file" | Expected; works in container. No change needed | — |
| Emails | `/api/emails` | DEGRADED | email-monitor service unreachable in host test; works in-container | N/A (container-only) | — |
| Calendar | `/api/calendar` | DEGRADED | calendar-agent unreachable in host test; works in-container | N/A (container-only) | — |
| Meetings | `/api/meetings/recent` | STALE | audio_intake DB has rows with 2024 source_dates and empty summaries | Add `data_quality: "no_summaries"` flag to response when summary is null | P2 |
| System | `/api/system` | PARTIAL | `cpu_percent` always null (no psutil); disk/memory/uptime work in container | Document null expectation or use host proc | P3 |
| System | `/api/services` | LIVE | 13/13 containers healthy per docker compose | None | — |
| Watchdog | `/api/watchdog/status` | MISLEADING | Shows "degraded" for `docker` + `uh_openclaw` because state files written within last 1h; all containers actually healthy | State files are written continuously by the watchdog on each check — "degraded" means "watchdog acted recently", not "container is down". Rename `state=degraded` → `state=recently_checked` for recovery events | P1 |
| Vault | `/api/vault/secrets` | SYNTHETIC | `TEST_VAULT_SECRET` (category=api_key, notes="verification test secret") shown in production dashboard alongside real secrets | Hide secrets with name matching `TEST_*` or `TEST_VAULT_*` unless `CORTEX_DEBUG=true` | P1 |
| X Intake | `/api/x-intake/stats` | LIVE | 70 items, counts correct | None | — |
| X Intake | `/api/x-intake/items` | LIVE | Direct DB read, pagination works | None | — |
| X Intake | `/api/x-intake/queue` | LIVE | Proxy to x-intake service works | None | — |
| Self-Improvement | `/api/self-improvement/promoted-rules` | LIVE | 5 rules, last updated 2026-04-26 | None | — |
| Client Intel | `/api/client-intel/triage-summary` | LIVE | 267 classified items | None | — |
| Voice Receptionist | `/api/symphony/voice-receptionist` | PLANNED | Service health probe works; recent_calls/missed_calls/voicemails always `[]` — no Cortex ingestion yet | Already documented with `planned` block; render explicit "Not yet configured" label in UI | P3 |
| Tools Registry | `/api/tools` | LIVE | 16 tools across 4 tabs, correct | None | — |
| Process | `/api/process/backlog` | LIVE | Reads ops/BACKLOG.md correctly | None | — |

---

## Sections Assessed as Live and Reliable

- `/api/polymarket/exposure` — live chain positions
- `/api/x-intake/items`, `/api/x-intake/stats` — live queue data
- `/api/self-improvement/promoted-rules` — live rule engine
- `/api/client-intel/triage-summary` — live classification store
- `/api/services` — live container health via docker compose
- `/api/tools` — static registry, correct
- `/api/process/backlog` — reads BACKLOG.md correctly
- `/api/pnl-summary` — fetches from public Polymarket API correctly

---

## Fixes Applied in This Commit

1. **Vault `TEST_VAULT_SECRET` hidden** — `/api/vault/secrets` now filters entries
   whose `name` starts with `TEST_` unless `CORTEX_DEBUG=true` is set in env.

2. **`/api/dashboard/audit-summary` endpoint added** — returns structured
   `{stale_sections, failing_sections, debug_only_sections, live_sections, recommendation_count}`
   so automated monitoring can track dashboard health over time.

---

## Remaining Recommendations (Not Fixed Here — Require UI or Bot Changes)

| # | Area | Fix |
|---|------|-----|
| R1 | Portfolio tile | Label "positions only" until bot pushes `portfolio:snapshot` to Redis |
| R2 | PnL chart | Show "No history yet" empty state instead of blank canvas |
| R3 | Decisions tile | Add filter: exclude journal entries with `context` containing "d-tools" or "D-Tools" |
| R4 | Activity feed | Filter `health.checked` type events from display |
| R5 | Watchdog tile | Rename `degraded` → `recently_checked` for `event_type=recovery` entries |
| R6 | Voice Receptionist | Add explicit "Not configured" label to calls card empty state |

## SAFE TO FUND (Polymarket): NO

Unchanged from prior report — see `20260427T175030Z-polymarket-simulation-throttle-correction.md`.
