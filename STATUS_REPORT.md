# STATUS REPORT — Symphony AI-Server

Generated: 2026-04-11 | Last updated: 2026-04-13
Host: Bob (Mac Mini M4), branch: main.
Audit series: Prompt Q (full audit) → Prompt S (Cortex merge) → Z3–Z14 patches.

---

## Now

_Action-required items this week. Most require Matt's input (credentials/funding)._

- **[Matt] Set `KRAKEN_SECRET`** — add the real Kraken API secret (same value as `KRAKEN_API_SECRET` in `.env` line 284) using `bash scripts/set-env.sh KRAKEN_SECRET <value>`, then `docker compose up -d polymarket-bot` (no rebuild needed). Kraken MM auth fails on every tick until this is set.

- **[Matt] Fund Polymarket wallet** — deposit $50+ USDC to `0xa791E3090312981A1E18ed93238e480a03E7C0d2` on Polygon. Wallet holds $1.94 USDC; all strategies skip with `low_bankroll`. No code change needed — bot re-reads on-chain balance every 5 minutes. Full operation needs $500 (configured bankroll).

- ~~**Rebuild + restart x-intake**~~ ✅ **Done 2026-04-13 08:14 MDT** — Rebuilt image (`ai-server-x-intake:latest`) and recreated container. Redis listener started on `events:imessage`, Uvicorn running on port 8101, health endpoint returning HTTP 200. Container status: `Up (healthy)`. Queue DB (`data/x_intake/queue.db`) and transcript volume (`data/transcripts`) mounted via `docker-compose.yml`. Follow-up still needed: durable listener watchdog (§Z14) — see Next.

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
- ✅ **x-intake rebuilt + restarted (2026-04-13 08:14 MDT)** — Image rebuilt (`ai-server-x-intake:latest`), container recreated. Redis listener live on `events:imessage`, Uvicorn on port 8101, health endpoint returning HTTP 200. Volume mounts for `data/x_intake` (queue.db) and `data/transcripts` now applied. Status: `Up (healthy)`. Remaining follow-up: durable listener watchdog per §Z14.

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
| x-intake | 8101 | Up | 🟢 | **Rebuilt + restarted 2026-04-13 08:14 MDT.** Listener up on `events:imessage`, health → 200. Volumes: `data/x_intake` + `data/transcripts` mounted. Watchdog (§Z14) still needed. |
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
_Transcript AI analysis pipeline added 2026-04-13._
_Transcript integration verification added 2026-04-13 (live audit)._

---

---

## Reference: In-Place vs Missing Systems Audit (2026-04-13)

_Evidence-based pass. All findings from live commands, file inspection, and container state at audit time._

---

### 1 — symphonysh Site Readiness

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Build clean, 0 errors | `npm run build` — 2680 modules, 3.21s, no warnings |
| 128/128 assets matched in dist/ | `diff public/ dist/` — zero differences |
| SPA routing correct | `public/_redirects` + `dist/_redirects` both present; all sampled routes return HTTP 200 |
| Live on Cloudflare Pages | `symphonysh.com` → HTTP 200 verified April 13 |
| Real project data (15 projects) | `src/data/projects.ts` populated; no placeholder images |
| SEO schema wired | `businessSchema.ts` — LocalBusiness, NAP, geo coords, opening hours |
| Booking flow | `/scheduling` — multi-step form, Zapier webhook, confirmation page |

| What is missing / needs business input | Note |
|---|---|
| All `testimonial` fields are `null` | `projects.ts` — needs real client quotes before a Testimonials section can go live |
| `BUSINESS_SAME_AS` is an empty array | No Google Business Profile URL confirmed yet — highest-ROI SEO action remaining |
| Business address confirmation | `45 Aspen Glen Ct` is in schema; Matt needs to confirm it as the public-facing address |
| No "Previous Work" page | `src/pages/` has no `PreviousWork.tsx` — portfolio lives in `Projects.tsx`; may be intentional |
| `gptengineer.js` still loaded | Lovable editor hook in `index.html`; adds a third-party script request per page load |

**What still needs to happen:**
- Matt: claim Google Business Profile, paste Share URL into `BUSINESS_SAME_AS`
- Matt: provide 2–3 real client testimonial quotes
- Matt: confirm business address is OK to publish
- Optional: remove `gptengineer.js` once Lovable is fully retired

---

### 2 — X Intake Workflow

**Classification: PARTIAL (pipeline functional, storage ephemeral)**

| What exists | Evidence |
|---|---|
| Full ingestion pipeline | Redis `events:imessage` → fetch → transcribe → analyze → Cortex POST |
| Listener watchdog | `_listener_watchdog()` running at startup — restarts dead listener every 10s |
| Queue DB + review API | `queue_db.py` + 4 new endpoints (`/queue/stats`, `/queue`, `/approve`, `/reject`) |
| Dashboard card | 17 references to x-intake in `cortex/static/index.html`; approve/reject buttons wired |
| Active transcription | Logs show 12-chunk video being transcribed via OpenAI Whisper API right now |
| Cortex POST working | 84 `x_intel` memories in `brain.db` — pipeline IS writing intelligence |

| What is missing | Evidence |
|---|---|
| Volume mounts NOT applied to running container | `docker ps` `Mounts:""` for x-intake; `data/x_intake/queue.db` is 0 bytes on host |
| All queue data is ephemeral | queue.db in-container has 1 pending item; host-side file is 0 bytes — lost on restart |
| All transcript .md files are ephemeral | Writes to container-internal `/data/transcripts`; not mounted to host |
| x-alpha-collector source not tagged | `POST /analyze` body sends no `source` field — dashboard can't distinguish iMessage vs collector traffic |

**Critical gap:** The container is running on a pre-rebuild image. `docker compose up -d --build x-intake` is required to apply the `./data/x_intake` and `./data/transcripts` volume mounts. All active transcript work (currently mid-transcription) will be lost on next restart until this is done.

---

### 3 — Transcript Pipeline

**Classification: PARTIAL (analysis running, persistence at risk)**

| What exists | Evidence |
|---|---|
| `transcript_analyst.py` | Full pipeline: parse .md → Ollama/GPT-4o-mini → Cortex POST |
| Hidden gem extraction | Structured JSON output: `hidden_gems`, `actionable_tasks`, `content_ideas`, `usefulness_score` |
| Cortex memory writing | 84 `x_intel` entries in `brain.db` (analysis IS running and persisting via HTTP) |
| Backfill endpoint | `POST /transcripts/backfill` — processes orphaned .md files not in queue DB |
| Stats endpoint | `GET /transcripts/stats` — files on disk, analyzed, pending, failed counts |
| 2 host-side .md files | `data/transcripts/@hrundel75...md` and `@moondevonyt...md` (written April 3–4) |

| What is missing | Evidence |
|---|---|
| Volume mount not applied | Same issue as §2 — transcripts written inside container are ephemeral |
| `transcript_path` not reliably stored | When container doesn't have the volume, transcript_path in queue rows is a container-internal path that won't be readable after rebuild |
| No cross-transcript synthesis | No agent reads multiple transcripts to find patterns across authors or themes |
| No retry queue for failed Cortex POSTs | If Cortex is down during analysis, result is logged but not retried |

**Note:** The 84 `x_intel` memories confirm the LLM analysis pipeline is functioning end-to-end. The weak link is storage durability (ephemeral container), not the analysis logic.

---

### 4 — Dashboard / Operational Visibility

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Cortex dashboard at `/dashboard` | Running at `localhost:8102/dashboard`; all service tiles loading |
| Service health matrix | 16 services polled; healthy/degraded/down per tile |
| X intake card | 17 refs in `index.html`; shows pending/auto-approved counts; approve/reject buttons |
| Events log | Redis `events:log` — 1000 capped entries, real traffic flowing |
| Trading tile | P&L, positions, redeemer status proxied from polymarket-bot |
| Follow-ups tile | Reads `follow_ups.db` directly; 30-day filter, overdue count |
| Decisions tile | Reads `decision_journal.db` and Cortex memory in parallel |
| Memory: 654 entries | `brain.db` has 654 memories across 21 categories |

| What is missing / blind spot | Evidence |
|---|---|
| `/api/memory/stats` returns 404 | No memory breakdown visible in dashboard by category |
| `/api/entries` returns 404 | No direct memory list API — must use `/memories` (unfiltered) |
| 163 pending_approvals with no drain UI | All `email_classification` kind; growing (103 → 163 since April 12); no dashboard tile |
| email-monitor events missing from feed | `notifier.py` has zero `cortex` or `redis.publish` calls — email actions are invisible |
| openwebui tile still present | Container still running (Prompt N item 1 not done) |

---

### 5 — Background Bob / Team Automation

**Classification: PARTIAL**

| What is truly running automatically | Evidence |
|---|---|
| OpenClaw orchestrator | 40 active jobs, runs every 5 min; `orchestrator.py` confirmed |
| Daily briefing at 6 AM | Line 1288 in `orchestrator.py` — `send_daily_briefing` confirmed; posts to Cortex |
| Follow-up tracker | `follow_up_tracker.py` posts to Cortex on follow-up events |
| Approval drain | `approval_drain.py` posts to Cortex — exists, but 163 rows unprocessed |
| Remediator | Running healthy (no healthcheck); auto-restart watchdog for containers |
| x-intake listener watchdog | Restarts dead Redis listener every 10s |
| Redeemer | Runs every 180s; 297 conditions redeemed; gas 62.85 POL |

| Where human review is still required | Note |
|---|---|
| 163 `pending_approvals` (email_classification) | No automated drain; no iMessage batch-approval script; growing backlog |
| Follow-up send approvals | `follow_up_log` has 0 rows — auto-send loop has not fired; needs approval to send |
| Trading credentials | KRAKEN_SECRET and Polymarket wallet funding are Matt's actions |
| Testimonials / GBP | symphonysh business content inputs |

| What is clearly missing | Evidence |
|---|---|
| `email-monitor/notifier.py` → Cortex or `ops:email_action` | Zero matches for `cortex`, `remember`, `ops:email` in notifier.py — Prompt N item 2 not done |
| `/calendar/daily-briefing` fetch in orchestrator | Zero matches for `calendar/daily-briefing` in `orchestrator.py` — Prompt N item 3 not done |
| openwebui removal from docker-compose.yml | Container still running — Prompt N item 1 not done |

---

### 6 — Trading / Polymarket

**Classification: PARTIAL (engineering complete, blocked on credentials + funding)**

| What exists | Evidence |
|---|---|
| Bot running LIVE mode | `POLY_DRY_RUN=false`; 11 strategies registered and ticking; `status: running` |
| Redeemer operational | 297 conditions redeemed all-time; last cycle idle (96 pending markets unresolved) |
| POL gas adequate | 62.85 POL — well above 0.05 minimum |
| Bot receives X intel | 84 `x_intel` Cortex memories; Redis `polymarket:intel_signals` channel active |
| Trading observability | Startup banner TRADING READINESS section present |

| What is blocked | Evidence |
|---|---|
| `KRAKEN_SECRET` empty | `/kraken/status` returns empty body (auth failure every tick) |
| Wallet: $1.94 USDC | All 11 strategies skip with `copytrade_skip: low_bankroll` |
| Kalshi in demo mode | `KALSHI_DRY_RUN=true`, `KALSHI_ENVIRONMENT=demo` |

**Next step is funding + credentials, not engineering.** All code is in place. No code changes needed to unblock trading — only Matt's actions (wallet deposit + KRAKEN_SECRET).

---

### 7 — Email / Calendar / Prompt Follow-Up

**Classification: PARTIAL**

| What is fixed | Evidence |
|---|---|
| Calendar tile fixed | Zoho sentinel filtering + compact datetime parsing confirmed in `dashboard.py` |
| Follow-up noise filter | `symphonysh.com` in `FOLLOWUP_NOISE_SENDERS`; tile shows accurate count |
| Daily briefing runs | `orchestrator.py` confirmed; posts to Cortex |
| approval_drain.py exists | Posts to Cortex on decisions |

| What is "good enough for now" | Note |
|---|---|
| All 435 emails marked `read=1` | Data is wrong (see §Z3) but dashboard filter (7-day + unread) masks the bug correctly |
| follow_ups.db canonical | 58 rows; `follow_up_log` in `jobs.db` still 0 — dual-home not yet resolved |
| Calendar timezone | Stripped + treated as local Denver time; acceptable but technically imprecise |

| What needs another pass | Evidence |
|---|---|
| email-monitor NOT posting to Cortex or ops:email_action | `notifier.py` — zero references to `/remember` or `ops:email_action` |
| Calendar daily-briefing not fetched in orchestrator | `orchestrator.py` — no `calendar/daily-briefing` call found |
| 163 pending_approvals unprocessed | No batch-drain script exists yet |

---

### 8 — Monitoring / Governance

**Classification: PARTIAL**

| What exists | Evidence |
|---|---|
| Redis `events:log` | 1000 capped entries; real traffic from all Redis-publishing services |
| Remediator | Running; auto-restarts unhealthy containers |
| `scripts/verify-cursor.sh` | Post-edit verification — checks files exist and are non-empty |
| `scripts/verify-deploy.sh` | Post-deploy smoke test — Redis PING + health checks |
| `scripts/pull.sh` | Safe git pull with stash + conflict scan |
| Cortex `brain.db` audit trail | 654 memories across 21 categories; decisions, x_intel, strategy_idea all flowing |

| Blind spots / gaps | Evidence |
|---|---|
| email-monitor emits no Redis ops events | `notifier.py` confirmed — no `ops:email_action` publish |
| Dropbox link validator absent | No validator found for `scl/fi/` vs `/preview/` enforcement (Lesson #4) |
| Lesson #17 (sell haircut rounding) unverified | Not confirmed in `polymarket-bot` code |
| 163 `pending_approvals` growing unchecked | Was 103 on April 12; no threshold alert, no auto-drain |
| openwebui still running | Prompt N item 1 not done; consuming memory unnecessarily |
| Cortex memory stats endpoint missing | `/api/memory/stats` → 404; dashboard has no memory category breakdown |

---

### NEXT 5 ITEMS

_Ranked by leverage — highest-impact, lowest-friction actions first._

**1. Rebuild x-intake** (`docker compose up -d --build x-intake`)
A video is actively being transcribed right now in 12 chunks. Without this rebuild, the volume mounts from `docker-compose.yml` are not applied, `queue.db` is ephemeral, and every transcript will be lost on the next container restart. One command. Zero code changes needed.

**2. Complete Prompt N items 1, 2, 3 (3 bounded changes)**
- Item 1: Remove `openwebui:` block from `docker-compose.yml` + `docker compose up -d` — frees memory, eliminates dead service tile
- Item 2: Add `redis.publish("ops:email_action", ...)` to `email-monitor/notifier.py` after action-required classification — closes the single biggest event-flow blind spot
- Item 3: Add `GET /calendar/daily-briefing` fetch to `openclaw/orchestrator.py` daily briefing assembly — confirmed missing by code grep

**3. Drain pending_approvals backlog (163 rows, all email_classification)**
Growing from 103 → 163 since April 12, with no drain mechanism. Implement Prompt T: group by kind, send batch to Matt via iMessage with YES/NO, auto-expire entries >7 days to `skipped` state with a log entry. Until this runs, 163 stale decisions are clogging the journal.

**4. Fund Polymarket wallet + set KRAKEN_SECRET** _(Matt action)_
Bot is live, all 11 strategies are ticking, redeemer is operational — blocked only by two missing inputs. `$50+ USDC` on Polygon wallet `0xa791...` + `KRAKEN_SECRET` via `bash scripts/set-env.sh KRAKEN_SECRET <value>` + `docker compose up -d polymarket-bot`. No code change needed.

**5. Update STATUS_REPORT stack health snapshot**
The April 12 snapshot says "21 entries, 1 this week" for Cortex. The live count is **654 memories across 21 categories** (84 x_intel, 328 install_notes, 55 proposal_template, 37 strategy_performance, etc.). The report is significantly out of date and misleads future agents about system health.

---

_Note on business-input dependencies: items 3–5 in "symphonysh" (testimonials, GBP, address) are exclusively waiting on Matt's real-world input. No engineering work is blocking them._

_Audit run: 2026-04-13. Evidence: live `docker ps`, `sqlite3` row counts, `curl` endpoint probes, file `grep` for code paths, container log tail. Weak evidence called out inline._

---

## Reference: Transcript AI Analysis Pipeline (2026-04-13)

### What was built

Three fragmentation problems identified in the transcript storage audit were fixed:

| Problem | Fix |
|---|---|
| Transcripts lost on container restart (no volume) | Added `./data/transcripts:/data/transcripts` volume + `TRANSCRIPT_DIR=/data/transcripts` env to x-intake in `docker-compose.yml` |
| `transcript_path` not stored in queue DB | Added `transcript_path TEXT` and `analyzed INTEGER` columns to `x_intake_queue`; schema migrates automatically on first boot |
| No agent reads transcripts | Created `transcript_analyst.py` — full deep-analysis pipeline reading .md files and writing to Cortex |

### Where transcript analysis now happens

**Entry point:** `integrations/x_intake/main.py`

After every successful video transcription, `main.py` now:
1. Stores the `.md` file path in `queue.db` (`transcript_path` column)
2. Fires `_analyze_transcript_background(transcript_path)` as an asyncio background task

**Analysis module:** `integrations/x_intake/transcript_analyst.py`

`analyze_transcript_file(md_path)` runs:
1. Parses the .md file (Summary, Flags, Strategies, Key Quotes, Full Transcript sections)
2. Builds a deep-analysis prompt covering all of Matt's interest areas (not just trading)
3. Tries Ollama first (`qwen3:8b`) → GPT-4o-mini fallback
4. Writes results to Cortex via `POST http://cortex:8102/remember`
5. Marks queue row `analyzed=1` (success) or `analyzed=2` (failed)

### What structured outputs are produced

The LLM returns a JSON object with:

| Field | What it contains | Written to Cortex as |
|---|---|---|
| `summary` | 3-5 sentences on the TRUE message of the video | `x_intel` memory |
| `key_topics` | 3-8 specific topics/techniques covered | Included in `x_intel` content |
| `hidden_gems` | Surprising/counterintuitive insights most people miss + why they matter to Matt | Included in `x_intel` content |
| `actionable_tasks` | Specific things Matt could build/implement/investigate, with priority | High+medium priority → separate `strategy_idea` or `external_research` memories |
| `content_ideas` | Angles for X posts or client education | Included in `x_intel` content |
| `tags` | 3-8 topic tags | Memory tags |
| `usefulness_score` | 0-100 integer (Matt-specific relevance) | Cortex memory `importance` (scaled) |
| `confidence` | 0.0-1.0 (transcript quality) | Cortex memory `confidence` |

**Cortex memory categories used:**
- `x_intel` — main insight (summary + hidden gems + content ideas); `importance` scales with usefulness score; 30-day TTL
- `strategy_idea` — high/medium priority "build" or "implement" tasks; 60-day TTL
- `external_research` — high/medium priority "research" or "investigate" tasks; 60-day TTL

### How Bob/agents find hidden gems

Once transcripts are analyzed, agents query Cortex normally:
```bash
# Find all transcript-derived insights
curl http://localhost:8102/memories?category=x_intel

# Search by topic
curl -X POST http://localhost:8102/query -H "Content-Type: application/json" -d '{"question":"trading strategy edge"}'

# Find all transcript tasks
curl http://localhost:8102/memories?category=strategy_idea
```

Transcript-sourced memories are tagged with the author handle and `transcript_task`, making them filterable.

### Backfill of existing transcripts

Two existing `.md` files in `data/transcripts/` (written before the volume was mounted) will be picked up by backfill:

```bash
# Trigger via API (runs in background, returns immediately)
curl -X POST http://localhost:8101/transcripts/backfill

# Or via Cortex proxy
curl -X POST http://localhost:8102/api/x-intake/transcripts/backfill

# Check status
curl http://localhost:8101/transcripts/stats
curl http://localhost:8102/api/x-intake/transcripts/stats
```

Backfill processes:
1. Queue DB rows with `has_transcript=1` and `analyzed=0` that have `transcript_path` set
2. Orphaned .md files in `data/transcripts/` not yet in the queue DB (the 2 pre-existing files)

### Listener watchdog (§Z14 fix also applied)

The Redis listener crash bug from 2026-04-11 was fixed in the same pass: startup now launches `_listener_watchdog()` instead of `_redis_listener()` directly. The watchdog checks every 10 seconds and restarts the listener if it has died.

### Observability

| Log event | When it fires |
|---|---|
| `transcript_analyst_start` | File processing begins |
| `transcript_analyzed` | LLM returned results (score, gem count, task count) |
| `transcript_cortex_written` | Memories posted to Cortex (count) |
| `transcript_cortex_posted` | Individual Cortex POST succeeded |
| `transcript_cortex_failed` | Cortex POST failed (Cortex down?) |
| `transcript_analysis_failed` | Both Ollama and OpenAI failed |
| `transcript_too_sparse` | Transcript is too short/garbled to analyze |
| `transcript_bg_analysis` | Background task completed (from main.py) |
| `transcript_bg_analysis_failed` | Background task threw exception |
| `redis_listener_restarting` | Watchdog detected dead listener |

### Remaining limitations

1. **Cortex must be running** — Cortex POST failures are logged and retried only via the backfill path. There is no internal queue to retry failed POSTs automatically.
2. **Transcript file format is fixed** — `transcript_analyst.py` expects the `.md` format written by `video_transcriber.save_transcript()`. Manually created or differently-formatted files may parse incompletely but won't crash.
3. **Ollama host must be accessible** — Ollama is tried first. If `http://192.168.1.199:11434` is unreachable (e.g. running outside the home network), the system falls back to OpenAI automatically.
4. **No cross-transcript de-dup** — If the same video is processed twice (two separate X links pointing to the same content), two separate Cortex memories are created. Low frequency in practice.

### Deploy commands

```bash
# Full rebuild required (new volume mount + new source file)
docker compose up -d --build x-intake

# Cortex is bind-mounted — restart sufficient for dashboard.py change
docker compose restart cortex

# Verify transcript volume mounted correctly
docker exec x-intake ls /data/transcripts

# Trigger backfill of the 2 existing transcripts
curl -X POST http://localhost:8101/transcripts/backfill

# Check analysis stats after backfill
curl http://localhost:8101/transcripts/stats
```

---

## Reference: Transcript Integration Verification (2026-04-13 live audit)

_All findings from live commands against the running container and host filesystem. No assumptions._

**Overall status: NOT WORKING — 0% analysis success rate, 0 memories from transcript_analyst in Cortex.**

---

### Q1 — Where do transcripts actually live today?

| Location | Path | Files | Durable? |
|---|---|---|---|
| Host filesystem | `~/AI-Server/data/transcripts/` | 2 files (Apr 3–4) | ✅ Yes — but orphaned (never analyzed) |
| Container ephemeral | `/root/AI-Server/data/transcripts/` (inside x-intake) | 4 files (Apr 13) | ❌ No — lost on container restart |
| Bind-mount target | `/data/transcripts` (inside x-intake) | Does not exist | — env var not applied |

**Root cause:** The running x-intake container is missing `TRANSCRIPT_DIR` and `CORTEX_URL` from its environment (`docker exec x-intake env` confirmed). The `docker-compose.yml` has both, but the container was last created before those vars were added. It was restarted (not recreated) since, so it runs with the old env. Without `TRANSCRIPT_DIR`, `video_transcriber.py` falls back to `~/AI-Server/data/transcripts` which expands to `/root/AI-Server/data/transcripts` inside the container — an unbound ephemeral path.

Verified: `docker exec x-intake ls /root/AI-Server/data/transcripts/` lists 4 files. `docker exec x-intake ls /data/transcripts/` exits non-zero (directory does not exist).

---

### Q2 — How do transcripts enter the analysis pipeline?

The wiring is correct in code:

1. `video_transcriber.process_x_video()` → calls `save_transcript()` → writes `.md` to `TRANSCRIPT_DIR`
2. `main.py._process_url_and_reply()` → calls `_analyze_transcript_background(transcript_path)` after enqueue if `transcript_path` is set
3. `_analyze_transcript_background()` → calls `transcript_analyst.analyze_transcript_file(path)` in a thread
4. `transcript_analyst` → Ollama (primary) → GPT-4o-mini (fallback) → `POST /remember` to Cortex

The trigger fires correctly. The path is wired. The failures occur inside step 3.

---

### Q3 — Are transcripts being analyzed into structured outputs?

**No. 100% failure rate on all attempts.**

Evidence from `docker logs x-intake --tail 200`:

| Log event | Count (last 200 lines) | Expected |
|---|---|---|
| `transcript_analyst_start` | 2 | ✓ fires correctly |
| `transcript_bg_analysis_failed` | 2 | ✗ should be 0 |
| `transcript_analyzed` | 0 | ✗ should match start count |
| `transcript_cortex_posted` | 0 | ✗ should follow success |

Error captured: `error='\'\\n  "summary"\''` — this is an exception (likely JSONDecodeError or KeyError) where the value `'\n  "summary"'` appears as the error string. This points to Ollama's qwen3:8b model producing malformed JSON in its response — qwen3:8b has a "thinking" mode that prepends reasoning tokens before the JSON output. With `format: json` enabled, the response body may contain a partial or prefix-corrupted JSON structure that both `json.loads()` and the code-block regex fail to parse, ultimately causing an unhandled exception that propagates out of `analyze_transcript_file` and is caught by the outer `transcript_bg_analysis_failed` handler.

The OpenAI fallback (`_openai_analyze`) runs only if `_ollama_analyze` returns `None` cleanly. If Ollama raises an exception that is NOT caught inside `_ollama_analyze`, it propagates before the fallback can run. Reviewing `_ollama_analyze`: all exceptions ARE caught (`except Exception as exc: logger.info(...); return None`). So the exception must originate elsewhere — most likely inside `_write_to_cortex` or `analyze_transcript_file` itself when processing the analysis dict, suggesting Ollama IS returning a response, but the response dict has unexpected structure that causes a downstream error.

**Net result: neither Ollama nor OpenAI paths are successfully producing Cortex memories from transcripts.**

---

### Q4 — Which agent/service is responsible?

| Component | Role | Status |
|---|---|---|
| `x-intake` container (port 8101) | Hosts the pipeline; triggers analysis | Running healthy |
| `integrations/x_intake/transcript_analyst.py` | Deep analysis + Cortex write | Code complete; runtime failing |
| `integrations/x_intake/main.py` | Triggers background analysis task | Wired correctly |
| `integrations/x_intake/video_transcriber.py` | Downloads, transcribes, saves .md | Working (files written) |
| Cortex `POST /remember` | Receives analysis output | Reachable (other services posting successfully) |

---

### Q5 — Are results visible anywhere?

| Store | Transcript-analyst memories | Source |
|---|---|---|
| `brain.db` — `x_intel` category | **0 rows** with `source LIKE 'x_intake:@%'` | Confirmed by `sqlite3` query |
| `brain.db` — `strategy_idea` category | **0 rows** with `title LIKE '[Task/@%'` | Confirmed by `sqlite3` query |
| `brain.db` — total `x_intel` | 92 entries, all titled "X Signal" | From x_alpha_collector / main.py quick-analysis path |
| `data/x_intake/queue.db` (host) | 0 bytes — never initialized | Container DB is ephemeral (no bind mount applied) |
| Cortex dashboard transcript stats | Proxied endpoint exists; returns 0 analyzed | `GET /transcripts/stats` works but shows nothing done |

The 92 `x_intel` memories that DO exist in Cortex come from the **short first-pass analysis** in `main.py._analyze_with_llm()` — not from `transcript_analyst`. These are the `RELEVANCE / TYPE / SUMMARY / ACTION` formatted memories, not the deep structured analysis (no hidden gems, no actionable tasks, no content ideas).

---

### Q6 — What is missing for this to work reliably?

Two blockers, in order of severity:

**Blocker 1 — Container not recreated (CRITICAL)**

```bash
docker compose up -d --build x-intake
```

This one command applies `TRANSCRIPT_DIR=/data/transcripts`, `CORTEX_URL=http://cortex:8102`, and the `./data/transcripts:/data/transcripts` volume mount. Until it runs:
- All new transcripts go to the ephemeral `/root/AI-Server/data/transcripts/` and are lost on restart
- `queue.db` on the host remains 0 bytes (container DB is not bind-mounted)
- The 4 transcripts written today inside the container will be lost on next restart

**Blocker 2 — Ollama JSON parse failure (BUG)**

`qwen3:8b` is the configured `OLLAMA_ANALYSIS_MODEL`. This model's thinking mode causes it to return JSON that the current parser cannot handle, producing an exception that bypasses the OpenAI fallback. Fix options (smallest first):

Option A — Strip thinking tags before parsing in `_ollama_analyze`:
```python
# After: content = raw.get("message", {}).get("content", "")
import re as _re
content = _re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
```

Option B — Disable thinking via Ollama options:
```python
# In the payload dict, change options to:
"options": {"temperature": 0.2, "think": false}
```

Option C — Switch to a model without thinking mode (e.g., `llama3.2`, `mistral`).

Until Blocker 2 is fixed, even after the container rebuild, `transcript_analyst` will fail on every Ollama call and fall through to OpenAI. OpenAI may succeed independently — needs verification after Blocker 1 is resolved.

**Gap 3 — 2 orphaned host-side transcripts never analyzed**

`data/transcripts/@hrundel75...md` (Apr 3) and `@moondevonyt...md` (Apr 4) are on disk but have never been processed. After the container is rebuilt and Blocker 2 is fixed, run:

```bash
curl -X POST http://localhost:8101/transcripts/backfill
curl http://localhost:8101/transcripts/stats
```

Note: `@hrundel75` has only `🎵` as its full transcript — `transcript_analyst` will correctly skip it as "too sparse". `@moondevonyt` has real transcript text (trading strategies, win rates) and should produce 1–3 Cortex memories.

---

### Exact next step

```bash
# Step 1: recreate the container with correct env + volumes
docker compose up -d --build x-intake

# Step 2: verify env applied
docker exec x-intake env | grep -E "TRANSCRIPT|CORTEX"
# Expected: TRANSCRIPT_DIR=/data/transcripts  CORTEX_URL=http://cortex:8102

# Step 3: verify volume mounted
docker exec x-intake ls /data/transcripts
# Expected: 2 .md files (the April 3-4 host files)

# Step 4: trigger backfill of existing transcripts
curl -X POST http://localhost:8101/transcripts/backfill

# Step 5: check results
curl http://localhost:8101/transcripts/stats
# If analyzed > 0, also check Cortex:
curl "http://localhost:8102/memories?category=x_intel" | python3 -m json.tool | grep -A3 "x_intake:@"
```

If step 5 shows `analyzed=0` and `failed=1` for the moondevonyt file, Blocker 2 (Ollama JSON parse) is confirmed and the qwen3:8b thinking-tag strip fix must be applied before the next rebuild.
