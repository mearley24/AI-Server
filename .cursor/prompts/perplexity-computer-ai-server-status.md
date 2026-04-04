# Perplexity Computer — AI-Server: what’s done, what’s left, what breaks

**Copy everything below the horizontal rule into Perplexity Computer.** Repo on Bob’s Mac Mini: `~/AI-Server` (change if your path differs).

---

## Your role

You are helping **prioritize, verify, and finish** work on **Symphony AI-Server**: Docker (OpenClaw, polymarket-bot, Mission Control, Redis, VPN, email-monitor, etc.), the **orchestrator tick**, **Redis / events**, and **Mission Control** UI. Treat paths in this repo as source of truth.

---

## A. Close the loop (outcomes, Redis audit, approvals) — **done in code**

| Item | Notes |
|------|--------|
| **`events:log`** + pub/sub | `openclaw/event_bus.py`, orchestrator `_redis_publish` / `_redis_log_only` |
| **`check_silent_services`** | ~2h missing heartbeats → alerts |
| **Approvals** | `pending_approvals`, iMessage YES/NO/EDIT, `POST /internal/approval`, `APPROVAL_BRIDGE_SECRET` |
| **Pattern engine + weekly digest** | `decision_journal.weekly_digest_text`, briefing |
| **Weather accuracy on redeem** | `polymarket_copytrade` → `weather_accuracy` store |
| **Ship script** | `scripts/symphony-ship.sh`; see `.cursor/rules/project.mdc` |

### A1. Still optional / not started (not blocking core loop)

| Item | Notes |
|------|--------|
| **Host backup cron** | `scripts/backup-data.sh` exists; **cron may not be installed** — e.g. `0 4 * * * ~/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1` |
| **Polymarket → same `events:log` LPUSH as OpenClaw** | Bot **PUBLISH**es only; unified audit list is optional |
| **Run real action after approval** (send draft, etc.) | Journal + notify only today |
| **Cursor deploy-only Agent** | Optional; see `.cursor/prompts/close-the-loop-part2.md` |

---

## B. Final wiring (orchestrator integration) — **implemented (verify in prod)**

See `.cursor/prompts/final-wiring-gaps.md` for the original gap list. Status:

| Area | What shipped |
|------|----------------|
| **Follow-up tracker** | `check_followups()` after emails; DB `DATA_DIR/follow_ups.db`; Redis `client.followup_alert` |
| **Payment tracker** | `check_payments()`; DB `DATA_DIR/payments.db`; Redis `job.payment_received` when payments detected |
| **D-Tools auto jobs** | `get_job_by_dtools_id()` + auto-create for **Won** / **On Hold** opps without duplicate `d_tools_id` |
| **Daily briefing script** | `_find_email_db()` + optional `dotenv` for cron |
| **Redis persistence** | `redis/redis.conf` + compose mount |
| **More bus traffic** | `email.processed`, `calendar.checked`, `jobs.synced`, `health.checked`, `briefing.sent` |
| **Outcome listener** | Already runs from `openclaw/main.py`; more events = more scoring opportunities |
| **Auto-responder** | **Off by default** — set **`AUTO_RESPONDER_ENABLED=true`** for OpenClaw to draft **one** `ACTIVE_CLIENT` reply per tick (uses OpenAI + IMAP + Zoho; costs $) |

### B1. Not started or needs your decision

| Item | Notes |
|------|--------|
| **Turn on auto-responder** | Only if you want automated drafts — env flag above |
| **End-to-end test** | Confirm follow-up/payment DBs populate and D-Tools job creation matches real API **status** strings (Won/On Hold naming) |
| **Deferred approval execution** | Still future (send email on grant) |

---

## C. Mission Control — **core done; polish not done**

**Files:** `mission_control/static/index.html`, `mission_control/main.py`, `mission_control/event_server.py`, port **8098**. Spec: `.cursor/prompts/mission-control-final.md`.

| Still thin / not finished |
|---------------------------|
| **Settings** — placeholder; no ports table, doc links, or env editor |
| **Digest modal** — plain text, not **rendered markdown** |
| **Trading view** — hierarchy, mobile, **offline bot** banner |
| **Expanded tiles** — some columns partial vs spec (`checked_at`, uptime, full subjects) |
| **Visual QA** — click every nav, quick action, tile, WS after each deploy |

---

## D. Still broken or fragile (symptoms → likely cause)

| Symptom | Likely cause |
|---------|----------------|
| **“Trading bot unreachable”** in OpenClaw | `polymarket-bot` down / **8430** not listening on **vpn** stack. Check `docker compose ps`, `curl http://127.0.0.1:8430/health`, `docker exec openclaw curl -sS http://vpn:8430/health`. |
| **`curl 127.0.0.1:8430` fails** | **vpn** + bot share network (`network_mode: service:vpn`). Restart **redis → vpn → polymarket-bot** order. |
| **Mission Control `/api/events-log` empty** | OpenClaw down, Redis down, or orchestrator not ticking |
| **Polymarket crash: `structlog.configure`** | Never add **`polymarket-bot/structlog.py`** — it shadowed PyPI `structlog`. |
| **Internal HTTP weirdness** | OpenClaw **httpx `trust_env=False`** — re-enabling proxy on internal URLs breaks `http://vpn:8430`. |
| **Redis IP for bot** | Bot may use fixed IP in env; after `docker network` recreate, confirm **REDIS_URL**. |
| **Follow-up/payment “no data”** | Need **`EMAIL_MONITOR_DB_PATH`** readable + writable **`DATA_DIR`** for SQLite sidecars |

---

## E. Suggested order of work

1. **`./scripts/symphony-ship.sh verify`** (or `ship` after pulls).
2. **`docker logs openclaw`** — confirm tick runs, no tracebacks in `check_followups` / `check_payments` / `sync_dtools`.
3. **`docker exec redis redis-cli LRANGE events:log 0 15`** — confirm new event types appear over time.
4. **Mission Control** manual QA + **Settings / digest markdown / trading polish** as desired.
5. **Backup cron** on host if not set.
6. **Optional:** enable `AUTO_RESPONDER_ENABLED`, approval side effects, polymarket `events:log` parity.

---

## F. Constraints

- Mission Control: **vanilla JS** only (no React/TS) per project rules.
- **Secrets:** never in client UI; use env / Docker.
- **Timezone:** **America/Denver** where relevant.

---

**End of prompt — use sections A–F to plan, test, and report what’s still broken vs environment vs not yet built.**
