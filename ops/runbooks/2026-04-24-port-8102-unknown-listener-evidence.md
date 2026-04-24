# Runbook — :8102 UNKNOWN second listener evidence capture

Status: ARMED (awaiting Bob operator)
Created: 2026-04-24 (UTC), Claude Code
Paired prompt: `.cursor/prompts/2026-04-24-cline-port-8102-unknown-listener-evidence.md`
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`

## Why this runbook exists

The 2026-04-24 audit flagged a second listener on :8102 bound LAN-wide,
owned by PID 962 (launchd mapping: `com.symphony.file-watcher`). Cortex's
legitimate :8102 is loopback-only. The audit marked this `[NEEDS_MATT]`
pending evidence. This runbook covers the read-only evidence capture pass
that unblocks that decision.

## Scope (read-only)

See paired prompt §Scope. Six required captures + one optional (sudo-gated)
capture.

## Out of scope

- Any mitigation (kill, unload, rebind, firewall).
- Cortex restart.
- Any sudo prompt or credential elevation beyond a non-interactive probe.

## Operator steps

1. `cd ~/Documents/AI-Server && git pull --ff-only`
2. Paste prompt into Cline (ACT MODE).
3. Cline captures the 6 read-only artifacts + sudo-gated 7th if allowed.
4. Cline writes receipt + STATUS_REPORT follow-up line, commits
   `ops(port-audit): :8102 unknown-listener evidence`, pushes.

## Exit criteria

- Receipt dir `ops/verification/${STAMP}-port-8102-evidence/` exists with
  `lsof-8102.txt`, `lsof-pid-962.txt`, `ps-pid-962.txt`, `launchctl-print.txt`,
  `plist.xml` (or "not-found" note), `grep-source.txt`, `sudo-probe.txt`,
  and `README.md` with verdict line.
- STATUS_REPORT has a new FOLLOWUP line quoting the verdict.
- Commit pushed to `main`.

## Rollback

- `git revert <hash>` — the pass is docs-only; no runtime state to unwind.

## Follow-up branches

Decided after evidence lands (NOT part of this runbook):
- `PID_COLLISION` → close, no action.
- `INTENTIONAL_SECONDARY` + LAN exposure unintended → author a rebind
  prompt with rollback.
- `UNINTENTIONAL_SECONDARY` → NEEDS_MATT ticket before any mitigation.
