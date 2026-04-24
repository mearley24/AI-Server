# BlueBubbles → Cortex Live Webhook Verification — Prompt Creation Receipt

UTC stamp: 20260424-151726
Runner: Claude Code (parent-agent repo pass, autonomous subagent)
Host: sandbox (not Bob)
Scope: repository-only; no runtime/external action performed.

## What this receipt attests

This repo pass added the autonomous prompt + companion runbook that
will, when executed on Bob by Matt via Cline, verify the fully-live
BlueBubbles → Cortex webhook path. The repo pass itself did **none**
of the runtime work — no curl, no docker, no BlueBubbles UI
inspection, no external message send, no settings or config mutation,
no service restart, no port change, no secret read, no sudo.

## Files created

| Path | Purpose |
|---|---|
| `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md` | Autonomous Cline prompt (Category: messaging, Risk: high, Trigger: manual, Status: active). |
| `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` | Human-approved companion runbook (no autonomy metadata; dispatcher-skipped). |
| `ops/verification/20260424-151726-bluebubbles-cortex-live-webhook-prompt-creation.md` | This receipt. |

## Files modified

| Path | Change |
|---|---|
| `STATUS_REPORT.md` | Prepended dated section "BlueBubbles → Cortex Live Webhook Verification Prompt Added (2026-04-24 UTC, Claude Code)" naming the new prompt/runbook and attesting no runtime/external action was performed. |

## Bounded path/existence checks

All checks below are read-only `ls -l` / `test -f` / `grep -n` — no
mutation, no secret read.

- `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md` — exists, 21504 bytes.
- `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` — exists, 7402 bytes.
- Prompt autonomy metadata block present (`<!-- autonomy: start --> ... <!-- autonomy: end -->`) with `Category: messaging`, `Risk tier: high`, `Trigger: manual`, `Status: active`.
- Prompt references source-of-truth webhook URL: `http://127.0.0.1:8102/hooks/bluebubbles` (matches `cortex/bluebubbles.py:680` and `docs/bluebubbles/MANUAL_WEBHOOK_TEST.md:9`).
- Prompt references companion runbook: `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md`.
- Runbook does **not** carry `<!-- autonomy: start -->` metadata — correct per `AUTONOMOUS_PROMPT_STANDARD.md` (runbooks are human-approved and dispatcher must skip).
- Runbook references the prompt by full path.
- Both files decline to print phone numbers, secrets, or message bodies; redaction rules are spelled out in both.

## No-runtime-action attestation

This pass did **not**:

- invoke `curl` against Cortex, BlueBubbles, Redis, or any endpoint;
- invoke `docker exec`, `docker logs`, `docker restart`, or any
  container lifecycle command;
- invoke `launchctl`, `sudo`, `pkill`, `kill`, or any process mutation;
- read, print, or echo values from `.env*`, `config/bluebubbles_routing.json`,
  or any secret store;
- open, forward, or change any port;
- send any iMessage, SMS, email, webhook, or Slack message;
- mutate BlueBubbles Settings UI or any BlueBubbles config file;
- mutate harness-owned files (`.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`);
- commit or push destructive operations on unrelated files.

Pre-existing dirty working tree (the `M` entries in
`git status --short` for `.claude/**`, `.mcp.json`, `CLAUDE.md`) is
preserved verbatim — this pass added only new files plus a single
prepended entry to `STATUS_REPORT.md`.

## Instructions for Matt (execution on Bob)

When ready, on Bob, with an external participant available:

1. Pull: `bash scripts/pull.sh` (or `git pull --ff-only` in the repo root).
2. Open the autonomous prompt in Cline:
   `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`.
3. Follow the runbook's pre-flight checklist:
   `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` §Pre-flight.
4. At Step 2, paste a redacted description of the BlueBubbles Settings
   Webhook URL field.
5. At Step 5, coordinate (out-of-band) a human on a distinct phone
   number to send an iMessage to your BlueBubbles handle containing
   only the nonce printed in Step 0.
6. Let the prompt complete Steps 6–10. The verdict + evidence file
   land under `ops/verification/<stamp>-bluebubbles-cortex-live-webhook.md`.
7. Commit and push happen at Step 10 per the prompt's verification
   contract.

If the BlueBubbles Webhook URL field is empty, wrong, or disabled, the
prompt will **stop** and emit `[FOLLOWUP: bluebubbles-webhook-url-mismatch]`.
A separate follow-up prompt gated on `APPROVE: bluebubbles-webhook-url`
is required to change the field; this run does not mutate it.

## Verdict for this repo pass

`PASS-repo-pass-complete` — prompt + runbook + STATUS_REPORT + receipt
written; no runtime/external action taken. Execution on Bob is queued
for Matt.
