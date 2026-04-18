# Guardrails Registry

Promoted operational rules. These are lessons that were observed often enough,
or with enough severity, that they are now **enforced practice**. New agents
MUST consult this file before designing new operational flows.

## Relationship to lessons

- Every guardrail is derived from one or more rows in `ops/LESSONS_REGISTRY.md`.
- When a lesson's `status` is flipped to `promoted_to_guardrail`, add a row here
  with `derived_from_lessons` pointing back at the lesson_id(s).
- If a guardrail is superseded, mark its `status` as `deprecated` here and flip
  the source lesson's `status` to `superseded`. Do not delete rows — history
  matters.

## Schema

| column | meaning |
|---|---|
| `guardrail_id` | Stable short ID, format `G-<NN>` (sequential, 2+ digits) |
| `derived_from_lessons` | Pipe-separated `lesson_id` list, or `manual` for policy-born rules |
| `description` | Short rule, one or two sentences max |
| `scope` | `task_runner`, `trading`, `email`, `calendar`, `symphonysh`, `pipeline_general`, `shell`, `git`, `docker`, `verification` |
| `risk_tier` | 0 (informational) · 1 (low) · 2 (medium) · 3 (high) — aligned with CLAUDE.md's tier model |
| `enforcement_mechanism` | Where/how the rule is actually enforced (preflight, runner, prompts, policy files) |
| `verification_method` | How an agent can confirm it is being followed |
| `status` | `proposed`, `active`, `deprecated` |

## How to add a guardrail

1. Pick the lesson(s) it derives from in `ops/LESSONS_REGISTRY.md` and flip
   their `status` to `promoted_to_guardrail`.
2. Append a new row below with the next `G-NN` id.
3. Commit both files in the same change.
4. If the guardrail introduces new automated enforcement, also update the
   relevant script (`ops/task_runner_preflight.py`,
   `ops/task_runner_gates.py`, etc.) and note it under `enforcement_mechanism`.

## Active guardrails

| guardrail_id | derived_from_lessons | description | scope | risk_tier | enforcement_mechanism | verification_method | status |
|---|---|---|---|---|---|---|---|
| G-01 | manual | Never ask Matt to paste terminal output; every diagnostic, verification, and final report must be written to `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`, then committed and pushed. | `verification` | 2 | `ops/AGENT_VERIFICATION_PROTOCOL.md` + agent prompts | `ls ops/verification/` has a file for every meaningful action | active |
| G-02 | manual | Always run `ops/task_runner_preflight.py` before dispatching queued tasks; clean ticks are silent, state-healing ticks write one report. | `task_runner` | 2 | `scripts/task_runner.py::run_once()` calls `run_preflight()` before `pull_latest()` | `python3 ops/task_runner_preflight.py --dry-run` exits 0 on clean tree | active |
| G-03 | manual | Repo-safe operational work (diagnostics, verification, repo hygiene, health checks, queue inspection, internal tooling) is **auto-approved**. High-risk work (data deletion, secrets rotation, money-moving, customer-visible comms) requires a committed `ops/approvals/<token>.approval` file OR `dry_run: true`. | `task_runner` | 3 | `ops/task_runner_gates.evaluate()` blocks high-risk tasks without approval | `python3 -m pytest ops/tests/test_task_runner_gates.py` | active |
| G-04 | manual | Never use `git pull` directly on AI-Server; always use `bash scripts/pull.sh`. The bare pull fails on `data/` state files and leaves the tree in a half-merged state. | `git` | 2 | `scripts/pull.sh` + agent prompts + `CLAUDE.md` hard rule | A bare `git pull` run on a dirty tree fails; `bash scripts/pull.sh` succeeds | active |
| G-05 | manual | No heredocs, multi-line quoted strings, or inline interpreters in any zsh/bash command block Cline/Claude hands the user. Use `python3 -c`, `printf`, or file writes. One unterminated quote locks the whole terminal session. | `shell` | 2 | `.clinerules` + `CLAUDE.md` "ABSOLUTE RULES" section | Agent prompts grep'd for `<<EOF` / `<<'EOF'` before shipping | active |
| G-06 | manual | Any service added to the stack MUST be declared in `docker-compose.yml` with a `GET /health` endpoint returning `{"status":"ok"}` that matches its healthcheck path. Orphan containers are invisible to `compose up/down`. | `docker` | 2 | `scripts/compose-drift-check.sh`; `CLAUDE.md` coding standards | `docker compose ps` lists every running Symphony container | active |
| G-07 | manual | Every lesson promoted from `ops/LESSONS_REGISTRY.md` must reference at least one verification file in its `evidence_refs` column. Guardrails born from policy may set `derived_from_lessons = manual`. | `pipeline_general` | 1 | `ops/learning_miner.py` enforces non-empty `evidence_refs` on write | Miner exits non-zero if an auto-mined lesson lacks evidence | active |

## Deprecated guardrails

<!-- keep a section for historical rules that have been replaced -->

_None yet._
