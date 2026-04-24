# Bob Docker Crash / Memory Diagnostic & Optimization — 2026-04-24

<!-- CLAUDE.md preamble: Read /CLAUDE.md first. Every shell command must
be zsh-safe: no heredocs, no inline interpreters, no interactive
editors, no long-running watch modes (no tail -f, no --watch, no npm
run dev). Use bounded commands: timeout, --lines N, --since, head/sed
-n ranges. -->

<!-- autonomy: start -->
Category: ops
Risk tier: high
Trigger:   manual
Status:    active
<!-- autonomy: end -->

**Title:** Bob Docker Crash / Memory Diagnostic & Optimization — bounded
read-only investigation of recurring Docker crashes on Bob (Mac Mini M4)
with a decision tree for safe optimization proposals. No runtime mutation
without an explicit `[NEEDS_MATT]` approval string in this chat turn.

**Owner:** Matt, on **Bob** (Mac Mini M4), via Cline. Not the task-runner,
not the self-improvement loop, not any auto-dispatcher. This prompt reads
live state and writes evidence only. Any change to Docker resources,
compose files, watchdog throttling, or launchd must go out as a separate
follow-up prompt proposed at the end of this run — never applied inline.

**Prerequisite reading (in order):**

1. `/CLAUDE.md`
2. `.clinerules`
3. `ops/AGENT_VERIFICATION_PROTOCOL.md`
4. `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`
5. `ops/runbooks/2026-04-24-bob-docker-crash-diagnostic.md` (human runbook
   that this prompt references — bounded command reference lives there)
6. `scripts/bob-watchdog.sh` — current Docker Desktop recovery path
7. `scripts/task_runner.py` — launchd-scheduled tick that touches docker
8. `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md` — prior
   freeze diagnosis; watchdog false-recovery and unbounded subprocess
   findings are directly relevant to the crash symptom
9. `STATUS_REPORT.md` — grep for `docker`, `watchdog`, `freeze`, `OOM`,
   `memory`, read the enclosing entries

---

## Goal

Produce a single bounded, read-only evidence capture on Bob that
classifies the current "Docker keeps crashing" symptom into one of the
defined categories (see Decision Tree) and emits a set of *proposals*
for safe optimization. Write the full report to
`ops/verification/YYYYMMDD-HHMMSS-bob-docker-crash-diagnostic.md`,
update `STATUS_REPORT.md` with a one-line pointer, commit and push.
Do not change Docker resources, restart containers, prune data, edit
`docker-compose.yml`, modify watchdog cadence, or touch launchd in this
run — every such change is deferred to an explicit follow-up prompt
that requires a `[NEEDS_MATT]` approval string.

## Non-goals

- **No `docker system prune`, no `docker volume rm`, no `docker image rm`.**
  Diagnostic only; prune is a separate, reviewed change.
- **No `docker restart <container>`, no `docker kill`, no `docker stop`.**
  Any hypothesis that a restart would help is captured as a proposal, not
  executed.
- **No Docker Desktop restart or quit.** The watchdog handles Docker
  Desktop recovery (`scripts/bob-watchdog.sh:260-295`); do not second-guess
  it during the diagnostic window.
- **No edits to `docker-compose.yml`, `.env`, `config/**`, or any compose
  override file.** Resource-limit / profile / logging-driver proposals go
  in the report as diffs-to-be-reviewed, not applied edits.
- **No `sudo`, no `launchctl bootstrap/bootout/kickstart` on any label,
  no `pkill`, no `kill -9`, no port changes, no firewall changes.**
- **No secret printing.** Do not `cat .env*`, do not echo values from
  `docker inspect` env arrays. If a container env is needed, redact
  values and capture only keys.
- **No `tail -f`, no `--follow`, no `watch`, no `--no-trunc` on logs
  without a line cap.** All log reads must be bounded by `--tail`,
  `--since`, `-n`, or `head`/`sed` range.
- **No external sends.** No Slack, no iMessage, no email, no webhook.
  The report is repo-local only.
- **No modification of `.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`, or anything
  harness-owned.** Preserve any pre-existing dirty working tree.
- **No autonomy metadata added to `ops/runbooks/**`** — runbooks are
  human-approved and the dispatcher must skip them.

## Context

Matt reported: *"something keeps crashing docker, it needs to be looked
into and see how we can optimize docker and Bob as it may be a memory
problem."* There is prior art in-repo we must build on rather than
re-derive:

- **Zombie Docker daemon** (`scripts/bob-watchdog.sh:128-133` comment,
  `ops/verification/…-watchdog-container-recovery-hotfix.txt`,
  2026-04-21): `docker info`/`docker ps` can return EOF with no exit,
  which the watchdog now bounds at 10 s per probe.
- **Watchdog false recovery** (historical): the recovery path re-opens
  `Docker.app`; on repeated triggers this masks a genuine crash loop as
  "healthy with churn."
- **Unbounded git subprocesses in `scripts/task_runner.py`** — documented
  in `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md`. While not
  directly Docker, the freeze symptom and the crash symptom can share
  the same root cause (flock held by a wedged tick → containers appear
  to stop getting health probes → watchdog races).
- **22 compose services** in `docker-compose.yml` (redis, vpn,
  polymarket-bot, proposals, email-monitor, voice-receptionist,
  calendar-agent, notification-hub, dtools-bridge, clawwork, openclaw,
  cortex, intel-feeds, x-intake, x-intake-lab, rsshub,
  x-alpha-collector, client-portal, cortex-autobuilder, plus networks
  and volumes). On a Mac Mini M4 with default Docker Desktop memory,
  concurrent steady-state usage + a periodic spike from any single
  container can tip the VM into swap and trigger OOM.

---

## Safety gates (hard)

`AUTO_APPROVE = true` **only for read-only evidence capture**. For any
proposal that would mutate state, the gate is `AUTO_APPROVE = false`
and the exact authorization string must be typed by Matt in this chat
turn before acting:

- `APPROVE: docker-desktop-resources` — allow a follow-up prompt to
  propose (not apply) new Docker Desktop memory / CPU / swap / disk
  limits based on the evidence.
- `APPROVE: compose-memory-limits` — allow a follow-up prompt to draft
  per-service `deploy.resources.limits.memory` / `mem_limit` entries.
- `APPROVE: watchdog-throttle` — allow a follow-up prompt to propose a
  reduced probe cadence or a cooldown bump in `scripts/bob-watchdog.sh`.
- `APPROVE: log-rotation` — allow a follow-up prompt to add
  `logging.driver: json-file` + `max-size` / `max-file` to compose.
- `APPROVE: container-decommission <name>` — allow a follow-up prompt
  to remove a specific container from compose (only after Matt names
  the service explicitly).

In this run, none of the above run. If the evidence is conclusive, the
prompt ends by listing which approvals would unblock which follow-up.

### Stop conditions (hard)

Bail out of the diagnostic and write a partial report if any of these
fire:

1. **Docker Desktop unavailable** — `docker info` returns a connection
   error twice within 30 s. Capture the error, do not attempt recovery.
2. **Memory pressure critical** — `memory_pressure` (if available)
   reports `critical` or `vm_stat` shows free pages < 10,000 on
   consecutive samples. Stop, do not run further docker probes.
3. **Suspected data corruption** — any `docker inspect` returns a
   parse error that references a volume or on-disk store; or
   `redis-cli` (if reachable) returns `LOADING`. Stop and escalate.
4. **Repeated crash loop** — `docker ps -a --format '{{.RestartCount}}'`
   shows any single container with RestartCount ≥ 10 inside the
   evidence window. Capture the name, stop further probes against
   that container.
5. **Any command requires sudo / admin** — immediately stop and write
   `STOP: sudo required for <cmd>` into the report.
6. **Host is not Bob** — `hostname` must contain `bob` (case-insensitive)
   or the prompt exits at Phase 0 with a no-op.

---

## Preconditions

Run these first. Any failure → abort, write partial report with
`precheck_failed: <which>`.

1. Host identity:
   - `hostname` must match `*bob*` (case-insensitive).
   - `pwd` must end in `AI-Server`.
   - `git rev-parse --abbrev-ref HEAD` must be `main`.
   - `git status --short | wc -l` — note count; unrelated dirty files
     are preserved, not reverted.

2. Repo pointers:
   - `test -f docker-compose.yml && echo ok-compose`
   - `test -f scripts/bob-watchdog.sh && echo ok-watchdog`
   - `test -f scripts/task_runner.py && echo ok-runner`
   - `test -d ops/verification && echo ok-ver`

3. Tool availability (record which are present):
   - `command -v docker && docker --version`
   - `command -v vm_stat && echo ok-vm_stat`
   - `command -v memory_pressure && echo ok-mp` (optional; not on every
     macOS; absence is not fatal)
   - `command -v top && echo ok-top`
   - `command -v log && echo ok-log` (macOS `log show`)

---

## Operating mode

- `AUTO_APPROVE = true` for phases 0–5 (read-only evidence + proposal draft).
- `AUTO_APPROVE = false` for anything that would mutate state. Any such
  step is not executed in this prompt — it is written as a proposal to
  the report and deferred to a follow-up prompt gated on the approval
  strings above.
- Bounded commands only. Every `docker`, `log`, `tail`, `ps`, and
  subprocess call must carry an explicit bound:
  - `timeout 10 docker …` for any daemon-touching call.
  - `docker logs --tail 200 <name>` never unbounded.
  - `docker stats --no-stream` (never streaming).
  - `log show --last 15m --predicate '…' --style compact` (macOS log).
  - `sed -n '1,200p'` or `head -n 200` for file reads.
- Evidence-first: every phase writes its raw summary to a temp file in
  `/tmp` then appends a redacted, structured block to the final report.
- Tee every capture: `cmd 2>&1 | tee -a /tmp/bob-docker-diag-<stamp>.raw`.
- Never expand `$<VAR>` from `.env` into logs.

---

## Step plan

Replace `<stamp>` below with `$(date -u +%Y%m%d-%H%M%S)`. The report path
is `ops/verification/<stamp>-bob-docker-crash-diagnostic.md`.

### Phase 0 — Host + repo sanity

Write a header block to the report: timestamp (UTC), `hostname`,
`uname -a` (one line), `sw_vers` (if macOS), `git rev-parse HEAD`, the
`git status --short` line count, and the tool-availability matrix
from Preconditions §3.

### Phase 1 — Docker Desktop / daemon status

Bounded probes only. Each wrapped in `timeout 10`:

1. `timeout 10 docker info --format '{{.ServerVersion}} / {{.OperatingSystem}} / mem={{.MemTotal}} / ncpu={{.NCPU}}'`
2. `timeout 10 docker version --format '{{.Server.Version}} / {{.Client.Version}}'`
3. `timeout 10 docker system df` (no `-v`; volumes list is captured
   separately, bounded).
4. `pgrep -fl 'Docker Desktop' | head -n 5`
5. `pgrep -fl 'com.docker.backend' | head -n 5`

Record exit codes. If any `timeout` returns 124, mark the daemon as
`zombie-suspect` and skip phases that need the daemon (§2, §3, §6).

### Phase 2 — Container inventory + restart counts

1. `timeout 10 docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'`
2. `timeout 10 docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.RestartCount}}'`
3. For any container with `RestartCount >= 5`, record the name and
   fetch **bounded** logs: `timeout 10 docker logs --tail 200 <name>`.
   Do **not** follow; do **not** widen the window.
4. `timeout 10 docker ps --filter health=unhealthy --format '{{.Names}}'`.

If **any** container has `RestartCount >= 10`, invoke the crash-loop
stop condition (§Safety gates): capture that container's name and logs
once, then exit the phase.

### Phase 3 — Resource snapshot (containers)

1. `timeout 15 docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}'`
2. `timeout 10 docker system df`
3. Top 5 containers by MemPerc (derive from §1 output via `sort -k4`
   and `head -n 5`).

### Phase 4 — Host memory / CPU snapshot

1. `vm_stat | head -n 20`
2. `top -l 1 -n 10 -o mem | head -n 25`
3. `memory_pressure` if available: `timeout 5 memory_pressure | head -n 10`
   (absence of binary → record `not-available` and continue).
4. `df -h /` and `df -h /Users/bob/AI-Server` — disk pressure check.
5. `uptime` — load average.

If `memory_pressure` reports `critical` or `vm_stat` free pages drop
below 10,000, fire the memory-pressure stop condition.

### Phase 5 — Crash / OOM hints from logs

All bounded. **None of these may use `-f` or `--follow`.**

1. Docker Desktop log window (macOS):
   `timeout 20 log show --last 60m --predicate 'subsystem contains "com.docker"' --style compact | tail -n 400`
2. Kernel OOM hints:
   `timeout 20 log show --last 6h --predicate 'eventMessage contains "memorystatus" or eventMessage contains "jetsam" or eventMessage contains "lowmem" or eventMessage contains "OOM"' --style compact | tail -n 200`
3. Watchdog log tail (repo-local, safe):
   `tail -n 400 data/task_runner/bob-watchdog.log 2>/dev/null || tail -n 400 /usr/local/var/log/bob-watchdog.log 2>/dev/null`
   Count distinct `docker_recover_failed` and `"Docker ready after"`
   lines inside a 2 h window — watchdog false-recovery signal if the
   ratio is churning.
4. Task runner recent ticks:
   `tail -n 200 data/task_runner/heartbeat.log 2>/dev/null` (if present)
5. Compose recent container logs per service (cap at N=6 services by
   highest MemPerc from Phase 3): `timeout 10 docker logs --tail 100
   --since 1h <name>` — scan for `Killed`, `OOMKilled`, `out of memory`,
   `ENOMEM`, `signal=9`, `exited with code 137`.

### Phase 6 — Compose config inspection (read-only)

1. `timeout 10 docker compose config --services` — list services as
   Docker sees them, sorted.
2. For each service, check for a resource limit declaration without
   *modifying* the file: `grep -nE '(mem_limit|memswap_limit|deploy:|resources:|limits:|cpus:)' docker-compose.yml`
3. Check logging-driver declarations:
   `grep -nE '(logging:|driver:|max-size|max-file)' docker-compose.yml`
4. Check healthchecks:
   `grep -cE '^\s*healthcheck:' docker-compose.yml`

This phase *reads* `docker-compose.yml` only. No edit, no write.

### Phase 7 — Classification (Decision Tree)

Write a `## Classification` section to the report. Assign **exactly
one** primary category, plus any secondary flags:

- **A. Memory pressure (host-level)** — macOS shows critical memory
  pressure, OOM/jetsam hits in `log show`, top container MemPerc
  summed > 70% of allocated Docker VM memory. Implication: Docker VM
  underallocated or steady-state demand exceeds headroom.
- **B. Memory pressure (container-level)** — one container dominates
  MemPerc (>60% alone) or exhibits `exited with code 137` / `OOMKilled`.
  Implication: that service needs a memory limit or a leak fix.
- **C. Disk pressure** — `docker system df` shows Reclaimable > 70% of
  total, or `df -h` on the Docker data root shows >90% used.
  Implication: log volume growth or image churn.
- **D. Container restart loop** — a single container with
  `RestartCount >= 5` and repeated crash signatures in its logs.
  Implication: bad image/config/runtime dependency — fix root cause,
  don't keep restarting.
- **E. Docker Desktop crash (daemon-level)** — `docker info`/`docker ps`
  returns EOF / 124 / connection-refused intermittently; Docker Desktop
  process disappears from `pgrep`; Docker.app PID churn in watchdog log.
  Implication: desktop-level issue — resource tuning or a Docker Desktop
  version bump, not a per-container fix.
- **F. Watchdog false recovery** — watchdog log shows frequent
  `Docker ready after Ns` cycles without a correlated user-visible
  restart, masking either (A) or (E). Implication: cadence needs
  throttling or recovery logic needs a hysteresis.
- **G. Compose misconfig** — a service declares no resource limit and
  Phase 3 shows it dominating the host. Implication: declarative fix
  in `docker-compose.yml`.
- **H. Unknown** — evidence inconclusive. Explicitly list what would
  disambiguate (e.g., a longer `log show` window, a single-container
  stats sample over 10 minutes — which is itself a follow-up prompt).

### Phase 8 — Safe recommendations (proposals only)

For whichever category fires, draft recommendations into the report.
**Do not apply any of these in this run.** Each recommendation must
name the approval string required.

| Category | Proposal | Approval string |
|---|---|---|
| A | Raise Docker Desktop memory from current to `current + 4 GB` ceiling (never > 75% of host RAM); document swap setting | `APPROVE: docker-desktop-resources` |
| B | Add `mem_limit` (v2) or `deploy.resources.limits.memory` (v3) for the offending service | `APPROVE: compose-memory-limits` |
| C | Add `logging.driver: json-file` with `max-size: 10m` / `max-file: 3` per service; propose (not execute) `docker system prune` one-shot in a separate reviewed prompt | `APPROVE: log-rotation` |
| D | Inspect service entrypoint + dependencies; propose a fix prompt targeting that container only | case-by-case |
| E | Propose Docker Desktop version pin / update check; propose watchdog cooldown bump on Docker restarts | `APPROVE: docker-desktop-resources` + `APPROVE: watchdog-throttle` |
| F | Increase watchdog Docker-probe cooldown from 180 s; add hysteresis so a successful probe must be seen twice before clearing | `APPROVE: watchdog-throttle` |
| G | Draft per-service compose deltas for review | `APPROVE: compose-memory-limits` |
| H | Propose a longer bounded capture (e.g., six 60-minute `docker stats --no-stream` snapshots across a day via a separate scheduled prompt) | none (read-only) |

Additional standing recommendations (always in report):

- **Optional / decommissioned services** — list any compose service in
  `docker ps -a` that has `Exited`/`Created` state and has not run in
  the last 24 h (derive from `log show` or the container `Status`
  field). Do **not** remove them; propose decommissioning with
  `APPROVE: container-decommission <name>`.
- **Dashboard containers** — if `cortex-autobuilder` or any `*-lab*`
  container is present and idle, flag for review. Do not remove.

### Phase 9 — Verification + receipt

1. Confirm the report file exists and is non-empty:
   `test -s ops/verification/<stamp>-bob-docker-crash-diagnostic.md && echo ok-report`
2. Confirm referenced paths in the report are real:
   `grep -oE 'ops/[^ )]+|scripts/[^ )]+|docs/[^ )]+|data/[^ )]+' ops/verification/<stamp>-bob-docker-crash-diagnostic.md | sort -u | while read p; do test -e "$p" && echo ok-$p || echo missing-$p; done | head -n 60`
3. Add a one-line pointer to `STATUS_REPORT.md` (append to the most
   recent section, don't rewrite the file): service symptom summary +
   report path + `[FOLLOWUP]` tag for any proposal-only recommendation.
4. Write `ops/verification/<stamp>-bob-docker-crash-diagnostic-receipt.txt`
   with: report path, total lines, classification, approval strings
   that would unblock follow-up prompts, and the line-count before/after
   of `STATUS_REPORT.md`.
5. `git add ops/verification/<stamp>-bob-docker-crash-diagnostic.md
   ops/verification/<stamp>-bob-docker-crash-diagnostic-receipt.txt
   STATUS_REPORT.md`
6. `git diff --cached --stat`
7. `git commit -m "ops(bob-docker-diag): <stamp> — classification=<X>"`
8. `git push origin main`

### Phase 10 — Post-run verification (bounded)

Re-run **only** the cheap read-only checks to confirm no regression in
watchdog cadence or compose state as a result of the diagnostic run:

- `tail -n 50 $(ls -1 ops/verification/*bob-docker-crash-diagnostic*.md | tail -n 1)`
- `grep -c '\[watchdog\]' data/task_runner/bob-watchdog.log 2>/dev/null`
- `timeout 10 docker ps --format '{{.Names}}\t{{.Status}}' | wc -l`
- `git log --oneline -1`

If any of the above differs materially from the Phase 1/2 snapshot,
append a `## Post-run delta` block to the report and commit an
amendment *as a new commit* (never `--amend`).

---

## Tests / verification

This prompt has no code changes, so the verification contract is:

- The report file exists, is non-empty, contains each of:
  `## Phase 0`, `## Phase 1`, …, `## Phase 9`, `## Classification`,
  `## Safe recommendations`.
- `STATUS_REPORT.md` has a single-line pointer added, not a section
  rewrite.
- `git diff --cached --stat` shows only the two verification files and
  `STATUS_REPORT.md` in the staged set.
- `git log --oneline -1` shows the new commit.
- `git push origin main` succeeds (or the prompt stops with
  `push-failed: <reason>` and returns the report path anyway).

---

## Guardrails (restated, high risk tier)

- No `docker system prune`, no `docker volume rm`, no `docker image rm`.
- No `docker restart`, no `docker stop`, no `docker kill`.
- No `sudo`, no `launchctl bootstrap/bootout/kickstart`, no `pkill`.
- No `tail -f`, no `--follow`, no `watch`, no `npm run dev`.
- No heredocs, no inline interpreters (`python3 <<EOF`), no `crontab -e`.
- No edits to `docker-compose.yml`, `.env*`, `config/**`, `scripts/**`
  (including `bob-watchdog.sh` and `task_runner.py`) in this run.
- No edits to `.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`.
- No autonomy metadata added to `ops/runbooks/**`.
- No external sends (Slack, iMessage, email, webhook).
- No secret printing; redact env values if they appear anywhere.
- All log reads bounded (`--tail N`, `--since T`, `head`, `sed -n`).

---

## Final report

Write `ops/verification/<stamp>-bob-docker-crash-diagnostic.md`
containing, in order:

1. `# Bob Docker Crash / Memory Diagnostic — <stamp>`
2. `## Phase 0` … `## Phase 9` with the captured bounded output,
   redacted of any env values.
3. `## Classification` — one of A–H plus any secondary flags.
4. `## Safe recommendations` — table from Phase 8, with the approval
   string each one needs.
5. `## Follow-up prompt candidates` — a bullet per approved path:
   name the future prompt file (e.g.
   `.cursor/prompts/2026-04-25-cline-docker-compose-memory-limits.md`)
   and the approval string that would unblock it.
6. `## Stop conditions fired` — list or `none`.
7. `## Commit` — hash from step 7.

Write the receipt
`ops/verification/<stamp>-bob-docker-crash-diagnostic-receipt.txt`
containing: timestamp, report path, classification, approval strings
listed, and `STATUS_REPORT.md` before/after line counts.

Commit and push to `origin/main`. Return to the operator: report path,
classification, approval strings that would unblock follow-ups, and
commit hash.
