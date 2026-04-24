# Bob Docker Crash / Memory Diagnostic — Human Runbook

**Status:** `DONE` — diagnostic ran 2026-04-24 09:12 MDT
(receipt `ops/verification/20260424-151202-bob-docker-crash-diagnostic.md`);
APPROVE ALL applied 09:25 MDT (commit `275f2a83`, STATUS_REPORT.md L39–L57).
Remaining follow-ups — restart Docker Desktop, deploy watchdog to system
path, reinstall Docker Desktop to `/Applications/` — tracked as individual
`[NEEDS_MATT]` / `[FOLLOWUP]` bullets, not by re-running this runbook.
Companion prompt: `.cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md`.

This file is a human-approved runbook, not an autonomous prompt.
Do **not** add `<!-- autonomy: start -->` metadata. Do not copy into
`.cursor/prompts/`. Dispatchers under `ops/cline-run-*.sh` must **skip**
anything in `ops/runbooks/`.

**Owner:** Matt (or a human operator with local shell access to Bob).
**Host:** Bob (Mac Mini M4), `~/AI-Server` checkout of `origin/main`.
**Scope anchor:** user report 2026-04-24 — "something keeps crashing
docker, it needs to be looked into and see how we can optimize docker
and Bob as it may be a memory problem."

---

## Why this runbook exists

Matt flagged recurring Docker crashes on Bob and asked whether the root
cause is memory pressure. The repo already contains:

- `scripts/bob-watchdog.sh` — Docker Desktop crash recovery with bounded
  10 s probes (`scripts/bob-watchdog.sh:234-259`) and a 120 s recovery
  window (`scripts/bob-watchdog.sh:260-295`).
- `docs/audits/bob-freezing-runtime-hangs-2026-04-23.md` — prior
  diagnosis that identified unbounded `git` subprocesses in
  `scripts/task_runner.py` as a wedge amplifier, and flagged the
  watchdog's own Docker probe as an extension risk.
- `docs/bob-freeze-diagnosis-prompt.md` — the freeze-diagnosis runbook
  (adjacent symptom; similar posture — bounded, read-only, no
  restarts).

We intentionally do **not** run Docker Desktop restarts, container
restarts, or `docker system prune` from the diagnostic prompt. Those
changes require explicit approval and live in follow-up prompts.

This runbook walks a human through invoking the diagnostic prompt on
Bob and interpreting the output. It is the "how to kick it off"
companion — the prompt itself is the spec.

---

## Prerequisites

- You are **on Bob**. `hostname` contains `bob`.
- `~/AI-Server` is clean on `origin/main` (or the only dirty files are
  the harness-owned set: `.claude/**`, `.mcp.json`, `CLAUDE.md`).
- Cursor / Cline is installed and can open this repo.
- Docker Desktop is at least reachable (`docker version` returns
  *something*, even if the daemon is degraded). If Docker Desktop is
  fully offline, the prompt will still capture that fact as evidence
  — invoke it anyway.

## How to run

### Primary path — Cline "New Task" on Bob

1. Open Cursor / Cline **on Bob** in the `AI-Server` repo.
2. New Task → paste exactly:

   ```
   Run .cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md.
   Follow every step. Read-only evidence phases run under AUTO_APPROVE=true.
   Any mutation requires the approval strings listed in §Safety gates.
   Do not restart Docker. Do not restart containers. Do not prune.
   Do not touch secrets. Commit and push at the end.
   Return the final report fields listed in the prompt.
   ```

3. Let it run. Expected wall time: **10–25 minutes** depending on how
   much of `log show` gets pulled.
4. When it finishes, read the last message — it returns classification
   (A–H), changed files, verification path, commit hash, and which
   approval strings would unblock follow-up prompts.

### Fallback — headless dispatch

If Cline on Bob is itself wedged (freeze symptom overlapping):

```
ops/cline-run-prompt.sh .cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md
```

Both paths must land on Bob. The prompt's first bounded check is
`hostname` — it will bail on anything else.

---

## What the prompt produces

- `ops/verification/<stamp>-bob-docker-crash-diagnostic.md` — the full
  evidence report: phases 0–9, classification, safe recommendations,
  follow-up prompt candidates, stop conditions fired, commit hash.
- `ops/verification/<stamp>-bob-docker-crash-diagnostic-receipt.txt` —
  short receipt for audit: report path, classification, approval
  strings, STATUS_REPORT line-count delta.
- `STATUS_REPORT.md` — single-line pointer appended to the latest
  section (no rewrite).
- A git commit on `main` (and a push) with the two new files and the
  STATUS_REPORT pointer.

---

## How to read the result

The prompt classifies the symptom into **exactly one** primary
category (see prompt §Phase 7). Act based on the category:

| Category | What it means | Next step |
|---|---|---|
| **A. Host memory pressure** | macOS OOM/jetsam hits, Docker VM at or near allocation ceiling | Reply `APPROVE: docker-desktop-resources` — get a follow-up prompt that *proposes* (not applies) new Docker Desktop memory/swap/CPU limits |
| **B. Container memory pressure** | One container dominates (`OOMKilled`, exit 137, MemPerc > 60%) | Reply `APPROVE: compose-memory-limits` for that service — get a follow-up prompt drafting `mem_limit` / `deploy.resources.limits.memory` |
| **C. Disk pressure** | `docker system df` reclaimable > 70% or disk > 90% used | Reply `APPROVE: log-rotation` — get a follow-up adding `logging` driver + `max-size`/`max-file`; a separate reviewed `docker system prune` prompt can follow if needed |
| **D. Restart loop** | One container `RestartCount >= 5` with repeat crash signatures | Fix the root cause in that service — a targeted follow-up prompt names the container and reviews its entrypoint/config |
| **E. Docker Desktop crash** | Daemon EOF / `docker info` 124 / Docker.app PID churn | Reply `APPROVE: docker-desktop-resources` + `APPROVE: watchdog-throttle` — combined follow-up |
| **F. Watchdog false recovery** | Watchdog "Docker ready after Ns" cycles without a real user-visible restart | Reply `APPROVE: watchdog-throttle` — follow-up proposes cooldown bump + hysteresis |
| **G. Compose misconfig** | Service without a resource limit dominates the host | Reply `APPROVE: compose-memory-limits` — follow-up drafts a per-service delta |
| **H. Unknown** | Evidence inconclusive | The report names what would disambiguate; usually a longer/scheduled capture |

You do **not** approve anything by reading this runbook — approval
strings are typed to the *follow-up* prompt, not this one.

---

## Things the prompt intentionally does **not** do

- Restart Docker Desktop. (The watchdog already handles that; second-
  guessing during a diagnostic window can mask evidence.)
- Restart, stop, or kill containers.
- Prune anything — images, volumes, networks, build cache.
- Edit `docker-compose.yml`, `.env*`, `config/**`, `scripts/**`,
  `setup/launchd/**`, or any launchd plist.
- Touch harness-owned files (`.claude/**`, `.mcp.json`, `CLAUDE.md`,
  `.cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md`).
- Tail logs with `-f` / `--follow`, run `watch`, or leave any long-
  running process behind.
- Send anything externally (iMessage, Slack, email, webhook).
- Print secrets — `.env*` files are never read; `docker inspect` env
  arrays are redacted to keys only.

If you find yourself needing any of the above to make progress, stop
and spawn a separate reviewed prompt — never stretch this one.

---

## If the diagnostic itself hangs

The prompt uses bounded commands (`timeout 10`, `--tail`, `--since`,
`sed -n`) so it should always finish or bail cleanly. If it genuinely
hangs:

1. Cancel the task in Cline.
2. Read the partial
   `ops/verification/<stamp>-bob-docker-crash-diagnostic.md` — the
   last captured phase names the probe that stalled.
3. That hanging command *is* the crash signal — treat it as a finding.
   (E.g. a hanging `docker info` is itself evidence for category E.)
4. Do **not** rerun the prompt in a tight loop. Read the partial
   artifact first.

## Do not

- Do not run this on any machine other than Bob.
- Do not hand-edit the prompt mid-run to remove bounds — the bounds
  are what keep it safe on a crashing machine.
- Do not re-run after a watchdog-triggered Docker restart until the
  watchdog's own log shows a stable window of ≥ 5 minutes; otherwise
  the evidence will straddle a recovery boundary and classification
  will be muddied.
