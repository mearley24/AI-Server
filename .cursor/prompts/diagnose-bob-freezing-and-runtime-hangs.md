<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must be zsh-safe: no heredocs, no inline interpreters, no interactive editors, no long-running watch modes (no tail -f, no --watch, no npm run dev). Use bounded commands: timeout, --lines N, --since, head/sed -n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: medium
Trigger:   manual
Status:    active
<!-- autonomy: end -->

# Diagnose Bob Freezing and Runtime Hangs

## Goal

Bob (the Mac running AI-Server) is freezing up and becoming unresponsive. Run
a structured diagnosis **on Bob** via Cline, find the actual root cause, write
an audit report, record a verification artifact, update `STATUS_REPORT.md`, and
— only if the fix is clearly low-risk — implement it with tests. If the fix
is anything more than trivial, produce a Phase 1 fix prompt instead of shipping
code. Keep Bob's user-facing texts and calls silent the entire run; this is a
diagnostic pass, not a behavior change.

## Preconditions

Read these files before doing anything else:

- `/CLAUDE.md`
- `AGENTS.md`
- `.clinerules`
- `ops/AGENT_VERIFICATION_PROTOCOL.md`
- `ops/GUARDRAILS.md`
- `STATUS_REPORT.md` (skim the last ~200 lines only)
- `docs/audits/` (list filenames; do not read them all)
- `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
- `.cursor/prompts/bob-24-7-hardening.md` (for the known launchd + watchdog surface)

Confirm you are on Bob and inside the repo:

```
hostname
pwd
git rev-parse --show-toplevel
git status --short
git rev-parse --abbrev-ref HEAD
git log -1 --format='%h %s'
```

If `git status` shows unexpected local changes, stop and report — do **not**
stash, reset, or clean. Matt may have in-progress work.

Then sync:

```
git pull --ff-only
```

If the fast-forward fails, report and stop.

## Operating mode

- `AUTO_APPROVE = true` for diagnosis, report writing, verification capture,
  and commit/push of prompt + docs + audits + verification artifacts.
- `AUTO_APPROVE = false` for any code change that alters runtime behavior,
  restarts a service, kills a process, or touches launchd / Redis / Docker
  state. If a safe low-risk fix exists, see the "Safe low-risk fix gate"
  below — otherwise emit a Phase 1 fix prompt and stop there.
- **Hard bans** (enforced by `.clinerules`):
  - No heredocs (`<<EOF`, `<<'EOF'`), no multi-line quoted strings.
  - No inline interpreters (`python3 <<EOF`, `node -e '...multi-line...'`).
  - No interactive editors (vim, nano, `crontab -e`).
  - No long-running watch modes (`tail -f`, `--watch`, `npm run dev`,
    `docker compose logs -f`, `journalctl -f`).
  - No `rm -rf` of anything outside a scratch directory you just created.
  - Do **not** print contents of `.env`, `.env.*`, `secrets/`, `*.pem`,
    `*.key`, Keychain entries, or any file matching `*secret*`, `*token*`,
    `*credential*`. `grep` for key *names* is OK; never dump values.
- **Verification-to-file-then-commit** contract: every diagnostic command's
  output goes to a bounded file under `ops/verification/`, then committed.
  Do not rely on scrollback.
- **Bounded commands only**. Every command must terminate in ≤ 30s on its
  own, or be wrapped in `timeout 30 <cmd>` (or `timeout 10` for log reads).
- **Quiet mode**. Do not send iMessages, emails, Slack, webhooks, X posts,
  or any outbound user-facing message during this run, even for "testing".
  Local approved reply-path smoke tests are allowed only if the existing
  test harness already routes them to a local sink.

## Step plan

Each phase is bounded. Capture output to the verification file listed in the
"Final report" section as you go — do not batch everything at the end.

### Phase 1 — Baseline system health (≤ 2 min)

Capture a single bounded snapshot of the machine. Do not loop.

```
date -u +%Y-%m-%dT%H:%M:%SZ
uptime
sw_vers
uname -a
sysctl -n hw.ncpu hw.memsize
vm_stat | head -20
df -h | head -20
top -l 1 -n 20 -stats pid,command,cpu,mem,state,time | head -40
ps -axo pid,pcpu,pmem,etime,stat,command | sort -rk 2 | head -30
ps -axo pid,pcpu,pmem,etime,stat,command | sort -rk 3 | head -30
```

Flags to raise:
- Any process in `U` (uninterruptible) or `D`-like state stuck for hours.
- Load average > ncpu for sustained windows (cross-check with `uptime`).
- Memory pressure: free pages < 5% of total, high swap-ins in `vm_stat`.
- Disk > 90% on `/` or the data volume.

### Phase 2 — AI-Server process inventory (≤ 3 min)

Identify which AI-Server components are actually running. Every command is
bounded.

```
launchctl list | grep -E 'symphony|bob|cline|claude|cortex|bluebubbles|dispatch' | head -80
ps -axo pid,ppid,pcpu,pmem,etime,stat,command | grep -E 'python|node|uvicorn|gunicorn|docker|redis|ollama|claude|cline|ai-dispatch|task_runner|self_improvement|watchdog|x_intake|cortex|bluebubbles' | grep -v grep | head -80
pgrep -lf task_runner | head
pgrep -lf self_improvement | head
pgrep -lf ai-dispatch | head
pgrep -lf watchdog | head
pgrep -lf cortex | head
pgrep -lf bluebubbles | head
```

For each long-running process of interest, capture:

```
lsof -p <PID> 2>/dev/null | wc -l
lsof -p <PID> 2>/dev/null | head -40
sample <PID> 2 -mayDie 2>/dev/null | head -200
```

`sample <PID> 2` runs for 2 seconds and exits — safe. It reveals where the
process is spending time (e.g. stuck in a `read`, `select`, HTTP call, or
LLM request). If `sample` is not available, use `spindump` with
`-notarget`+`-file` + `timeout 5`, or skip.

Flags to raise:
- Processes at 100% CPU but no progress in logs → hot loop.
- Processes with 1000+ open file descriptors → leak.
- `sample` stack dominated by a single `requests.get` / `httpx` / `openai` /
  `anthropic` call → synchronous slow LLM call with no timeout.
- `sample` stack dominated by `lock`, `acquire`, `Queue.get` with no
  producer → classic deadlock.

### Phase 3 — Wrapper, dispatch, and orchestrator (≤ 5 min)

These are the most likely culprits for "Bob freezes up":

- Claude Code / Cline wrapper
- `ai-dispatch`
- `task_runner`
- `self-improvement` watcher
- `watchdog`

For each, find the entry point and its log:

```
grep -RIn --include='*.py' --include='*.sh' -E 'def (main|run|tick)\b' task_runner self_improvement watchdog ai-dispatch 2>/dev/null | head -60
grep -RIn --include='*.py' -E 'while True|while 1|while not' task_runner self_improvement watchdog ai-dispatch 2>/dev/null | head -60
grep -RIn --include='*.py' -E 'requests\.(get|post)\(|httpx\.(get|post)\(|openai|anthropic\.' task_runner self_improvement watchdog ai-dispatch 2>/dev/null | head -60
grep -RIn --include='*.py' -E 'timeout\s*=' task_runner self_improvement watchdog ai-dispatch 2>/dev/null | head -60
grep -RIn --include='*.py' -E 'subprocess\.(run|check_output|Popen)|os\.system\(' task_runner self_improvement watchdog ai-dispatch 2>/dev/null | head -60
```

For every HTTP/LLM/subprocess call above, confirm there is a **bounded
timeout**. A `requests.get(url)` or `subprocess.run([...])` with no timeout
is a freeze risk by definition.

Find the latest log for each service and read the **tail only**, bounded:

```
ls -lt logs 2>/dev/null | head -40
ls -lt ~/Library/Logs 2>/dev/null | grep -i 'symphony\|bob\|cline\|dispatch\|task_runner\|self_improve\|watchdog' | head -20
```

Then for each log of interest:

```
wc -l <logfile>
tail -n 500 <logfile>
grep -Ein 'traceback|error|timeout|deadlock|stuck|hang|rate.?limit|429|5\d\d|killed|oom|retry' <logfile> | tail -n 80
```

Never `tail -f`. If a log is > 500 MB, flag it as unbounded-log risk and
read only the last 2000 lines.

### Phase 4 — Heartbeat / wedge / lock loops (≤ 3 min)

Bob has a heartbeat loop and periodic "wedge" recovery logic. When these
loop hot, the machine appears frozen.

```
grep -RIn --include='*.py' --include='*.sh' -E 'heartbeat|wedge|preflight' ops task_runner self_improvement watchdog 2>/dev/null | head -60
find . -maxdepth 4 -name '*.lock' -o -name '*.pid' 2>/dev/null | head -40
find . -maxdepth 4 -name '.*_lock' -type d 2>/dev/null | head -20
ls -la .bob_sort_lock 2>/dev/null
```

For each lock / pid file found:

```
ls -la <lockfile>
cat <pidfile> 2>/dev/null
```

Cross-check: is the PID actually alive? (`ps -p <pid>`). A stale lock owned
by a dead PID is a classic freeze cause. **Do not delete** — record it.

Recent commits tend to introduce freeze loops. Inspect the last 30 ops
commits:

```
git log -n 30 --format='%h %ai %s' | head -40
git log -n 30 --format='%h %ai %s' -- ops task_runner self_improvement watchdog ai-dispatch | head -40
```

Flag any "heartbeat" / "preflight" / "auto-heal" / "tick" commit within the
last 48h as a likely suspect.

### Phase 5 — Docker, Redis, and launchd (≤ 4 min)

Docker:

```
timeout 15 docker ps -a | head -40
timeout 15 docker stats --no-stream | head -40
timeout 15 docker compose ls 2>/dev/null | head
```

If `docker ps` itself hangs past 15s, that's the freeze — record it and do
not retry in a loop. Record the stuck compose project name.

Redis (queue buildup, duplicate consumers):

```
timeout 10 redis-cli -n 0 ping
timeout 10 redis-cli info clients | head -30
timeout 10 redis-cli info memory | head -20
timeout 10 redis-cli info stats | head -40
timeout 10 redis-cli --scan --pattern '*' | head -100
timeout 10 redis-cli --scan --pattern 'queue:*' | head -50
timeout 10 redis-cli --scan --pattern 'stream:*' | head -50
```

For any queue/stream surfaced, check depth (bounded, do not drain):

```
timeout 5 redis-cli llen <queue>
timeout 5 redis-cli xlen <stream>
timeout 5 redis-cli xinfo groups <stream> | head -40
```

Flags:
- Any queue with depth > 10× its usual size.
- Any consumer group with `lag` climbing and `pending` stuck > 0 for
  minutes → dead/duplicate consumer.

Launchd (looping jobs):

```
launchctl list | grep -E 'symphony|bob|cline|claude|cortex|bluebubbles|dispatch' | awk '{print $1" "$2" "$3}' | head -80
```

A service whose PID column keeps changing across two bounded snapshots
(take a second snapshot 10s later with `sleep 10`) is crash-looping. One
`sleep 10` is allowed; do not loop.

### Phase 6 — X-intake, Cortex, BlueBubbles (≤ 3 min)

Bounded checks only — do not send any message.

```
grep -RIn --include='*.py' -E 'while True|while 1' x_intake cortex bluebubbles 2>/dev/null | head -40
grep -RIn --include='*.py' -E 'requests\.|httpx\.|openai|anthropic|claude' x_intake cortex bluebubbles 2>/dev/null | head -40
grep -RIn --include='*.py' -E 'timeout\s*=' x_intake cortex bluebubbles 2>/dev/null | head -40
```

Log tails (bounded):

```
find logs -name '*x_intake*' -o -name '*cortex*' -o -name '*bluebubbles*' 2>/dev/null | head -20
```

For each: `wc -l`, `tail -n 300`, `grep -Ein 'traceback|error|timeout|5\d\d|rate.?limit' ... | tail -n 60`.

### Phase 7 — Synthesize root cause and decide fix path

Write the audit report to:

```
docs/audits/bob-freezing-runtime-hangs-YYYY-MM-DD.md
```

Sections:

1. **Summary** — one paragraph, root cause in plain English.
2. **Evidence** — file:line references, log excerpts (redacted, no secrets),
   PIDs, queue depths, lock owners. Every claim cites a captured artifact.
3. **Contributing factors** — second-order issues (unbounded log, missing
   timeout, duplicate consumer, etc.) even if not the primary cause.
4. **Fix options** — at least two, with risk tier and blast radius.
5. **Recommended next step** — either (a) a named safe low-risk fix to
   apply now, or (b) a Phase 1 fix prompt path under `.cursor/prompts/`.

#### Safe low-risk fix gate

Only implement a fix inline if **all** of these are true:

- Change is ≤ ~40 lines total across ≤ 3 files.
- Change does not touch `launchd/`, Docker compose files, Redis config,
  auth, messaging send-paths, or anything under `secrets/`.
- Change adds a bounded timeout, fixes an obvious unbounded log/loop, or
  removes a stale-lock hazard with a safe guard — nothing behavioral.
- A unit or smoke test can be added or updated to cover it.
- Matt does not need to restart anything by hand for the fix to take
  effect (or the restart is via an already-documented, non-destructive
  path).

If any of those fail: **do not patch**. Instead, create
`.cursor/prompts/fix-bob-freezing-phase-1-<topic>.md` following
`AUTONOMOUS_PROMPT_STANDARD.md`, with a concrete, bounded fix plan and the
same Operating-mode guardrails as this prompt.

If the gate passes: implement, add/adjust tests, run them locally with
bounded timeouts, and include the test output in the verification file.

### Phase 8 — STATUS_REPORT update

Append a dated entry to `STATUS_REPORT.md` (do not rewrite existing
entries):

- Date (UTC), brief root cause, link to the audit doc, link to the
  verification artifact, whether a fix was applied or deferred to a Phase 1
  prompt, and the commit hash.

Keep the entry under ~25 lines.

### Phase 9 — Commit and push

Stage exactly these paths (adjust if a safe fix was applied):

- `.cursor/prompts/diagnose-bob-freezing-and-runtime-hangs.md` (this file,
  if edited during the run)
- `.cursor/prompts/fix-bob-freezing-phase-1-*.md` (if created)
- `docs/audits/bob-freezing-runtime-hangs-*.md`
- `docs/bob-freeze-diagnosis-prompt.md` (if edited)
- `ops/verification/<timestamp>-bob-freeze-diagnosis.txt`
- `STATUS_REPORT.md`
- Any safe-fix code + tests (only if gate passed)

Commit message:

```
ops(bob): diagnose runtime freeze — audit + verification (<root-cause-slug>)
```

Push to `main` only if the repo's standard workflow allows it; otherwise
open a PR following `docs/` conventions. Do **not** force-push. Do **not**
skip hooks.

## Guardrails

Medium-risk tier — in addition to the hard bans in Operating mode:

- Off-limits to edit in this run: `secrets/`, `.env*`, `setup/launchd/`,
  `docker-compose*.yml`, anything under `bluebubbles/` that sends messages,
  anything under `cortex/` that calls out to paid APIs. Read-only is fine.
- Off-limits commands: `launchctl bootout`, `launchctl unload`,
  `docker compose down`, `docker kill`, `redis-cli flushall`, `redis-cli
  flushdb`, `pkill`, `killall`, `kill -9` on any PID you did not start in
  this session.
- No outbound messages of any kind (see "Quiet mode" above).
- If a diagnostic command itself hangs, record it and move on — **do not**
  re-run it in a tight loop. A hanging diagnostic is itself a datapoint.
- If you can't finish within ~20 minutes of wall time, stop and report
  partial findings with what was captured so far.

## Final report

Write a single verification artifact to:

```
ops/verification/<YYYYMMDD-HHMMSS>-bob-freeze-diagnosis.txt
```

It must contain, in order:

1. The exact `hostname`, `pwd`, `git rev-parse HEAD`, start and end UTC
   timestamps of the run.
2. Phase 1–6 command outputs, each preceded by a `## Phase N — <name>`
   heading. Truncate long outputs to the first/last 200 lines with a
   `[truncated]` marker. Redact any line containing `secret`, `token`,
   `password`, `api_key`, `authorization` — replace the value with
   `[REDACTED]`.
3. Phase 7 synthesis: root cause, contributing factors, chosen fix path.
4. Phase 8 summary of what was written to `STATUS_REPORT.md`.
5. Phase 9 commit hash (fill in after the commit) and pushed-branch name.

Then in Cline's final chat response (separate from the file), return:

- **Root cause** (1–2 sentences).
- **Changed files** (bullet list of paths).
- **Tests / checks run** (bullet list with pass/fail).
- **Verification artifact path.**
- **Commit hash.**
- **Next Cline task** — if a Phase 1 fix prompt was generated, its path
  and a one-line "run this next" instruction; otherwise "no follow-up".
