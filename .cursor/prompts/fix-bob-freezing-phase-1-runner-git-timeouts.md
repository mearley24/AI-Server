<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# Fix Bob Freezing — Phase 1: Bound the Task Runner's Git Subprocess Calls

## Goal

Stop Bob from wedging when a `git pull` / `git push` / `git commit` /
`git status` inside `scripts/task_runner.py` stalls on the network or
on auth. Today those subprocesses have no `timeout=`, so one stuck git
process holds the `fcntl.flock` lock on
`data/task_runner/.runner.lock` indefinitely. Every subsequent launchd
tick (120 s) no-ops with "another runner holds the lock" and Bob looks
frozen from the outside. Same pattern applies to `scripts/bob-watchdog.sh`
where `docker info` / `docker ps` can hang on a zombie Docker daemon.
Audit: `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md`.

## Preconditions

Read first:

- `/CLAUDE.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md` (this fix is
  Recommended next step "Option A + B" from that audit)
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`

Confirm host + clean tree:

```
hostname
pwd
git rev-parse --show-toplevel
git status --short
git log -1 --format='%h %s'
bash scripts/pull.sh
```

Stop and report if anything outside `ops/verification/`,
`ops/work_queue/`, or `data/task_runner/heartbeat.txt` is dirty. Do not
stash, reset, or clean.

## Operating mode

- `AUTO_APPROVE = true` for the code change, tests, verification file,
  commit, and push.
- Hard bans (per `.clinerules`): no heredocs, no multi-line quoted
  strings, no inline interpreters, no interactive editors, no long-
  running watch modes, no `rm -rf` outside a scratch dir.
- Do NOT restart any service, do NOT touch `.env`, `secrets/`,
  `setup/launchd/`, `docker-compose*.yml`, or anything under
  `bluebubbles/` that sends messages.
- Verification-to-file-then-commit: every check output goes to
  `ops/verification/<YYYYMMDD-HHMMSS>-bob-freeze-fix1.txt`.
- Bounded commands only (`timeout 30 <cmd>` or bounded `-n` flags).

## Step plan

### Phase 1 — Capture baseline on Bob (≤ 3 min)

Before changing code, snapshot the state the audit could not see:

```
date -u +%Y-%m-%dT%H:%M:%SZ
uptime
ls -la data/task_runner/.runner.lock 2>/dev/null
cat data/task_runner/.runner.lock 2>/dev/null
ls -la data/task_runner/heartbeat.txt
cat data/task_runner/heartbeat.txt
launchctl list | grep -E 'symphony|bob' | head -40
ps -axo pid,etime,stat,command | grep -E 'task_runner|bob-watchdog|python.*scripts/task_runner' | grep -v grep | head -40
pgrep -fl 'scripts/task_runner.py' | head -10
tail -n 200 data/task_runner/bob-watchdog.log 2>/dev/null
git log --since='2026-04-21' --until='today' --oneline -- data/task_runner/heartbeat.txt | head -40
```

Flag: if a `task_runner.py` process shows `etime` > 10 min, that is the
wedged tick. Record its PID for later killing (after the fix lands).

### Phase 2 — Edit `scripts/task_runner.py`

Add bounded timeouts to every `subprocess.run` that shells out to
`git`. Apply a shared constant at the top of the module, e.g.:

```
GIT_TIMEOUT = 60  # seconds; bounded so a stalled network never wedges the lock
```

Then:

1. In the `git(...)` helper at `scripts/task_runner.py:131`, pass
   `timeout=GIT_TIMEOUT` to `subprocess.run` and catch
   `subprocess.TimeoutExpired`; log the timeout via `log(...)` and
   re-raise a clear error or return a `CompletedProcess`-shaped
   failure so callers (`commit_and_push`, etc.) treat it as a
   non-zero-exit commit failure rather than crashing.
2. `handle_git_pull` at `scripts/task_runner.py:218`: pass
   `timeout=GIT_TIMEOUT`. On `TimeoutExpired`, write
   `"TIMEOUT after <N>s"` to the result file and return exit 124.
3. `has_changes` at `scripts/task_runner.py:652`: pass
   `timeout=GIT_TIMEOUT`. On timeout, return False and log; the runner
   then skips the commit for this tick.
4. `pull_latest` at `scripts/task_runner.py:722` and its rebase
   fallback at `scripts/task_runner.py:743`: pass
   `timeout=GIT_TIMEOUT`. On `TimeoutExpired`, log and return without
   crashing (same "runner still processes locally-pending tasks"
   contract as the existing docstring).

Do NOT change `TASK_TIMEOUT`. Do NOT alter lock semantics in this
phase. Keep the diff scoped to subprocess-timeout additions and their
exception handlers.

### Phase 3 — Edit `scripts/bob-watchdog.sh`

In `docker_healthy()` (line ~134), wrap the `docker info` and
`docker ps -q` probes in `timeout 10`, e.g.
`timeout 10 docker info --format '{{.ServerVersion}}' 2>/tmp/docker_info.err`
and
`timeout 10 docker ps -q >/dev/null 2>/tmp/docker_ps.err`.
If `timeout(1)` is not present on Bob, fall through with a shell-side
`&` + `wait -n` pattern — still bounded to 10 s. Do NOT change the
recovery loop; it is already bounded.

### Phase 4 — Add a smoke test

Create `ops/tests/test_task_runner_git_timeouts.py`:

- Imports `scripts.task_runner` (add `ops/tests/conftest.py` or
  `sys.path` shim if needed).
- Monkey-patches `subprocess.run` to raise
  `subprocess.TimeoutExpired` and asserts each of the four helpers
  (`git`, `handle_git_pull`, `has_changes`, `pull_latest`) returns
  gracefully — no uncaught exception, no crash.
- Runs under `python3 -m pytest ops/tests/test_task_runner_git_timeouts.py`
  in ≤ 10 s. Record the output in the verification file.

### Phase 5 — Verification on Bob

```
date -u +%Y-%m-%dT%H:%M:%SZ
python3 -m pytest ops/tests/test_task_runner_git_timeouts.py -q
timeout 30 python3 scripts/task_runner.py || echo "(expected: exits on lock contention or no work)"
tail -n 40 data/task_runner/heartbeat.txt
git log -n 5 --format='%h %ai %s'
```

If any existing stuck `task_runner.py` process is still in the
process table from Phase 1, kill ONLY that PID with
`kill <PID>` (not `kill -9 <PID>` as a first attempt, and never a
broad `pkill`). Wait 30 s, re-check with `pgrep -fl`. If it refuses
to exit gracefully, escalate to a single `kill -9 <PID>` on that PID
only.

### Phase 6 — STATUS_REPORT and commit

Append a ≤ 25-line entry to `STATUS_REPORT.md` referencing the audit
and the fix commit. Stage and commit exactly:

- `scripts/task_runner.py`
- `scripts/bob-watchdog.sh`
- `ops/tests/test_task_runner_git_timeouts.py`
- `ops/verification/<stamp>-bob-freeze-fix1.txt`
- `STATUS_REPORT.md`

Commit message:

```
ops(bob): bound git+docker subprocess calls to stop runner/watchdog hangs
```

Push to `main`. Do not force-push. Do not skip hooks.

## Guardrails

Low-risk tier. In addition to the hard bans in Operating mode:

- Do NOT change `TASK_TIMEOUT` or `HEARTBEAT_EVERY`.
- Do NOT touch `fcntl.flock` / lock path semantics in this phase.
- Do NOT modify any file outside the five listed in Phase 6.
- Do NOT run any outbound messaging (iMessage, Slack, email, X).
- If the smoke test fails, revert the change (do NOT commit) and
  emit a blocker report instead.

## Final report

Write to `ops/verification/<YYYYMMDD-HHMMSS>-bob-freeze-fix1.txt`:

1. Host, pwd, git HEAD, start/end UTC.
2. Phase 1 baseline output (lockfile state, heartbeat age, stuck-PID
   findings).
3. The diff you applied (the `git diff HEAD~1` output after commit).
4. `pytest` output.
5. `tail data/task_runner/heartbeat.txt` after running the patched
   runner once via `timeout 30 python3 scripts/task_runner.py`.
6. Commit hash and pushed branch.

Final chat reply (≤ 10 lines):

- Root cause (1 sentence).
- Files changed.
- Tests + pass/fail.
- Verification artifact path.
- Commit hash.
- "No follow-up" OR the next Phase-2 prompt if Option C is needed.
