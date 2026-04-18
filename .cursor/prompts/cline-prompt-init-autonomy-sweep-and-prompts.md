# Cline Autorun — Autonomy Sweep & Prompt Set Bootstrap

<!-- autonomy: start -->
Category: meta
Risk tier: low
Trigger:   manual
Status:    active
<!-- autonomy: end -->

You are working in the AI-Server repo on Bob or Bert.

Read these files first, in this order:

1. `.clinerules`
2. `CLAUDE.md`
3. `STATUS_REPORT.md`
4. `ops/AGENT_VERIFICATION_PROTOCOL.md`
5. `.cursor/prompts/cline-prompt-task-runner.md`
6. `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`

## Goal

Rebuild and standardize the autonomous prompt set, then add a
realized-change-driven `run_autonomy_sweep` capability so Bob or Bert can
fire sweeps automatically when changes are realized.

## Preconditions

- `AUTO_APPROVE = true` for low-risk, repo-safe operational improvements
  inside AI-Server.
- Do not ask the user to paste terminal output back into chat.
- All diagnostics, audits, and final reports must be written into
  `ops/verification/` as timestamped files, then committed and pushed.

## Operating mode

- Pre-empt all interactive prompts. Do not use workflows that can hang
  (SSH host-key prompts, sudo prompts, git credential prompts, REPLs,
  vim, nano, `docker logs -f`, `tail -f`, `watch`, or attached
  interactive shells).
- Do not use bare `git pull`. Use `bash scripts/pull.sh`.
- Keep changes small, clear, reversible, and aligned with the repo's
  current architecture.
- When writing bash snippets into repo docs or prompts, do not include
  inline comments inside the code blocks.

## Step plan

1. Add / update the **prompt standard** at
   `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md` and regenerate the
   index via `python3 scripts/build_prompt_index.py`.
2. Tag canonical active prompts with the autonomy metadata block so the
   index distinguishes standard from non-standard prompts.
3. Add the **autonomy sweep runner** at
   `scripts/autonomy_sweep.py` — diagnostic + verification report + safe
   auto-heals; see its docstring for the full contract.
4. Wire `run_autonomy_sweep` as an allowlisted task type in
   `scripts/task_runner.py` so remote agents can queue a sweep and walk
   away.
5. Install a **realized-change watcher** launchd job
   (`com.symphony.realized-change-watcher`) that enqueues an
   `run_autonomy_sweep` task every time a sentinel path under
   `ops/realized_changes/` is updated. Installer script must be bounded
   and idempotent — `setup/install_realized_change_watcher.sh`.
6. Commit + push. Write a final verification report to
   `ops/verification/<stamp>-autonomy-sweep-and-prompts-final.txt`.

## Guardrails

- No private keys in git. No secrets in commit messages.
- Do not enable sweep execution on high-risk task types (financial,
  customer-facing comms, secret rotation) — those still require the
  existing `ops/approvals/*.approval` gate.
- Do not run the realized-change watcher on a path that includes any
  `data/` or `knowledge/` content. It only watches `ops/realized_changes/`
  and `STATUS_REPORT.md`.

## Final report

Write to `ops/verification/YYYYMMDD-HHMMSS-autonomy-sweep-and-prompts-final.txt`:

- Files added / changed, with line counts.
- Index build output (`python3 scripts/build_prompt_index.py`).
- Autonomy sweep self-test output (`python3 scripts/autonomy_sweep.py --dry-run`).
- Launchd install status (or a note that install was deferred if the
  session is not on Bob).

Commit, push, and tell the next agent to pull.

AUTO_APPROVE: true
