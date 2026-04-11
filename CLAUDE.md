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
├── docker-compose.yml     # 19 containers
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

### Shell and Terminal
- **All scripts must be zsh-compatible.** Matt runs directly in Cline/Claude Code terminal on macOS.
- **No interactive editors.** Never use vim, nano, or `crontab -e`. One-liner commands only.
- **No inline JSON in curl commands.** Write JSON to a temp file first, then `curl -d @file`. Shell escaping breaks every time (lesson 19). Use `scripts/api-post.sh` for API calls.
- **Full paths in launchd scripts.** Always use `/usr/local/bin/docker`, `/opt/homebrew/bin/python3`, etc. Launchd has minimal PATH (lesson 24).
- **pip install needs `--break-system-packages`** on macOS Sonoma+ due to PEP 668, or use the venv at `~/AI-Server/.venv/` (lesson 25).
- **Never use `echo "KEY=value" >> .env`** — first entry wins, duplicates are ignored (lesson 18). Use `scripts/set-env.sh KEY value` instead.

### Docker
- OpenClaw code is bind-mounted (`./openclaw:/app`). Python-only edits just need `docker restart openclaw`.
- **ALWAYS rebuild after code pushes:** `docker compose up -d --build <service>`. Bare restart does NOT pick up code changes baked into images. The trading bot burned $1,900 because strategy filters weren't deployed (lesson 16).
- Ship script: `./scripts/symphony-ship.sh` (build + up + verify).
- `pull.sh` auto-detects changed service directories and rebuilds them.

### Redis
- **All connections MUST use auth:** `redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379`
- Redis has a static IP in docker-compose.yml to prevent the polymarket bot from losing connection after restarts (lesson 13).

### Inter-Service Communication
- **Services NEVER import Python modules from other containers.** All inter-service communication is via HTTP endpoints. `from other_service import ...` causes ModuleNotFoundError (lesson 15).
- OpenClaw API: `http://openclaw:3000`
- Email Monitor: `http://email-monitor:8092`
- Cortex Memory: `http://cortex:8102`
- D-Tools Bridge: `http://dtools-bridge:8096`
- Mission Control: `http://mission-control:8098`

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
| client-portal | 8096 (internal) | Python | E-signature, per-client pages (no published host port). |
| dtools-bridge | 8096 → 5050 | Python | D-Tools Cloud API bridge (published on 8096). |
| polymarket-bot | 8430 (via vpn) | Python | Trading via VPN. Records every trade into Cortex. |
| calendar-agent | 8094 | Python | Zoho calendar sync |
| voice-receptionist | 8093 → 3000 | Node.js | Twilio voice |
| clawwork | 8097 | Python | Background workflow runner |
| knowledge-scanner | 8100 | Python | Symphony knowledge ingest |
| x-intake | 8101 | Python | X/Twitter link analysis |
| intel-feeds | 8765 | Python | Intel RSS aggregator |
| context-preprocessor | 8028 | Python | Pre-filter for agent context |
| remediator | 8090 | Python | Auto-remediation watchdog |
| openwebui | 3000 → 8080 | — | Local LLM UI |
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

---

## Prompts Directory

All task prompts live in `.cursor/prompts/`. Key series:
- **A-N**: Infrastructure, trading, monitoring, operations backbone
- **O**: Website experience overhaul (symphonysh repo)
- **P**: Full site audit and polish (symphonysh repo)
- `lessons-learned-april4.md`: 25 documented failures with root causes
- `close-all-gaps-april10.md`: 6 independent gap-closing tasks
- `symphony-mega-prompt.md`: Full stack fix (7 parts)

The `DONE/` subfolder contains completed prompts.

---

## Security

- All API keys via environment variables in `.env` — never hardcoded.
- Version numbers are internal only — client-facing docs use "updated proposal."
- Each client document needs its own separate Dropbox share link.
- Redis password is in this file for operational convenience — it's internal-only on Docker network.

---

## Startup Health Checks

When starting a session, verify these before doing anything else:

```zsh
cd ~/AI-Server
docker compose ps                                    # all containers running?
curl -s http://127.0.0.1:8099/health                 # openclaw alive?
curl -s http://127.0.0.1:8098/health                 # mission control alive?
curl -s http://127.0.0.1:8102/api/stats              # cortex alive?
docker exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 PING   # redis alive?
docker exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 LRANGE events:log 0 2  # events flowing?
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
bash scripts/set-env.sh REDIS_URL "redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379"

# Safe API POST (no inline JSON)
bash scripts/api-post.sh http://localhost:8099/api/endpoint '{"key":"value"}'

# Trigger manual daily briefing
docker compose exec openclaw python -c "from daily_briefing import DailyBriefing; import asyncio; asyncio.run(DailyBriefing().send())"

# Check Redis events
docker exec redis redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 LRANGE events:log 0 10
```

---

## Commit and Push

```zsh
git add -A
git commit -m "descriptive imperative message"
git push origin main
```

Never create PRs for this repo. Push directly to main. Matt is the sole developer.
