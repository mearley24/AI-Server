<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger:   manual
Status:    done
<!-- autonomy: end -->

<!-- closure: start -->
Closed: 2026-04-24 by Claude Code (parent-agent loose-ends reconciliation).
Phase-1 commit: `4b7485f` (plist add+lint) — "Completed + verified" in
STATUS_REPORT.md L535 (Five-Prompt Reconciliation table).
LaunchAgent armed on Bob 2026-04-23 10:15 MDT; receipt
`ops/verification/20260424-083518-bluebubbles-health-arm.txt`
(`run interval = 300`, `.err` empty, 269 log lines, BlueBubbles 1.9.9 healthy).
Runtime arm runbook: `ops/runbooks/2026-04-23-bluebubbles-health-plist-bob-arm.md`
(`Status: DONE`).
Reconciliation audit: `docs/audits/2026-04-24-loose-ends-reconciliation.md`.
<!-- closure: end -->

# BlueBubbles Health Plist — Repo-Owned LaunchAgent (Cline-first, Phase-1 Add + Lint Only)

## Owner / runtime context

- Repo-side authoring + linting is runnable from any clean checkout
  of `origin/main`.
- Anything that loads the plist into `launchctl` is **[NEEDS_MATT]**
  and **[BOB_CLINE_ONLY]** — this prompt **does not** load, arm, or
  kickstart any job. That mirrors how the network-monitoring
  Phase-1 prompt (now closed) separated "add + lint" from "arm".
- Scope anchor: `docs/audits/2026-04-23-unfinished-setup-audit.md`
  §1 "BlueBubbles attachment bodies + outbound-reply consolidation
  + `bluebubbles-health.sh` plist". This prompt closes the
  `bluebubbles-health.sh` plist half only.

## Goal

Add a committed launchd plist for the existing
`scripts/bluebubbles-health.sh` probe so Bob can supervise BlueBubbles
reachability (Cortex `/api/bluebubbles/health` + the BlueBubbles
server `/api/v1/server/info`) on a bounded cadence, and produce a
committed verification artifact proving the plist passes
`plutil -lint`, the script passes `bash -n`, and a one-shot `--json`
invocation succeeds on Bob.

## Non-goals

- **Not** arming the LaunchAgent. No `launchctl load/bootstrap/
  kickstart/enable`. That is a separate `[NEEDS_MATT]` step.
- **Not** running the script in a long-lived foreground watch. One
  bounded `--json` call only.
- **Not** the attachment-bodies / outbound-reply work — see
  `.cursor/prompts/2026-04-23-cline-bluebubbles-attachment-bodies.md`.
- **Not** editing `scripts/bluebubbles-health.sh` beyond additive,
  backwards-compatible changes (e.g. a new `--once` flag if the
  current default is already a one-shot, leave it alone).
- **Not** opening a new port. The script only does outbound HTTP
  reads to `127.0.0.1:8102` (Cortex) and the LAN-only BlueBubbles
  server URL already in `.env`.

## Safety gates

- **No secrets**: never `cat .env`. The script already loads
  `BLUEBUBBLES_SERVER_URL` and `BLUEBUBBLES_API_PASSWORD` via its
  own bounded loader — don't print them from the prompt.
- **No destructive data changes**. Plist only; no DB writes.
- **No external sends / posts / messages.** The probe is
  read-only — `curl -sS -m 8` against internal endpoints.
- **No recurring/scheduled jobs loaded in this run.** The plist is
  committed but **not** `launchctl load`-ed. Arming is a separate
  `[NEEDS_MATT]` handoff.
- **Bob runtime actions are [BOB_CLINE_ONLY]**. If this prompt is
  being run on Matt's MacBook, skip the live probe steps and record
  that fact in the verification artifact.
- **No sudo. No interactive editors. No heredocs. No `tail -f` /
  `--watch`.**

## Preconditions

Read in this order:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (§1 only)
- `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`
  — **model this prompt's structure on that one**; network-monitoring
  is already closed and its shape is known-good.
- `scripts/bluebubbles-health.sh` (full — it is short)
- `setup/launchd/com.symphony.network-dropout-watch.plist`
  — model for a read-only, bounded LaunchAgent.
- `setup/launchd/com.symphony.network-guard.plist`
  — model for a paired health LaunchAgent.

Confirm git state:

```
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
git pull --ff-only
```

Stop if `git pull --ff-only` fails or if there are unexpected local
changes outside the BlueBubbles / launchd surface.

## Safe inspection steps (read-only, bounded)

```
bash -n scripts/bluebubbles-health.sh
sed -n '1,40p' scripts/bluebubbles-health.sh
ls -la setup/launchd/ | head -n 60
grep -E "com.symphony.(network-dropout-watch|network-guard)" -l setup/launchd/ | head -n 4
plutil -lint setup/launchd/com.symphony.network-dropout-watch.plist
plutil -lint setup/launchd/com.symphony.network-guard.plist
```

On Bob only (**[BOB_CLINE_ONLY]**):

```
curl -sS -m 8 http://127.0.0.1:8102/api/bluebubbles/health | head -c 400
timeout 8 bash scripts/bluebubbles-health.sh --json | head -c 800
```

## Implementation tasks (scoped to this one item)

1. **Add `setup/launchd/com.symphony.bluebubbles-health.plist`** —
   a LaunchAgent (not a LaunchDaemon — matches
   `com.symphony.network-dropout-watch.plist`) that:
   - Runs `/bin/bash /Users/bob/AI-Server/scripts/bluebubbles-health.sh
     --json`.
   - Uses `RunAtLoad=true`, `KeepAlive=false`,
     `StartInterval=300` (every 5 min — change only if Matt
     requests). `ThrottleInterval=60`.
   - `WorkingDirectory=/Users/bob/AI-Server`.
   - `StandardOutPath=/Users/bob/AI-Server/logs/bluebubbles-health.log`.
   - `StandardErrorPath=/Users/bob/AI-Server/logs/bluebubbles-health.err`.
   - `EnvironmentVariables` block setting
     `PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin`
     (matches the network-dropout-watch PATH fix committed at
     `4dbd996`).
   - Label: `com.symphony.bluebubbles-health`.
   - No `Sockets`, no `MachServices`, no `UserName`/`GroupName`
     override, no `LowPriorityIO`.

2. **No edits to `scripts/bluebubbles-health.sh`** unless it fails
   `bash -n` on a clean checkout — in which case fix only the parse
   error and stop. Behavior change is out of scope for this prompt.

3. **`.gitignore`** — confirm `logs/` is already ignored. Add
   `logs/bluebubbles-health.*` explicitly if the current rule doesn't
   cover it; do not commit log files.

4. **Do not `launchctl load`.** The plist lives in `setup/launchd/`
   only; Matt copies to `~/Library/LaunchAgents/` and loads manually
   (separate `[NEEDS_MATT]` step).

## Full verification / test checklist (bounded)

### V1 — Repo static checks

```
plutil -lint setup/launchd/com.symphony.bluebubbles-health.plist
bash -n scripts/bluebubbles-health.sh
git diff --stat
git diff setup/launchd/com.symphony.bluebubbles-health.plist
```

### V2 — Cross-plist sanity

```
grep -H "com.symphony.bluebubbles-health" setup/launchd/com.symphony.bluebubbles-health.plist
grep -H "/Users/bob/AI-Server/scripts/bluebubbles-health.sh" setup/launchd/com.symphony.bluebubbles-health.plist
grep -H "StartInterval" setup/launchd/com.symphony.bluebubbles-health.plist
grep -H "StandardOutPath\|StandardErrorPath" setup/launchd/com.symphony.bluebubbles-health.plist
```

### V3 — Path existence checks

```
test -f scripts/bluebubbles-health.sh && echo ok-script
test -f setup/launchd/com.symphony.bluebubbles-health.plist && echo ok-plist
test -d setup/launchd/ && echo ok-launchd-dir
grep -E "^logs/|^logs$" .gitignore && echo ok-logs-ignored
```

### V4 — Unit / static test (add if missing)

Add a small `ops/tests/test_launchd_plists.py` (or extend an existing
test) that iterates over every `setup/launchd/*.plist`, asserts
`plutil -lint` exit 0 on each, and asserts
`<key>Label</key>` + a matching `<string>` on the next line. Run:

```
python3 -m pytest ops/tests/test_launchd_plists.py -q
```

If `plutil` isn't available in the test environment (Linux CI), mark
the test `skipif` on non-Darwin and still exercise an XML-parse
check (`xml.etree.ElementTree.fromstring`) as a fallback.

### V5 — Live one-shot probe (**[BOB_CLINE_ONLY]**, bounded)

Skip on MacBook. On Bob only:

```
timeout 10 bash scripts/bluebubbles-health.sh --json | head -c 1200
curl -sS -m 8 http://127.0.0.1:8102/api/bluebubbles/health | head -c 400
```

Record exit codes + first 1 KB of JSON output in the verification
artifact. If the BlueBubbles server is unreachable, capture the
`status`/`reason` fields verbatim — those are the intended signal
from the probe, not a failure to fix here.

### V6 — Do NOT

```
# DO NOT RUN in this prompt:
#   launchctl load ...
#   launchctl bootstrap ...
#   launchctl kickstart ...
#   cp setup/launchd/*.plist ~/Library/LaunchAgents/
#   sudo ...
```

Those commands are documented as a `[NEEDS_MATT]` follow-up only.

## Required artifacts

1. **STATUS_REPORT.md** — append a dated entry under
   `BlueBubbles Health Plist — Phase 1 Add+Lint (<YYYY-MM-DD>)`:
   - Commit hash(es).
   - Files touched.
   - `plutil -lint` + `bash -n` results.
   - Explicit note: **plist not loaded**, deferred to `[NEEDS_MATT]`
     follow-up. Include the exact copy command Matt should run next:
     `cp setup/launchd/com.symphony.bluebubbles-health.plist
     ~/Library/LaunchAgents/ && launchctl load
     ~/Library/LaunchAgents/com.symphony.bluebubbles-health.plist`.
2. **Verification receipt** —
   `ops/verification/<YYYYMMDD>-<HHMMSS>-bluebubbles-health-plist.txt`
   containing raw V1–V5 output.
3. **Commit** — single commit preferred, subject:
   `feat(launchd): add bluebubbles-health plist (phase-1 add+lint)`.
4. **Push** — `git push origin main`.
5. **Summary** — final message lists changed files, commit hash, and
   the exact `[NEEDS_MATT]` arm command.

## Stop conditions / blockers

- `plutil -lint` fails on the new plist — fix the XML, do not ship.
- `bash -n scripts/bluebubbles-health.sh` fails — fix the parse error
  but nothing else in that script.
- The plist would require `sudo` or a LaunchDaemon posture — stop;
  this is a LaunchAgent by design.
- The live probe (V5 on Bob) returns HTTP 5xx from Cortex — record
  as `[FOLLOWUP]` in STATUS_REPORT, do not "fix" Cortex from here.
- Any attempt to fold in the attachment-bodies work — stop; that is
  a separate prompt.

## Closing checklist

- [ ] `setup/launchd/com.symphony.bluebubbles-health.plist` committed.
- [ ] `plutil -lint` PASS + `bash -n` PASS captured in artifact.
- [ ] No `launchctl` mutation run in this prompt.
- [ ] STATUS_REPORT entry landed.
- [ ] Verification artifact landed.
- [ ] `git push origin main` succeeds.
- [ ] `[NEEDS_MATT]` arm command included verbatim in STATUS_REPORT.
