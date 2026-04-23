# Reply-Actions Phase 1 — Run Prompt

Phase 1 of the reply-action loop implementation is designed and ready
to run as an autonomous Cline/Claude Code task.

- **Design inputs**:
  - `docs/audits/x-intake-deep-dive-audit.md` §3 and §4
  - `config/reply_actions.schema.json`
- **Prompt file**: `.cursor/prompts/phase-1-reply-actions-foundation.md`

## What Phase 1 ships

- Outbound x-intake messages carry a per-message `ID:<hex>` and a
  numbered options block (one message, not a thread).
- Inbound BlueBubbles/iMessage reply parser accepts `1`, `reply 1`,
  `r1`, `option 2`, and bare digits; normalizes and resolves to a
  known `action_id`.
- Dispatcher with idempotency (dedupe window) and expiry enforcement,
  backed by `data/x_intake/reply_action_audit.jsonl`.
- Slots executed in Phase 1: **1 build_card, 2 deep_research,
  4 save_to_cortex, 6 open_thread**.
- Slots deferred to later phases (Phase 1 returns a pending-approval
  stub or a "not implemented yet" reply only): **3 prototype,
  5 mute_author**.
- No Docker testbed enablement. No trading, money, or external comms
  beyond the existing local BlueBubbles/iMessage path.

## Run command

Paste this exact command into a Claude Code session at the repo root:

```
claude --dangerously-skip-permissions -p "$(cat .cursor/prompts/phase-1-reply-actions-foundation.md)"
```

Or, from Cline, open the prompt file and run it with AUTO_APPROVE on.

## Expected final deliverables from the agent

- List of changed files.
- Tests added / skipped / results.
- Absolute path of the verification artifact under
  `ops/verification/YYYYMMDD-HHMMSS-phase-1-reply-actions.txt`.
- Commit hash (short SHA) pushed to `origin/main`.
- 3-bullet operator quickstart for using reply actions.
