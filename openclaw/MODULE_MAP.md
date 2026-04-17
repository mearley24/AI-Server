# OpenClaw Module Map

Short description of every Python module in `openclaw/` with its current
status and known callers. Generated 2026-04-17 (Category 6 campaign pass).

## Legend

- **active** — Confirmed running and referenced by the orchestrator,
  the task runner, or an external client.
- **partial** — Module is in use but something is not firing
  end-to-end (e.g. `follow_up_engine`).
- **unknown** — File is present but no current doc / schedule /
  caller has been identified. Candidate for removal.
- **stale** — Known to be obsolete.

## Core

| Module | Status | Notes |
|---|---|---|
| `main.py` | active | FastAPI app entrypoint, port 8099. |
| `orchestrator.py` | active | 5-min tick loop. Handlers: emails, followups, payments, calendar, redis listener. |
| `agent_bus.py`, `event_bus.py` | active | Internal pub/sub between OpenClaw components. |
| `memory.py` | active | OpenClaw working memory bridge into Cortex. |
| `preflight_check.py` | active | OpenClaw-internal preflight. Distinct from `ops/task_runner_preflight.py`. |
| `outcome_listener.py` | active | Redis listener for outcome events. |
| `zoho_auth.py` | active | OAuth refresh helper for Zoho Mail + Calendar. |
| `webhook_server.py` | unknown | No current external webhook source wired. |

## Email / Follow-up / Approval

| Module | Status | Notes |
|---|---|---|
| `email_workflow.py` | active | Routes classified emails. |
| `auto_responder.py` | active | Automated responses to classified categories. |
| `approval_bridge.py` | active | Routes decisions to Matt via iMessage. |
| `approval_drain.py` | active | Auto-expires stale pending approvals. |
| `follow_up_tracker.py` | active | POSTs due follow-ups to Cortex. |
| `follow_up_engine.py` | partial | 3/7/14-day auto-send. `follow_up_log` empty — not yet fired. |

## Decision / Learning

| Module | Status | Notes |
|---|---|---|
| `decision_engine.py` | active | Chooses action given context + risk tier. |
| `decision_journal.py` | active | 4,642+ decisions logged. |
| `continuous_learning.py` | active | Daily 50-query Perplexity research loop. |
| `confidence.py` | active | Confidence scoring utilities. |
| `context_cleaner.py`, `context_store.py` | active | Context windowing helpers. |
| `pattern_engine.py` | unknown | No wiring observed. |
| `project_learner.py`, `trade_learner.py` | active | Feeds Cortex via POST /remember. |
| `research_agent.py` | active | Works with `continuous_learning.py`. |

## D-Tools / Jobs / Proposals

| Module | Status | Notes |
|---|---|---|
| `dtools_sync.py` | active | Keeps jobs.db in sync with D-Tools (41 jobs). |
| `dtools_change_watcher.py` | active | Emits `doc.stale` on D-Tools price changes. |
| `job_api.py`, `job_lifecycle.py`, `job_worker.py` | active | Job pipeline. |
| `client_tracker.py`, `scope_tracker.py` | active | Client prefs + scope tracking. |
| `project_template.py` | active | Proposal-template rendering. |
| `product_recommender.py` | active | Product suggestions from knowledge_base. |
| `sow_assembler.py` | active | Statement-of-work builder. |
| `proposal_checker.py` | active | Lints proposals before sending. |
| `design_validator.py` | active | Design rule checks. |
| `lifecycle_coordinator.py` | active | Coordinates job lifecycle transitions. |
| `llm_router.py`, `llm_cache.py` | active | LLM call routing + caching. |

## Money / Payments

| Module | Status | Notes |
|---|---|---|
| `cost_tracker.py` | partial | cost_tracker.db is sparse (~20 KB). |
| `payment_tracker.py` | active | Tracks payment schedules. |
| `treasury.py` | partial | Treasury helpers — depth unverified. |
| `invoice_generator.py` | unknown | No caller found in STATUS_REPORT. |
| `price_monitor.py` | partial | price_monitor.db last updated Apr 10 — may be dead. |

## Docs / External

| Module | Status | Notes |
|---|---|---|
| `doc_generator.py` | active | Wraps `tools/generate_agreement.py`. |
| `doc_staleness.py` | active | Flags stale docs on D-Tools price drift. |
| `docusign_integration.py` | unknown | Client-portal is the current e-sign path. Possibly legacy. |
| `dropbox_integration.py` | partial | Dropbox client hooks. dropbox-organizer is the external launchd agent. |
| `linear_sync.py` | unknown | Linear.app integration; no active compose or schedule reference. |

## Briefing / Tasks

| Module | Status | Notes |
|---|---|---|
| `daily_briefing.py` | active | Canonical 6 AM iMessage briefing. |
| `daily_briefing_v2.py` | in-flight | Experimental redesign. See DAILY_BRIEFING_V2_STATUS.md. |
| `task_board.py` | active | Shared with `orchestrator/task_board.py` on the host. |
| `knowledge_base.py` | active | Local product/knowledge lookups. |

## Healing

| Module | Status | Notes |
|---|---|---|
| `self_healer.py` | partial | Overlaps with `scripts/bob-watchdog.sh`. Scope unclear. |

## Notes

- Any `unknown` module should be investigated before a removal pass.
  Do not delete on the strength of this table alone — run `grep -r
  "from openclaw.<mod>" --include='*.py'` and verify no callers.
- Module ownership is not yet documented. Add a section here when
  you touch a module.
