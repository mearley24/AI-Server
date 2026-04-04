# Perplexity Computer — Symphony AI-Server handoff (paste as task)

Use this as the **system or first message** for a Perplexity Computer session. It assumes connectors to **GitHub** (repo `AI-Server` or local clone), optional **Google Drive / Notes** if the user links them, and **web** for docs.

---

## Project

**Symphony AI Server** — AI backend for Symphony Smart Homes (Vail Valley / Eagle County AV integration). Monorepo on a **Mac Mini** (Docker Compose): OpenClaw orchestrator, Mission Control dashboard (port **8098**), Redis, D-Tools Cloud bridge (**dtools-bridge**, host **127.0.0.1:8096** → container **5050**), email-monitor, proposals, voice, calendar, notification-hub, polymarket bot (vpn), OpenClaw, knowledge-scanner, intel-feeds, etc.

Key docs in repo: **`AGENTS.md`**, **`CLAUDE.md`**, **`.cursor/prompts/final-wiring-gaps.md`**, **`docs/PROPOSAL_DTOOLS_NEXT.md`**, **`knowledge/agents/LEARNER_ROADMAP.md`**, **`scripts/smoke-test.sh`**.

---

## Recently fixed (2026-04) — double-check on host

1. **D-Tools Bridge Docker health** — `GET /health` used to call `snapshot()` (three slow D-Tools API calls) and blew past Docker’s **10s** healthcheck. **Fix:** `integrations/dtools/dtools_server.py` — `/health` is now **liveness only** (API key present, fast **200**). Deep connectivity: **`GET /snapshot`**. Image rebuilt and container recreated on the host; **`docker compose ps dtools-bridge`** should show **`healthy`**, not stuck in **`health: starting`**.

---

## Implemented in code (verify behavior, not just files)

| Area | Status |
|------|--------|
| Follow-up + payment trackers on orchestrator tick | **`openclaw/orchestrator.py`** — `check_followups()`, `check_payments()` |
| D-Tools → jobs for Won / On Hold | **`openclaw/dtools_sync.py`** — auto-create path with duplicate check |
| Daily briefing email DB paths | **`openclaw/daily_briefing.py`** — `_find_email_db()` |
| Redis persistence | **`redis/redis.conf`** mounted in **`docker-compose.yml`** |
| Orchestrator Redis events | **`email.processed`**, **`jobs.synced`**, **`health.checked`**, **`briefing.sent`**, **`calendar.checked`** in **`orchestrator.py`** |
| Outcome listener | **`openclaw/main.py`** — `run_outcome_listener` task |
| Mission Control core UX | Digest markdown (**marked**), sidebar, invalid-date guards — see **`mission_control/static/index.html`** |
| Auto-responder | Wired in **`check_emails()`** — requires **`AUTO_RESPONDER_ENABLED=true`** (or `1` / `yes`) in env; **ACTIVE_CLIENT** cap per tick |

---

## Not finished / product gaps (your job to drive or verify)

1. **D-Tools Cloud proposal loop (business process)** — Engineering checklist in **`docs/PROPOSAL_DTOOLS_NEXT.md`**: search **`get_projects` / `get_opportunities` / `get_clients`** before creating duplicates; align pipeline with active installs; Control4 fallback patterns in **`tools/bob_export_dtools.py`**. The **API client** exists; **full workflow enforcement** in agents/UI may still be partial.

2. **Continuous learning / learner roadmap** — **`knowledge/agents/LEARNER_ROADMAP.md`**: steady **`continuous_learning.py`** / launchd, transcript mining → **`AGENTS.md`**, growing **`knowledge/cortex/`**. Confirm what is scheduled vs aspirational.

3. **Optional / flaky services** — Mission Control marks **Remediator** and **ClawWork** as optional for the “core” badge. If smoke or `/api/services` shows **11/12** or core **9/10**, distinguish **optional** vs **core** failures.

4. **Environment flags** — **`AUTO_RESPONDER_ENABLED`**, **`DTOOLS_API_KEY`**, Zoho tokens, etc. Confirm what is set in production **`.env`** (never paste secrets into chat).

5. **Git / data hygiene** — If **`git status`** shows conflicts on **`data/`** or `*.db`, those are **runtime/local** artifacts; resolve per team policy (often keep local DBs untracked or merge carefully).

---

## What to run on the Mac (Bob) to see “what’s still broken”

```bash
cd ~/AI-Server
./scripts/smoke-test.sh
curl -sS http://127.0.0.1:8098/api/services | python3 -m json.tool
curl -sS http://127.0.0.1:8096/health | python3 -m json.tool
curl -sS http://127.0.0.1:8096/snapshot | python3 -m json.tool   # D-Tools cloud connectivity (slower)
docker compose ps
```

Interpretation: **`/health`** on dtools-bridge = process + key; **`/snapshot`** = cloud round-trip. Mission Control **`healthy_core` / `total_core`** = operational summary.

---

## Ask of Perplexity Computer

1. Cross-check this handoff against **current** repo files (especially **`final-wiring-gaps.md`** and **`docs/PROPOSAL_DTOOLS_NEXT.md`**) and list **only** gaps that are still open or need validation.

2. Propose a **short ordered backlog** (P0 → P2) for the next work session, including anything that is **still not working** on the host (flapping containers, missing env, failing smoke sections).

3. If the user pastes **smoke-test output** or **`/api/services` JSON**, diagnose which services are down or degraded and suggest **one concrete fix** per item (compose service name, env var, or code path).

---

*Generated for Symphony AI-Server — update dates and outcomes when the situation changes.*
