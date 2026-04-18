# CLAUDE.md — Symphony AI-Server

You are working on the AI backend for **Symphony Smart Homes**, a residential AV/smart-home integration company in Eagle County, Colorado (Vail Valley). Owner: Matt Earley. This runs on a Mac Mini M4 nicknamed "Bob."


Read this file completely before doing anything. Every section exists because time was wasted learning it the hard way.

---

## Repository Map

```
AI-Server/
├── openclaw/              # Orchestrator — Python, runs every 5 min
│   ├── orchestrator.py    # Main tick loop (follow-ups, payments, D-Tools sync, health)
│   ├── main.py            # FastAPI app, starts outcome listener
│   ├── daily_briefing.py  # 6 AM iMessage briefing (POSTs to Cortex on send)
│   ├── follow_up_tracker.py  # POSTs due follow-ups to Cortex
│   ├── follow_up_engine.py
│   ├── dtools_sync.py     # D-Tools Cloud job auto-create
│   ├── decision_journal.py
│   ├── continuous_learning.py
│   └── task_board.py
├── cortex/                # Bob's brain + unified dashboard (port 8102)
│   ├── engine.py          # FastAPI app, background loops, /health /query /remember /goals
│   ├── dashboard.py       # Ports MC /api/* endpoints onto Cortex
│   ├── memory.py          # SQLite-backed memory store
│   ├── goals.py / improvement.py / digest.py / opportunity.py
│   └── static/index.html  # Single-page dashboard (replaces mission-control UI)
├── polymarket-bot/        # Prediction market trading (Python)
│   └── src/
│       ├── pnl_tracker.py  # Every trade → Cortex /remember
│       └── cortex_client.py  # Fire-and-forget Cortex helper
├── email-monitor/         # Zoho IMAP polling (Python)
│   └── monitor.py         # Classified email → Cortex /remember
├── notification-hub/      # iMessage / Telegram / email dispatcher (Python)
├── integrations/
│   ├── x_intake/          # Twitter/X link analysis
│   └── dtools/            # D-Tools Cloud bridge
├── client-portal/         # Per-client status + e-signature (internal port 8096)
├── scripts/
│   ├── pull.sh            # THE ONLY WAY TO GIT PULL — never bare git pull
│   ├── symphony-ship.sh   # Build + deploy + verify
│   ├── smoke-test.sh      # Full stack health check
│   ├── verify-deploy.sh   # Post-deploy verification
│   ├── backup-data.sh     # Data backup
│   ├── set-env.sh         # Safe .env key setter
│   ├── api-post.sh        # JSON POST helper (no inline JSON)
│   └── bob-watchdog.sh    # Service watchdog
├── docker-compose.yml     # 19 containers (3 dead services removed in security cleanup)
├── .clinerules            # Cline context (kept for compatibility)
├── CLAUDE.md              # THIS FILE — Claude Code reads this first
└── .cursor/prompts/       # Task prompts (A through P, plus operational)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Runtime | Docker Compose, 19 containers on Mac Mini M4 ("Bob") |
| Voice | Node.js, Twilio Media Streams, OpenAI Realtime API |
| AI/LLM | OpenAI API (GPT-4o, Whisper), Ollama (qwen3:8b local) |
| Database | SQLite (decision_journal.db, jobs.db, follow_ups.db, emails.db) |
| Messaging | Redis (auth required — see below) |
| Infrastructure | Docker, Tailscale VPN, Mac Mini M4 |
| Frontend | Vanilla JS/HTML/CSS (no frameworks) |
| Website | React + Vite + shadcn/ui (separate repo: mearley24/symphonysh) |

---

## HARD RULES — Violating These Wastes Real Time and Money

### Git
- **ALWAYS** use `bash scripts/pull.sh` instead of bare `git pull`. Every bare pull fails on data file conflicts. This was lesson 6 and 22 from April 4.
- Commit messages: imperative mood, 72 chars max subject.
- Never commit .env files, API keys, or SQLite databases.
- Git config: email `earleystream@gmail.com`, name `Matt Earley`.

### Shell and Terminal (zsh — Cline/Claude Code on macOS)

**ABSOLUTE RULES — violating any of these locks the terminal and kills the session:**
- No heredocs (`<<EOF`, `<<'EOF'`, `<< 'DELIM'`)
- No multi-line quoted strings (triggers `dquote>` lock)
- No inline interpreters (`python3 <<EOF`, `node -e 'multi\nline'`)
- No interactive editors (vim, nano, `crontab -e`)
- No long-running dev servers or watch modes (`--watch`, `npm run dev`, `tail -f`)
- Use bounded commands only — every command must terminate on its own

**Safe ways to create multi-line files:**
```zsh
python3 -c "open('file.txt','w').write('line1\nline2\nline3\n')"
printf 'line1\nline2\nline3\n' > file.txt
echo 'line1' > file.txt && echo 'line2' >> file.txt
```

**Other shell rules:**
- All scripts must be zsh-compatible
- No inline JSON in curl commands — write to temp file, then `curl -d @file` (lesson 19). Use `scripts/api-post.sh`.
- Full paths in launchd scripts (`/usr/local/bin/docker`, `/opt/homebrew/bin/python3`)
- `pip install` needs `--break-system-packages` on macOS Sonoma+ (PEP 668), or use `~/AI-Server/.venv/`
- Never `echo "KEY=value" >> .env` — first entry wins, duplicates ignored. Use `scripts/set-env.sh KEY value`.

### Docker
- OpenClaw code is bind-mounted (`./openclaw:/app`). Python-only edits just need `docker restart openclaw`.
- **ALWAYS rebuild after code pushes:** `docker compose up -d --build <service>`. Bare restart does NOT pick up code changes baked into images. The trading bot burned $1,900 because strategy filters weren't deployed (lesson 16).
- Ship script: `./scripts/symphony-ship.sh` (build + up + verify).
- `pull.sh` auto-detects changed service directories and rebuilds them.

### Redis
- **All connections MUST use auth:** `redis://:<password>@redis:6379` (credentials in `.env` as `REDIS_URL` — never hardcode)
- Redis has a static IP in docker-compose.yml to prevent the polymarket bot from losing connection after restarts (lesson 13).

### Inter-Service Communication
- **Services NEVER import Python modules from other containers.** All inter-service communication is via HTTP endpoints. `from other_service import ...` causes ModuleNotFoundError (lesson 15).
- OpenClaw API: `http://openclaw:3000`
- Email Monitor: `http://email-monitor:8092`
- Cortex (brain + dashboard): `http://cortex:8102`
  - Health: `http://cortex:8102/health`
  - Dashboard: `http://cortex:8102/dashboard`
  - Memory POST: `http://cortex:8102/remember`
  - API: `http://cortex:8102/api/*`
- Notification Hub: `http://notification-hub:8095`
- D-Tools Bridge: `http://dtools-bridge:5050` (internal) / host port 8096
- Proposals: `http://proposals:8091`

### Verification — Trust Nothing
- **After every prompt, verify files exist.** Cursor/Cline/Claude Code may report "done" when files were never created (lessons 12, 20). Run: `for f in [expected files]; do [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"; done`
- **After any UI change, screenshot at 1280px and 375px** before deploying. Dashboard was rebuilt 4 times because nobody checked (lesson 21).
- **After deploying, run `scripts/verify-deploy.sh`** or `scripts/smoke-test.sh` to confirm services are healthy.
- **Check DB tables have actual data.** Empty tables mean a dead pipeline. D-Tools sync built to FIND jobs but not CREATE them — zero rows for weeks (lesson 11).
- **After launchd plist install, verify target script exists first:** `[ -f /path/to/script ] && launchctl load plist` (lesson 23).

---

## Coding Standards

- **Python**: PEP 8, type hints where practical, docstrings on public functions.
- **JavaScript**: 'use strict', CommonJS, 2-space indent, single quotes.
- **Shell scripts**: `set -euo pipefail`, comment every non-obvious step.
- **No TypeScript, no React/Vue in this repo** — plain JS only. (The website repo symphonysh is React.)
- Every script that reads a file must have **path fallback logic**. Never hardcode a single path (lesson 9).
- All Cortex/external service calls wrapped in **try/except** so a down service never crashes the caller.

---

## Key Paths on Bob

| Path | Contents |
|---|---|
| `~/AI-Server/` | This repo |
| `~/AI-Server/.env` | All secrets (OpenAI, Zoho, Kraken, ACH, etc.) |
| `~/AI-Server/data/openclaw/` | SQLite DBs (jobs.db, decision_journal.db, follow_ups.db) |
| `~/AI-Server/data/email-monitor/` | emails.db |
| `~/AI-Server/data/transcripts/` | X video transcripts by author |
| `~/Dropbox/[Project]/Client/` | Shared client files (use `scl/fi/` links, NEVER `/preview/`) |
| `~/Dropbox/[Project]/Internal/` | Internal work (never shared) |
| `/tmp/imessage-bridge.log` | iMessage bridge logs |
| `knowledge/brand/matt_earley_signature.png` | Matt's signature for documents |

---

## Docker Services Quick Reference

| Service | Port | Language | Notes |
|---|---|---|---|
| openclaw | 8099 | Python | Orchestrator, bind-mounted, restart for Python edits |
| cortex | 8102 | Python | **Brain + dashboard** — memory, goals, digests, improvement loop, and the unified web UI at `/dashboard`. Replaces the old mission-control on 8098. |
| email-monitor | 8092 | Python | Zoho IMAP, SQLite dedup. POSTs each classified email to Cortex. |
| notification-hub | 8095 | Python | iMessage / Telegram / email routing. POSTs high-priority sends to Cortex. |
| proposals | 8091 | Python | Proposal PDF + approval flow |
| client-portal | 8096 (internal) | Python | E-signature, per-client pages — health endpoint on 8096. |
| dtools-bridge | 8096 → 5050 | Python | D-Tools Cloud API bridge (published on 8096). |
| polymarket-bot | 8430 (via vpn) | Python | Trading via VPN. Records every trade into Cortex. |
| calendar-agent | 8094 | Python | Zoho calendar sync |
| voice-receptionist | 8093 → 3000 | Node.js | Twilio voice |
| clawwork | 8097 | Python | Background workflow runner |
| x-intake | 8101 | Python | X/Twitter link analysis |
| cortex-autobuilder | 8115 | Python | Bob/Betty research loop + topic scanning |
| rsshub | 1200 (internal) | Node.js | RSS feed proxy for X accounts |
| x-alpha-collector | — | Python | Monitors 40+ X accounts every 10 min via RSSHub |
| intel-feeds | 8765 | Python | Intel RSS aggregator |
| redis | 6379 | — | Auth required, static IP `172.18.0.100` |
| vpn | — | — | WireGuard, polymarket-bot routes through this |

---

## Common Failure Modes (Don't Repeat These)

| Failure | Root Cause | Prevention |
|---|---|---|
| `git pull` always fails | `data/network_watch/dropout_watch_status.json` conflicts | Use `bash scripts/pull.sh` exclusively |
| Bot deploys old code after push | `docker restart` doesn't rebuild images | Always `docker compose up -d --build <service>` |
| Redis connection lost after restart | Dynamic container IPs | Redis has static IP `172.18.0.100` in compose |
| Zoho token expired mid-session | Tokens expire every hour | Use auto-refresh helper `openclaw/zoho_auth.py` |
| Cross-container Python import fails | Containers don't share filesystems | HTTP endpoints only between services |
| .env key not updating | Appending creates duplicates; first wins | Use `scripts/set-env.sh KEY value` |
| Curl with inline JSON breaks | Shell escaping mangles quotes | Write JSON to temp file, use `-d @file` |
| Files "created" but don't exist | AI reported done without writing files | Verify with `ls -la` after every prompt |
| Launchd script can't find docker | Minimal PATH in launchd environment | Use full paths: `/usr/local/bin/docker` |
| pip install fails on macOS | PEP 668 externally managed environment | `pip3 install --break-system-packages [pkg]` |
| Dashboard text unreadable | No visual QA before deploying | Screenshot at 1280px and 375px, verify fonts |
| D-Tools sync creates zero jobs | Logic was find-only, not auto-create | Check DB tables have rows after deployment |
| Trading bot lost $1,900 in one day | Strategy filters never deployed (no rebuild) | Always `--build` after code changes |
| Document pricing out of sync | No staleness detection across doc types | Doc staleness tracker flags stale docs |
| Cortex orphaned from compose | Service running but not in docker-compose.yml | Every service MUST be defined in docker-compose.yml |
| Service reports unhealthy in compose | Missing `/health` endpoint in the app | Every service MUST have a `GET /health` endpoint matching its healthcheck path |
| Terminal stuck at `heredoc>` or `dquote>` | Used `<<EOF` heredoc or multi-line quoted string in zsh | NEVER use heredocs or multi-line quotes. Use `python3 -c` or `printf` with `\n` instead. This is the most common session-killer. |

---

## Standing Approval and Risk Tiers

**Default operating mode for agents working inside AI-Server is autonomous, not synchronous.** Matt's time and chat credits are expensive. Use the Symphony Task Runner (`scripts/task_runner.py`) and repo-based verification (`ops/verification/`) instead of asking him to copy, paste, or relay output. The one-paste rule in `ops/AGENT_VERIFICATION_PROTOCOL.md` is authoritative.

### Standing approval (LOW risk — just do it)

Standing approval is granted for low-risk, repo-safe operational work inside `/Users/bob/AI-Server`. An agent does not need to stop and ask before doing any of the following:

- **Diagnostics** — reading logs, querying SQLite, `docker compose ps`, health probes
- **Verification** — writing timestamped reports to `ops/verification/` and committing them
- **Repo hygiene** — resolving conflicts in whitelisted generated/state files (see preflight below), linting, formatting
- **Safe state-file conflict resolution** — `knowledge/markup_exports/.session_tracking.json`, `data/cortex/digests/**`, and any file covered by `merge=ours` in `.gitattributes`
- **Health checks** — running `ops/task_runner_health.py`, smoke tests, service probes
- **Queue inspection** — listing/reading `ops/work_queue/`, `ops/verification/`, launchd state
- **Logging improvements** — adding structured log lines, new events to `events:log`
- **Prompt updates** — editing `.cursor/prompts/`, `AGENTS.md`, `CLAUDE.md`, `.clinerules` for clarity
- **Productivity tooling** — helper scripts under `scripts/`, `ops/`, and `tools/` that don't touch production data
- **Internal automation improvements** — task runner, preflight, audit, health utilities

### Medium risk (verify and log — don't necessarily ask)

Medium-risk work proceeds without synchronous approval, but MUST log clearly to `ops/verification/` and leave a verifiable trail:

- Docker service restarts (`docker compose restart <svc>`)
- Rebuilds of bind-mounted services
- New launchd plists (install + kickstart, with a verification report)
- Non-secret env changes via `scripts/set-env.sh`
- Schema migrations on non-financial SQLite DBs
- New endpoints on existing services

### High risk (explicit approval required before execution)

These actions require explicit approval from Matt before running. Do not shortcut these:

- Deleting production data (databases, transcripts, memory stores, Dropbox content)
- Changing secrets or credentials (`.env` keys like `KRAKEN_SECRET`, `REDIS_PASSWORD`, OAuth tokens)
- Spending money (paid API calls with material cost, funding wallets)
- Trading or financial actions (Polymarket orders, Kraken trades, ACH transfers)
- Customer-visible outbound communication (email send, iMessage to client, public social post)
- Destructive infrastructure changes (dropping containers outside AI-Server, routing/DNS changes, VPN config)
- Actions outside AI-Server's current operational boundary (modifying another machine's filesystem beyond `ssh_and_run` allowlisted scripts, touching unrelated repos)

#### How the runner enforces the high-risk gate

`scripts/task_runner.py` invokes `ops/task_runner_gates.evaluate()` on every
task. A task is flagged **high-risk** when any of the following is set
(either at the top level or inside `payload`):

- `requires_approval: true`
- `risk_tier: "high"` (or `"critical"`)

A high-risk task is only executed if **one** of the following is true:

1. `dry_run: true` — no side effects, so no approval is required.
2. The task JSON carries `approval_token: "<token>"` AND the repo contains
   a committed file `ops/approvals/<token>.approval`. The file's contents
   are free-form; its presence + commit history is the audit trail.
3. `approval_token` equals the task's own `task_id`, AND that task_id is
   listed in `ops/approvals/AUTO_APPROVE_IDS.txt` (self-approval for
   pre-authorized recurring operations only).

Otherwise the runner writes a blocker report to
`ops/verification/YYYYMMDD-HHMMSS-blocker-<task_id>.txt`, moves the task
to `ops/work_queue/blocked/`, and does NOT execute it. A future agent
can unblock it by committing the approval file and re-queuing.

A future agent requesting approval should:

1. Queue the task JSON with `requires_approval: true` and a chosen
   `approval_token`.
2. Commit a `ops/approvals/<token>.approval` file describing the
   justification.
3. Matt (or another authorized agent) reviews and pushes the approval
   commit, at which point the next runner tick will execute the task.

See `ops/approvals/README.md` for the full operational recipe and
`ops/AGENT_VERIFICATION_PROTOCOL.md` for the tier model this implements.

#### Dry-run / staging lane

For high-risk campaigns, the recommended pattern is to **first queue the
task with `dry_run: true`** to exercise the logging path without any
write side-effects. The runner:

- Marks the gate decision as `approval_source=dry_run`.
- Propagates `dry_run=true` into the handler payload so handlers that
  support the flag (e.g. `run_cline_prompt`, `run_cline_campaign`) pass
  `--dry-run` to their launcher.
- Records the dry-run decision in the task's result file.

Once the dry-run log looks correct, re-queue the same task with
`dry_run: false` plus a valid `approval_token` + committed
`.approval` file to promote it to live. There is no separate staging
host today; dry-run is the staging lane within the same runner.

### Default behavior

When in doubt:

1. Write a timestamped report to `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`, commit, push
2. Use `scripts/task_runner.py` or a task JSON under `ops/work_queue/pending/` for operations that need to happen later
3. If blocked, write a blocker report to `ops/verification/` naming exactly what is needed — do not ask Matt to paste terminal output back

**Never ask Matt to manually relay command output.** The verification-to-file-then-commit pattern is the only supported way to share results between agents.

### Task Audit — linking a task to its artifacts

Every task produces a chain of artifacts: the signed JSON file under
`ops/work_queue/`, optional prompt file(s) for `run_cline_prompt` /
`run_cline_campaign` tasks, one or more verification logs under
`ops/verification/`, and the git commits that touched any of them.

Two repo-local CLI tools resolve this chain:

- `python3 ops/task_audit.py <query>` — fast substring search across
  verification + queue dirs. Good for "show me everything matching X".
- `python3 ops/task_audit_index.py <task_id_or_substring>` — loads the
  task JSON and follows its references. Prints the task JSON path,
  linked prompt file(s), verification artifacts, and relevant git
  commits in a single compact summary. Accepts `--json` for machine
  output and `--out PATH` to persist the report under
  `ops/verification/`.

Use `ops/task_audit_index.py` whenever you need to answer "what did this
task actually do, and where is the proof?" without paging through logs
by hand.


---

## Learning and Lessons

The pipeline now has a lightweight self-learning layer. Every meaningful
action already writes to `ops/verification/`; those files are mined into a
machine-readable **lessons registry**, stable patterns are promoted to a
**guardrails registry**, and a **digest** script teaches Matt what changed.
Full spec: `ops/AUTONOMOUS_EXECUTION_PIPELINE.md` → "Learning and continuous
improvement".

Key files:

- `ops/LESSONS_REGISTRY.md` — mined + hand-added lessons (Markdown table
  between `<!-- LESSONS_TABLE_START -->` markers).
- `ops/GUARDRAILS.md` — promoted operational rules. Bootstrap rows G-01 …
  G-07 cover the verification contract, preflight, approval gate, pull
  script, shell hazards, compose hygiene, and the lessons/guardrails
  contract itself.
- `ops/learning_miner.py` — scans recent `ops/verification/` files and
  upserts rows into `LESSONS_REGISTRY.md`. Idempotent, stdlib-only.
- `ops/learning_digest.py` — writes a plain-language digest to
  `ops/verification/YYYYMMDD-HHMMSS-learning-digest.md`.

Expectations for every agent working in this repo:

1. **Consult first.** Before writing a new fix for something that looks
   like a known problem, grep `ops/LESSONS_REGISTRY.md` and
   `ops/GUARDRAILS.md`. Don't rediscover what the system already learned.
2. **Record new fixes with miner-friendly headings.** In verification
   reports use the headings the miner recognises: `Root cause`,
   `Fix applied` (or `Minimal fix applied` / `Exact fix made`),
   `Remaining blocker`, `Next`, `Limitations` / `Known limitations`,
   `TODO`, `Follow up`. That's how the next miner tick picks them up.
3. **Promote lessons that stabilize.** If a lesson shows up in more than
   one verification file and describes a stable rule (not a one-off
   incident), flip its `status` to `promoted_to_guardrail` and add a new
   row to `ops/GUARDRAILS.md` with the next `G-NN` id.
4. **Run the miner and digest on demand.** Suggested cadence: miner
   daily, digest weekly.
   ```zsh
   python3 ops/learning_miner.py --days 7 --update
   python3 ops/learning_digest.py --days 7 --write
   ```
   The digest output is committed to `ops/verification/` like any other
   verification artifact.

No scheduler is wired yet; the runner already knows how to execute those
scripts via the `run_script` handler when you queue the task JSON.

---

## Running Cline Prompts via the Task Runner

The Symphony Task Runner can launch a Cline prompt end-to-end without any
manual copy-paste:

- Launcher: `ops/cline-run-prompt.sh <prompt-file> [--dry-run] [--timeout SEC]`
  - Detects the Cline CLI (`$CLINE_CLI` env override, else `cline` in PATH)
  - Verifies prompt exists, tees output to
    `ops/verification/YYYYMMDD-HHMMSS-cline-run-<basename>.log`
  - Exit codes: `0` OK · `3` missing prompt · `4` CLI not found · `5` CLI
    failure/timeout
- Campaign wrapper: `ops/cline-run-campaign.sh [--dry-run] [--stop-on-fail]
  [--timeout SEC] <prompt1> [prompt2 ...]`
  - Stops on unsafe failures; treats missing prompt / missing CLI as "safe
    blockers" (log a report, continue) unless `--stop-on-fail`.
- Task-runner task types: `run_cline_prompt` (payload:
  `{"prompt_file": "<repo-relative>", "dry_run": false, "timeout": 1800}`)
  and `run_cline_campaign` (payload: `{"prompt_files": [...], "stop_on_fail":
  false, ...}`). See `ops/work_queue/TASK_SCHEMA.md` → "How to queue a
  `run_cline_prompt` task" for the full recipe.

The launcher is safe to invoke by hand for a smoke test:

```zsh
bash ops/cline-run-prompt.sh --dry-run .cursor/prompts/cline-prompt-noop-smoke.md
```

---

## Prompts Directory

All task prompts live in `.cursor/prompts/`. Key series:
- **A-N**: Infrastructure, trading, monitoring, operations backbone
- **O**: Website experience overhaul (symphonysh repo)
- **P**: Full site audit and polish (symphonysh repo)
- **Q**: Full stack audit and status baseline → `STATUS_REPORT.md`
- **S**: Mission Control merged into Cortex — single brain + dashboard
- **T**: Approval drain — auto-expire stale pending approvals
- **U**: Client portal health + DB consolidation
- **V**: CLAUDE.md accuracy pass (this prompt)
- `lessons-learned-april4.md`: 25 documented failures with root causes
- `close-all-gaps-april10.md`: 6 independent gap-closing tasks
- `symphony-mega-prompt.md`: Full stack fix (7 parts)

The `DONE/` subfolder contains completed prompts.

---

## Security

- All API keys via environment variables in `.env` — never hardcoded.
- Version numbers are internal only — client-facing docs use "updated proposal."
- Each client document needs its own separate Dropbox share link.

---

## Startup Health Checks

When starting a session, verify these before doing anything else:

```zsh
cd ~/AI-Server
docker compose ps                                    # all containers running?
curl -s http://127.0.0.1:8099/health                 # openclaw alive?
curl -s http://127.0.0.1:8102/health                 # cortex brain + dashboard alive?
curl -s http://127.0.0.1:8092/health                 # email-monitor alive?
curl -s http://127.0.0.1:8095/health                 # notification-hub alive?
docker exec redis redis-cli -a "$REDIS_PASSWORD" PING   # redis alive?
docker exec redis redis-cli -a "$REDIS_PASSWORD" LRANGE events:log 0 2  # events flowing?
ls ~/Library/CloudStorage/Dropbox*/ >/dev/null 2>&1 && echo "Dropbox OK" || echo "Dropbox NOT syncing"
```

If any of these fail, fix them before proceeding with the task. A broken foundation wastes entire sessions.

---

## When Editing the Website (symphonysh repo)

The Symphony website is a **separate repo**: `mearley24/symphonysh`
- Stack: React + Vite + Tailwind + shadcn/ui
- Deploys via Cloudflare Pages on push to main
- Real project data in `src/data/projects.ts` (Eagle-Vail Theater, Beaver Creek Condo, Cordillera Media Room, West Vail Residence)
- No fake testimonials, no cookie-cutter filler text. Everything must be real.
- Slogan: "We Build Smart Homes That Just Work"
- Phone: 970-519-3013
- Service area: Vail, Beaver Creek, Edwards, Avon, Eagle, Minturn

---

## Quick Commands

```zsh
# Pull safely (THE way to pull)
bash scripts/pull.sh

# Deploy a service after code changes
docker compose up -d --build <service>

# Full deploy + verify
bash scripts/symphony-ship.sh

# Smoke test everything
bash scripts/smoke-test.sh

# Check a service's logs
docker logs <service> --tail 50 2>&1

# Restart bind-mounted Python service (no rebuild needed)
docker restart openclaw

# Safe .env update
bash scripts/set-env.sh REDIS_URL "redis://:<password>@redis:6379"

# Safe API POST (no inline JSON)
bash scripts/api-post.sh http://localhost:8099/api/endpoint '{"key":"value"}'

# Trigger manual daily briefing
docker compose exec openclaw python -c "from daily_briefing import DailyBriefing; import asyncio; asyncio.run(DailyBriefing().send())"

# Check Redis events
docker exec redis redis-cli -a "$REDIS_PASSWORD" LRANGE events:log 0 10
```

---

## Commit and Push

```zsh
git add -A
git commit -m "descriptive imperative message"
git push origin main
```

Never create PRs for this repo. Push directly to main. Matt is the sole developer.
