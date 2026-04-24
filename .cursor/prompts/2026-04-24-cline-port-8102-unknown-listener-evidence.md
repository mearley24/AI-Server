# Cline Prompt — :8102 UNKNOWN second listener evidence capture (read-only)

Status: active
Owner: Cline (ACT MODE on Bob) — read-only evidence capture
Created: 2026-04-24 (UTC)
Parent evidence: `ops/verification/20260424-182340-port-api-surface-audit/classification.md`
Paired runbook: `ops/runbooks/2026-04-24-port-8102-unknown-listener-evidence.md`

## Why this prompt exists

The 2026-04-24 port/API surface audit flagged one port as UNKNOWN and
`[NEEDS_MATT]`: a **second listener on :8102** bound to ALL interfaces
(`*:8102`) owned by PID 962, which launchd maps to
`com.symphony.file-watcher`.

Bob's Cortex container is the legitimate :8102 listener and is bound to
`127.0.0.1`. The file-watcher binding LAN-wide on the same port is
unexpected. Two possibilities:

1. PID collision — the launchd PID we read was reused by another process
   that happens to bind 8102.
2. An actual second listener inside the file-watcher agent (config drift,
   leftover test code, or a port typo).

Either way we need evidence before deciding whether to disable, rebind,
or accept. **No runtime actions in this prompt.** This is purely evidence
capture to unblock the `[NEEDS_MATT]` decision.

## Scope (read-only)

Gather the following into
`ops/verification/${STAMP}-port-8102-evidence/`:

1. `lsof -nP -iTCP:8102 -sTCP:LISTEN` — all listeners on 8102.
2. `lsof -p 962 -nP -iTCP` — every TCP endpoint held by PID 962.
3. `ps -o pid,ppid,user,%cpu,%mem,etime,command -p 962` — process identity
   (full argv).
4. `launchctl print gui/$(id -u)/com.symphony.file-watcher | head -120` or
   `launchctl print system/com.symphony.file-watcher | head -120`
   (whichever domain the agent is loaded in) — program, program
   arguments, stdout/stderr paths.
5. If the plist is under `~/Library/LaunchAgents/com.symphony.file-watcher.plist`
   or `/Library/LaunchAgents/...` or `/Library/LaunchDaemons/...`, print
   the plist with `plutil -convert xml1 -o - <path>`.
6. `grep -RIn --max-count=3 "8102" <program-working-directory-from-plist>`
   — look for the port number in the file-watcher source tree to confirm
   whether the binding is intentional.
7. `sudo -n true 2>/dev/null && echo SUDO_OK || echo SUDO_UNAVAILABLE` —
   one-line sudo probe only; if unavailable, mark the steps below as
   `N/A: sudo-required` rather than prompting.
8. (If SUDO_OK only) `sudo lsof -nP -iTCP:8102 -sTCP:LISTEN` — catches
   listeners the user shell can't see.

Capture each into a named file under the receipt dir. If any step errors,
include the error verbatim — do not retry with elevated privileges that
were not granted.

## Hard "do-not" list

- No `kill`, `launchctl unload/bootout/stop/disable`, `pkill`.
- No firewall / pfctl / socketfilterfw edits.
- No restart of file-watcher, Cortex, or Docker.
- No env, secret, or compose edits.
- No change to PID 962's working directory or its config files.
- No SUDO prompts. If SUDO_OK is false, skip step 8 and proceed.

## Deliverables

`ops/verification/${STAMP}-port-8102-evidence/README.md` must summarize:

- Whether PID 962 actually holds `:8102` as a listener (confirm with
  `lsof -p 962 -iTCP`).
- The binary path + argv for PID 962.
- Whether "8102" appears in the file-watcher source tree or plist.
- A classification verdict: one of
  - `PID_COLLISION` — PID was reused; 962 does not bind 8102.
  - `INTENTIONAL_SECONDARY` — file-watcher genuinely binds 8102 LAN-wide.
    (If so, list why — grep hits, comment, plist env var.)
  - `UNINTENTIONAL_SECONDARY` — binding is real but unexplained. Needs
    Matt decision on disable vs rebind.

## Follow-ups the operator may approve *after* evidence is in

(Not part of this prompt. Listed so the operator sees the branch.)

- If `PID_COLLISION` → close as documentation-only; update audit.
- If `INTENTIONAL_SECONDARY` + LAN exposure unintended → separate prompt
  to rebind file-watcher to loopback with rollback + verification.
- If `UNINTENTIONAL_SECONDARY` → NEEDS_MATT ticket before any action.

## STATUS_REPORT update (mandatory)

Append to the Port & API Surface Audit section:

```
- [FOLLOWUP] :8102 UNKNOWN second listener evidence captured
  Receipt: ops/verification/${STAMP}-port-8102-evidence/
  Verdict: <PID_COLLISION | INTENTIONAL_SECONDARY | UNINTENTIONAL_SECONDARY>
```
