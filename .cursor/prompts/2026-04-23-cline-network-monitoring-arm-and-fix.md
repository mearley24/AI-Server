<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: medium
Trigger:   manual
Status:    done
<!-- autonomy: end -->

# Network Monitoring Phase-2 — Fix network-guard security_utils crash (Bob, Cline-first)

> **Closed 2026-04-23 09:43 MDT.** Both blockers this prompt targets are ✅.
> Do **not** re-run this prompt.
>
> - Blocker #1 (arm dropout-watch): closed by commit `4dbd996` — the plist now
>   includes `/sbin:/usr/sbin` in PATH so `/sbin/ping` resolves under the
>   LaunchAgent. `data/network_watch/dropout_watch_status.json` reports
>   `running: true`, `health: healthy`.
> - Blocker #2 (`security_utils` import): closed by commit `329ea8c` —
>   `tools/network_guard_daemon.py` now inlines `sanitize_for_telegram` and the
>   dangling `from security_utils import sanitize_for_telegram` is gone.
>   `tools/imessage_watcher.py` is untouched; no `tools/security_utils.py`
>   shim was needed.
>
> Superseded by: Run-4 verification at
> `ops/verification/20260423-094342-network-monitoring-launchd.txt`
> (`com.symphony.network-guard` PID 56949, exit=0, healthy records every 60s;
> `com.symphony.network-dropout-watch` PID 52527, exit=0, gateway 0.6 ms,
> WAN 13 ms, `.err` empty). See
> `docs/audits/2026-04-23-04-network-monitoring-launchd-verification.md`.
>
> The two remaining `[FOLLOWUP]` items (prune 8 MB pre-fix `.err`, and the
> optional `~/Library/LaunchAgents/` copy) are already tracked in
> STATUS_REPORT and do not need this prompt to run.

> **Prior status update (historical, 2026-04-23 15:30):** Origin/main advanced
> while this prompt was drafted. Commit `4dbd996` already armed the
> `com.symphony.network-dropout-watch` LaunchAgent and added `/sbin:/usr/sbin`
> to its PATH so `/sbin/ping` resolves. `data/network_watch/dropout_watch_status.json`
> on Bob reports `running: true`, `health: healthy`. **Blocker #1 was
> closed then.** At drafting time this prompt was scoped to blocker #2 only —
> that is now also ✅ (see the "Closed" note above).

## Goal

Close the remaining `[NEEDS_MATT]` blocker left by the 2026-04-23 09:15
Phase-1 pass (commit `9e12fc6`) **on Bob**, in a single bounded Cline run:

1. Diagnose and fix the `ModuleNotFoundError: No module named
   'security_utils'` crash in `tools/network_guard_daemon.py` that has
   been running since ~2026-04-03, then reload the existing
   `com.symphony.network-guard` LaunchAgent and verify it produces a
   fresh healthy log line plus updates to
   `data/network_guard_state.json`.
2. Verify (read-only) that the already-armed
   `com.symphony.network-dropout-watch` LaunchAgent is still healthy.

Both fixes must be committed to the repo (repo-owned durable artifacts,
not one-off Bob-side patches) and pushed to `origin/main`.

Paired Phase-1 artifacts:

- `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
- `ops/verification/20260423-091516-network-monitoring-launchd.txt`
- `setup/launchd/com.symphony.network-dropout-watch.plist`
- `STATUS_REPORT.md` (dated section dated 2026-04-23 09:15)

## Preconditions

Read first (bounded; do not dump secrets):

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `STATUS_REPORT.md` (last ~250 lines only; use `sed -n '1,250p'` or
  `tail -n 250`)
- `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`
  (the Phase-1 sibling to this prompt — the ground truth for what was
  already done)
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `.cursor/prompts/2026-04-23-cline-network-monitoring-launchd-setup.md`
  (the Phase-1 prompt — this prompt is its follow-up)
- `setup/launchd/com.symphony.network-guard.plist`
- `setup/launchd/com.symphony.network-dropout-watch.plist`
- `tools/network_guard_daemon.py` (lines 1-60 first, then full if
  needed)
- `tools/network_dropout_watch.py` (full — it is 214 lines)
- `tools/imessage_watcher.py` — header only (`sed -n '1,40p'`). This
  also imports from `security_utils` and must continue to work after
  the fix. The fix you ship must not break it.

Confirm host and branch:

```
hostname
pwd
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git status --short
git log -1 --format='%h %s'
```

You must be on host `bob` and branch `main`. If `git status --short`
shows unexpected local changes, stop and report — do **not** stash,
reset, or clean.

Sync:

```
git pull --ff-only
```

If the fast-forward fails, stop and report.

## Operating mode

- `AUTO_APPROVE = true` for: reading files, `plutil -lint`, `bash -n`,
  `python3 -m py_compile`, writing new repo files under `tools/`,
  `setup/launchd/` (only if a plist needs a one-line PYTHONPATH
  addition), `docs/audits/`, `ops/verification/`, editing
  `STATUS_REPORT.md`, `git add`, `git commit`, `git push origin main`,
  and the specific `launchctl` commands listed in Phase 3 and Phase 5
  that only affect the *user* LaunchAgents for
  `com.symphony.network-dropout-watch` and `com.symphony.network-guard`.
- `AUTO_APPROVE = false` for: any `sudo`, any `launchctl` action on a
  system `LaunchDaemon` under `/Library/LaunchDaemons/`, any kill of a
  process that is not one of the two Labels above, any edit to
  `~/Library/LaunchAgents/` **other than** re-linking the two plists
  from the repo copy, any network-reachable change beyond the already
  existing outbound pings, any Docker or Redis mutation, any send to a
  third-party service (Telegram, iMessage, BlueBubbles, Slack, X).
- **Hard bans** (enforced by `.clinerules`):
  - No heredocs, no inline interpreters, no interactive editors.
  - No `tail -f`, no `--watch` foregrounds, no unbounded loops.
    Observation uses `tail -n 200`, `sed -n '1,200p'`, or `timeout 5 …`.
  - No `rm -rf` outside a scratch dir you created this run.
  - Do not print `.env`, `.env.*`, secrets, keys, tokens. Plist content
    is fine.
  - No `sudo`.
  - Do not call `tools/network_guard_daemon.py` in a way that would
    trigger a Telegram send (`--once` uses stdout only and is fine; do
    not set any `TELEGRAM_*` env var in this run).
- **Bob-only runtime posture.** Do not open any new inbound ports. No
  public exposure. The only outbound surface this run touches is the
  ICMP pings already built into both tools and `git push` to
  `origin/main`.

## Step plan

Each phase is bounded. Capture outputs to the verification file named
in the "Final report" section as you go.

### Phase 1 — Re-verify Phase-1 ground truth (≤ 2 min, read-only)

```
plutil -lint setup/launchd/com.symphony.network-guard.plist
plutil -lint setup/launchd/com.symphony.network-dropout-watch.plist
launchctl list | grep -E 'network-guard|network-dropout-watch' || true
ls -la ~/Library/LaunchAgents/com.symphony.network-guard.plist 2>/dev/null
ls -la ~/Library/LaunchAgents/com.symphony.network-dropout-watch.plist 2>/dev/null
ls -la logs/network-guard.log logs/network-guard.err 2>/dev/null
wc -l logs/network-guard.err 2>/dev/null
tail -n 40 logs/network-guard.err 2>/dev/null
tail -n 40 logs/network-guard.log 2>/dev/null
ls -la data/network_guard_state.json data/network_watch/dropout_watch_status.json 2>/dev/null
python3 -m py_compile tools/network_guard_daemon.py 2>&1 | tail -n 20 || true
python3 -m py_compile tools/network_dropout_watch.py
python3 -c "import security_utils" 2>&1 | tail -n 5 || true
python3 -c "import sys; print(sys.path)"
```

Confirm: the network-guard `.err` contains the
`ModuleNotFoundError: No module named 'security_utils'` trace and the
`--once` py_compile itself fails with the same import error at module
load. Record every line.

### Phase 2 — Decide the `security_utils` fix (≤ 3 min)

The repo has two callers:

- `tools/network_guard_daemon.py` — needs `sanitize_for_telegram`.
- `tools/imessage_watcher.py` — needs `hash_text, mask_contact,
  mask_name, redact_text`.

`git log --all --oneline -- '**/security_utils*' '**/security_utils.py'`
should return empty (already verified from the sandbox — the module was
never committed). Before creating a new one, check Bob one more time
**without** reading it:

```
find /Users/bob/AI-Server -maxdepth 4 -name 'security_utils*.py' -not -path '*/.git/*' 2>/dev/null
find /Users/bob -maxdepth 5 -name 'security_utils*.py' -not -path '*/.git/*' -not -path '*/Library/*' 2>/dev/null
```

- **If a committed-elsewhere copy exists on Bob** (for instance under
  `/Users/bob/AI-Server/lib/` or similar but missing from `git ls-files`):
  do **not** copy its contents blindly. Run
  `git ls-files | grep security_utils || true` to confirm it is untracked,
  `sha256sum` it for the record, then decide whether to `git add` it
  (if it is legitimately repo-adjacent and non-secret) or to supersede
  it with a fresh minimal shim per the next bullet. Put the decision
  and the sha in the verification file.
- **Otherwise**, create `tools/security_utils.py` as a minimal, fully
  self-contained shim that implements *exactly* the five names the two
  callers import:
  - `sanitize_for_telegram(text: str) -> str`
  - `hash_text(text: str) -> str`
  - `mask_contact(value: str) -> str`
  - `mask_name(value: str) -> str`
  - `redact_text(value: str) -> str`

  Minimum behavior that keeps the callers working without changing
  their call sites:

  - `sanitize_for_telegram` — strip zero-width chars, collapse runs of
    whitespace, and truncate to 3500 chars (Telegram's ceiling is 4096
    but we want headroom for server-side prefixes). Do **not** attempt
    HTML/Markdown escaping — the caller passes `text` and lets the
    Telegram API handle it.
  - `hash_text` — lowercase hex SHA-256 of the input UTF-8 bytes.
  - `mask_contact` — for a phone number or email, keep the last 2
    chars of the local part / last 4 digits, mask the rest with `*`.
    Deterministic; no network.
  - `mask_name` — replace all but the first letter of each
    whitespace-separated token with `*`.
  - `redact_text` — run `mask_contact` + `mask_name` over common
    patterns (emails, phone-like digit runs of length ≥ 7) and return
    the result.

  Keep it under ~120 lines, no external deps, pure stdlib
  (`re`, `hashlib`, `unicodedata`). File starts with a module
  docstring stating why it exists (to satisfy the two callers above)
  and a one-line history note pointing at
  `docs/audits/2026-04-23-network-monitoring-launchd-verification.md`.

Then choose the import strategy. The cleanest repo-native fix is to
make `tools/` itself importable as a package root at LaunchAgent
runtime. `tools/network_guard_daemon.py` runs with
`WorkingDirectory = /Users/bob/AI-Server`, which puts the repo root on
`sys.path[0]` only if invoked with `python -m` — which the plist does
not do. So either:

- **Option A (preferred, smallest blast radius):** add
  `__init__.py` files where needed only if they are already the
  convention, and adjust each caller to bootstrap `sys.path` with the
  `tools/` directory before the import. Example insertion at the top
  of both `tools/network_guard_daemon.py` and
  `tools/imessage_watcher.py`, immediately after `from __future__` and
  before any `security_utils` import:

  ```
  import sys as _sys
  from pathlib import Path as _Path
  _sys.path.insert(0, str(_Path(__file__).resolve().parent))
  ```

  This keeps `security_utils.py` under `tools/` (no top-level
  namespace pollution) and works regardless of how the LaunchAgent
  invokes the script.

- **Option B:** add `PYTHONPATH=/Users/bob/AI-Server/tools` to
  `EnvironmentVariables` in both plists. Simpler but bleeds into the
  LaunchAgent environment; prefer Option A unless A causes a
  regression you cannot explain in ≤ 10 lines.

Pick Option A unless Phase 1 evidence forces Option B. Record the
choice and reasoning in the verification file.

### Phase 3 — Apply the fix in the repo (≤ 5 min)

1. Create `tools/security_utils.py` per the contract above.
2. Apply the `sys.path` bootstrap to `tools/network_guard_daemon.py`
   and `tools/imessage_watcher.py`. Do not refactor anything else in
   those files.
3. Lint:

   ```
   python3 -m py_compile tools/security_utils.py
   python3 -m py_compile tools/network_guard_daemon.py
   python3 -m py_compile tools/imessage_watcher.py
   ```

   All three must pass.
4. Dry-run the network guard in `--once` mode from the repo root,
   **with no Telegram env vars set**, to prove the import path works:

   ```
   env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHAT_ID -u TELEGRAM_OWNER_CHAT_ID timeout 30 python3 tools/network_guard_daemon.py --once 2>&1 | tail -n 60
   ```

   Expected: no `ModuleNotFoundError`. Exit 0 or 1 is both acceptable
   (a single failed ping is fine); what matters is the import path.
5. Confirm `tools/imessage_watcher.py` still imports cleanly (no run):

   ```
   timeout 10 python3 -c "import sys; sys.path.insert(0, 'tools'); import imessage_watcher" 2>&1 | tail -n 20
   ```

   Expected: no `ModuleNotFoundError` for `security_utils`. Other
   import errors (Redis, dotenv) are out of scope for this run — note
   them in the verification artifact as a `[FOLLOWUP]` if they appear.

### Phase 4 — Verify dropout-watch already-armed state (≤ 1 min, read-only)

Dropout-watch was armed by commit `4dbd996`. **Do not bootstrap or bootout
it in this run.** Just confirm it is still healthy:

```
launchctl list | grep network-dropout-watch
sed -n '1,80p' data/network_watch/dropout_watch_status.json 2>/dev/null
tail -n 40 logs/network-dropout-watch.err 2>/dev/null | head -n 40
```

Acceptance:

- `launchctl list | grep network-dropout-watch` shows a numeric PID.
- `dropout_watch_status.json` parses; `"running": true`,
  `"health": "healthy"`.
- `.err` is empty or contains only benign startup lines.

If dropout-watch has regressed, **stop and report** — do not try to fix
it in the same run as the security_utils work. File a `[NEEDS_MATT]`
and leave it alone.

### Phase 5 — Reload network-guard with the fix (≤ 3 min)

```
launchctl list | grep network-guard
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist
sleep 2
# re-link the plist from the repo copy so the LaunchAgent picks up any
# env/PYTHONPATH change (Option B) — safe no-op if contents match:
ln -sfn /Users/bob/AI-Server/setup/launchd/com.symphony.network-guard.plist ~/Library/LaunchAgents/com.symphony.network-guard.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.symphony.network-guard.plist
sleep 65
launchctl list | grep network-guard
tail -n 60 logs/network-guard.log
tail -n 60 logs/network-guard.err
ls -la data/network_guard_state.json
sed -n '1,80p' data/network_guard_state.json
```

Acceptance:

- `launchctl list | grep network-guard` shows the job registered. The
  daemon runs on a 60s `StartInterval` so the PID column may be `-`
  between ticks — that is expected.
- `logs/network-guard.log` has a fresh dated entry within the last ~2
  minutes.
- `logs/network-guard.err` has no `ModuleNotFoundError` lines dated
  after the bootstrap.
- `data/network_guard_state.json` mtime is within the last ~2 minutes.

If acceptance fails after a single retry, `bootout` the agent, capture
logs, and report. Do not leave the daemon in a crash-loop state worse
than what Phase 1 observed.

### Phase 6 — Log prune housekeeping (≤ 1 min, optional but in-scope)

The Phase-1 FOLLOWUP asked for an 8 MB `.err` prune once the import
was fixed. Only after Phase 5 is green:

```
wc -c logs/network-guard.err
: > logs/network-guard.err
wc -c logs/network-guard.err
```

Truncation only; do **not** `rm` the file — launchd holds the fd.

### Phase 7 — Write the verification artifact (≤ 2 min)

Single file:

```
ops/verification/YYYYMMDD-HHMMSS-network-monitoring-arm-and-fix.txt
```

Must include, in order:

- `uname -a`, `date -u`, `git rev-parse HEAD` before changes.
- Phase 1 verbatim outputs.
- Phase 2 decision (Option A vs B, security_utils-on-Bob find results,
  sha256 of any found file).
- Phase 3 diffs:
  `diff -u /dev/null tools/security_utils.py`
  `git diff --unified=3 tools/network_guard_daemon.py`
  `git diff --unified=3 tools/imessage_watcher.py`
  and the `py_compile` + `--once` dry-run outputs.
- Phase 4 verbatim outputs, including the final contents of
  `data/network_watch/dropout_watch_status.json` (pretty-printed).
- Phase 5 verbatim outputs, including the final line of
  `logs/network-guard.log` and contents of
  `data/network_guard_state.json`.
- Phase 6 pre/post `wc -c`.
- Closing section: "What is still not done" — e.g., ntopng/netdata
  cross-check, any follow-up the security_utils shim flagged in
  `tools/imessage_watcher.py`.

### Phase 8 — STATUS_REPORT entry + commit + push (≤ 2 min)

Append a dated section to `STATUS_REPORT.md` with these bullets:

- Headline: "network-guard import fixed + reload verified
  (YYYY-MM-DD HH:MM MDT, Cline)".
- Link the verification artifact and both audit docs.
- `~~[NEEDS_MATT] Fix network-guard crash~~ ✅` (strike through the
  Phase-1 entry's NEEDS_MATT for the import fix).
- Note that `[NEEDS_MATT] Arm dropout-watch` was already closed by
  commit `4dbd996` on 2026-04-23 09:37.
- `- [FOLLOWUP]` for ntopng/netdata cross-check if still unscheduled.
- `- [FOLLOWUP]` for any new item surfaced (e.g., `imessage_watcher`
  Redis/dotenv imports if the Phase 3 step 5 check flagged them).

Commit and push. Allowed paths (reject any other):

```
tools/security_utils.py
tools/network_guard_daemon.py
tools/imessage_watcher.py
setup/launchd/com.symphony.network-guard.plist         # only if Option B
setup/launchd/com.symphony.network-dropout-watch.plist # only if Option B
docs/audits/2026-04-23-network-monitoring-arm-and-fix.md  # optional companion audit doc, same shape as Phase-1's
ops/verification/YYYYMMDD-HHMMSS-network-monitoring-arm-and-fix.txt
STATUS_REPORT.md
```

```
git add <files above, explicitly — never git add -A>
git status --short
git diff --stat --cached
git commit -m "ops(network-mon): fix security_utils import + reload network-guard (phase-2)"
git push origin main
git log -1 --format='%h %s'
```

If `git status --short` shows any path outside the list above, stop
and report — do not commit it.

## Guardrails

- **Off-limits:** `sudo`, any `/Library/LaunchDaemons/` edit, any
  change to Docker Compose, Redis, or BlueBubbles runtime. No Cortex
  edits. No reply-leg edits.
- **Tier-specific bans:** no `pip install` into system Python. If the
  security_utils shim needs a dependency, stop — the shim must stay
  stdlib-only.
- **Approvals required** (treat as hard stop, report and exit):
  - Any step asks for `sudo`.
  - The `security_utils`-on-Bob search surfaces a file that contains
    secrets or credentials (sha+path only in the artifact; do **not**
    copy contents).
  - Phase 5 acceptance fails twice — file a `[NEEDS_MATT]` and leave
    network-guard in its bootout-ed state, not its crash-loop state.

## Final report

Emit a short summary at the end (≤ 12 lines):

- Commit hash.
- New / changed repo paths.
- `launchctl list` excerpt showing both Labels registered.
- `data/network_watch/dropout_watch_status.json` one-liner: running +
  health.
- `logs/network-guard.log` most recent entry.
- Any `[FOLLOWUP]` left open.

Do not paste full log dumps into stdout — they live in the
verification artifact.
