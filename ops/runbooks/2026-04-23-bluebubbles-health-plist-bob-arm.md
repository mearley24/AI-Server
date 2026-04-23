# BlueBubbles Health Plist — Bob Runtime Arm Runbook

**Status:** `[NEEDS_MATT]` + `[BOB_CLINE_ONLY]` — **NOT auto-run by
Computer / Cline / Claude Code / task-runner / self-improvement
loop.** This file is a human-approved runbook, not an autonomous
prompt. Do **not** add `<!-- autonomy: start -->` metadata. Do not
copy into `.cursor/prompts/`. Dispatchers under `ops/cline-run-*.sh`
must **skip** anything in `ops/runbooks/`.

**Owner:** Matt (or a human operator with local shell access to Bob).
**Host:** Bob (Mac Mini M4), `~/AI-Server` checkout of `origin/main`.
**Prerequisite prompt:** `.cursor/prompts/2026-04-23-cline-bluebubbles-health-plist.md`
(Status: `done`, Phase-1 add+lint closed).
**Scope anchor:** STATUS_REPORT entry "BlueBubbles Health Plist —
Phase 1 Add+Lint" + Audit §1/§2 BlueBubbles bullets.

---

## Why this runbook exists

Repo-side work — plist file + `plutil -lint` pass + per-plist unit
test — landed at commit `4b7485f`. What remains is a one-time
operator action on Bob to copy the plist into
`~/Library/LaunchAgents/`, load it via user-scoped `launchctl`, and
confirm the probe runs on its 5-minute cadence. No `sudo`, no port,
no external surface.

---

## Prechecks (required, run before arming)

Capture into
`ops/verification/<YYYYMMDD-HHMMSS>-bluebubbles-health-arm-precheck.txt`
before proceeding.

1. Checkout clean, on `origin/main`:
   ```
   cd ~/AI-Server
   git status --short
   git rev-parse --abbrev-ref HEAD
   git rev-parse HEAD
   git log --oneline -1
   ```
   Expect: branch `main`, HEAD contains commit `4b7485f` (plist add).

2. Repo plist exists and lints:
   ```
   test -f setup/launchd/com.symphony.bluebubbles-health.plist && echo ok-plist
   plutil -lint setup/launchd/com.symphony.bluebubbles-health.plist
   grep -H "com.symphony.bluebubbles-health" setup/launchd/com.symphony.bluebubbles-health.plist
   grep -H "StartInterval" setup/launchd/com.symphony.bluebubbles-health.plist
   ```
   Expect: `OK`; Label line present; `StartInterval=300`.

3. Script exists and is parseable:
   ```
   test -f scripts/bluebubbles-health.sh && echo ok-script
   bash -n scripts/bluebubbles-health.sh
   ```

4. **Disabled vs. loaded state** — confirm the job is not already
   present. Both of these must return empty output; if either
   returns a match, stop — the job is already loaded and this
   runbook would double-load it:
   ```
   launchctl list | grep com.symphony.bluebubbles-health || echo not-loaded
   launchctl print gui/$(id -u)/com.symphony.bluebubbles-health 2>&1 | head -n 3
   ls -la ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist 2>&1 || echo not-installed
   ```
   Expect: `not-loaded`, `Could not find service` (or similar), and
   `not-installed`. **Stop** if already loaded — open a FOLLOWUP to
   reconcile instead.

5. One-shot `--json` probe works manually (proves Cortex + BlueBubbles
   endpoints are reachable from Bob's shell, independent of launchd):
   ```
   timeout 10 bash scripts/bluebubbles-health.sh --json | head -c 1200
   ```
   Expect: JSON with `status` and per-endpoint fields. Non-zero exit
   or HTTP 5xx from Cortex means the probe should not be armed until
   the `/api/bluebubbles/health` endpoint is live (currently tracked
   as a FOLLOWUP in STATUS_REPORT).

6. Log directory exists and is writable:
   ```
   mkdir -p ~/AI-Server/logs
   test -w ~/AI-Server/logs && echo ok-logs
   ```

**Stop conditions (abort, do not continue):**

- `plutil -lint` fails.
- The job is already loaded (precheck 4 returns a match).
- Cortex `/api/bluebubbles/health` returns 5xx (not 404 — a 404 is
  a known FOLLOWUP and does not block arming).
- `logs/` is not writable.
- Dirty tree in `setup/launchd/` or `scripts/bluebubbles-health.sh`.

---

## Ordered arm sequence (Matt or human operator)

All commands are user-scoped; **no `sudo`**. Capture each command's
stdout/stderr into the precheck verification file.

1. **Copy the plist into `~/Library/LaunchAgents/`** (a plain `cp`,
   no symlink — launchd resolves symlinks inconsistently on macOS):
   ```
   cp setup/launchd/com.symphony.bluebubbles-health.plist ~/Library/LaunchAgents/
   ls -la ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist
   plutil -lint ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist
   ```

2. **Load the LaunchAgent (user scope — `gui/$(id -u)`).**
   ```
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist
   launchctl enable gui/$(id -u)/com.symphony.bluebubbles-health
   ```
   If `bootstrap` reports "service already loaded", **stop** and
   re-check precheck 4. Do not fall back to `launchctl load`.

3. **Confirm the job is listed.**
   ```
   launchctl list | grep com.symphony.bluebubbles-health
   launchctl print gui/$(id -u)/com.symphony.bluebubbles-health | head -n 30
   ```
   Expect: one entry with PID `-` (between runs) or a numeric PID (if
   `RunAtLoad=true` is mid-execution); last-exit-status `0`.

4. **Kickstart a single run and capture its output** (bounded — the
   job already exits on its own, no `--watch`):
   ```
   launchctl kickstart -k gui/$(id -u)/com.symphony.bluebubbles-health
   sleep 3
   tail -n 40 ~/AI-Server/logs/bluebubbles-health.log
   tail -n 10 ~/AI-Server/logs/bluebubbles-health.err 2>/dev/null || echo "no err output"
   ```
   Expect: fresh JSON in the log, no traceback in `.err`.

5. **Sanity-check the 5-minute cadence is in effect** (read-only):
   ```
   launchctl print gui/$(id -u)/com.symphony.bluebubbles-health | grep -E 'start interval|last exit code|path'
   ```
   Expect: `start interval = 300`, `last exit code = 0`, log paths
   point at `~/AI-Server/logs/bluebubbles-health.{log,err}`.

---

## Verification receipt requirements

After the arm sequence completes (or aborts), write a single
receipt to:

```
ops/verification/<YYYYMMDD-HHMMSS>-bluebubbles-health-arm.txt
```

The receipt **must** include, verbatim:

- `git rev-parse HEAD` on Bob at run time.
- Precheck outputs (lint + one-shot probe + not-loaded confirmation).
- `cp` + `bootstrap` + `enable` output.
- `launchctl list | grep bluebubbles-health` line.
- `launchctl print` excerpt showing `start interval=300` and
  `last exit code=0`.
- First 2 KB of `~/AI-Server/logs/bluebubbles-health.log`.
- Any content of `~/AI-Server/logs/bluebubbles-health.err` (often
  empty — record that explicitly).

Then add a dated STATUS_REPORT entry named
`## BlueBubbles Health — LaunchAgent Armed on Bob (<YYYY-MM-DD> <HH:MM TZ>, Matt)`
that:

- Records the above.
- **Strikes through** the prior `[NEEDS_MATT] Arm the LaunchAgent`
  bullet with `~~...~~ ✅` so the summarizer moves it out of "Needs
  Matt" and into history.

Commit with:

```
docs(launchd): bluebubbles-health armed on Bob — verification + STATUS_REPORT
```

Do **not** `git push --force` and do **not** amend prior commits.

---

## Rollback / stop conditions

| Condition | Immediate action |
|-----------|------------------|
| `launchctl bootstrap` fails with "service already loaded" | Abort. Open FOLLOWUP; this runbook assumes the arm is a first-time action. |
| `.err` file fills with tracebacks | Disarm (see below). Investigate `scripts/bluebubbles-health.sh` offline. |
| Cortex `/api/bluebubbles/health` flipping to 5xx (not 404) after arm | Disarm. The probe is noise if Cortex is broken. |
| Probe hanging beyond `StartInterval` (5 min) with no new log | Disarm. Script may be blocking on a network read — re-examine its timeouts. |

**Disarm (user scope, no sudo):**

```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist
rm ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist
launchctl list | grep com.symphony.bluebubbles-health || echo disarmed
```

The repo-side plist under `setup/launchd/` is the source of truth;
removing the `~/Library/LaunchAgents/` copy leaves it intact for a
future re-arm.

---

## What this runbook explicitly forbids

- **Any use of `sudo`.** This is a LaunchAgent (user scope), not a
  LaunchDaemon. If `sudo` feels required, **stop** — the plist is
  mis-specified.
- Opening a new port; exposing the probe publicly; editing the
  BlueBubbles server config.
- `launchctl load` without `bootstrap` (the legacy command is
  quietly broken on current macOS user scope).
- Editing `scripts/bluebubbles-health.sh` during this runbook. Any
  script change is a separate repo-side PR.
- Running from a non-interactive dispatcher. If a scheduled job
  attempts these steps, **it is a bug**.
- Copying this runbook into `.cursor/prompts/` or adding autonomy
  metadata.

---

## Appendix: why split from the Phase-1 prompt

The Phase-1 Cline prompt (`2026-04-23-cline-bluebubbles-health-plist.md`)
is runnable from any clean checkout and deliberately does not touch
`~/Library/LaunchAgents/` or invoke `launchctl`. That split is the
same pattern the network-monitoring work used successfully (Phase-1
add+lint → Phase-2 arm). Keeping the live `launchctl bootstrap` in a
separate, non-autonomous runbook prevents accidental arming from any
scheduled/autonomous path.
