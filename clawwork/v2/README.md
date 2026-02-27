# ClawWork Operations Guide
## Bob the Conductor — Side Hustle System Documentation

**Version:** 2.0.0  
**Updated:** 2026-02-27  
**System:** Symphony Smart Homes AI — Side Hustle Mode  

---

## What Is ClawWork?

ClawWork is Bob's freelance income engine. When the Symphony Smart Homes task queue is empty, Bob activates ClawWork mode and earns money by completing professional freelance tasks — 24 hours a day, 7 days a week.

Bob works the GDPVal benchmark (professional tasks valued at BLS occupational wages), Upwork, Fiverr, and direct client relationships. Every idle minute is a revenue opportunity.

**Symphony always takes priority.** The moment a Symphony task arrives, Bob suspends ClawWork and handles the primary job.

---

## Repository Structure

```
phase2/clawwork/
├── README.md                          # This file
├── strategy.md                        # Master earning strategy
├── financial_projections.md           # 12-month revenue model
│
├── sector_playbooks/                  # Per-sector tactical guides
│   ├── data_entry_automation.md
│   ├── content_writing.md
│   ├── research_reports.md
│   ├── code_review.md
│   ├── real_estate_support.md
│   ├── bookkeeping.md
│   ├── customer_support.md
│   └── technical_writing.md
│
├── platform_configs/                  # Platform-specific configurations
│   ├── upwork_profile.json
│   ├── fiverr_gigs.json
│   └── direct_outreach.json
│
├── task_scoring.py                    # Task evaluation and selection algorithm
├── earnings_dashboard.py              # Analytics and reporting
├── client_relationship.py             # Client management and retention
└── quality_control.py                 # Pre-submission QA checks
```

---

## Quick Start

### 1. Configure the system

Ensure `clawwork_config.json` at `/home/user/workspace/clawwork_integration/` has:
- `symphony_queue_check.endpoint` pointing to your OpenClaw API
- `earnings_tracking.database_path` set to your desired DB location
- `notifications.telegram` enabled with your bot token

### 2. Start a ClawWork session

Bob's session loop (integrated into Symphony's idle handler):

```python
from task_scoring import TaskScorer, TaskCandidate
from quality_control import QualityChecker
from client_relationship import ClientManager

scorer = TaskScorer(config)
qc = QualityChecker()
clients = ClientManager()

while symphony_queue_is_empty():
    # 1. Get available tasks from platform(s)
    candidates = fetch_available_tasks()
    
    # 2. Score and rank tasks
    ranked = scorer.rank_tasks(candidates)
    
    if not ranked:
        time.sleep(300)  # Wait 5 min for new tasks
        continue
    
    # 3. Accept top-ranked task
    best = ranked[0]
    
    # 4. Execute the task (ClawWork agent does this)
    deliverable = execute_task(best.task)
    
    # 5. Quality check
    report = qc.check(deliverable)
    if not report.passed:
        deliverable = revise(deliverable, report)
    
    # 6. Submit
    submit_task(best.task.task_id, deliverable)
    
    # 7. Log
    earnings_tracker.log_task(...)
    
    # 8. Update client relationship
    if best.task.client_id:
        clients.log_project(best.task.client_id, ...)
        
        should_review, reason = clients.should_request_review(...)
        if should_review:
            send_review_request(clients.generate_review_request(...))
```

### 3. View earnings dashboard

```bash
# Terminal dashboard
python earnings_dashboard.py dashboard

# Daily report
python earnings_dashboard.py daily

# Forecast
python earnings_dashboard.py forecast

# Export to CSV
python earnings_dashboard.py export --format csv
```

### 4. Check milestones

```bash
python earnings_dashboard.py milestones
```

---

## Module Reference

### task_scoring.py

**Purpose:** Evaluates and ranks available tasks before acceptance.

**Key Classes:**
- `TaskCandidate` — Represents an available task with all scoring inputs
- `TaskScorer` — Scores tasks on 5 dimensions with configurable weights
- `ScoredTask` — Result of scoring with accept/decline decision

**Key Methods:**
```python
scorer = TaskScorer(config, start_date=datetime(2026, 2, 27))

# Evaluate a single task
result = scorer.evaluate(task_candidate)
# result.accept → True/False
# result.composite_score → 0.0–1.0
# result.action → 'accept' | 'decline' | 'queue'

# Rank multiple tasks
ranked = scorer.rank_tasks([task1, task2, task3])
# Returns list of ScoredTask sorted by composite_score descending
```

### quality_control.py

**Purpose:** Pre-submission quality checks to maintain platform reputation.

**Checks performed:**
- Word count within spec
- Spelling and grammar pass
- Formatting compliance (headers, bullet points, code blocks)
- Plagiarism indicators
- Tone consistency
- Deliverable completeness (all required sections present)

**Key Methods:**
```python
qc = QualityChecker()
report = qc.check(deliverable)
# report.passed → True/False
# report.score → 0.0–1.0
# report.issues → list of QualityIssue
# report.summary → str
```

### client_relationship.py

**Purpose:** Track client interactions, manage communication, and optimize review acquisition.

**Key Methods:**
```python
clients = ClientManager()

# Log a completed project
clients.log_project(client_id, task_id, value, rating, review_text)

# Check if review request is appropriate
should_request, reason = clients.should_request_review(client_id, task_id)

# Generate personalized review request
message = clients.generate_review_request(client_id, task_id)

# Get client score (for task prioritization)
score = clients.get_client_score(client_id)
```

### earnings_dashboard.py

**Purpose:** Real-time analytics on ClawWork performance.

**CLI Commands:**
```bash
python earnings_dashboard.py dashboard   # Live terminal dashboard
python earnings_dashboard.py daily       # Today's performance
python earnings_dashboard.py weekly      # 7-day summary
python earnings_dashboard.py monthly     # 30-day summary
python earnings_dashboard.py forecast    # 90-day projection
python earnings_dashboard.py milestones  # Progress vs. targets
python earnings_dashboard.py export      # Export to CSV/JSON
```

---

## Configuration

The system reads from `clawwork_config.json`. Key settings:

```json
{
  "version": "2.0",
  "symphony_queue_check": {
    "endpoint": "https://api.openclaw.io/v1/queue/status",
    "interval_seconds": 300,
    "priority": "always_first"
  },
  "task_scoring": {
    "min_accept_score": 0.65,
    "auto_decline_below": 0.45,
    "weights": {
      "pay_rate": 0.35,
      "completion_time": 0.20,
      "skill_match": 0.25,
      "reputation_impact": 0.10,
      "client_quality": 0.10
    }
  },
  "earnings_tracking": {
    "database_path": "/data/clawwork_earnings.db",
    "daily_target": 75.00,
    "currency": "USD"
  },
  "quality_control": {
    "min_score": 0.85,
    "auto_revise_threshold": 0.80,
    "hard_reject_below": 0.70
  },
  "notifications": {
    "telegram": {
      "enabled": true,
      "alerts": ["daily_summary", "milestone_achieved", "low_balance"]
    }
  },
  "platforms": {
    "upwork": {"enabled": true, "primary": true},
    "fiverr": {"enabled": true},
    "gdpval": {"enabled": true, "priority": "high"},
    "codementor": {"enabled": true},
    "direct": {"enabled": true}
  },
  "risk_limits": {
    "max_client_revenue_pct": 0.25,
    "min_balance_alert": 5.00,
    "daily_task_cap": 50
  }
}
```

---

## Sector Playbooks

Detailed operational guides for each sector are in `sector_playbooks/`:

| Playbook | Sector | Key Tactics |
|----------|--------|-------------|
| `data_entry_automation.md` | Data Entry | Bulk processing, Python automation, speed techniques |
| `content_writing.md` | Content | SEO templates, domain-specific tone matching, research shortcuts |
| `research_reports.md` | Research | Report structure, source validation, executive summary templates |
| `code_review.md` | Code Review | Review checklists, bug pattern recognition, security scanning |
| `real_estate_support.md` | Real Estate | Listing templates, market report formats, CRM integration |
| `bookkeeping.md` | Bookkeeping | Chart of accounts, reconciliation workflows, QuickBooks integration |
| `customer_support.md` | Support | Response templates, escalation trees, sentiment analysis |
| `technical_writing.md` | Tech Writing | API doc templates, user manual structure, diagram guidelines |

---

## Platform Configurations

Platform profiles in `platform_configs/`:

- **`upwork_profile.json`** — Bob's Upwork profile, portfolio items, and proposal templates
- **`fiverr_gigs.json`** — All active Fiverr gig configurations with pricing tiers
- **`direct_outreach.json`** — Target client lists and outreach message templates

---

## Performance Targets

| Timeframe | Daily Net | Monthly Net | Key Goal |
|-----------|-----------|-------------|----------|
| Days 1–30 | $20–40 | $600–1,200 | 20 reviews, platform reputation |
| Days 31–60 | $50–80 | $1,500–2,400 | Top Rated, first $100 day |
| Days 61–90 | $75–100 | $2,250–3,000 | First recurring client |
| Months 4–6 | $100–200 | $3,000–6,000 | 5+ recurring clients |
| Months 7–12 | $150–250 | $4,500–7,500 | Full autonomous operation |

---

## Integration Points

ClawWork integrates with Symphony Smart Homes in three ways:

1. **Priority interruption:** Symphony queue check every 5 minutes during ClawWork sessions
2. **Earnings routing:** All ClawWork revenue flows through Symphony's financial tracking
3. **Skill transfer:** Domain knowledge from Symphony installations (real estate, smart home tech, project management) feeds directly into ClawWork task quality

---

*Built by Symphony Smart Homes AI System | ClawWork v2.0.0 | 2026*
