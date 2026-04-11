# STATUS REPORT — Symphony AI-Server

Generated: 2026-04-11 (Prompt Q — Full Project Audit & Status Baseline)
Host: Bob (Mac Mini M4), branch: main, clean working tree.

---

## 1. Stack Health

Run against `docker compose ps` and the health endpoints listed in CLAUDE.md's "Startup Health Checks" plus Phase 1 of Prompt Q.

| Service | Port | State | Health | Notes |
|---|---|---|---|---|
| openclaw | 8099 → 3000 | Up 26s (starting → healthy) | 🟢 | `/health` → 200. Orchestrator restarted during audit; backfilling client preferences from 200 stored emails, 40 active jobs. |
| mission-control | 8098 | **Restarting (1)** | 🔴 **P0** | `ModuleNotFoundError: No module named 'redis'` — crash loops every few seconds. Container image is stale; `redis` missing from image even though bind-mounted `main.py` imports it. Needs `docker compose up -d --build mission-control`. |
| cortex | 8102 | Up 26 hours | 🟢 | `/api/stats` → 21 entries, 10 neural paths, 6 problems. **Not defined in docker-compose.yml** — orphaned container from a prior compose (see §5). |
| email-monitor | 8092 | Up 2 hours | 🟢 | `{"status":"ok"}`. 435 emails in DB. |
| notification-hub | 8095 | Up 2 hours | 🟢 | Running, but bound to **8095**, not 8091 as CLAUDE.md claims. Port 8091 is actually `proposals`. CLAUDE.md's service table is out of date. |
| proposals | 8091 | Up 6 days | 🟢 | `{"status":"ok","service":"proposals"}`. Not mentioned in CLAUDE.md service table. |
| polymarket-bot | 8430 (via vpn) | Up 2 hours | 🟢 | `{"status":"healthy","version":"3.0.0"}`. Dry-run off, 5 strategies registered (copytrade, weather_trader, cvd_arb, mean_reversion, presolution_scalp), all at 0 trades since last boot. |
| client-portal | 8096 (container only) | Up 4 min | 🟡 **P1** | Listed "unhealthy". Internal healthcheck hits `/health` and gets 404 — the endpoint isn't defined in `client-portal/main.py`. Service itself is serving fine; only the healthcheck is wrong. |
| dtools-bridge | 8096 → 5050 | Up 6 days | 🟢 | `{"dtools":"ready","status":"healthy"}`. (Note: externally on 8096 you hit dtools-bridge, not client-portal — the latter has no published host port.) |
| redis | 6379 | Up 6 days | 🟢 | PING → PONG with auth, static IP `172.18.0.100`. `events:log` = 1000 entries, flowing in real time. |
| vpn (wireguard) | — | Up 3 days | 🟢 | Fronts polymarket-bot. |
| voice-receptionist | 8093 → 3000 | Up 6 days | 🟢 | — |
| calendar-agent | 8094 | Up 5 days | 🟢 | — |
| clawwork | 8097 | Up 6 days | 🟢 | — |
| context-preprocessor | 8028 | Up 6 days | 🟢 | — |
| intel-feeds | 8765 | Up 5 days | 🟢 | — |
| knowledge-scanner | 8100 | Up 5 days | 🟢 | — |
| openwebui | 3000 → 8080 | Up 6 days | 🟢 | — |
| remediator | 8090 | Up 6 days | 🟢 (no healthcheck) | — |
| x-intake | 8101 | Up 8 hours | 🟢 | — |
| browser-agent | 9091 | **not running** | ⚪ N/A | Referenced in CLAUDE.md service table but **no container named `browser-agent` exists** and it is not defined in `docker-compose.yml`. Either delete from docs or create the service. |

**Legend:** 🟢 healthy · 🟡 running-but-degraded · 🔴 broken · ⚪ not deployed

---

## 2. Data Pipeline Verification

### SQLite row counts
| DB | Table | Rows | Status |
|---|---|---|---|
| `data/openclaw/jobs.db` | jobs | **40** | flowing |
| | clients | 3 | thin — only 3 client records for 40 jobs |
| | job_events | 40 | flowing |
| | client_preferences | **0** | 🟡 EMPTY — pipeline never wrote here; orchestrator just started a backfill from 200 emails |
| | follow_up_log | **0** | 🟡 EMPTY — data lives in a separate `follow_ups.db`, not this table |
| `data/openclaw/decision_journal.db` | decisions | **3413** | flowing |
| | pending_approvals | **103** | 🔴 P0 BACKLOG — 103 approvals waiting on Matt (threshold: escalate if >20) |
| `data/openclaw/follow_ups.db` | follow_ups | **58** | flowing |
| `data/email-monitor/emails.db` | emails | **435** | flowing |
| | notified_emails | 39 | flowing |

### Redis events
- `events:log` length: **1000** (capped).
- Latest entries (as of audit) show real traffic: `email.client_reply` for Adam Bersin (positive sentiment), polymarket `strategy_dashboard` snapshots, polymarket `heartbeat` via orchestrator, calendar checks. Everything flowing.
- Subscribed channels (from openclaw outcome_listener): `events:email`, `events:trading`, `events:jobs`, `events:clients`, `events:system` — all wired.

### Cortex memory (`http://127.0.0.1:8102/api/stats`)
- 21 entries total, 1 this week, success rate 100%, 10 neural paths, 6 problems, 0 decisions pending.
- Top tags: deployment(10), failure(8), trading(5), email(4), fix(4), polymarket(4), docker(3), infrastructure(3).
- Healthy but **light** — only 1 new entry in the last week, suggesting most services are not yet POSTing to Cortex (see close-all-gaps Task 3).

### Orchestrator activity
- `openclaw.orchestrator` healthy loop with `AUTO_RESPONDER_ENABLED=off`.
- On startup: loaded 6 agents (bob_conductor, clawwork_agent, dtools_agent, proposals_agent, voice_agent, + one mis-labelled "unknown"), initialized memory / job_lifecycle / knowledge_base / client_tracker / dtools_sync / linear_sync / agent_bus, started outcome listener.
- Currently backfilling client preferences from 200 stored emails for 40 jobs.

---

## 3. Prompt Completion Matrix

Audit of the A–P Cline series plus operational prompts. (Titles abbreviated; full files in `.cursor/prompts/`.)

| Prompt | Topic | Status | Notes |
|---|---|---|---|
| **A** | copytrade-cleanup | 🟡 PARTIAL | `neg_risk` wiring done; quiet-hours disabled; fake P&L seeds + priority wallet injection removed. Runtime verification still needed. |
| **B** | mission-control-redesign | 🟢 COMPLETE | Trading-first 3-column dashboard, `/api/wallet`, `/api/positions`, `/api/pnl-series`, `/api/activity`, ops.html, dark theme — all present. **BUT the container is crash-looping (see §1), so none of this is user-visible right now.** |
| **C** | sandbox-bankroll | 🟡 PARTIAL | ExecutionSandbox referenced in copytrade; bankroll refresh tweaks started. Pre/post-trade checks need validation. |
| **D** | profitability-overhaul | 🟢 COMPLETE | Entry brackets (0.05–0.08 / 0.15–0.30), $3 copytrade size, $30 daily loss limit, 60 max positions, category reclassification — all merged. |
| **G** | spread-arb-fix (+G) | 🟢 COMPLETE | `GAS_FEE=0.005`, tuned `execute_opportunities`, complement arb cost guard shipped. |
| **I** | redeem-cleanup | 🟡 PARTIAL | `polymarket-bot/src/redeemer.py` exists with check/redeem methods; runtime validation of redemption success rate still pending. |
| **J** | performance-monitor | 🟢 COMPLETE | `performance_snapshot.py` with bracket analysis, USDC checks, trade history logging. ISO-8601 timestamp fix committed. |
| **K** | x-intake-bot-bridge | 🟢 COMPLETE | `_extract_polymarket_signals` in `integrations/x_intake/main.py` + Redis signal pub wired. |
| **L** | x-alpha-collector | 🟢 COMPLETE | `integrations/x_alpha_collector/` (collector.py + watchlist.json + Dockerfile). RSSHub integration present. |
| **M** | cortex | 🟢 COMPLETE (but orphaned) | `cortex/` has 9 Python modules (engine, memory, goals, improvement, opportunity, digest, migrate, config) + seed data. Container running. **Not defined in docker-compose.yml** — see §5. |
| **N** | operations-backbone | 🟡 PARTIAL | `voice_receptionist/system_prompt.md` and `calendar-agent/api.py` in place. Linear workflow integration not fully wired; openwebui removal not confirmed. |
| **O** | website-experience | ⚪ EXTERNAL | Targets `mearley24/symphonysh` repo (not this one). Not auditable from AI-Server. |
| **P** | site-audit-polish | ⚪ EXTERNAL | Same — `symphonysh` repo. |

### close-all-gaps-april10.md — 6 tasks
| Task | Topic | Status | Evidence |
|---|---|---|---|
| 1 | x-intake deep analysis (threads, link fetch, video, Cortex wiring) | 🟡 PARTIAL | `post_fetcher.py` (526), `video_transcriber.py` (892), `main.py` (565) all present with LLM hooks. Thread-continuation & Cortex POST wiring need runtime verification. |
| 2 | follow-up engine auto-send | 🟡 PARTIAL | `follow_up_engine.py` (579 lines) exists; 58 follow_ups tracked; **0 rows in `follow_up_log`** → auto-send-after-approval loop may not have fired yet. |
| 3 | Cortex wire-up for all services | 🟡 PARTIAL | Cortex is only receiving ~1 entry/week. Email-monitor, daily_briefing, notification-hub, polymarket-bot likely still not POSTing. |
| 4 | daily briefing improvements | 🟡 PARTIAL | `daily_briefing.py` (345 lines) present; last run recorded in `data/openclaw/briefing_status.json` at 2026-04-11 00:03. Cortex neural-paths section unverified. |
| 5 | pull.sh hardening (py_compile, --verify, auto compose up) | 🟡 PARTIAL | `scripts/pull.sh` is 50 lines — does stash + pull + conflict scan, but is short enough that the full hardening checklist likely isn't in. |
| 6 | Dropbox organizer fix | 🟡 PARTIAL | `scripts/dropbox-organizer.py` exists, plus `scripts/com.symphonysh.dropbox-organizer.plist`. Launchctl load status not verified in this audit. |

---

## 4. Missing Files

Against the file manifest in Phase 4 of Prompt Q, all 34 expected files exist **except**:

| Path | Situation |
|---|---|
| `integrations/cortex/main.py` | Referenced in CLAUDE.md ("integrations/cortex/") but the service actually lives at **`cortex/`** (top-level) as `cortex/server.py`, baked into the image. CLAUDE.md's path is wrong. |

No stub files (<10 lines) in the manifest — smallest real files are `scripts/api-post.sh` (14), `scripts/set-env.sh` (18), and `openclaw/doc_generator.py` (42), which match what the prompts asked for.

---

## 5. Docker Compose vs Running Reality

### Defined in `docker-compose.yml` (19 services)
openwebui, remediator, redis, vpn, polymarket-bot, proposals, email-monitor, voice-receptionist, calendar-agent, notification-hub, dtools-bridge, clawwork, openclaw, knowledge-scanner, mission-control, intel-feeds, context-preprocessor, x-intake, client-portal.

### Actually running (20 containers)
All 19 defined services + **cortex** (image `ai-server-cortex`, labeled compose project `ai-server`).

### Discrepancies
- 🟡 **cortex** is running but has **no entry in `docker-compose.yml`**. `grep cortex docker-compose.yml` → no matches. It was almost certainly defined in a prior compose and was removed (or lives in a compose override) but the container persists. This means `docker compose up/down` will not touch it, and a future `docker compose down --volumes` could orphan its data. **Action:** add the cortex service back to `docker-compose.yml` OR explicitly remove it from Bob.
- 🟡 **browser-agent** in CLAUDE.md (port 9091) is **not defined and not running**. The port is already used by some other host process. Fix CLAUDE.md.
- 🟡 **notification-hub** is documented as port 8091 / Node.js; in reality it's Python on **8095**. Port 8091 is `proposals` (which isn't mentioned in the CLAUDE.md table at all).
- No services are defined-but-not-running.

---

## 6. Lessons Learned Implementation (April 4 — 25 lessons)

| # | Lesson | Status | Evidence |
|---|---|---|---|
| 1 | Agreement doc stale after price change | 🟡 PARTIAL | `doc_staleness.py` (61 lines) — tracker exists but is thin |
| 2 | Deliverables doc stale after scope change | 🟡 PARTIAL | Covered by same doc_staleness tracker; `doc_staleness_state.json` being written (last update 2026-04-11 05:58) |
| 3 | TV Mount doc references wrong product | 🟡 PARTIAL | No email-to-doc linkage verified |
| 4 | Dropbox links must be `scl/fi/` not `/preview/` | ⚪ UNKNOWN | No automated link validator found |
| 5 | Docs must be signed automatically | 🟢 DONE | `knowledge/brand/matt_earley_signature.png` present; `doc_generator.py` (42 lines) wires it |
| 6 | `git pull` broken by data-file conflicts | 🟢 DONE | `scripts/pull.sh` (50 lines) is the canonical pull path |
| 7 | Dropbox not installed/signed-in on Bob | 🟢 DONE | `~/Library/CloudStorage/Dropbox*/` reachable |
| 8 | iCloud not signed in on Bob | ⚪ UNKNOWN | `brctl status` not checked this audit |
| 9 | Hardcoded paths blow up scripts | 🟢 DONE (policy) | Documented as a rule in CLAUDE.md |
| 10 | Mission Control fonts unreadable | 🟢 DONE | Redesigned per Prompt B — **but MC currently crash-looping** |
| 11 | D-Tools sync created 0 jobs | 🟢 DONE | jobs.db has 40 jobs now |
| 12 | Cursor files claimed but not created | 🟢 DONE | `scripts/verify-cursor.sh` present; Q audit reconfirms |
| 13 | Redis IP changes after Docker restart | 🟢 DONE | Static IP 172.18.0.100 in compose, password auth |
| 14 | Zoho token expires every hour | 🟢 DONE | `openclaw/zoho_auth.py` (69 lines) |
| 15 | Cross-container Python imports | 🟢 DONE (policy) | Codified in CLAUDE.md |
| 16 | `docker restart` doesn't pick up new code | 🟢 DONE (policy) | In CLAUDE.md; pull.sh rebuilds changed services |
| 17 | Sell haircut rounding — exit loops | ⚪ UNKNOWN | Not verified in polymarket-bot this audit |
| 18 | `.env` append duplicates first-wins bug | 🟢 DONE | `scripts/set-env.sh` (18 lines) |
| 19 | Shell escaping breaks inline-JSON curl | 🟢 DONE | `scripts/api-post.sh` (14 lines) |
| 20 | Post-prompt file verification | 🟢 DONE | `scripts/verify-cursor.sh` present |
| 21 | Dashboard rebuilt 4x without QA | 🟢 DONE (policy) | In CLAUDE.md screenshot rule |
| 22 | `git pull` always fails | 🟢 DONE | Duplicate of #6 |
| 23 | Launchd plists reference missing scripts | 🟢 DONE (policy) | CLAUDE.md lesson 23 |
| 24 | Launchd `docker` not in PATH | 🟢 DONE (policy) | CLAUDE.md lesson 24 |
| 25 | pip PEP 668 on macOS | 🟢 DONE (policy) | CLAUDE.md lesson 25 |

**Score:** 17/25 green, 4/25 yellow, 4/25 unknown. Open items concentrated in doc-staleness wiring and unverified macOS-host checks.

---

## 7. Open Issues (Prioritized)

### P0 — Fix today
1. **mission-control crash loop** — `redis` module missing from image. Rebuild: `docker compose up -d --build mission-control`. Verify `redis` is in `mission_control/requirements.txt`; if not, add it. Bonus lesson: this reproduces failure mode #16 from April 4 — code/requirements changed but image not rebuilt.
2. **103 pending_approvals in decision_journal.db** — massive backlog; approval UX is blocked. Triage: are any stale? Bulk-expire? Or drain via iMessage prompts.

### P1 — Fix this week
3. **client-portal unhealthy** — add a `GET /health` endpoint to `client-portal/main.py` that returns `{"status":"ok"}`, or fix the compose healthcheck path so the container reports healthy.
4. **cortex is orphaned from docker-compose.yml** — add the service definition back (build: `./cortex`, volumes, port 8102, healthcheck) so `docker compose down` / `symphony-ship.sh` actually manage it. Otherwise the next full restart will silently lose it.
5. **Cortex is starving** — only 1 entry in the last 7 days. Finish close-all-gaps Task 3: wire email-monitor, daily_briefing, follow_up_tracker, notification-hub, and polymarket-bot to POST to `http://cortex:8102/api/entries`.
6. **CLAUDE.md port/service table out of date.** Fix:
   - notification-hub is **8095**, Python, not 8091/Node.
   - proposals (**8091**) is missing from the table entirely.
   - browser-agent (9091) doesn't exist — remove or stand up.
   - integrations/cortex/* path is wrong — it's top-level `cortex/`.
7. **jobs.db tables scattered**: `client_preferences` and `follow_up_log` are empty in jobs.db, but `follow_ups.db` holds 58 rows. Pick one home; the current split is confusing and risks duplication as the orchestrator backfill runs.

### P2 — Cleanup
8. Finish `scripts/pull.sh` hardening from close-all-gaps Task 5 (py_compile, `--verify`, auto `docker compose up` on compose.yml change). Current pull.sh is 50 lines; target is ~90–100.
9. Verify Dropbox-organizer LaunchAgent is actually loaded (`launchctl list | grep dropbox-organizer`).
10. Verify iCloud sign-in on Bob (`brctl status`) — lesson 8 is still "unknown" a week later.
11. A–Prompt partials (A, C, I, N) need runtime validation, not more code.
12. Reconcile `openclaw/continuous_learning.py` (133 lines) with `openclaw/decision_journal.py` (437 lines) — both exist and may overlap.

---

## 8. Recommended Next Prompts (for Claude Code)

In order, each should be one self-contained prompt:

1. **Prompt R — Mission Control resurrection.** Add `redis` to `mission_control/requirements.txt`, rebuild the container, screenshot the dashboard at 1280px and 375px, verify `/api/wallet`, `/api/positions`, `/api/pnl-series`, `/api/activity` all return 200 with real data. Then document the redis dep in the mission_control Dockerfile so this can't silently regress again.
2. **Prompt S — Cortex re-adoption + wide wire-up.** (a) Add cortex back to `docker-compose.yml` with build context `./cortex`, port 8102, volumes, healthcheck. (b) Wire email-monitor, daily_briefing, follow_up_tracker/engine, notification-hub, and polymarket-bot to POST to `http://cortex:8102/api/entries` with try/except. Target: Cortex entry count >100 within 24h of deploy.
3. **Prompt T — Approval backlog drain.** Write a one-shot script that reads `pending_approvals` (103 rows), groups by kind, and sends Matt a batched iMessage summary with YES/NO quick actions. Stale approvals >7 days auto-expire to a "skipped" state with a log entry.
4. **Prompt U — client-portal health + jobs DB consolidation.** (a) Add `/health` to `client-portal/main.py`. (b) Decide canonical home for follow-up data — either fold `follow_ups.db` into `jobs.db.follow_up_log` or kill the empty table. (c) Decide canonical home for client preferences and retire the duplicate.
5. **Prompt V — CLAUDE.md accuracy pass.** Run the audit in §5 and §1 of this report, fix the service table (notification-hub port, proposals, browser-agent removal, cortex path), and add the two CLAUDE.md gaps exposed by this audit: (i) cortex must be in docker-compose, (ii) any new service MUST have a `/health` endpoint that matches its healthcheck.
6. **Prompt W — pull.sh hardening, round 2.** Finish close-all-gaps Task 5 exactly as specified: `py_compile` every service dir, `--verify` flag runs smoke-test, auto `docker compose up -d --build <changed>` on compose.yml change.

---

## Audit meta

- Audit run by Claude Code on 2026-04-11 using CLAUDE.md as context.
- Did NOT re-explore the codebase from scratch — worked from the CLAUDE.md repo map.
- Health checks, row counts, and compose diffs are from live commands at audit time.
- Prompt status for A–P validated by skimming each prompt and checking referenced files exist with real content.
