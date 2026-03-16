# SymphonyOps Flow-State Blueprint

## Goal

Make SymphonyOps feel fast, modern, and calm while preserving the depth of operations workflows.

This blueprint combines proven UX patterns from top apps without cloning any one product.

## Borrowed Patterns (Adapted)

- Linear: fast command-first flow and strict task progression.
- Notion: flexible, reusable information blocks and consistent primitives.
- Slack: actionable inbox with strong triage and handoff.
- Stripe Dashboard: clean data hierarchy and confidence-oriented status surfaces.
- Uber: clear state transitions and "what happens next" certainty.

## Symphony Flow Model

### Primary Navigation

Use 5 stable work areas:

1. Today
2. Work
3. Clients
4. Ops
5. Settings

### Today = Action Hub

Top cards only:

- Urgent now
- Due today
- Waiting on you

Every card has one clear primary action.

### Unified Action Queue

Merge iMessage intake, approvals, failures, and follow-ups into a single queue model with:

- priority
- state
- owner
- next action

### Workflow State Rail

Standardize all major flows with the same stages:

- Draft
- Review
- Sent
- Approved
- Scheduled
- Completed
- Archived

Use the same state language across proposals, install tasks, and customer communications.

## Interaction Principles

- Keep every screen under 3 primary CTAs.
- Prefer one-tap actions over deep forms.
- Use subtle haptics/animation for state transitions only.
- Keep empty states actionable, not informational.
- Show progress and ownership at all times.

## Phase Plan

### Phase 1: Shell Refresh (Immediate)

- Modernize workspace chip/nav styling and hierarchy.
- Reduce visual clutter in section headers.
- Standardize spacing + typography rhythm.

### Phase 2: Queue Unification

- Build one unified action queue model.
- Route iMessage intake and retry pipeline into the queue.
- Add bulk actions and "next best action" hints.

### Phase 3: End-to-End Flows

- Apply shared status rail to proposals + field jobs.
- Add deterministic handoffs and completion states.
- Add lightweight timeline per client/job.

## Guardrails

- Do not copy layouts 1:1 from any source app.
- Keep Symphony vocabulary and domain language first.
- Preserve durable logs/history and existing backend contracts.
- Validate every UX change against "can complete the job in fewer taps."

