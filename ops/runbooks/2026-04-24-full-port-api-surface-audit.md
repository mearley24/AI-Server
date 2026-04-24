# Runbook — Full Bob Port & API Surface Audit

Status: DONE (snapshot delivered 2026-04-24 18:23 UTC, commit `0f8c97e2`)
Created: 2026-04-24 (UTC), Claude Code (parent-agent docs-only pass)
Closed: 2026-04-24 (UTC) — Claude Code parent-agent docs-only pass
Paired prompt: `.cursor/prompts/2026-04-24-cline-full-port-api-surface-audit.md` (Status: done)
Parent receipt: `ops/verification/20260424-port-api-surface-audit-prompt-armed.txt`
Delivery receipt: `ops/verification/20260424-182340-port-api-surface-audit/`
Follow-ups armed (separate runbooks):
- `ops/runbooks/2026-04-24-x-intake-lab-compose-removal.md`
- `ops/runbooks/2026-04-24-ports-md-registry-refresh.md`
- `ops/runbooks/2026-04-24-port-8102-unknown-listener-evidence.md`

## Why this runbook exists

Matt asked whether a full port audit had been done recently, and whether the
BlueBubbles API connection should be turned off now. The answer to the first
is: the closest existing snapshot is the full-system sweep from
`ops/verification/20260421-143522-full-system-sweep-and-audit.txt` (three
days stale, and it did not enumerate every host listener or classify each
port). The answer to the second is: **do not disable BlueBubbles before
this audit ships**, because (a) the inbound webhook leg was confirmed live
on 2026-04-24 (receipt `20260424-161534-bluebubbles-cortex-live-webhook.md`,
verdict `PASS-webhook-only`), and (b) the x-intake reply-leg live smoke is
still `PRECHECKS_PASSED` and depends on BlueBubbles outbound.

## Scope

Read-only inventory of:
- Host listening sockets (loopback vs LAN vs Tailscale)
- Docker container port maps vs `PORTS.md` registry
- launchd plist → port ownership
- BlueBubbles inbound webhook and outbound REST surface
- Classification: REQUIRED / OPTIONAL / STALE / UNKNOWN
- Recommendation per row (advisory only — no action taken)

## Out of scope (do not do in this runbook)

- Stopping, restarting, or unloading any service
- Editing `.env`, secrets, firewall, or launchd state
- Disabling BlueBubbles or any API client
- Public-exposure probes from the internet side
- Any `sudo` action that is not already passwordless

## Operator steps (copy-paste from the prompt)

1. `git pull --ff-only` in `~/Documents/AI-Server`
2. Open `.cursor/prompts/2026-04-24-cline-full-port-api-surface-audit.md`
   and paste the full prompt into Cline (ACT MODE).
3. Cline emits four sub-files under
   `ops/verification/${STAMP}-port-api-surface-audit/`:
   - `host-listeners.txt`
   - `docker-ports.txt`
   - `launchd-ports.txt`
   - `bluebubbles-surface.txt`
   and a summary `classification.md` + `README.md`.
4. STATUS_REPORT appended; commit pushed to `main`.

## Exit criteria

- All bounded checks in the prompt's §Bounded-check checklist completed
  or explicitly marked `N/A: needs-matt`.
- Receipt dir exists with the five files above.
- STATUS_REPORT has the dated "Port & API surface audit" section.
- Commit hash captured in the receipt.

## Follow-up (if audit surfaces items to disable)

Any recommendation to disable or close a port requires a separate,
explicitly-approved prompt that includes:
- Rollback plan (exact load/start command)
- Verification plan that the kill did not regress a live feature
- For BlueBubbles specifically: verification that the AppleScript
  bridge (`scripts/imessage-server.py`, `:8199`) remains healthy as a
  fallback outbound path, and that no `[NEEDS_MATT]` / `[FOLLOWUP]`
  item depends on the webhook.
