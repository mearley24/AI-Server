# Process Policy — Linear vs Repo vs Cortex

**Audience:** anyone deciding *where* a piece of process state should live.
**Status:** authoritative as of 2026-04-25. Changes require a STATUS_REPORT
entry.

---

## TL;DR

Three surfaces, three jobs. Do not duplicate state across them.

| Surface | Owns | Does **not** own |
|---|---|---|
| **Linear** | Live client / business operations | Engineering, repo, ops, runbooks, verification |
| **Repo** (this codebase) | Engineering + process + handoff source of truth | Live client work queue |
| **Cortex** (`:8102` dashboard) | Operator action surface; surfaces (1) + (2) read-only | Persistence of canonical text |

---

## 1. Linear — live client / business ops only

**What goes in Linear:**

- Active client jobs as Linear *Projects* (per-client).
- Phase-task issues created on phase advance
  (`openclaw/linear_sync.py::create_phase_issues`).
- Inbound-email comments on the matched open issue, or new issues
  for newly-detected client signals
  (`openclaw/linear_sync.py::LinearEmailSync`).
- New leads (`BID_INVITE`) → `create_doc_regeneration_issue`.
- 14-day silent-client follow-up notes
  (`openclaw/follow_up_engine.py`).
- Scope changes (`openclaw/scope_tracker.py`).

**What does NOT go in Linear:**

- Engineering work (refactors, code, commits, PRs).
- Ops verification receipts (`ops/verification/*`).
- Runbooks (`ops/runbooks/*`).
- Cursor/Cline prompts.
- Self-improvement loop output.
- Cortex moderate/risky proposals (the
  `ops:cortex_proposal` Redis bridge stays dormant —
  `operations/linear_ops.py` is intentionally not in
  `docker-compose.yml`).
- Trading alerts (handled by Notification Hub / iMessage).
- Calendar prep duplicates of existing calendar events.
- Voice-receptionist per-call followups (covered by Cortex; the
  `ops:voice_followup` Redis path remains, but its Linear bridge is
  dormant by policy).

**Why:** Linear's free-tier active-issue cap should not be hit by
client work alone. If it is, that is the signal to clean up stale
Linear issues — not to migrate engineering work in. Engineering
context belongs with the code so a future repo clone is
self-sufficient without Linear access.

---

## 2. Repo — engineering / process / handoff source of truth

**What lives in the repo (canonical):**

- `HANDOFF.md` — entry point for a fresh cloner.
- `CLAUDE.md`, `AGENTS.md` — agent instructions and long memory.
- `STATUS_REPORT.md` — living journal; the most up-to-date view of
  what landed, what's blocked, what's `[NEEDS_MATT]`.
- `ops/BACKLOG.md` — engineering backlog (formerly attempted in
  Linear).
- `ops/PROCESS_POLICY.md` — this file.
- `ops/runbooks/` — one runbook per repeatable operation.
- `ops/verification/` — receipts (live smokes, port audits, etc.).
- `ops/REPO_LAYOUT.md`, `ops/INTEGRATIONS.md` — the topology.
- `PORTS.md` — port registry.
- `.cursor/prompts/` — active prompts; archive in `DONE/`.

**Conventions:**

- When work lands, append a dated line to `STATUS_REPORT.md`.
- If the work involves a live external system (BlueBubbles, Twilio,
  Zoho, Bob's launchd), drop a receipt under
  `ops/verification/<stamp>-<slug>/`.
- Use the `[FOLLOWUP]` and `[NEEDS_MATT]` tags so the summarizer
  (`ops/status_report_summarizer.py`) can group them.
- Backlog items in `ops/BACKLOG.md` follow the shape documented at
  the top of that file so they can be parsed by tooling
  (`/api/process/backlog`).

---

## 3. Cortex — operator dashboard / action surface

**What Cortex owns:**

- The dashboard SPA (`cortex/static/`) and its routes
  (`cortex/dashboard.py::register_dashboard_routes`).
- Read endpoints for every other service's status (Symphony tab).
- Action endpoints for x-intake approvals, reply-actions, agreement
  generation, intel-briefing, etc.
- A read-only summary of the engineering backlog at
  `/api/process/backlog` (parsed from `ops/BACKLOG.md`).

**What Cortex does NOT own:**

- Persistence of canonical text. The repo is the source of truth;
  Cortex parses and surfaces it. If a Cortex card disagrees with the
  repo file, the repo file wins.
- Engineering history. The dashboard does not have its own audit
  trail of code changes; that's `git log` + `STATUS_REPORT.md`.

**Why surface backlog/process in Cortex:** so the operator can see
"what's on the engineering backlog right now?" without leaving the
dashboard. The endpoint is read-only; mutations only happen by
editing `ops/BACKLOG.md` and committing.

---

## 4. Decision tree — where should this go?

```
Is it about a real client or job moving through a phase?
  └─ Yes → Linear (auto, via openclaw/linear_sync.py).
  └─ No → Is it engineering, ops, or process?
        └─ Yes → Repo. Pick the file:
              - in-flight context this session  → STATUS_REPORT.md
              - future work, not started        → ops/BACKLOG.md
              - reusable operation              → ops/runbooks/
              - evidence of a live action       → ops/verification/
              - long-lived agent memory         → AGENTS.md
              - lessons / postmortems           → ops/LESSONS_REGISTRY.md
        └─ No → Is it operator UI / action surface?
              └─ Yes → Cortex (cortex/dashboard.py route).
              └─ No → reconsider; it probably does not need to be tracked.
```

---

## 5. Failure modes this policy prevents

- **Linear cap blocking real client work** because engineering
  issues used the active-issue budget. Engineering now lives in
  `ops/BACKLOG.md`, no quota.
- **Future cloner cannot see what's going on** because state is in
  a private Linear workspace. Now `HANDOFF.md` + `STATUS_REPORT.md`
  + `ops/BACKLOG.md` are sufficient on their own.
- **Duplicate sources of truth** for engineering items (Linear +
  STATUS_REPORT + a runbook). Now: one canonical file, others link
  to it.
- **Cortex dashboard claiming things go to Linear that don't.**
  The `operations/linear_ops.py` listener is intentionally not in
  compose; surfaces that imply otherwise must say so explicitly.

---

## 6. Hygiene — quarterly check

Once a quarter (or any time the active-issue cap warning appears):

1. Run `git log --since=3.months -- ops/BACKLOG.md` to confirm the
   backlog has been kept current.
2. Walk Linear's open-issue list and drop anything that should have
   been a `STATUS_REPORT` line, a runbook, or a `BACKLOG` item.
3. Confirm `/api/process/backlog` parses without warnings.
4. Append a hygiene line to `STATUS_REPORT.md`.

---

## 7. Source

This policy was written 2026-04-25 after the Linear free-tier cap
blocked an engineering backlog push. The full coverage audit is at
`/tmp/claude_code_output.md` (also summarized inline in
`ops/BACKLOG.md`'s preamble).
