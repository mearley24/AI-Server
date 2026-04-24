# Reconciliation Receipt — Port & API Surface Audit closure + follow-ups armed

UTC: 2026-04-24
Runner: Claude Code (parent-agent docs-only pass)
Host: parent agent environment (no Bob runtime actions)

## Summary

The full Bob port/API surface audit armed in commit `ae4fc5c0` landed as
commit `0f8c97e2` on 2026-04-24 12:26 MDT (18:23 UTC). Receipt directory
`ops/verification/20260424-182340-port-api-surface-audit/` contains the
classification table (29 TCP listeners: 15 REQUIRED, 9 OPTIONAL, 1 UNKNOWN,
0 STALE), BlueBubbles surface, host listeners, docker port map, and
launchd port inventory. This pass reconciles the armed prompt/runbook
against that delivered evidence and arms three targeted follow-up
prompts+runbooks for the concrete gaps surfaced.

## Closures (prompts + runbooks moved from active/ARMED → done/DONE)

- `.cursor/prompts/2026-04-24-cline-full-port-api-surface-audit.md`
  → Status: **done** (closure block added, links receipt commit + dir).
- `ops/runbooks/2026-04-24-full-port-api-surface-audit.md`
  → Status: **DONE** (header updated with delivery receipt path).

## Follow-ups armed this pass

All three are docs-only on the parent side; none execute any Bob runtime
action. Each has precheck, approval gate, rollback, verification receipt
requirements, and STATUS_REPORT closure instructions.

### 1. x-intake-lab compose removal (concrete safe cleanup)

Audit finding #4: service defined in docker-compose.yml but not running;
STATUS_REPORT L133 already marks it decommissioned.

- Prompt: `.cursor/prompts/2026-04-24-cline-x-intake-lab-compose-removal.md`
- Runbook: `ops/runbooks/2026-04-24-x-intake-lab-compose-removal.md`
- Risk: **low**. Container is already stopped. No service is affected.
- Explicitly out of scope: `docker rm`, `docker volume rm` (separate
  approvals).

### 2. PORTS.md registry refresh (docs-only safe cleanup)

Audit finding #2 + #5: 6 active services missing, "loopback-only" footnote
inaccurate (4+ services bind LAN-wide).

- Prompt: `.cursor/prompts/2026-04-24-cline-ports-md-registry-refresh.md`
- Runbook: `ops/runbooks/2026-04-24-ports-md-registry-refresh.md`
- Risk: **none**. Pure docs change. Nothing runtime depends on PORTS.md.

### 3. :8102 UNKNOWN second listener evidence (evidence-gap, not cleanup)

Audit finding #1 [NEEDS_MATT]: second listener on :8102 bound LAN-wide
owned by PID 962 (launchd mapping `com.symphony.file-watcher`). Classification
cannot be decided without more evidence.

- Prompt: `.cursor/prompts/2026-04-24-cline-port-8102-unknown-listener-evidence.md`
- Runbook: `ops/runbooks/2026-04-24-port-8102-unknown-listener-evidence.md`
- Risk: **read-only**. No kill / unload / rebind / sudo prompts. Emits a
  verdict line (PID_COLLISION | INTENTIONAL_SECONDARY | UNINTENTIONAL_SECONDARY)
  for downstream decision.

## BlueBubbles disable decision (confirmed)

**KEEP ENABLED.** The audit classification table + BlueBubbles surface JSON
confirm the analysis armed in the parent prompt (commit `ae4fc5c0`):

- **Inbound webhook**: live. The counters show zero because the Cortex
  container was restarted at 18:23 UTC (quiet window). The last confirmed
  live event is `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md`
  (verdict `PASS-webhook-only`, 2026-04-24 16:17 UTC).
- **Outbound BlueBubbles send path**: ping healthy (`server_version: 1.9.9`,
  `private_api: true`, 369ms to `bobs-mac-mini.tailbcf3fe.ts.net`). The
  block is not in BlueBubbles: it is the macOS 26 AppleScript path that
  hangs, with the private-api helper not yet connecting.
- **Host AppleScript bridge fallback**: `com.symphony.imessage-bridge`
  (PID 2322, port 8199) is running. Last exit `-15` (SIGTERM) is a prior
  restart, not a crash — it is the live outbound fallback while the
  BlueBubbles AppleScript path remains broken on macOS 26.
- **Dependencies**: disabling the BlueBubbles API would regress the Cortex
  iMessage ingest path and kill the x-intake reply-leg fan-in (currently
  `PRECHECKS_PASSED`).

Any future proposal to disable BlueBubbles must be a separate prompt that
ships with: rollback plan, verification that :8199 fallback is healthy,
confirmation `BLUEBUBBLES_SERVER_URL` is Tailscale-only, and evidence that
no `[NEEDS_MATT]` or `[FOLLOWUP]` item depends on the webhook.

## Docker Desktop / memory implications from audit

The classification table reflects the memory/VPN fixes already landed this
session (commit `4efdbc3b`): rsshub and dtools-bridge at 512m, polymarket-bot
re-attached to the VPN namespace, WireGuard handshake OK. The audit did not
surface additional Docker memory work; no new prompt needed on that axis.

## Hard "did-not-do" list for this pass

- No Bob runtime actions (no `docker`, `launchctl`, `sudo`, firewall).
- No env mutation, no secrets access, no external sends, no money/trading.
- No service disabled or restarted.
- No destructive changes.
- Unrelated dirty-work files (`.claude/*`, `.mcp.json`, `CLAUDE.md`)
  preserved — not staged, not modified.

## Next command(s) for operator (in priority order)

1. `cd ~/Documents/AI-Server && git pull --ff-only` — pull this
   reconciliation commit onto Bob.
2. Paste `.cursor/prompts/2026-04-24-cline-x-intake-lab-compose-removal.md`
   into Cline (ACT MODE). Quickest, lowest-risk cleanup.
3. Paste `.cursor/prompts/2026-04-24-cline-ports-md-registry-refresh.md`
   after #2 lands. Docs-only.
4. Paste `.cursor/prompts/2026-04-24-cline-port-8102-unknown-listener-evidence.md`
   when ready to resolve the `[NEEDS_MATT]` on the unknown secondary :8102
   binding. Read-only evidence capture; verdict unblocks further action.
