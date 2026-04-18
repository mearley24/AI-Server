# Agent Verification Protocol

**Authoritative rule for any AI agent (Cline, Perplexity Computer, Claude, etc.) working in this repo.**

Matt's time is expensive and chat credits are expensive. Don't ask him to paste output. Ever.

---

## The rule

**Every diagnostic / verification / seed-run / deployment command block an agent hands Matt MUST end with tee-to-file + git commit + git push to `ops/verification/`, so another agent can pull the repo and read the result directly.**

No "paste this output back to me." No screenshots of terminal windows. No multi-step conversations where Matt copies long logs. One paste in, one commit out.

---

## Required tail for every command block

Every bash block an agent produces for Matt to run must end with this pattern (or its functional equivalent):

```bash
# at the very top of the block, before any real work:
OUT="ops/verification/$(date '+%Y%m%d-%H%M%S')-<topic>.txt"
mkdir -p "$(dirname "$OUT")"

{
  # ... all the real work (checks, rsyncs, curls, sqlite queries, etc.) ...
} > "$OUT" 2>&1

cd /Users/bob/AI-Server
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" add "$OUT"
git -c user.email="earleystream@gmail.com" -c user.name="Perplexity Computer" commit -m "ops: <topic> verification $(date '+%Y-%m-%d %H:%M')"
git push origin main 2>&1 | tail -3
echo "DONE. Tell the agent: pulled."
```

If the block runs on Bert (or any non-repo host), it must `scp` the log to Bob at `/Users/bob/AI-Server/ops/verification/<filename>` and trigger the commit+push via `ssh`. See the Meeting Audio seed-run block in `MEETING_INGEST_STEPS.md` for a worked example.

---

## Naming

- File: `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`
- Topic: dash-separated, lowercase, matches the task (e.g. `audio-pipeline`, `bb-handshake`, `polymarket-dns`, `seed-run`)
- Commit subject: `ops: <topic> verification YYYY-MM-DD HH:MM` (or `ops: <topic> seed-run log ...` for runs)

---

## Interactive-prompt hazards (MUST pre-empt)

A block that stops to ask Matt a question is as bad as asking him to paste output — both break the one-paste rule. Every command that can prompt MUST be pre-empted inside the block:

| Hazard | Pre-empt |
|---|---|
| `ssh` first-connect → "Are you sure you want to continue connecting (yes/no/[fingerprint])?" | Pin the host key non-interactively with `ssh-keyscan -t ed25519 <host> >> ~/.ssh/known_hosts` (guarded by `ssh-keygen -F`), then use `-o BatchMode=yes -o StrictHostKeyChecking=yes`. Never use `StrictHostKeyChecking=no` — it silently accepts MITM swaps. Only `BatchMode=yes` is OK — it fails loudly instead of prompting. |
| `sudo` password prompt | Passwordless sudo rule in `/etc/sudoers.d/` OR avoid sudo entirely (prefer user-scoped paths). |
| `git push` with no cached credentials | Use SSH remotes with pinned host key (github.com host key is stable, add to `known_hosts` once). HTTPS + token works only if the token is already in the keychain — never echo tokens inline. |
| `rm -i`, `cp -i`, `mv -i` aliases | Call binaries directly: `command rm ...` or `\rm ...`. |
| Python REPL / node REPL / interactive menus | Always pass scripts via file or `-c`, never drop into a shell. |
| `apt-get install` prompts | `apt-get install -y`. On macOS, `brew install` is non-interactive by default but `brew upgrade` can prompt for confirmations — pass `--force` or `HOMEBREW_NO_AUTO_UPDATE=1` as needed. |
| `ssh-copy-id` on first run | Same as ssh — pin known_hosts first. |
| `gh auth login` / `vault login` / any OAuth device flow | Never embed in a verification block — those require browser handoff. Do the auth in a separate, explicitly-user-driven step. |

**Rule of thumb:** if there's *any* command in your block that might have asked the user a question the first time *you* ran it in a fresh environment, pre-empt it. Test mentally: "If Matt pastes this on a clean machine, does it ever stop and wait for input?" If yes, patch the block.

---

## What goes in the log

Whatever the receiving agent needs to verify the task. Default sections:

1. Labelled banner with timestamp + topic
2. Every check or command under an `echo "=== N. NAME ==="` header so the receiving agent can grep
3. `set +e` or `|| true` on exploratory checks so one failure doesn't abort the whole dump
4. `set -euo pipefail` on destructive / seed-run blocks so failures don't silently continue
5. Full output of relevant commands — don't pre-truncate, the receiving agent will `head` / `tail` as needed

---

## What Matt does

1. Pastes the block once
2. Waits for `DONE. Tell the agent: pulled.` (or `seed run pushed`, etc.)
3. Replies with a single word: `pulled` (or `seed run pushed`)
4. The receiving agent clones the repo and reads the file

That's it. No copying output, no scrolling, no credit waste.

---

## When NOT to use this pattern

- **One-line facts** Matt already has on screen (e.g. "what's the BB server URL?") — just answer inline
- **Interactive / mutative flows** that require live decision points (e.g. `npm init`) — but these should be rare and explicitly flagged
- **Commands the receiving agent can run itself** via its own tools — in that case, don't ask Matt to run anything

---

## Autonomous Execution Policy

This protocol is paired with the "Standing Approval and Risk Tiers" section in `CLAUDE.md`. Together they define a single rule: **AI-Server's default operating mode is autonomous + repo-verified, not synchronous + paste-back.**

### Repo-first verification

- Every meaningful action produces a file at `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`.
- The file is committed and pushed **before** the agent ends its turn or hands off to another agent.
- No user paste-back loops. If you need to see something, go read the file yourself after pulling.

### Preflight repo sanity (required before task execution)

Before the Symphony Task Runner (`scripts/task_runner.py`) dispatches work, it invokes `ops/task_runner_preflight.py`. The preflight:

1. Runs `git status --porcelain` and detects unmerged/conflicted files.
2. Auto-resolves **only** whitelisted generated/state files using `git checkout --ours`:
   - `knowledge/markup_exports/.session_tracking.json`
   - `data/cortex/digests/**`
   - Any other path explicitly listed as `merge=ours` in `.gitattributes`.
3. Ensures `.gitattributes` contains the `merge=ours` rules for those patterns.
4. Writes a timestamped preflight report to `ops/verification/<stamp>-preflight.txt`.
5. Never silently swallows a non-whitelisted conflict. If something outside the whitelist is conflicted, the preflight reports it in detail and the runner is expected to stop processing tasks until a human (or a later agent) resolves it.
6. May commit and push its own safe changes — but only whitelisted auto-resolutions. It never touches user code.

The preflight is **advisory** to the runner: a preflight that finds nothing to do exits cleanly. A preflight that does heal something commits the fix. A preflight that finds an unsafe conflict writes a blocker report.

### Auto-follow-up verification

After any successful operational change — preflight auto-heal, task completion, service restart, schema migration — the agent (or its runner handler) writes a follow-up verification file describing what changed and proof that it took effect. Example follow-ups:

- After `preflight` self-heals `.session_tracking.json` → `ops/verification/<stamp>-preflight.txt` with the resolved list.
- After `task_runner_health.py` runs → `ops/verification/<stamp>-task-runner-health.txt`.
- After `task_audit.py` runs → written inline to stdout, but re-run with `--out <path>` to persist when investigating.

### Risk-tier model (matches CLAUDE.md)

| Tier | Examples | Approval |
|---|---|---|
| Low | diagnostics, verification, repo hygiene, preflight auto-heal, health checks, queue inspection, logging improvements, internal tooling | Standing — just do it and log |
| Medium | service restarts, non-secret env changes, launchd plist installs, non-financial SQLite migrations | No synchronous approval, but must write a verification file |
| High | data deletion, secrets rotation, money-moving actions, trading actions, customer-visible outbound comms, destructive infra changes, cross-repo/cross-host actions outside AI-Server's current boundary | Explicit approval required before execution |

Anything ambiguous defaults **down** one tier — treat it as higher risk until proven otherwise.

### Interactive-prompt hazards (always pre-empt)

The hazards table above remains binding. In addition:

- `ssh_and_run` tasks MUST pin host keys before running. The runner assumes `-o BatchMode=yes -o StrictHostKeyChecking=yes`.
- Never run `crontab -e`, `vim`, `nano`, or any TTY-driven tool from an agent. Commit plist/cron files to the repo and install them non-interactively.
- Shell scripts committed to `ops/task_runner/` and `ops/**` must be bounded (no `tail -f`, no `watch`, no long-running servers).

### Blocker reports (not paste-back)

If a task cannot proceed autonomously — because a secret is missing, a high-risk action is required, or an external dependency is down — the agent writes a blocker report to `ops/verification/<stamp>-blocker-<topic>.txt` naming exactly:

1. What was attempted
2. Why it could not complete
3. The precise change, credential, or approval that is needed
4. Whether it is Low / Medium / High risk

The blocker report is committed and pushed like any other verification artifact. **An agent does not ask Matt to paste terminal output back into chat.** If the blocker is informational, the report itself is the channel; a future agent (or Matt) can act on it.

### High-risk approval tokens

**Where:** `ops/approvals/*.approval` files (committed) and
`ops/approvals/AUTO_APPROVE_IDS.txt`.

**What counts as high-risk:** see the list in CLAUDE.md → "High risk" and
the tier table above. Any task whose JSON declares
`requires_approval: true` or `risk_tier: "high"` / `"critical"` (top
level OR inside `payload`) is flagged high-risk by
`ops/task_runner_gates.evaluate()`.

**How the gate works:**

1. Low / medium risk — no gate change; runs autonomously, writes a
   verification report as usual.
2. High-risk task with `dry_run: true` — allowed (no side effects).
3. High-risk task with `approval_token: "<tok>"` — allowed iff
   `ops/approvals/<tok>.approval` is a file already committed in the
   repo.
4. High-risk task with `approval_token == task_id` — allowed iff the
   task_id is listed on its own line in
   `ops/approvals/AUTO_APPROVE_IDS.txt` (pre-authorized recurring
   operations only).
5. Anything else — the runner writes
   `ops/verification/YYYYMMDD-HHMMSS-blocker-<task_id>.txt`, moves the
   task to `ops/work_queue/blocked/`, and returns without executing.

**How to request approval (as a future agent):**

1. Commit the task JSON to `ops/work_queue/pending/` with
   `requires_approval: true` (or `risk_tier: "high"`) and a chosen
   `approval_token`.
2. Write a short approval file:
   `printf 'approved by <name> at %s\n' "$(date -u +%FT%TZ)" > ops/approvals/<token>.approval`
3. Commit both in separate commits if you want the approval to land
   after review; commit them together if you are Matt.
4. On the next runner tick the gate sees the approval file and executes
   the task. The task result references the token in its first result
   line so the audit trail is one `git log`.

**How to revoke approval:** `git rm ops/approvals/<token>.approval &&
git commit && git push`. Subsequent ticks will block any task reusing
that token.

**Self-approval (`AUTO_APPROVE_IDS.txt`):** intended for routine,
scheduled, pre-authorized operations only. Add an entry only after
explicit human sign-off. Any new recurring high-risk workflow should
document its entry in a commit message referencing the policy review
that authorized it.

### Dry-run / staging lane

There is no separate staging AI-Server host. The runner supports an
in-place dry-run lane instead:

- Any task with `dry_run: true` at the top level or in `payload` runs
  through the normal dispatch path with `dry_run=true` propagated into
  the handler payload.
- Handlers that understand the flag (`run_cline_prompt`,
  `run_cline_campaign`) pass `--dry-run` to their launcher. The Cline
  launcher validates the prompt file and detects the CLI but does not
  invoke it. Handlers that don't support dry-run will still execute —
  only add `dry_run` to tasks whose side effects are bounded and safe.
- The task's result file records the gate decision, including whether
  approval was granted via `dry_run` vs a committed approval file.

**Promotion from dry-run to live:**

1. Queue the task with `dry_run: true` (and `requires_approval: true`
   if it is high-risk — the dry-run path allows it through without a
   token).
2. Read the resulting `ops/verification/<task_id>-result.txt` and the
   launcher log to confirm the planned actions look right.
3. Queue the same task again with `dry_run: false` and a committed
   `approval_token`. The runner executes it live on the next tick.

### Queue visibility

`ops/task_queue_status.py` prints a concise queue summary: pending
count by task_type and category, oldest pending task, pending tasks
older than a stale threshold, and the most recent completed / failed /
rejected / blocked tasks. Use `--json` for machine output and `--out
PATH` to persist into `ops/verification/`. `scripts/task-queue-stats.sh`
is a complementary shell snapshot focused on launchd status.

### Tooling

Repo-based tooling that implements this policy:

- `scripts/task_runner.py` — main autonomous executor (launchd `com.symphony.task-runner`)
- `ops/task_runner_preflight.py` — preflight self-heal + report
- `ops/task_runner_gates.py` — approval-token + dry-run gate evaluated on every task
- `ops/task_runner_health.py` — periodic health snapshot
- `ops/task_audit.py` — fast substring inspection of verification + queue state
- `ops/task_audit_index.py` — follow a task from task JSON → prompt files → verification artifacts → git commits
- `ops/task_queue_status.py` — queue-visibility summary with staleness flags
- `ops/tests/test_task_runner_gates.py` — smoke test for the gate policy
- `ops/learning_miner.py` — mines recent verification files and upserts rows in `ops/LESSONS_REGISTRY.md`
- `ops/learning_digest.py` — generates the owner-facing "teach Matt" digest under `ops/verification/`

### Learning loop (feeds the registry)

Verification reports are **input** to a lightweight self-learning loop. See
`ops/AUTONOMOUS_EXECUTION_PIPELINE.md` → "Learning and continuous
improvement" for the full spec.

Agent obligations when producing a verification file:

1. **Use miner-friendly section headings** for any non-obvious finding.
   Supported labels (case-insensitive, any Markdown heading level, or
   plain `===` / `---` banners): `Root cause`, `Cause`, `Fix applied`,
   `Minimal fix applied`, `Exact fix made`, `Remaining blocker`, `Next`,
   `Next action`, `Limitations`, `Known limitations`, `TODO`,
   `Follow up`, `Approval pattern`. The miner keys on these headings and
   captures the next few non-empty lines as the lesson summary.
2. **Add a lesson row when appropriate.** Any significant failure, fix,
   or workflow gap that could repeat should end up in
   `ops/LESSONS_REGISTRY.md`. The miner does this automatically for
   headings that match; if the finding is subtler, hand-edit the file.
3. **Promote stable lessons into guardrails.** If a lesson recurs across
   verification files or is clearly a safety/money concern, flip its
   `status` to `promoted_to_guardrail` and add a row to
   `ops/GUARDRAILS.md` with the next `G-NN` id pointing back at the
   lesson_id(s) via `derived_from_lessons`. Evidence references must
   remain non-empty — guardrail G-07 enforces this.
4. **Never paste-back.** If the learning loop surfaces something the
   owner needs to know, let the digest (`ops/learning_digest.py
   --write`) produce the report; do not ask Matt to read raw verification
   files.

Suggested operator cadence (manual for now; scheduling is tracked in the
pipeline doc's "Scheduling (recommended)" section):

```
python3 ops/learning_miner.py --days 7 --update
python3 ops/learning_digest.py --days 7 --write
```


---

## Rationale

Matt said it on 2026-04-17:

> "anything you ever need from me should be added to the code at the end and saved to the file so you can access it without me pasting a bunch of credit wasting slop"

Honor this. Every block. No exceptions.
