# Lessons Registry

Machine-readable, agent-maintained registry of lessons learned by the Symphony
AI-Server. Every row is mined from `ops/verification/` (and, in future passes,
from `data/openclaw/decision_journal.db` + `data/email-monitor/follow_ups.db`)
by `ops/learning_miner.py`. Agents can also add rows manually — the miner will
preserve unknown `lesson_id` values.

## Schema

| column | meaning |
|---|---|
| `lesson_id` | Stable short ID, format `L-<8hex>` (hash of normalized summary) |
| `first_seen_at` | ISO 8601 (UTC) when the miner first created the row |
| `last_seen_at` | ISO 8601 (UTC) last time new evidence was observed |
| `source` | Where the lesson came from: verification filename(s), `decision_journal`, `follow_ups`, `manual` |
| `pattern_type` | One of: `failure`, `fix`, `opportunity`, `workflow_gap`, `approval_pattern`, `todo`, `blocker` |
| `summary` | Short human description (<= 240 chars) |
| `evidence_refs` | Pipe-separated list of verification filenames / IDs |
| `status` | `new`, `under_review`, `promoted_to_guardrail`, `superseded` |
| `impact_hint` | `reliability`, `speed`, `safety`, `business_impact`, `cost`, `unknown` |

## How to use

- Miner run: `python3 ops/learning_miner.py --days 7 --update`
- Miner dry-run: `python3 ops/learning_miner.py --days 7 --dry-run`
- Digest for Matt: `python3 ops/learning_digest.py --days 7 --write`
- When a lesson is stable, flip its `status` to `promoted_to_guardrail` and add
  a matching row to `ops/GUARDRAILS.md` with `derived_from_lessons` set to the
  lesson_id(s).

Do not hand-edit the table's `first_seen_at` / `last_seen_at` columns — the
miner manages them. Agents may update `status` and `impact_hint` freely.

## Lessons table

<!-- LESSONS_TABLE_START -->
| lesson_id | first_seen_at | last_seen_at | source | pattern_type | summary | evidence_refs | status | impact_hint |
|---|---|---|---|---|---|---|---|---|
| L-f0bef9ee | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-093125-autonomous-hardening-final.txt | workflow_gap | " below) M  scripts/task_runner.py wires ops/task_runner_preflight.run_preflight() into run_once() ahead of pull_latest(); if preflight reports unsafe conflicts, task dispatch is skipped for the tick but heartbeat continues | 20260417-093125-autonomous-hardening-final.txt | new | reliability |
| L-e30955c6 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-095615-memory-state-knowledge-audit.txt | todo | (17%) = 86% of memories. Polymarket research + per-tick follow-up writes dominate the brain. This is expected given the copytrade + research loops, but prune/TTL policies for high-volume trading categories should be reviewed. | 20260417-095615-memory-state-knowledge-audit.txt | new | business_impact |
| L-b8dd835f | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-095615-memory-state-knowledge-audit.txt | todo | TTL 30 days). Write a `knowledge/MANIFEST.json` listing every content path with a short description and last-updated ISO date; add a drift check. Evaluate litestream once brain.db is funded (cheap: backup-only profile). | 20260417-095615-memory-state-knowledge-audit.txt | new | unknown |
| L-b502f9fa | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-095857-cortex-brain-snapshot.txt | todo | 6531 tech_infrastructure   3469 trading               585 install_notes         329 ai_tools              224 x_intel               180 business              96 smart_home            80 | 20260417-095857-cortex-brain-snapshot.txt | new | business_impact |
| L-a8294468 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260418-082600-autonomy-gap-closer-resume-final.txt | fix | File: ops/task_runner_preflight.py | 20260418-082600-autonomy-gap-closer-resume-final.txt | new | unknown |
| L-99ed6e89 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260418-082600-autonomy-gap-closer-resume-final.txt | workflow_gap | closer" work: approval-token + dry-run gates, queue-status tool, task audit-index tool, preflight self-heal, and the associated documentation. That work was NOT redone. This resume pass focused strictly on the runaway preflight artefact lo… | 20260418-082600-autonomy-gap-closer-resume-final.txt | new | reliability |
| L-6e5be964 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-094200-reliability-observability-final.txt | workflow_gap | actions (deferred to later passes) | 20260417-094200-reliability-observability-final.txt | new | unknown |
| L-4d8089dc | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260418-082600-autonomy-gap-closer-resume-final.txt | failure | identified `ops/task_runner_preflight.py::run_preflight()` previously wrote a timestamped `ops/verification/YYYYMMDD-HHMMSS-preflight.txt` on *every* invocation — including clean no-op ticks. The runner's commit/push loop then added those… | 20260418-082600-autonomy-gap-closer-resume-final.txt | new | reliability |
| L-3889ada4 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-093900-reliability-observability-audit.txt | blocker | 6 (doc staleness, dropbox link validator, sell-haircut rounding) are tracked in Later. | 20260417-093900-reliability-observability-audit.txt | new | unknown |
| L-0b742109 | 2026-04-18T16:32:41Z | 2026-04-18T16:32:41Z | ops/verification/20260417-095615-memory-state-knowledge-audit.txt | todo | 6,529  (17%) tech_infrastructure 3,469  (9%) trading               585 install_notes         329 ai_tools              224 x_intel               180 ... (20+ categories) | 20260417-095615-memory-state-knowledge-audit.txt | new | business_impact |
<!-- LESSONS_TABLE_END -->
