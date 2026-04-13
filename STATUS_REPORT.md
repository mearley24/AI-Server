# STATUS REPORT — Symphony AI-Server

Generated: 2026-04-11 | Last updated: 2026-04-12
Host: Bob (Mac Mini M4), branch: main.
Audit series: Prompt Q (full audit) → Prompt S (Cortex merge) → Z3–Z14 patches.

---

## Now

_Action-required items this week. Most require Matt's input (credentials/funding)._

- **[Matt] Set `KRAKEN_SECRET`** — add the real Kraken API secret (same value as `KRAKEN_API_SECRET` in `.env` line 284) using `bash scripts/set-env.sh KRAKEN_SECRET <value>`, then `docker compose up -d polymarket-bot` (no rebuild needed). Kraken MM auth fails on every tick until this is set.

- **[Matt] Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $1.94 USDC; all strategies skip with `low_bankroll`. No code change needed — bot re-reads on-chain balance every 5 minutes. Full operation needs $500 (configured bankroll).

- **Rebuild + restart x-intake** — `docker compose up -d --build x-intake` deploys the new queue DB, review API endpoints, and volume mount. Previous listener died 2026-04-11 14:46; restart is the immediate fix. See §Z14 for the durable listener watchdog fix still needed.

- **Drain 103 pending approvals** — `decision_journal.db` has 103 `pending_approvals` rows (P0 threshold: 20). Write a one-shot Prompt T script: group by kind, batch to Matt via iMessage with YES/NO actions, auto-expire stale entries >7 days to a "skipped" state with a log entry.

- **Finish Prompt N** — 3 bounded changes remaining (9 of 12 deliverables already done):
  1. Remove `openwebui:` service block and its `volumes:` entry from `docker-compose.yml`, then `docker compose up -d`.
  2. Add `ops:email_action` Redis publish to `email-monitor/notifier.py` after action-required classification.
  3. Add `/calendar/daily-briefing` fetch to `openclaw/orchestrator.py` daily briefing assembly.

---

## Next

_Important but not blocking; no credentials required._

- **Fix email `read=1` upstream** — all 438 emails in `emails.db` have `read=1`; the email tile correctly shows 0 unread but the data is wrong. Audit `email-monitor/notifier.py` and `monitor.py::_scan_sent_for_replies()` to find where read is set to 1 and limit it to emails Matt has actually replied to (Sent folder In-Reply-To match). See §Z3.

- **Wire Cortex (all services)** — Cortex receives ~1 entry/week; most services still not POSTing to `http://cortex:8102/api/entries`. Add calls (with `try/except`) to `email-monitor`, `daily_briefing`, `follow_up_engine`, and `notification-hub`. Target: >100 entries within 24h of deploy. See §3 close-all-gaps Task 3.

- **x-intake listener watchdog** — store the `_redis_listener` Task reference and add a 10-second watchdog loop so the listener restarts on failure. Also remove the nested `asyncio.new_event_loop()` from `_analyze_url_sync` — call the async function directly instead. See §Z14.

- **Verify Prompt I runtime** — all code changes for redeem-cleanup are confirmed present; what's unverified is runtime execution. Run `docker compose logs --tail=100 polymarket-bot 2>&1 | grep redeemer` to confirm `redeemer_redeemed` events appear. Check POL gas balance on the wallet. See §14.

- **Fix CLAUDE.md service table** — four stale entries:
  - `notification-hub` is Python on port **8095** (not 8091/Node).
  - `proposals` (**8091**) is missing from the table.
  - `browser-agent` (9091) does not exist — remove or create.
  - `integrations/cortex/*` path is wrong — the service is top-level `cortex/`.

- **jobs.db consolidation** — `follow_up_log` in `jobs.db` has 0 rows while `follow_ups.db` has 58. Pick one canonical home and retire the duplicate to avoid confusion as the orchestrator backfill runs. See §7 item 7.

---

## Later

_Low priority / cleanup; no production impact today._

- **client-portal `/health` endpoint** — container reports unhealthy because `client-portal/main.py` has no `GET /health` route. Add one returning `{"status":"ok"}` to fix the compose healthcheck. See §1.

- **pull.sh hardening** — current `scripts/pull.sh` is 50 lines (stash + pull + conflict scan). Target ~90 lines: add `py_compile` check per service dir, `--verify` flag for smoke tests, auto `docker compose up -d --build <svc>` on compose.yml change. See §3 close-all-gaps Task 5.

- **Dropbox link validator** — lesson #4 (links must use `scl/fi/` not `/preview/`) has no automated validator; still "unknown" from the April 4 audit.

- **Sell haircut rounding** — lesson #17 (exit loops from rounding) is unverified in `polymarket-bot`. Check and confirm or fix.

- **imessage-server `_re` NameError** — `scripts/imessage-server.py::handle_reset_command` references `_re` which is not defined at module level (only `_idea_re = re` is). Low severity / rarely hit. See §Z14 secondary finding #3.

- **Supabase cleanup (AI-Server)** — env vars `SUPABASE_*` exist in `.env` but zero Docker services use them; `integrations/supabase/` is an empty shell. Safe to remove vars and uninstall the Python package from `.venv` with no runtime effect. See §22.

- **Supabase → Bob migration (symphonysh)** — contact form, appointment booking, confirmation emails, and Matterport upload all depend on Supabase. Not urgent while the free tier covers load; estimated ~8–9h to migrate to Bob-hosted endpoints. See §22.

- **Kalshi live mode** — `KALSHI_DRY_RUN=true` / `KALSHI_ENVIRONMENT=demo`. Set to production once API key is verified. See §Z9.

- **Vite/esbuild upgrade (symphonysh)** — `npm audit` reports 2 moderate findings (esbuild ≤0.24.2 via vite ≤6.4.1); dev-server only, not in production build. Requires `vite@8` upgrade; see `symphonysh/SITE_STATUS.md`.

---

## Done

_Completed since the April 11 audit baseline._

- ✅ **Mission Control dissolved** — crash-looping container removed from `docker-compose.yml`; Cortex (8102) is now the single brain + dashboard; all services POST to `http://cortex:8102/remember`.
- ✅ **Cortex added to docker-compose.yml** — was an orphaned container; now properly defined (Prompt S).
- ✅ **Prompts A, C** — copytrade fake seeds/priority-wallet injection removed; sandbox fully wired; runtime-verified via code grep (§14).
- ✅ **Prompts B, D, G, J, K, L, M** — trading dashboard, profitability overhaul, spread-arb fix, performance monitor, x-intake signal bridge, x-alpha collector, Cortex — all complete per audit.
- ✅ **Calendar tile fixed** — Zoho sentinel objects filtered; `_parse_zoho_datetime` + `_normalize_calendar_event` added to `cortex/dashboard.py`; frontend shows `start_display`, recurring `↻` badge, up to 5 events (§Z4).
- ✅ **Follow-up noise filter fixed** — `symphonysh.com` domain added to `FOLLOWUP_NOISE_SENDERS`; follow-ups tile dropped 8→6 (§Z3).
- ✅ **Trading observability** — startup banner TRADING READINESS section + `trading_readiness_summary` structured log added to `polymarket-bot/src/main.py` (§Z8).
- ✅ **Auto-redeemer wired** — 297 conditions redeemed all-time; running every 180s; `redeemer_summary.json` persisted after each cycle; no code changes needed (§Z10/Z12).
- ✅ **Dropbox-organizer LaunchAgent** — verified running (PID 32502, exit 0, plist loaded) (§Z7).
- ✅ **iCloud verified** — 16 containers synced, no stalled items, `ever-caught-up:YES` (§Z7).
- ✅ **CVE-2026-4800 lodash remediation** — `"overrides": {"lodash": "4.17.21"}` in `symphonysh/package.json`; build passing; deployed to Cloudflare Pages (§Z13).
- ✅ **Supabase classified** — AI-Server: legacy (no live code paths); symphonysh: required (contact, booking, upload) (§22).
- ✅ **Lessons scorecard 19/25 green** — up from 17/25; lessons #6 (Dropbox organizer) and #8 (iCloud) closed this pass.
- ✅ **.env deduplication** — duplicate `# Crypto` block removed; `KRAKEN_SECRET=` placeholder added (§Z5).
- ✅ **symphonysh debug cleanup** — 8 debug console.log statements removed, dead `testNavigation` button removed, debug dropdown entries removed (§15).

---

## Reference: Stack Health

_Snapshot from 2026-04-12. Re-run `docker compose ps` for current state._

| Service | Port | State | Health | Notes |
|---|---|---|---|---|
| openclaw | 8099 | Up | 🟢 | `/health` → 200. 40 active jobs, backfilling client preferences. |
| cortex | 8102 | Up | 🟢 | 21 entries, 10 neural paths. Starving — only 1 entry/week (see Next). |
| email-monitor | 8092 | Up | 🟢 | 435 emails in DB; all marked `read=1` (see Next). |
| notification-hub | 8095 | Up | 🟢 | Python on 8095 — CLAUDE.md incorrectly says 8091/Node. |
| proposals | 8091 | Up | 🟢 | Not in CLAUDE.md service table. |
| polymarket-bot | 8430 (via vpn) | Up | 🟢 | LIVE mode; 11 strategies registered; blocked on credentials + funding (see Now). |
| client-portal | (internal) | Up | 🟡 | Unhealthy — missing `GET /health` endpoint (see Later). |
| dtools-bridge | 8096→5050 | Up | 🟢 | `{"dtools":"ready"}`. |
| redis | 6379 | Up | 🟢 | PING→PONG; static IP 172.18.0.100; `events:log` 1000 entries. |
| vpn | — | Up | 🟢 | WireGuard; fronts polymarket-bot. |
| voice-receptionist | 8093→3000 | Up | 🟢 | — |
| calendar-agent | 8094 | Up | 🟢 | — |
| clawwork | 8097 | Up | 🟢 | — |
| context-preprocessor | 8028 | Up | 🟢 | — |
| intel-feeds | 8765 | Up | 🟢 | — |
| knowledge-scanner | 8100 | Up | 🟢 | — |
| openwebui | 3000→8080 | Up | 🟢 | Pending removal (Prompt N). |
| remediator | 8090 | Up | 🟢 (no healthcheck) | — |
| x-intake | 8101 | Up | 🟢 | Redis listener dead since 2026-04-11 14:46 — needs restart (see Now). |
| browser-agent | 9091 | Not running | ⚪ | In CLAUDE.md but never existed — remove from docs. |

---

## Reference: Data Pipeline

_Row counts from 2026-04-12 audit._

| DB | Table | Rows | Status |
|---|---|---|---|
| `data/openclaw/jobs.db` | jobs | 40 | flowing |
| | client_preferences | **0** | Empty — backfill started at audit time; unverified |
| | follow_up_log | **0** | Empty — data lives in `follow_ups.db` instead |
| `data/openclaw/decision_journal.db` | decisions | 3413 | flowing |
| | pending_approvals | **103** | P0 backlog — drain needed (see Now) |
| `data/openclaw/follow_ups.db` | follow_ups | 58 | flowing — canonical home TBD (see Next) |
| `data/email-monitor/emails.db` | emails | 435 | flowing; all `read=1` (see Next) |

Redis `events:log`: 1000 entries (capped), real traffic flowing across all subscribed channels.

Cortex memory: 21 entries, 1 this week — most services not yet POSTing.

---

## Reference: Prompt Completion Matrix

| Prompt | Topic | Status |
|---|---|---|
| **A** | copytrade-cleanup | ✅ PASS — seeds/injection gone; neg_risk wired; quiet hours disabled (intentional 24/7) |
| **B** | mission-control-redesign | ✅ COMPLETE — dissolved; replaced by Cortex |
| **C** | sandbox-bankroll | ✅ PASS — sandbox wired; `_tick_in_progress` + `_maybe_refresh_bankroll` confirmed |
| **D** | profitability-overhaul | ✅ COMPLETE |
| **G** | spread-arb-fix | ✅ COMPLETE |
| **I** | redeem-cleanup | 🟡 PARTIAL — code confirmed; runtime redemption not verified (see Next) |
| **J** | performance-monitor | ✅ COMPLETE |
| **K** | x-intake-bot-bridge | ✅ COMPLETE |
| **L** | x-alpha-collector | ✅ COMPLETE |
| **M** | cortex | ✅ COMPLETE — in docker-compose, running |
| **N** | operations-backbone | 🟡 PARTIAL — 9/12 done; 3 gaps remain (see Now) |
| **O, P** | website-experience, site-audit-polish | ✅ EXTERNAL — symphonysh repo; debug cleanup done |

### close-all-gaps-april10 tasks

| Task | Topic | Status |
|---|---|---|
| 1 | x-intake deep analysis | 🟡 PARTIAL — files present; Cortex POST + thread wiring unverified |
| 2 | follow-up engine auto-send | 🟡 PARTIAL — engine present; `follow_up_log` empty → auto-send loop not yet fired |
| 3 | Cortex wire-up (all services) | 🟡 PARTIAL — see Next |
| 4 | daily briefing improvements | 🟡 PARTIAL — last run 2026-04-11; Cortex neural-paths section unverified |
| 5 | pull.sh hardening | 🟡 PARTIAL — see Later |
| 6 | Dropbox organizer fix | ✅ DONE — LaunchAgent verified running (§Z7) |

---

## Reference: Lessons Learned (April 4 — 25 lessons)

_19/25 green after Z7 pass._

| # | Lesson | Status |
|---|---|---|
| 1 | Agreement doc stale after price change | 🟡 PARTIAL — `doc_staleness.py` thin |
| 2 | Deliverables doc stale after scope change | 🟡 PARTIAL — covered by same tracker |
| 3 | TV Mount doc references wrong product | 🟡 PARTIAL — no email-to-doc linkage |
| 4 | Dropbox links must use `scl/fi/` | ⚪ UNKNOWN — no validator found (see Later) |
| 5 | Docs must be signed automatically | ✅ DONE |
| 6 | `git pull` broken by data-file conflicts | ✅ DONE — `scripts/pull.sh` |
| 7 | Dropbox not installed on Bob | ✅ DONE |
| 8 | iCloud not signed in on Bob | ✅ DONE — verified Z7 |
| 9 | Hardcoded paths blow up scripts | ✅ DONE (policy) |
| 10 | Mission Control fonts unreadable | ✅ DONE — MC dissolved; Cortex redesigned |
| 11 | D-Tools sync created 0 jobs | ✅ DONE — jobs.db has 40 jobs |
| 12 | Cursor files claimed but not created | ✅ DONE — `scripts/verify-cursor.sh` |
| 13 | Redis IP changes after Docker restart | ✅ DONE — static IP 172.18.0.100 |
| 14 | Zoho token expires every hour | ✅ DONE — `openclaw/zoho_auth.py` |
| 15 | Cross-container Python imports | ✅ DONE (policy) |
| 16 | `docker restart` doesn't pick up new code | ✅ DONE (policy) |
| 17 | Sell haircut rounding — exit loops | ⚪ UNKNOWN — see Later |
| 18 | `.env` append duplicates first-wins bug | ✅ DONE — `scripts/set-env.sh` |
| 19 | Shell escaping breaks inline-JSON curl | ✅ DONE — `scripts/api-post.sh` |
| 20 | Post-prompt file verification | ✅ DONE — `scripts/verify-cursor.sh` |
| 21 | Dashboard rebuilt 4× without QA | ✅ DONE (policy) |
| 22 | `git pull` always fails | ✅ DONE (dup of #6) |
| 23 | Launchd plists reference missing scripts | ✅ DONE (policy) |
| 24 | Launchd `docker` not in PATH | ✅ DONE (policy) |
| 25 | pip PEP 668 on macOS | ✅ DONE (policy) |

---

## Reference: Trading State (2026-04-12)

_All trading diagnostic runs (Z5, Z6, Z8, Z9) reach the same conclusion:_

Bot is in **LIVE mode** (`POLY_DRY_RUN=false`). 11 strategies registered and ticking. Two blockers prevent all trades:

| Blocker | Evidence | Fix (see Now) |
|---|---|---|
| `KRAKEN_SECRET` is empty | Auth error every 15s; `/kraken/status` → HTTP 500 | Set via `scripts/set-env.sh`, restart bot |
| Polymarket wallet $1.94 USDC | All signals skip with `copytrade_skip: low_bankroll` | Fund wallet with $50+ USDC on Polygon |

Historical P&L from `data/polymarket/trades.csv` (477 rows, live trades Apr 3–12): crypto +$2.11, weather −$7.22 = **−$5.11 net realized**. Wallet depleted by live trades, not missing redemptions.

Platform modes:

| Platform | Mode | Notes |
|---|---|---|
| Polymarket | LIVE (blocked by funds) | `POLY_DRY_RUN=false`; private key set; $1.94 USDC |
| Kraken MM | DRY-RUN + AUTH BROKEN | `KRAKEN_DRY_RUN=true` AND `KRAKEN_SECRET` empty |
| Kalshi | DEMO | `KALSHI_DRY_RUN=true`, `KALSHI_ENVIRONMENT=demo` |

Once both blockers are resolved, `trading_readiness_summary` will flip to `"status": "READY"` and the startup banner will show `[OK]` for both lines.

---

## Reference: Auto-Redeemer Status (2026-04-12)

Redeemer is fully wired and operational. Summary from `data/polymarket/redeemer_summary.json`:

- Running: `true` | Check interval: 180s | Wallet: `0xa791E3090312981A1E18ed93238e480a03E7C0d2`
- Conditions redeemed all-time: **297** | Last redemption: `2026-04-12T08:09:06Z`
- Last cycle (2026-04-12 16:07 UTC): pending=96, redeemable=0 — correctly idle
- Gas (POL): **62.85** — well above 0.05 minimum
- No redeemer errors observed (`redeemer_loop_error`, `redeemer_init_failed`, `redeemer_fetch_positions_error` all absent)

96 currently-pending positions are in unresolved markets. Redeemer will fire automatically once any market resolves on-chain (`payoutDenominator > 0`), checked every 3 minutes. **No code changes needed.**

Prerequisite: wallet must be funded ($50+ USDC) so new trades can execute and create new winning positions to redeem.

---

## Reference: X-Intake Listener Failure (§Z14)

**Root cause:** On 2026-04-11 14:46:32, the `_redis_listener` asyncio Task was garbage-collected after `RuntimeError: aclose(): asynchronous generator is already running` on the `redis.asyncio` pubsub iterator. The reconnect loop inside the coroutine never ran because the Task object itself was destroyed. No watchdog exists to restart it.

**Immediate fix:** `docker compose restart x-intake` — re-subscribes to `events:imessage` within seconds.

**Durable fix** (code change):
```python
# integrations/x_intake/main.py — replace startup handler with:
_listener_task: asyncio.Task | None = None

async def _listener_watchdog():
    global _listener_task
    while True:
        if _listener_task is None or _listener_task.done():
            logger.warning("redis_listener_restarting")
            _listener_task = asyncio.create_task(_redis_listener())
        await asyncio.sleep(10)
```
Also remove nested `asyncio.new_event_loop()` from `_analyze_url_sync` — call the async function directly instead.

Secondary finding: `scripts/imessage-server.py::handle_reset_command` references `_re` (not defined; only `_idea_re = re` exists at module level) — causes a NameError on reset commands (low severity, see Later).

---

## Reference: Supabase Audit (§22, 2026-04-12)

| Repo | Classification | Rationale |
|---|---|---|
| **AI-Server** | 🟡 LEGACY | Zero Docker service code paths use Supabase. `integrations/supabase/` is an empty shell. Removing `SUPABASE_*` vars from `.env` has no runtime effect. |
| **symphonysh** | 🔴 REQUIRED | Contact form, appointment booking (read+write), confirmation emails, and Matterport upload all depend on Supabase Edge Functions + PostgREST. Turning it off breaks three user-facing flows. |

symphonysh migration estimate (if needed): ~8–9h (stand up `website-api` on Bob + migrate edge functions + replace Storage with R2 + remove `@supabase/supabase-js`). Not urgent while free tier covers current load.

---

## Reference: Calendar Tile Fix (§Z4, 2026-04-12)

Two root causes fixed in `cortex/dashboard.py` + `cortex/static/index.html`:

1. **Zoho sentinel not filtered** — `[{"message": "No events found."}]` was passed as a fake event when no events existed. Fixed: filter objects without `uid`, `title`, or `dateandtime`.
2. **Raw Zoho events not normalized** — start time was buried in `dateandtime.start` in compact format (`20260412T080000Z`). Fixed: `_parse_zoho_datetime()` + `_normalize_calendar_event()` produce a human-readable `start_display` field.

Remaining known limitation: timezone is stripped and treated as local; if Zoho stores UTC and Bob's TZ differs, times may be off. Acceptable for now — calendar-agent already queries in local Denver time.

---

## Reference: Lodash CVE-2026-4800 (§Z13, 2026-04-12)

Fix applied in `symphonysh/package.json`:
```json
"overrides": { "lodash": "4.17.21" }
```
Forced all transitive consumers (via `recharts`) to `4.17.21` — the only safe, non-deprecated, non-compromised lodash release. Build verified passing. Deployed to Cloudflare Pages (commit `967bdd2`).

`npm audit` still flags `lodash <=4.17.23` — this is a known false positive; the advisory range was written to block `4.18.0`/`4.18.1` (the compromised packages) but also catches `4.17.21`. **Do not run `npm audit fix`** — it would "upgrade" to `4.18.1`. Runtime exposure is none (no app code reaches `_.template` or `_.unset`).

---

---

## Reference: X Intake Review Queue (2026-04-13)

### Current behavior (before this change)

| Step | What happens |
|---|---|
| **Entry** | iMessage → Redis `events:imessage` (primary) OR x-alpha-collector → `POST /analyze` (every 10 min) |
| **Classification** | GPT-4o-mini: RELEVANCE 0-100, TYPE (build/alpha/stat/tool/warn/info), SUMMARY, ACTION. Fallback: keyword scoring when no OpenAI key. |
| **Routing** | relevance ≥ 40 → `polymarket:intel_signals`; ≥ 50 → `polymarket:knowledge_ingest`; always → iMessage reply |
| **Storage** | None — all ephemeral (Redis pub/sub + iMessage only). No persistence, no visibility, no approvals. |
| **Dedupe** | x-alpha-collector: JSON file (`/data/x_alpha_seen.json`, 7-day TTL). Main pipeline: none. |
| **Errors** | Logged only; silently dropped on task death (see §Z14 listener failure). |

### What was added (2026-04-13)

- **`integrations/x_intake/queue_db.py`** — lightweight SQLite queue at `/data/x_intake/queue.db` (Docker volume `./data/x_intake:/data/x_intake`). Every analyzed post is written with status, relevance, author, summary, action, poly_signals, and source. Auto-pruned after 30 days.
- **`integrations/x_intake/main.py`** — three changes:
  1. `_analyze_url` now returns structured `relevance`, `post_type`, `action`, `has_transcript` fields (previously swallowed).
  2. `_process_url_and_reply(url, source="imessage")` now enqueues every analyzed item; `/analyze` endpoint enqueues with `source=api`.
  3. Four new API endpoints: `GET /queue/stats`, `GET /queue?status=&limit=`, `POST /queue/{id}/approve`, `POST /queue/{id}/reject`.
- **`cortex/dashboard.py`** — four new proxy endpoints (`/api/x-intake/stats`, `/api/x-intake/queue`, `/api/x-intake/{id}/approve`, `/api/x-intake/{id}/reject`) routing to x-intake.
- **Cortex dashboard (X Intake card)** — new card in Column 3 (Brain) between Decisions and Daily Digest. Shows pending / auto-approved counts, up to 5 pending items with ✓ approve / ✗ reject buttons and "view →" link. Card border turns red when pending > 0. Refreshes every 60s (part of main refresh cycle) and immediately on action.

### Auto-approve thresholds (recommended default policy)

| Relevance | Status | Routing | Review needed? |
|---|---|---|---|
| ≥ 70 | `auto_approved` | polymarket+memory (as before) | No |
| 30–69 | `pending` | polymarket if ≥ 40 (unchanged) | Yes — visible in dashboard |
| < 30 | `auto_rejected` | none | No — visible in dashboard only |

Background automation is **unchanged** — all existing routing thresholds (40/50) continue to fire regardless of queue status. The queue is purely additive visibility and feedback capture, not a gate.

### Learning hooks

Human approve/reject decisions are stored in `reviewed_at` + `review_note` columns. These can be used to:
- Tune the auto-approve threshold (if most "pending" items are approved, raise the floor from 30 to 40).
- Identify high-value authors to promote to `ALWAYS_PROCESS_AUTHORS`.
- Build a fine-tuning dataset for the relevance classifier.

Query feedback: `sqlite3 data/x_intake/queue.db "SELECT status, COUNT(*) FROM x_intake_queue GROUP BY status"`

### Remaining follow-up work

1. **Rebuild x-intake** — `docker compose up -d --build x-intake` (new volume mount + queue_db.py).
2. **Rebuild cortex** — `docker compose restart cortex` (new proxy endpoints; bind-mounted so restart sufficient).
3. **Listener watchdog** — still needed (§Z14); the queue will have a gap while the listener is dead.
4. **Optional**: promote `x-alpha-collector` to pass `"source": "alpha_collector"` in its `POST /analyze` body so the dashboard distinguishes iMessage vs collector traffic.

---

---

## Reference: Transcript Storage & Agent Access (2026-04-13)

### Q1 — Where are transcripts stored?

Two stores exist; neither is complete.

**A. Flat-file store — `~/AI-Server/data/transcripts/`**

Created by `integrations/x_intake/video_transcriber.py::save_transcript()`.
Format: Markdown files named `@{author} — {topic summary} — {date}.md`.
Content: Summary, emoji-flagged insights (🔨💡📊🔧⚠️), strategies, key quotes, full transcript text.
Currently contains **2 files** (both written 2026-04-03/04).

Key finding: `TRANSCRIPT_DIR` defaults to `~/AI-Server/data/transcripts` in the Python source, but the x-intake docker-compose service block sets **no `TRANSCRIPT_DIR` env var and mounts no transcript volume**. Inside the container, `~` expands to the container home (not the host), so any transcripts produced by the Docker service are written to an ephemeral container path and **lost on restart**. The 2 existing host-side files were written by `scripts/imessage-server.py` calling `video_transcriber` directly on the host — not by the containerized x-intake service.

**B. SQLite queue DB — `data/x_intake/queue.db`**

Schema: `x_intake_queue` table (see §X Intake Review Queue above).
The `has_transcript` column is an **integer flag (0/1)** — it records whether a transcript was produced, but does **not store the transcript text or path**. The `summary` column holds up to 2,000 chars of the iMessage-formatted analysis output, not the raw transcript.

---

### Q2 — Does every new video/X item get transcribed into that store?

**No.** Transcription is attempted for all incoming X links, but succeeds and persists only under specific conditions:

| Condition | Result |
|---|---|
| Post has no video (text-only) | No transcription attempted; LLM analyzes post text directly |
| Post is image-only | GPT-4o vision analysis runs; `mode=image_vision` returns before `save_transcript()` — **no .md file written** |
| Video download fails (yt-dlp / gallery-dl / fxtwitter all fail) | `has_transcript=False`; nothing written |
| Video has no audio stream | Skipped with `video_has_no_audio_stream` log; nothing written |
| Transcription too short (≤1 char) | Error returned; nothing written |
| **Video transcribes successfully** | .md file written to `TRANSCRIPT_DIR` (host path if running outside Docker; ephemeral if inside container) |

The Whisper fallback chain is: whisper.cpp CLI → mlx-whisper → openai-whisper Python package → OpenAI Whisper API. If all four fail (e.g., no local Whisper installed and no `OPENAI_API_KEY`), nothing is written.

**Bottom line:** Only successfully-transcribed videos produce a .md file, and only then if the code is running on the host (not inside the container). The Docker x-intake service produces no durable transcript files today.

---

### Q3 — Do Bob and the agents read transcripts to analyze content and find hidden gems?

**No.** There is no reader anywhere in the codebase.

| Component | Transcript access |
|---|---|
| OpenClaw (orchestrator) | Zero references to `transcript`, `data/transcripts`, or `video_transcriber` in any `.py` file |
| Cortex engine | Receives `polymarket:knowledge_ingest` Redis events; these contain the ~500-char `summary` string only — not the full transcript |
| Cortex dashboard | Proxies x-intake queue stats and list; displays `has_transcript` boolean and truncated summary; does not fetch or render transcript text |
| iMessage reply | Receives the iMessage-formatted summary (flags + strategies); full transcript is never surfaced |
| bookmark_scraper.py | Writes a `_master_summary.md` to `TRANSCRIPT_DIR`; no agent reads it |

The .md files in `data/transcripts/` are **write-only dead ends** — produced as a best-effort artifact, never queried by any service or agent.

---

### Next Steps — Single Source of Truth (notes only, no code changes)

The current setup has three fragmentation problems:

1. **Volume not mounted.** The x-intake Docker service needs `./data/transcripts:/data/transcripts` added to its `volumes:` block, and `TRANSCRIPT_DIR=/data/transcripts` in its `environment:` block. Without this, all container-side transcripts are lost on restart and only the host-side imessage-server path ever writes durable files.

2. **Transcript text not persisted in the queue DB.** The `x_intake_queue` table has `has_transcript INTEGER` but no `transcript_path TEXT` or `transcript_text TEXT` column. Adding `transcript_path` (the .md file path) would let any agent find and read the file by querying the DB, creating a proper index.

3. **No agent reads transcripts.** Even if storage were fixed, no agent currently opens a .md file and mines it. A single-source-of-truth pattern would be:
   - x-intake writes transcript to `data/transcripts/@{author}...md` (persistent volume)
   - `queue.db` stores the path in a new `transcript_path` column
   - A new Cortex endpoint (e.g. `GET /api/x-intake/transcripts`) reads the queue for rows where `has_transcript=1` and serves the file content
   - OpenClaw's orchestrator (or a dedicated digest step) queries that endpoint, summarizes high-relevance transcripts, and writes insights to Cortex memory via `POST /remember`

This would close the loop from "video watched → transcript filed → insights surfaced in brain."

---

_Audit run by Claude Code on 2026-04-11/12. Health checks, row counts, and compose diffs are from live commands at audit time._
_X Intake review queue section added 2026-04-13._
_Transcript storage audit added 2026-04-13._
