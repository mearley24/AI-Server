# ClawWork Integration — Bob the Conductor's Side Hustle

> **TL;DR:** When Bob isn't running Symphony Smart Homes, he earns real money completing professional tasks from the GDPVal dataset — literally paying for his own API costs and generating surplus revenue.

---

## What This Is

ClawWork ([mearley24/ClawWork](https://github.com/mearley24/ClawWork), forked from HKUDS/ClawWork) is a framework that turns AI agents into economically-accountable "coworkers." Agents start with $10, pay for their own token usage, and earn income by completing professional tasks from OpenAI's **GDPVal dataset** — 220 real-world tasks spanning 44 occupations across the 9 sectors that collectively contribute the most to U.S. GDP.

**The key insight for Bob:** He already has deep expertise in technology, smart-home systems, real estate integration, project management, and professional services from his Symphony Smart Homes work. ClawWork tasks in those same sectors are high-ROI because Bob can leverage that domain knowledge without starting from zero.

---

## Architecture

```
 Mac Mini M4 Host
  OpenClaw Docker Stack
    bob (claude-sonnet-4-5) [PRIMARY — Symphony]
    side-hustle (claude-sonnet-4-5) [ClawWork — idle only]
    proposals (claude-haiku-3-5)
    dtools (gpt-4o-mini)
```

The `side-hustle` agent activates only when Bob's Symphony task queue is empty.

---

## How It Works

Every 5 minutes:
1. Check: Is Symphony task queue empty?
2. Check: Is system health OK?
3. Check: Is balance above $5 threshold?

If ALL true:
- TaskSelector picks highest-ROI available task
- side-hustle agent executes task via ClawWork tools
- Quality scored by GPT-4o using sector rubrics
- Payment = quality_score × (est_hours × BLS_wage)
- EarningsTracker logs transaction
- Telegram notification if daily goal hit

---

## Economic Model

| Metric | Target |
|--------|--------|
| Average quality score | 0.80+ |
| Average task earnings | $200+ |
| Average task token cost | $0.50–$2.00 |
| Profit margin | 95%+ |
| Daily earnings (2–3 tasks) | $400–$600 |

---

## Task Selection Strategy

### Tier 1 — Highest ROI (Bob's Home Turf)

| Sector | Why Bob Wins Here |
|--------|-------------------|
| **Information Technology** | Smart home systems = AV networking, IoT, system integration |
| **Professional Services** | Proposals, project management, technical consulting |
| **Real Estate & Leasing** | Smart home installations = deep RE knowledge |
| **Finance & Insurance** | Proposal pricing, ROI analysis, financial planning |

---

## Setup

```bash
# 1. Clone and install
bash install_clawwork.sh

# 2. Add API keys to environment
echo "CLAWWORK_OPENAI_KEY=sk-..." >> ~/.symphony/.env
echo "CLAWWORK_E2B_KEY=e2b_..." >> ~/.symphony/.env

# 3. Verify with a test task
python bob_side_hustle.py --test

# 4. Start the daemon
python bob_side_hustle.py --daemon
```

---

## File Reference

| File | Purpose |
|------|---------|
| `clawwork_config.json` | All configuration (model, economics, schedule, limits) |
| `bob_side_hustle.py` | Main orchestration script / daemon |
| `earnings_tracker.py` | SQLite earnings database + analytics |
| `task_selector.py` | Intelligent task selection with sector scoring |
| `docker-compose.clawwork.yml` | Docker overlay for ClawWork service |
| `install_clawwork.sh` | One-shot installation script |
| `clawwork_openclaw_agent.json` | OpenClaw agent definition for `side-hustle` |
| `earnings_report_template.md` | Telegram report templates |
| `sector_strategies/` | Detailed strategy guides per sector |

---

*Part of the Symphony Smart Homes AI-Server infrastructure. Bob's primary job is always Symphony operations — this is his side hustle that pays for itself.*
