# Perplexity Computer Prompt — What’s Left, Started, and Still Broken

Use this as your first message in Perplexity Computer.

---

You are auditing and planning next steps for the `AI-Server` repo on Bob’s Mac (`~/AI-Server`).
Your output must clearly separate:
1) what is complete,
2) what has started but still needs finishing,
3) what has not started,
4) what is still broken or unknown due to missing host verification.

## Ground truth already implemented in code

Treat these as implemented (verify behavior on host, but do not re-plan from scratch):
- `openclaw/orchestrator.py`: follow-up + payment checks on tick, event emissions (`email.processed`, `calendar.checked`, `jobs.synced`, `health.checked`, `briefing.sent`), weekly learning hook.
- `openclaw/dtools_sync.py`: D-Tools won/on-hold job auto-create path.
- `openclaw/daily_briefing.py`: email DB path fallback.
- `openclaw/main.py`: outcome listener lifecycle.
- `integrations/dtools/dtools_server.py`: `/health` is liveness-only; `/snapshot` is deep cloud check.
- `mission_control/main.py`: optional services logic (`Remediator`, `ClawWork`) and service summary fields.
- `mission_control/static/index.html`: sidebar, digest markdown rendering, date guard work.
- New support scripts present:
  - `openclaw/continuous_learning.py`
  - `openclaw/task_board.py`
  - `tools/bob_maintenance.py`
  - `tools/bob_export_dtools.py`
  - `setup/nodes/configure_bob_always_on.sh`
  - `setup/nodes/BOB_24_7_RUNBOOK.md`
  - `setup/launchd/com.symphony.learning.plist`

## Started but not fully aligned

These are partially complete and need cleanup/alignment:
- AGENTS/docs refer to `orchestrator/continuous_learning.py` and `orchestrator/task_board.py`, but implementation currently lives in `openclaw/`.
- `knowledge/agents/LEARNER_ROADMAP.md` still points to `orchestrator/continuous_learning.py`.
- Need decision: move files to `orchestrator/`, add thin wrapper files there, or update docs to canonical `openclaw/` paths.

## Not started / still missing vs AGENTS references

These appear referenced but missing in repo:
- `orchestrator/WORK_IN_PROGRESS.md`
- `knowledge/agents/ULTRA_RUNBOOK.md`
- `.cursor/prompts/close-the-loop-part2.md`

## Still broken or unknown (requires host verification now)

Cannot be confirmed from static code alone. Validate on Bob host:
- Is D-Tools bridge stable/healthy after the liveness fix?
- Are core services at `healthy_core == total_core` in Mission Control?
- Are follow-up/payment DB sidecars populating?
- Is `events:log` receiving fresh entries continuously?
- Is `AUTO_RESPONDER_ENABLED` set intentionally in production env?
- Is weekly learning launchd job installed/loaded and actually running?

## Run these checks on host

```bash
cd ~/AI-Server
./scripts/smoke-test.sh
curl -sS http://127.0.0.1:8098/api/services | python3 -m json.tool
curl -sS http://127.0.0.1:8096/health | python3 -m json.tool
curl -sS http://127.0.0.1:8096/snapshot | python3 -m json.tool
docker compose ps
launchctl list | rg symphony
```

## Your deliverable

Produce a concise report with 4 sections:
1. **Done** (confirmed)
2. **In Progress** (started but incomplete/misaligned)
3. **Not Started** (missing artifacts)
4. **Still Not Working / Unknown** (based on runtime evidence)

Then provide a prioritized action list (P0/P1/P2) with exact file paths and commands for each action.

Do not include generic advice; tie every recommendation to a specific file, endpoint, service, or command.
