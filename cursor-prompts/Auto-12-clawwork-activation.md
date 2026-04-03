# Auto-12: ClawWork Activation — Bob's Side Hustle

## Context Files to Read First
- clawwork/v2/README.md
- clawwork/v2/strategy.md
- clawwork/v2/task_scoring.py
- clawwork/v2/quality_control.py
- clawwork/v2/client_relationship.py
- clawwork/v2/earnings_dashboard.py
- clawwork/v2/sector_playbooks/*.md
- clawwork/bob_side_hustle.py

## Prompt

ClawWork is Bob's idle-time revenue engine — freelance work on Upwork/Fiverr when the Symphony queue is empty. The framework is built. Wire it up for real operation:

1. **Task Selector** (`clawwork/v2/task_scoring.py` — expand):
   - Score available tasks by: estimated time, pay rate, match to Bob's skills, quality risk
   - Tier 1 sectors (highest fit): research/analysis, technical writing, data entry automation, code review
   - Skip anything requiring human identity, phone calls, or real-time video
   - Maximum concurrent tasks: 3
   - Auto-pause all ClawWork when Symphony queue has pending items

2. **Quality Control** (`clawwork/v2/quality_control.py` — expand):
   - Before submitting any deliverable, run a self-review pass
   - Check: grammar, factual accuracy (cross-reference with web search), formatting, completeness against task requirements
   - Score 0-100. If <85, revise automatically. If <70 after revision, flag for human review.
   - Log all quality scores for performance tracking

3. **Earnings Dashboard** (`clawwork/v2/earnings_dashboard.py`):
   - Track: tasks completed, revenue earned, hours spent, effective hourly rate, quality scores
   - Daily summary via iMessage: "ClawWork today: 3 tasks, $47 earned, avg quality 91"
   - Weekly summary: total revenue, best-performing sector, worst-performing sector
   - Store in SQLite `clawwork/earnings.db`

4. **Integration with Bob's schedule**:
   - ClawWork runs ONLY when: Symphony task queue is empty AND no emails pending response AND no scheduled meetings in next 2 hours
   - Check these conditions every 5 minutes
   - When a Symphony task arrives, save ClawWork state and switch immediately
   - Resume ClawWork when Symphony queue is empty again

5. **Revenue target tracking**: Show progress toward the $50/day target. Alert Matt when a new milestone is hit (first $100, first $500, first $1000).

Use standard logging.
