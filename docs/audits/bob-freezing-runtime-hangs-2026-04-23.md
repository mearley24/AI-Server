# Bob Freezing / Runtime Hangs — Diagnosis Audit (2026-04-23)

## Summary

Bob's recurring freezes are most likely caused by the Symphony Task Runner
holding its single-instance `fcntl.flock` lock while a child `git` call
blocks without a timeout. `scripts/task_runner.py` runs `git pull`,
`git push`, `git commit`, and `git status` via `subprocess.run` with **no
`timeout=` argument**; when any of those calls stall (network blip, auth
prompt, stuck credential helper, slow remote), the tick holds the lock
indefinitely and every subsequent launchd tick (every 120s) no-ops with
"another runner holds the lock." `bob-watchdog.sh` secondarily uses
`docker info` / `docker ps` with no `--timeout`, which can extend the
user-visible freeze in the Docker-Desktop "zombie daemon" state that was
already documented in-repo on 2026-04-21.

This audit was produced from **static analysis only** (code grep, git
log, repo inspection) because the diagnosis had to run on Matt's MacBook
M2 Pro — not on Bob — so the dynamic checks in the prompt (top, ps,
`launchctl list`, `docker stats`, `redis-cli`, lockfile and log tails)
could not be executed. A follow-up run on Bob is required to confirm
which of the known-unbounded calls is the one currently stuck, to see
queue depths and consumer lag, and to inspect `data/task_runner/.runner.lock`.

## Evidence

Captured artifact: `ops/verification/20260423-131042-bob-freeze-diagnosis.txt`.

### Unbounded git subprocesses in the task runner

`scripts/task_runner.py`:

- `git(...)` helper, `scripts/task_runner.py:131` — generic git dispatcher, no `timeout=`. Reached by:
  - `commit_and_push` → `git add` (line 673), `git commit` (line 686), `git push` (line 697)
- `handle_git_pull`, `scripts/task_runner.py:218` — `git pull --ff-only` on behalf of a queued task, no `timeout=`.
- `has_changes`, `scripts/task_runner.py:652` — `git status --porcelain`, no `timeout=`.
- `pull_latest`, `scripts/task_runner.py:722` — `git pull --ff-only`, no `timeout=`.
- `pull_latest` rebase fallback, `scripts/task_runner.py:743` — `git pull --rebase`, no `timeout=`.

The `_run_and_tee` helper used for task subprocesses does pass
`timeout=TASK_TIMEOUT` (2 h, `scripts/task_runner.py:241`), but none of
the git-plumbing calls above go through that helper.

### Lock semantics turn a single hang into a durable wedge

`scripts/task_runner.py:155-173` uses `fcntl.flock(LOCK_EX | LOCK_NB)` on
`data/task_runner/.runner.lock`. If `run_once()` blocks on one of the
unbounded git calls, the lock is held for the entire duration; every
subsequent launchd tick exits with `another runner holds the lock`
(`scripts/task_runner.py:805`). Heartbeats stop. The observable symptom
matches "Bob freezing up": the runner appears dead even though launchd
keeps firing.

### Watchdog docker probes also unbounded

`scripts/bob-watchdog.sh:134-155` (`docker_healthy`) calls
`docker info` and `docker ps -q` without `--timeout`. The comment at
`scripts/bob-watchdog.sh:128-133` already documents the 2026-04-21
"EOF / zombie backend" mode that stranded Bob. The recovery loop at
`scripts/bob-watchdog.sh:173-181` IS bounded (120 s cap), but the
initial probe is not — which means the watchdog can also hang on a
zombie daemon before ever entering recovery.

### Services that look healthy (no primary freeze risk)

- Cortex loops (`cortex/engine.py:84, 93, 110, 128`) all use
  `asyncio.sleep(N)` + `try/except` backoff. All HTTP calls in
  `cortex/` pass explicit `httpx.AsyncClient(timeout=...)`. Redis
  clients use `socket_timeout=2`. Subprocess calls in
  `cortex/dashboard.py:1185, 1214` pass `timeout=30/60`.
- `integrations/x_intake/main.py:845, 904` Redis listener + watchdog
  use `while True` with `asyncio.sleep`-backoff. All `httpx` callers
  pass explicit timeouts.
- `cortex/bluebubbles.py` uses configured `self.timeout` on every
  `httpx` call and `socket_timeout=2` on Redis.

The only notable gap is that OpenAI `client.chat.completions.create`
calls at `integrations/x_intake/main.py:120, 481`,
`integrations/x_intake/transcript_analyst.py:215`,
`integrations/x_intake/video_transcriber.py:653, 691` rely on the
openai SDK default timeout (10 min on v1.x). These can extend tail
latency but are unlikely to freeze the machine.

### Commit cadence confirms the runner is usually healthy

`git log` on 2026-04-21 shows the task-runner tick landing every
~10 minutes (HEARTBEAT_EVERY=600 s). Fetch after the fact shows the
remote heartbeating through 2026-04-23 07:00 -0600, i.e. the freezes
are intermittent — not a continuous crash loop. That matches a
network/auth stall on one particular tick wedging the lock until
someone kills the stuck process or reboots Bob.

## Contributing factors

- Frequent `auto: local changes before pull` and
  `ops: task-runner preflight — N conflicts resolved` commits indicate
  Bob's working tree is dirty on many ticks. The preflight only heals
  whitelisted state files. Any non-whitelisted conflict will block task
  dispatch (by design) but can also leave the process paused in `pull`
  — still under the unbounded `git pull` problem.
- Pre-existing unresolved merge conflict on the machine used for this
  diagnosis (`ios-app/SymphonyOps/SymphonyOps/ContentView.swift`,
  `UU`) prevented `git pull --ff-only` and prevented this pass from
  committing its findings directly from the main checkout — a second
  symptom of the same class of problem (pull failure leaves the tree
  half-merged).

## Fix options

### Option A — Add bounded timeouts to every git call in the task runner (LOW risk, recommended)

Scope: `scripts/task_runner.py` only. Adds
`timeout=<SECONDS>` kwargs + a `TimeoutExpired` handler that logs and
returns a non-zero code. One file, ≤ ~40 lines of change including a
smoke test under `ops/tests/`.

Risk tier: low. Blast radius: the task-runner tick itself — a timeout
aborts the tick cleanly, releases the lock, and the next launchd tick
can try again.

### Option B — Bound the watchdog docker probes as well (LOW risk, pairs with A)

Scope: `scripts/bob-watchdog.sh`. Wrap `docker info` and `docker ps -q`
in `timeout 10 ...` (Bash). ≤ 5 lines. Risk tier: low.

### Option C — Replace fcntl.flock with a bounded lock-then-pid-stamp scheme (MEDIUM risk, deferred)

If timeouts are added (A+B) but the root cause recurs, rework the
lock so stale locks older than ~30 minutes are considered dead and
reclaimable. This is a more invasive change and is not required once
A+B are in place.

## Recommended next step

Apply Option A (+B) via the Phase 1 fix prompt at
`.cursor/prompts/fix-bob-freezing-phase-1-runner-git-timeouts.md` on
Bob. The "safe low-risk fix gate" is satisfied, but this diagnosis
pass was done on Matt's MacBook — the code change should land from a
Cline session actually running on Bob so Phase 1–2 baseline capture
(top, ps, `launchctl list`, lockfile inspection) can precede and
confirm the patch.

## Known limitations of this diagnosis

- No dynamic verification was performed. Phases 1, 2, 5, and the log-
  tail / lockfile-inspection slices of Phases 3, 4, 6 were skipped.
- The static evidence above is sufficient to explain the symptom ("Bob
  freezes up" with launchd task-runner running but silent), but the
  actual stuck call / network failure mode on the day of the freeze
  was not captured. Re-run on Bob to confirm.
