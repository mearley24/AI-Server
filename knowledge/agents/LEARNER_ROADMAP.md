# Learner roadmap — Symphony AI Server

Referenced from `AGENTS.md`. This file tracks **continuous learning** and **autonomous Q&A** direction (not a sprint backlog).

## North star

- **24/7 learner** — Company + industry knowledge compounds; ship agents for front-end and ops work faster.
- **Autonomous Q&A** — Claude Code, Perplexity, and local tools handle questions with humans optional for approvals and edge cases.

## Near-term (ops)

- Run `orchestrator/continuous_learning.py` (or launchd `com.symphony.learning`) on a steady schedule.
- Mine `~/.cursor/.../agent-transcripts/` → update `AGENTS.md` (continual-learning skill).
- Keep `knowledge/cortex/` and `knowledge/news/` growing from Perplexity + local captures.

## Medium-term (product)

- Tighten **D-Tools Cloud** proposal loop: search existing projects before duplicate work; use `integrations/dtools/dtools_client.py` and `DTOOLS_API_KEY` (see `docs/PROPOSAL_DTOOLS_NEXT.md`).
- Expand **cortex** chunk links (`tools/knowledge_graph.py`, outline-creator inbox) for proposal and commissioning context.

## Review

Revisit this file when quarterly goals shift or after major releases.
