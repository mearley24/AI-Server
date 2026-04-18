# Autonomous Execution Pipeline — Symphony AI-Server

**Audience:** Cline, Claude Code, Perplexity Computer, and any other AI agent
operating inside `AI-Server`. This is the authoritative spec for how the
system runs itself without the owner in the loop.

Read `CLAUDE.md` (standing approval + hard rules) and
`ops/AGENT_VERIFICATION_PROTOCOL.md` (verification + repo-first proof) first.
This document wires them together and describes how the system **learns from
its own runs**.

---

## 1. Pipeline stages

```
[ queue ]   ->   [ preflight ]   ->   [ gate ]   ->   [ runner ]   ->   [ verify ]   ->   [ learn ]
 pending         heal whitelist       approval       handlers          write proof       update
 tasks           state files          token /        (cline, ssh,      to ops/           lessons /
                 + .gitattributes     dry_run        scripts, etc.)    verification/     guardrails
                                                                                         + digest
```

Concrete implementations:

| Stage | Files | What it does |
|---|---|---|
| Queue | `ops/work_queue/{pending,completed,failed,rejected,blocked}/`, `ops/work_queue/TASK_SCHEMA.md` | Signed JSON task files. `pending/` is the inbox. |
| Preflight | `ops/task_runner_preflight.py` | Heals whitelisted state-file conflicts (`data/cortex/digests/**`, `.session_tracking.json`), enforces `.gitattributes merge=ours` rules, commits + pushes safe changes. Writes a report only when it did real work. |
| Gate | `ops/task_runner_gates.py`, `ops/approvals/*.approval`, `ops/approvals/AUTO_APPROVE_IDS.txt` | Blocks high-risk tasks without a committed approval token. Passes dry-runs through unconditionally. |
| Runner | `scripts/task_runner.py` (launchd: `com.symphony.task-runner`) | Dispatches handlers: `run_cline_prompt`, `run_cline_campaign`, `run_script`, `ssh_and_run`, `verify_dump`. Writes `ops/verification/<task_id>-result.txt`. |
| Verify | `ops/verification/YYYYMMDD-HHMMSS-*.txt`, `scripts/verify-deploy.sh`, `scripts/verification-index.sh` | Every meaningful action commits a timestamped report to this directory. |
| Learn | `ops/LESSONS_REGISTRY.md`, `ops/GUARDRAILS.md`, `ops/learning_miner.py`, `ops/learning_digest.py` | Parses recent verification files, extracts patterns, promotes stable lessons to guardrails, produces a weekly digest for the owner. |

## 2. Risk tiers (mirror of CLAUDE.md)

| Tier | Example | Gate |
|---|---|---|
| Low | read-only diagnostics, verification writes, repo hygiene | auto-approved, just log |
| Medium | service restarts, non-secret env changes, launchd plist installs | auto-approved, must log |
| High | data deletion, secrets rotation, money-moving, customer-visible comms | `ops/approvals/<token>.approval` **required** |

The gate module's unit tests live at `ops/tests/test_task_runner_gates.py`.

## 3. Verification contract

Every agent action produces a file at
`ops/verification/YYYYMMDD-HHMMSS-<topic>.txt` (or `.md` for digests) that is
committed and pushed before the agent ends its turn. No paste-backs. Ever.
See `ops/AGENT_VERIFICATION_PROTOCOL.md` for the exact shell scaffold and
hazards list.

## 4. Learning and continuous improvement

This is the newest loop in the pipeline. It turns the stream of verification
artifacts into a durable, machine-readable memory, and makes sure the owner
sees the important patterns without reading raw logs.

```
            +-----------------+
            | observe          |   ops/verification/*   (every meaningful action)
            | (verify stage)   |
            +---------+--------+
                      |
                      v
            +-----------------+
            | extract lessons  |   ops/learning_miner.py
            | (heuristic mine) |   -> upsert rows in ops/LESSONS_REGISTRY.md
            +---------+--------+
                      |
                      v
            +-----------------+
            | promote to rules |   ops/GUARDRAILS.md
            | (agent curation) |   -> lesson.status = promoted_to_guardrail
            +---------+--------+
                      |
                      v
            +-----------------+
            | teach Matt       |   ops/learning_digest.py
            | (weekly digest)  |   -> ops/verification/*-learning-digest.md
            +---------+--------+
                      |
                      v
            +-----------------+
            | feed backlog     |   (future: auto-create remediation tasks
            | (future loop)    |    for lessons whose status is "new" >7 days)
            +-----------------+
```

### 4.1 Observe

Stage output: `ops/verification/*` files. The format conventions (explicit
`Root cause`, `Fix applied`, `Remaining blocker`, `Next`, `Limitations` /
`Known limitations`, `TODO` headings) are what the miner looks for. When you
write a new verification file, use those headings so the miner can learn from
it.

### 4.2 Extract lessons — `ops/learning_miner.py`

```
python3 ops/learning_miner.py --days 7              # dry-run summary
python3 ops/learning_miner.py --days 7 --update     # write to the registry
python3 ops/learning_miner.py --days 7 --update --out ops/verification/<stamp>-miner.txt
```

Behavior:

- Scans non-preflight `ops/verification/` files whose mtime is within the
  window.
- Parses headings matching the patterns listed above and captures the next
  few non-empty lines as the lesson summary.
- Computes a stable `lesson_id = "L-" + sha1(type+summary)[:8]`, so re-runs
  update `last_seen_at` + `evidence_refs` instead of creating duplicates.
- Preserves hand-edited `status` and `impact_hint` columns.
- Limits `evidence_refs` to the 6 most recent source files per lesson.

Where it writes: the Markdown table between
`<!-- LESSONS_TABLE_START -->` / `<!-- LESSONS_TABLE_END -->` in
`ops/LESSONS_REGISTRY.md`. Everything outside those markers is agent-editable
prose.

### 4.3 Promote to guardrails

Manual + structured. When a lesson has been observed across multiple
verification files (or is clearly a safety issue), an agent:

1. Opens `ops/LESSONS_REGISTRY.md` and flips that lesson's `status` to
   `promoted_to_guardrail`.
2. Adds a row to `ops/GUARDRAILS.md` with the next `G-NN` id and
   `derived_from_lessons = <lesson_id>`.
3. Updates the relevant enforcement code path (if any) — preflight, gate,
   prompt, or policy doc.
4. Commits both files in the same change.

Bootstrap guardrails (`G-01` through `G-07`) were policy-born (`manual`
source). Future guardrails should be lesson-backed whenever possible.

### 4.4 Teach Matt — `ops/learning_digest.py`

```
python3 ops/learning_digest.py --days 7              # stdout only
python3 ops/learning_digest.py --days 7 --write      # write to ops/verification/<stamp>-learning-digest.md
python3 ops/learning_digest.py --days 1 --write      # daily brief
```

The digest pulls new / updated lessons in the window, active guardrails, the
list of recent verification reports, and specifically flags any report
containing owner-action keywords (`[Matt]`, `Needs Matt`, `Blocker`,
`Awaiting Matt`, `Requires approval`, `Fund wallet`, `KRAKEN_SECRET`). Output
is plain English, no LLM, no fluff.

### 4.5 Scheduling (recommended)

- **Weekly digest**: queue a `run_script` task every Sunday 09:00 MT that
  executes `python3 ops/learning_miner.py --days 7 --update` followed by
  `python3 ops/learning_digest.py --days 7 --write`. Low-risk. Committed
  output lands under `ops/verification/`.
- **Daily miner (optional)**: queue the miner alone once a day so
  `last_seen_at` stays current without a full digest.

No scheduler has been wired in this pass. Entry points are the two scripts
above; the task runner already knows how to execute them via the
`run_script` handler.

### 4.6 Feed backlog (future)

Not yet built. The intended next iteration:

- For every lesson with `status="new"` whose `last_seen_at` is older than
  7 days and `impact_hint != "unknown"`, queue a low-risk `verify_dump` task
  asking an agent to either fix, promote, or mark `superseded`.
- For every lesson that has been superseded by a guardrail, auto-link the
  guardrail id into the digest's "Guardrails promoted" section.

## 5. Interfaces and file inventory

| Concern | Path | Role |
|---|---|---|
| Task runner | `scripts/task_runner.py` | Event loop + handler dispatch |
| Preflight | `ops/task_runner_preflight.py` | State-file self-heal |
| Gate | `ops/task_runner_gates.py` | Approval + dry-run policy |
| Health | `ops/task_runner_health.py` | Heartbeat / queue / preflight freshness |
| Queue stats | `ops/task_queue_status.py` | Pending / stale / recent summary |
| Audit | `ops/task_audit.py`, `ops/task_audit_index.py` | Forensics per task id |
| Lessons | `ops/LESSONS_REGISTRY.md`, `ops/learning_miner.py` | Machine-readable lessons |
| Guardrails | `ops/GUARDRAILS.md` | Promoted rules |
| Digest | `ops/learning_digest.py` | Owner-facing summary |
| Approvals | `ops/approvals/*.approval`, `ops/approvals/AUTO_APPROVE_IDS.txt` | Committed approval tokens |
| Verification | `ops/verification/*` | Ground truth of every action |

## 6. Agent etiquette

- **Consult before re-doing work.** Grep `ops/LESSONS_REGISTRY.md` and
  `ops/GUARDRAILS.md` before writing a new fix for a known problem.
- **Record when you fix something new.** Use consistent headings
  (`Root cause`, `Fix applied`, `Remaining blocker`, `Next`, `Limitations`,
  `TODO`) in verification reports — that is how the miner learns.
- **Promote carefully.** A lesson should be stable across at least two
  verification files before becoming a guardrail, unless it is clearly a
  safety / money issue.
- **Never delete history.** Deprecated guardrails and superseded lessons
  stay in the files with an updated status. Git log is the audit trail.
