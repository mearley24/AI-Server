# HANDOFF — Symphony AI-Server

**Audience:** anyone (human or agent) who just cloned this repo and needs to
get oriented in under 15 minutes.

**TL;DR:** This repo runs **Bob** — a Mac mini M4 hosting Symphony Smart
Homes' autonomous operations stack (client ops, trading, intake, voice
receptionist, intel feeds). The brain is **Cortex**. Process and engineering
history lives **in this repo** — not in Linear. If the Cortex dashboard is
up, start there. If not, this file points at the canonical text.

---

## 1. Read these first, in this order

| # | File | Why |
|---|------|-----|
| 1 | `CLAUDE.md` | Top-level instructions for any Claude Code agent in this repo. Authoritative. |
| 2 | `AGENTS.md` | Long-form agent memory: north-star, runbooks, conventions, ULTRA prep. |
| 3 | `STATUS_REPORT.md` | Living journal of every recent landing, follow-up, NEEDS_MATT, and verification receipt. The single most up-to-date source on what is actually deployed. |
| 4 | `ops/BACKLOG.md` | The deduped Symphony Ops engineering backlog (this is what we *would* have put in Linear). |
| 5 | `ops/PROCESS_POLICY.md` | Division of responsibility: Linear vs Repo vs Cortex. Read before touching either. |
| 6 | `ops/REPO_LAYOUT.md` | Map of the directory tree by subsystem. |
| 7 | `ops/INTEGRATIONS.md` | External service catalog (Zoho, BlueBubbles, D-Tools, Twilio, Linear, etc.). |
| 8 | `PORTS.md` | Live port registry. Run `lsof -nP -iTCP -sTCP:LISTEN` on Bob to verify. |
| 9 | `docker-compose.yml` + `.env.example` | What runs in containers and what env it needs. |

---

## 2. What this thing is

- **Bob** — Mac mini M4, runs everything 24/7. Networking, power, and
  always-on rules: `setup/nodes/BOB_24_7_RUNBOOK.md`, `BOB_DEPLOY_GUIDE.md`.
- **Cortex** — central brain + operational dashboard. FastAPI app at
  `127.0.0.1:8102`. Code: `cortex/`. UI: `cortex/static/`.
  Routes: `cortex/dashboard.py` (`register_dashboard_routes`).
- **OpenClaw** — LLM orchestration + client-job lifecycle (`openclaw/`,
  port 8099). Owns Linear sync (client/job side only).
- **Symphony service mesh** — proposals, voice receptionist, calendar
  agent, email monitor, D-Tools bridge, notification hub, x-intake,
  bluebubbles, file-watcher, ClawWork, intel feeds. All loopback-bound
  except BlueBubbles (LAN, password-protected). See `PORTS.md`.
- **Trading** — Polymarket bot + research API. `polymarket-bot/`,
  `services/` for trading-api host launchd unit.
- **Operator surfaces** — Cortex dashboard (web), iMessage via
  BlueBubbles (mobile), iOS app (`ios-app/`), Telegram Bob remote
  (`telegram-bob-remote/`).

---

## 3. How process is tracked (canonical)

> Linear is **not** the system of record for engineering. See
> `ops/PROCESS_POLICY.md` for the full split.

| Concern | Where it lives |
|---|---|
| What's deployed / what landed today | `STATUS_REPORT.md` (always current) |
| Engineering backlog (was Linear, hit free-tier cap) | `ops/BACKLOG.md` |
| Verification receipts (live smokes, port audits, etc.) | `ops/verification/<stamp>-*` |
| Runbooks (one per repeatable op) | `ops/runbooks/` |
| Cursor/Cline prompts (active + archived) | `.cursor/prompts/` (`DONE/` for archive) |
| Lessons learned | `ops/LESSONS_REGISTRY.md`, `AGENT_LEARNINGS.md` |
| Self-improvement loop | `ops/self_improvement/`, summarized into `STATUS_REPORT.md` |
| Live client/business ops queue | **Linear only** — leads, jobs, follow-ups, scope changes |
| Operator action surface | Cortex dashboard (`/dashboard`) + iMessage approvals |

A read-only summary of the engineering backlog is exposed by Cortex at
`GET /api/process/backlog` (counts + headings parsed from
`ops/BACKLOG.md`), so the operator dashboard can surface "what are we
actually working on" without anyone having to open the file.

---

## 4. Common starting points

### "I want to see system health"
- Cortex dashboard: `http://127.0.0.1:8102/dashboard` (Overview tab,
  Symphony tab, Autonomy tab).
- Live listeners on Bob: `lsof -nP -iTCP -sTCP:LISTEN`.
- Container health: `docker compose ps` from repo root.
- Verification receipts: `ls -lt ops/verification/ | head -20`.

### "I want to run / debug something"
- Daemon launchers: `RUN_BOB.command`, `START_ALL_DAEMONS.command`,
  `START_TEAM.command`, `STOP_BOB.command`. Mac-only (require
  `osascript`).
- Bob deploy: `BOB_DEPLOY_GUIDE.md`.
- API smoke: `CHECK_APIS.command`.
- Task runner heartbeats are in `git log` (filter on
  `ops: task-runner preflight`).

### "I want to ship a change"
- Coding workflow + PR conventions: see `CLAUDE.md` and the
  `coding-workflow` / `pr-description` skills.
- Verification protocol: `ops/AGENT_VERIFICATION_PROTOCOL.md`.
- After landing, append a dated line to `STATUS_REPORT.md` and (if
  applicable) drop a receipt under `ops/verification/`.

### "I want to know what's broken / who's blocked"
- `STATUS_REPORT.md` — search for `[FOLLOWUP]` and `[NEEDS_MATT]` tags.
- Cortex `/api/process/backlog` for a machine-readable summary.

---

## 5. Secrets and env

- All secrets live in `.env` on Bob. **Never** commit secrets, never
  hardcode in source. Template: `.env.example`.
- Linear API key (`LINEAR_API_KEY`) is forwarded to the OpenClaw
  container only (`docker-compose.yml`); the standalone
  `operations/linear_ops.py` listener is not in compose and is dormant
  by design today.
- Redis password lives in `.env`; static Redis IP for the polymarket
  bot's network is `172.18.0.100`.
- LAN binding policy is enforced by `PORTS.md` — only BlueBubbles
  (`:1234`) is intentionally LAN-exposed.

---

## 6. What is Cortex, in one paragraph

Cortex is the FastAPI service that owns Bob's operational dashboard,
memory store, embeddings, autonomy/decision tracking, and an API
surface every other service consumes for status. It runs in a container
bound to `127.0.0.1:8102`. The dashboard SPA lives at
`cortex/static/index.html` (split into `dashboard.css` +
`dashboard.js`) and is served from `/dashboard`. New endpoints are
registered in `cortex/dashboard.py::register_dashboard_routes`. The
Bluebubbles webhook leg, x-intake reply approval flow, and process
backlog read endpoint all live there.

---

## 7. If Linear comes up

Short version: Linear is for **live client/business operations only**
(leads, active jobs, phase tasks, inbound-email signals, scope
changes, follow-up nudges). Engineering, ops, runbooks, verification,
and process history live in this repo. The free-tier active-issue cap
should not be hit by client work alone; if it ever is, that's the
signal to clean up stale issues — not to migrate engineering work in.

Full policy + rationale: `ops/PROCESS_POLICY.md`.

---

## 8. If you only have 60 seconds

Read `STATUS_REPORT.md` (top to first `---`), then `ops/BACKLOG.md`,
then this file's section 3. That's the minimum to not break anything.
