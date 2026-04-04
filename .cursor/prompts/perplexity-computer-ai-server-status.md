# Perplexity Computer — AI-Server status, gaps, and what’s still broken

**Copy everything below the horizontal rule into Perplexity Computer.** Repo path on Bob’s Mac Mini: `~/AI-Server` (adjust if different).

---

## Your role

You are helping **prioritize, verify, and finish** remaining work on **Symphony AI-Server**: Docker services (OpenClaw, polymarket-bot, Mission Control, Redis, VPN, email-monitor, etc.), the **close-the-loop** outcome pipeline, and the **Mission Control** dashboard. Use **official repo files** as source of truth when paths are mentioned.

---

## A. Close the loop (OpenClaw + Redis + approvals) — **largely DONE in code**

| Item | Status |
|------|--------|
| Redis **`events:log`** audit (LPUSH + LTRIM alongside pub/sub) | **Done** — `openclaw/event_bus.py`, orchestrator |
| **`check_silent_services`** (~2h without heartbeats → alert) | **Done** — `openclaw/orchestrator.py` |
| **Approvals** — decision IDs, `pending_approvals`, iMessage YES/NO/EDIT, `POST /internal/approval`, `APPROVAL_BRIDGE_SECRET` | **Done** |
| **Pattern engine** — client email timing → `patterns.json` | **Done** |
| **Weekly “What I learned” digest** in daily briefing | **Done** — `decision_journal.weekly_digest_text` + costs |
| **Weather accuracy on redeem** | **Done** — hook in `polymarket_copytrade._emit_trade_resolved_event` → `strategies/weather_accuracy` store |
| **Ops: `scripts/backup-data.sh`, `backups/` gitignored, Redis in compose** | **In repo** |

**Ship / verify script:** `scripts/symphony-ship.sh` (`verify` | `ship` | `restart` | `full`). Docs: `.cursor/skills/symphony-docker-ship/SKILL.md`, `.cursor/rules/project.mdc`.

### A1. Not started / optional (possibles — not blocking)

| Item | Notes |
|------|--------|
| **Host backup cron** | Script exists; **cron line not necessarily installed** on the Mac: `0 4 * * * ~/AI-Server/scripts/backup-data.sh >> /tmp/backup-data.log 2>&1` |
| **Unified `events:log` from polymarket-bot** | Bot **PUBLISH**es to Redis; **does not** LPUSH audit lines like OpenClaw. Only needed if you want one list for every producer without going through orchestrator heartbeats. |
| **Execute real actions after approval** | Today: journal outcome + notification. **Not built:** auto-send draft email / run side effect on `approval_granted` for `email_classification`. |
| **Cursor “deploy” Agent** | Cursor **Skills → Create** makes an **Agent**, not an imported skill. Optional UX only; see `.cursor/prompts/close-the-loop-part2.md` **Possibles**. |

---

## B. Mission Control dashboard — **core UX done; polish thin**

**Files:** `mission_control/static/index.html`, `mission_control/main.py`, `mission_control/event_server.py`, port **8098**. Full intended UX: `.cursor/prompts/mission-control-final.md`.

| Area | Status |
|------|--------|
| §1–§10 baseline (dates, fonts, sidebar, quick actions, toasts, trading tag, sparklines, etc.) | **Implemented** — may still need **visual QA** after rebuild |
| **Settings view** | **Mostly placeholder** — no real settings editing, env editor, or doc links |
| **Daily Digest modal** | **Plain text**, not **rendered markdown** as spec asked — needs sanitizer + MD library or server-rendered HTML |
| **Trading view** | Works but can be **polished** (layout, mobile, error state when bot down) |
| **Expanded tiles vs spec** | Some columns **partial** (e.g. `checked_at`, container uptime, full subjects) depending on APIs |

---

## C. Still not working or fragile (production failure modes)

These are **symptoms**, not necessarily code bugs — environment and process matter.

| Symptom | Likely cause |
|---------|----------------|
| OpenClaw logs **“Trading bot unreachable”** | `polymarket-bot` down, restarting, or **8430** not up on **vpn** namespace. Check: `docker compose ps`, `curl http://127.0.0.1:8430/health`, `docker exec openclaw curl -sS http://vpn:8430/health`. |
| **`curl 127.0.0.1:8430` refused / empty** | **vpn** + **polymarket-bot** share network; bot uses `network_mode: service:vpn`. Restart order: redis → vpn → polymarket-bot. |
| Mission Control **`/api/events-log` empty or unavailable** | **OpenClaw** down or **REDIS_URL** wrong; orchestrator must run ticks to fill **`events:log`**. |
| **`structlog` crash in polymarket-bot** | Do **not** add `polymarket-bot/structlog.py` — it shadowed PyPI `structlog`. Use requirements only. |
| **Internal HTTP fails with proxy** | OpenClaw uses **`trust_env=False`** for httpx to internal Docker URLs. Reverting to `trust_env=True` can break `http://vpn:8430`. |
| **Redis IP drift for bot** | Compose may hardcode Redis IP for bot; after network recreate, verify **REDIS_URL** still valid. |

---

## D. What you should do next (suggested order)

1. **Smoke-test the stack:** `~/AI-Server/scripts/symphony-ship.sh verify` (or `ship` after code changes).
2. **Mission Control:** Manual click-through every nav, quick action, tile expand, WS; note regressions vs `mission-control-final.md`.
3. **Implement or schedule:** Settings content (non-secret), **safe markdown** for digest modal, Trading/expanded-tile polish as time allows.
4. **Ops:** Install **backup cron** on the host if not already.
5. **Optional:** Deferred approval actions; polymarket → `events:log` LPUSH; align any **`VERIFICATION_REPORT.md`** with repo reality.

---

## E. Constraints

- Dashboard: **vanilla JS** only (no React/TS) per project rules.
- **Secrets:** never embed in UI; env/Docker only.
- **Timezone display:** **America/Denver** where relevant.

---

**End of prompt — use sections A–E to plan work, run tests, and report what’s still broken vs environment.**
