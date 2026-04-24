# BlueBubbles → Cortex Live Webhook — Evidence Gap Reconciliation

UTC stamp: 20260424-153124
Runner: Claude Code (parent-agent repo reconciliation pass, autonomous subagent)
Host: sandbox (not Bob)
Scope: repository-only; no runtime/external action; no secret read; no config mutation.

## Why this file exists

Matt reports he has entered/saved the BlueBubbles webhook URL in the
BlueBubbles Settings UI and sent a message. This pass looked for
evidence that the live message reached Cortex at
`/hooks/bluebubbles` and found **no such evidence committed to the
repo**. Per the parent-agent workflow, the live webhook gate **must
not** be closed on verbal report alone — a committed evidence
artifact with a verdict class is required.

## What was searched (read-only)

- `git status --short` — only pre-existing harness-owned `M` entries
  (`.claude/**`, `.mcp.json`, `CLAUDE.md`); local branch in sync with
  `origin/main` (no ahead/behind).
- `git log 40213345..HEAD` — only `c1e52d33` (task-runner preflight
  heartbeat). No new BlueBubbles/webhook/cortex-live commits.
- `STATUS_REPORT.md` top — still shows the
  *"BlueBubbles → Cortex Live Webhook Verification Prompt Added"*
  section written at 40213345. No PASS/FAIL closure entry has been
  prepended.
- `ops/verification/` — newest file matching
  `*bluebubbles*webhook*` is
  `20260424-151726-bluebubbles-cortex-live-webhook-prompt-creation.md`
  (the *pre-run* receipt committed by 40213345). No artifact matching
  the prompt's contract output name
  `<stamp>-bluebubbles-cortex-live-webhook.md` exists.
- `ops/verification/` — no `*cortex-live-webhook*` evidence file, no
  `*inbound-count*` delta capture, no Redis `events:bluebubbles`
  snapshot, no Cortex dedup-store delta for the putative inbound
  event.
- `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`
  — still present, unchanged since 40213345; its Step 10 commit/push
  contract has not been triggered.
- `ops/runbooks/2026-04-24-bluebubbles-cortex-live-webhook.md` —
  still present, unchanged since 40213345.

## Interpretation

The verification prompt was written into the repo at 40213345 but
there is no committed proof that a Cline/Bob execution of it has
taken place. Specifically, **none** of the required evidence fields
are present in the repo:

- No redacted sender receipt (distinct-phone attestation).
- No nonce/timestamp witnessed on both sender side and Cortex side.
- No Cortex `/api/bluebubbles/health` `inbound_count` /
  `last_inbound_event_at` delta capture.
- No Redis `events:bluebubbles` (or `events:imessage`) LRANGE
  snapshot.
- No Cortex log excerpt (`docker logs cortex`) showing a
  `POST /hooks/bluebubbles` 2xx response for the relevant stamp.
- No dedup-store row proof.
- No BlueBubbles UI Webhook URL field status capture (Step 2 of the
  prompt is `[NEEDS_MATT]` and would be redacted into the verdict
  file).
- No pass/fail classification emitted
  (`PASS-webhook-and-policy` / `PASS-webhook-only` / `FAIL-no-webhook`
  / `BLOCKED-*`).

Possible causes (all indistinguishable from this pass without
executing on Bob, which is out of scope):

1. The verification prompt has not yet been run on Bob by Cline.
2. The prompt was executed but did not reach Step 10 (commit/push),
   so the artifact lives only on Bob's local filesystem.
3. The URL entry was saved but the send was self-to-self (same
   handle) — per Matt's own 40213345 note and Apple iMessage routing
   behavior, that path does **not** trigger the webhook and so would
   not produce a PASS even if evidence were captured.
4. The URL in the BlueBubbles Settings UI differs from the
   source-of-truth `http://127.0.0.1:8102/hooks/bluebubbles`
   (or points at a container-only host that is unreachable from the
   BlueBubbles LaunchAgent running host-side).

## Classification

**UNKNOWN** — the repo holds no committed evidence supporting PASS,
and no committed evidence supporting FAIL. This pass therefore does
**not** close the live webhook gate. The 40213345 follow-up remains
open.

## No-runtime-action attestation

This reconciliation pass did **not**:

- invoke `curl` against Cortex, BlueBubbles, Redis, or any endpoint;
- invoke `docker`, `launchctl`, `sudo`, or any process mutation;
- read, echo, or evaluate `.env*`, `config/bluebubbles_routing.json`,
  or any secret store;
- open/forward/change any port;
- send any iMessage / SMS / email / webhook / Slack message;
- modify any BlueBubbles or Cortex configuration;
- restart or recycle any service;
- mutate harness-owned files (`.claude/**`, `.mcp.json`, `CLAUDE.md`);
  pre-existing `M` entries in `git status` preserved verbatim.

Only this receipt file is added; no other files are modified.

## Exact next action

On Bob, with an external participant available (a human on a
**different** phone number than Matt's BlueBubbles handle):

1. `bash scripts/pull.sh` (or `git pull --ff-only`).
2. Open in Cline:
   `.cursor/prompts/2026-04-24-cline-bluebubbles-cortex-live-webhook-verify.md`.
3. Complete its Steps 0–10. Step 10 will commit and push the
   `ops/verification/<stamp>-bluebubbles-cortex-live-webhook.md`
   evidence file containing the verdict class + redacted evidence
   bundle.
4. After Step 10, a subsequent parent-agent pass can confirm PASS
   and close the live webhook gate in STATUS_REPORT.

If the send already occurred but was **self-to-self** (same handle),
no webhook fires by Apple-side routing — the artifact should
classify as `BLOCKED-no-external-sender` and a fresh send from a
distinct handle is required. The prompt handles this taxonomy.

If the send occurred from a distinct number but no Cortex inbound
event landed, the artifact should classify `FAIL-no-webhook` and the
follow-up is to inspect the BlueBubbles Settings UI Webhook URL
field (gated behind a separate `APPROVE: bluebubbles-webhook-url`
prompt — not this one).

## Verdict for this reconciliation pass

`PASS-reconciliation-only` — evidence gap documented; live webhook
gate remains **open**; no false closure performed.
