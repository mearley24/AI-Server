# Priority 1 Direct Runner (Claude Code, Sonnet 4.6 [1M])

One command on Bob to run all Priority 1 stages with verify / commit / push
gating between stages.

## The command

```bash
bash scripts/run-priority1-1m.sh
```

Run it from `~/AI-Server` (or anywhere inside the repo — the script
resolves the repo root itself).

## What it does

The script is a thin launcher. It performs no risky operations directly:

1. Locates the repo root (prefers `~/AI-Server`).
2. Smoke-tests the model by running:
   ```
   claude --model 'claude-sonnet-4-6[1m]' -p 'respond exactly: SONNET_1M_READY'
   ```
   and aborts if the reply does not contain `SONNET_1M_READY`.
3. Writes (or refreshes) the staged prompt at
   `.cursor/prompts/direct/priority1-stage-gate.md`.
4. Execs Claude Code with the full prompt against the 1M-context Sonnet 4.6
   model. Claude Code then carries out each Priority 1 stage, with
   verification artifacts under `ops/verification/`, `STATUS_REPORT.md`
   updates, and `git commit` + `git push origin main` between stages.

## Priority 1 stages (run in order)

1. Approval drainer LaunchAgent verification.
2. BlueBubbles webhook verification (or manual-test doc update).
3. Direct Claude Code Sonnet 4.6 [1M] docs (this file + discoverability).
4. Polymarket funding blocker verification.

After all four stages, a summary block is appended to `STATUS_REPORT.md`
and committed.

## Prerequisites on Bob

- `claude` CLI installed and on `PATH`.
- Logged into an Anthropic account with access to
  `claude-sonnet-4-6[1m]`.
- Repo checked out at `~/AI-Server` with `origin` set to the project
  remote and push access.
- `git` configured (user.name / user.email) for commits.

## Why this exists

Priority 1 needs reliable, auditable execution without a human juggling
heredocs or cursor. Running Claude Code directly against Sonnet 4.6 with
the 1M window lets the model hold the full stage plan + repo context in
one shot, while the launcher script keeps the invocation repeatable.

The staged prompt itself lives at
`.cursor/prompts/direct/priority1-stage-gate.md` and is the source of
truth for stage order and gating rules. The runner regenerates it on each
invocation so drift between the launcher and the prompt cannot occur.
