<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger:   manual
Status:    done
<!-- autonomy: end -->

# Network Monitoring LaunchDaemon Setup & Verification (Bob, Cline-first)

> **Closed 2026-04-23 09:43 MDT.** All four goals below are satisfied by the
> Phase-1 → Phase-2 → Run-4 chain that landed on `origin/main` the same day.
> Do **not** re-run this prompt; the plist, verification artifacts, audit
> doc, and STATUS_REPORT entry it asked for are already in-tree.
>
> - Plist: `setup/launchd/com.symphony.network-dropout-watch.plist` (commit `9e12fc6`, PATH fix `4dbd996`).
> - Plist (paired): `setup/launchd/com.symphony.network-guard.plist` (pre-existing; `security_utils` crash fixed in commit `329ea8c`).
> - Verification artifacts: `ops/verification/20260423-091516-`, `-093448-`, `-093828-`, `-094342-network-monitoring-launchd.txt`.
> - Audit docs: `docs/audits/2026-04-23-network-monitoring-launchd-verification.md` (+ `-02-`, `-03-`, `-04-` runs).
> - STATUS_REPORT: dated section `network-monitoring run 4 — FULL PASS, both agents healthy` (2026-04-23 09:43 MDT).
> - Live state at closure: both agents `exit=0`, `.err` stopped growing, dropout-watch `health=healthy`.
>
> Superseded by: the Run-4 verification artifact above. The only remaining
> follow-ups are repo-safe housekeeping (`.err` prune after a stable day and
> optional `~/Library/LaunchAgents/` copy for the dropout-watch plist),
> both already captured as `[FOLLOWUP]` in STATUS_REPORT.

## Goal

Close the host-network monitoring supervision gap identified in
`docs/audits/2026-04-23-unfinished-setup-audit.md` **without arming
anything new on Bob in this run.** Produce:

1. A committed launchd plist for `tools/network_dropout_watch.py`.
2. A committed verification artifact proving the state of the already-
   committed `com.symphony.network-guard.plist` on Bob *as observed*,
   and proving the new dropout-watch plist's `plutil -lint` passes.
3. A dated verification doc under `docs/audits/` that cross-links 1+2.
4. A STATUS_REPORT entry linking to the above.

This is Phase-1: add, lint, document. **Do not `launchctl load` /
`bootstrap` the new plist.** Arming the daemon is gated behind an
explicit `[NEEDS_MATT]` step in the follow-up. Keep Bob's behavior
unchanged for anything already running; this run only *observes* the
existing `network-guard` plist.

## Preconditions

Read these files before doing anything else:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `STATUS_REPORT.md` (skim the last ~200 lines only)
- `docs/audits/2026-04-23-unfinished-setup-audit.md` (the source audit
  for this prompt — read it in full; it scopes the change)
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `.cursor/prompts/bob-24-7-hardening.md` (for the existing launchd surface)
- `tools/network_guard_daemon.py` (header + CLI only, do not dump secrets)
- `tools/network_dropout_watch.py` (full — it's 214 lines)
- `setup/launchd/com.symphony.network-guard.plist`

Confirm you are on Bob and inside the repo:

```
hostname
pwd
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
```

If `git status` shows unexpected local changes, stop and report — do
**not** stash, reset, or clean.

Then sync:

```
git pull --ff-only
```

If the fast-forward fails, report and stop.

## Operating mode

- `AUTO_APPROVE = true` for: reading files, `plutil -lint`, `bash -n`,
  writing new files under `setup/launchd/`, `docs/audits/`,
  `ops/verification/`, editing `STATUS_REPORT.md`, and committing
  those changes.
- `AUTO_APPROVE = false` for: anything that mutates launchd state
  (`launchctl load/unload/bootstrap/bootout/kickstart`), kills a
  process, touches `sudo`, edits `~/Library/LaunchAgents/` or
  `/Library/LaunchDaemons/` live, opens a port, or sends any external
  message.
- **Hard bans** (enforced by `.clinerules`):
  - No heredocs, no inline interpreters, no interactive editors.
  - No long-running watch modes. If you must observe the existing
    `network-guard` daemon's log, use `tail -n 200` (bounded) or
    `sed -n '1,200p'`, never `tail -f`.
  - No `rm -rf` outside a scratch dir you created this run.
  - Do **not** print `.env`, `.env.*`, secrets, keys, tokens. Reading
    plist files (non-secret) is fine.
  - No `sudo` in this run.
  - Do not run `tools/network_dropout_watch.py --watch` as a
    foreground process. A bounded 5-second `--status` probe is OK.
- **Bob-only runtime posture.** Do not add any new open inbound ports.
  Do not add any public exposure. Do not run anything that reaches out
  to third-party services except the ICMP pings already built into the
  tool. The tool pings `192.168.1.1` (gateway), `1.1.1.1` (WAN check),
  and optional Control4/Sonos IPs on the LAN. That is the entire
  outbound surface of this work.

## Step plan

Each phase is bounded. Capture output to the verification file named
in the "Final report" section as you go.

### Phase 1 — Observe the existing network-guard plist (≤ 2 min, read-only)

Already-committed plist: `setup/launchd/com.symphony.network-guard.plist`.
Verify repo copy passes lint, then *observe* Bob's runtime state without
changing it.

```
plutil -lint setup/launchd/com.symphony.network-guard.plist
launchctl list | grep network-guard
ls -la /Users/bob/Library/LaunchAgents/com.symphony.network-guard.plist 2>/dev/null
ls -la /Library/LaunchDaemons/com.symphony.network-guard.plist 2>/dev/null
ls -la /Users/bob/AI-Server/logs/network-guard.log 2>/dev/null
ls -la /Users/bob/AI-Server/logs/network-guard.err 2>/dev/null
test -f /Users/bob/AI-Server/logs/network-guard.log && sed -n '1,40p' /Users/bob/AI-Server/logs/network-guard.log
test -f /Users/bob/AI-Server/logs/network-guard.log && wc -l /Users/bob/AI-Server/logs/network-guard.log
test -f /Users/bob/AI-Server/logs/network-guard.log && tail -n 200 /Users/bob/AI-Server/logs/network-guard.log
test -f /Users/bob/AI-Server/logs/network-guard.err && tail -n 100 /Users/bob/AI-Server/logs/network-guard.err
```

Do not `load`, `unload`, `bootstrap`, `bootout`, or `kickstart` anything.
If `launchctl list` does not show `com.symphony.network-guard`, record
that fact in the verification artifact — do not try to fix it in this
run. That becomes a `[NEEDS_MATT]` follow-up.

### Phase 2 — Lint `tools/network_dropout_watch.py` (≤ 1 min)

```
python3 -m py_compile tools/network_dropout_watch.py
timeout 5 python3 tools/network_dropout_watch.py --status --state-dir data/network_watch
```

The `--status` call is bounded, read-only (it reads
`data/network_watch/status.json` if present, prints a dict, exits).
If `data/network_watch/` does not exist, `--status` prints a "no
state" dict and exits 0; that is expected. Do not run `--watch`.

### Phase 3 — Add the dropout-watch plist (LaunchAgent, not Daemon)

Create `setup/launchd/com.symphony.network-dropout-watch.plist`. Match
the style of the existing `com.symphony.network-guard.plist` and the
task-runner / ollama agents already in `setup/launchd/`:

- `Label` = `com.symphony.network-dropout-watch`
- `ProgramArguments` = `/usr/bin/python3`,
  `/Users/bob/AI-Server/tools/network_dropout_watch.py`, `--watch`,
  `--state-dir`, `/Users/bob/AI-Server/data/network_watch`,
  `--interval-sec`, `2.0`
- `WorkingDirectory` = `/Users/bob/AI-Server`
- `EnvironmentVariables.PATH` = same as `network-guard`
- `EnvironmentVariables.HOME` = `/Users/bob`
- `RunAtLoad` = `true`
- `KeepAlive` = `true` (the tool handles SIGTERM cleanly — see
  `tools/network_dropout_watch.py:21-28`)
- `ThrottleInterval` = `30` (bound restart storms)
- `StandardOutPath` = `/Users/bob/AI-Server/logs/network-dropout-watch.log`
- `StandardErrorPath` = `/Users/bob/AI-Server/logs/network-dropout-watch.err`
- **No** `UserName` key (run as the user under LaunchAgent).
- **No** `StartInterval` — this is a continuous process, not a tick.

`plutil -lint` must pass. **Do not `launchctl load` it.** Only commit
the file. If Matt decides to arm it, the steps are in Phase 6.

### Phase 4 — Write the verification artifact (≤ 1 min)

Write everything captured above to a single file:

```
ops/verification/YYYYMMDD-HHMMSS-network-monitoring-launchd.txt
```

Stamp format matches existing repo convention (see
`ls ops/verification/ | head`). Include:

- `uname -a`, `date -u`, `git rev-parse HEAD`.
- Phase 1 command outputs verbatim.
- Phase 2 command outputs verbatim.
- `plutil -lint` output for both plists.
- `diff -u /dev/null setup/launchd/com.symphony.network-dropout-watch.plist`
  (full contents of the new file for the record).
- A closing section: "NOT DONE IN THIS RUN — requires Matt: bootstrap
  the new LaunchAgent, validate the `network_watch/` state directory
  gets populated, cross-check against the `ntopng/netdata` stack (not
  yet scheduled)."

### Phase 5 — Write the paired audit doc (≤ 2 min)

Create `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
(or `2026-04-23-02-...` suffix if a same-day file already exists).
Contents:

- Link back to `docs/audits/2026-04-23-unfinished-setup-audit.md`.
- Summary: what the repo looked like before this run, what this run
  changed (one new plist file + this doc + verification artifact +
  STATUS_REPORT entry), and what is *still not done*.
- Explicit "out-of-scope for this run" list:
  - Any `launchctl` mutation.
  - Any change to `com.symphony.network-guard.plist` semantics.
  - Any new open port, any public exposure, any Docker service.
  - Any change to `docker-compose.yml`.
  - Any reply-leg / Cortex / BlueBubbles work.
  - Any Bob-only secret read.
- Reference the stamped verification artifact path.

### Phase 6 — STATUS_REPORT entry + commit + push

Append a dated section to `STATUS_REPORT.md` that:

- Names the Cline run and timestamp.
- Links the verification artifact and both audit docs.
- Includes a `[FOLLOWUP]` line for the verification receipt.
- Includes a `[NEEDS_MATT]` line for the `launchctl bootstrap` step,
  with the exact command Matt should run (no `sudo` required for a
  user LaunchAgent: `launchctl bootstrap gui/$(id -u) setup/launchd/com.symphony.network-dropout-watch.plist`
  — but put the command in the STATUS_REPORT, do **not** run it).
- Lists the TODOs explicitly (mirror the ones in
  `docs/audits/2026-04-23-unfinished-setup-audit.md`).

Commit and push:

```
git add setup/launchd/com.symphony.network-dropout-watch.plist
git add docs/audits/2026-04-23-network-monitoring-launchd-verification.md
git add ops/verification/YYYYMMDD-HHMMSS-network-monitoring-launchd.txt
git add STATUS_REPORT.md
git status --short
git diff --stat --cached
git commit -m "ops(network-mon): add network-dropout-watch LaunchAgent plist + verification (not loaded)"
git push origin main
git log -1 --format='%h %s'
```

Only the four paths above should be in the commit. If `git status`
shows other modified files, stop and report — do not include them.

## Safety checklist (must be true before push)

- [ ] No `launchctl` state-changing command was run.
- [ ] No `sudo` was used.
- [ ] No secrets, `.env`, keys, tokens, or Keychain contents were
      printed or committed.
- [ ] No inbound port was opened; no public exposure added.
- [ ] No runtime service on Bob was started, stopped, killed, or
      restarted.
- [ ] No Docker state, Redis state, or launchd state was mutated.
- [ ] No external message (iMessage, email, Slack, X) was sent.
- [ ] No files outside `setup/launchd/`, `docs/audits/`,
      `ops/verification/`, or `STATUS_REPORT.md` were modified.
- [ ] `plutil -lint` PASS on both plists.
- [ ] `python3 -m py_compile tools/network_dropout_watch.py` PASS.
- [ ] Verification artifact exists with the standard stamp format.
- [ ] STATUS_REPORT entry uses the `[FOLLOWUP]` / `[NEEDS_MATT]` tags.

## Final report

Emit a short summary to stdout at the end:

- Commit hash.
- Paths of new / changed files.
- One-paragraph "what is still not done" (the `[NEEDS_MATT]` arm step
  is the big one).
- The exact `launchctl bootstrap` command Matt would run to arm the
  new LaunchAgent, quoted for copy-paste. Do not run it.
