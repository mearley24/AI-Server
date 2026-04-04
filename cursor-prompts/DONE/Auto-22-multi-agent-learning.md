# Auto-22: Multi-Agent Learning — Employee Chit-Chat

## The Vision

Bob, Betty, and Beatrice learn from each other 24/7. One agent discovers a product compatibility issue → shares it → all agents know. Betty researches a wiring technique → logs it to the cortex → Bob uses it in tomorrow's proposal. The team's collective knowledge compounds over time without any human input.

## Context Files to Read First
- AGENTS.md (worker skills, task board, continuous learning)
- tools/cortex_curator.py
- tools/graph_learner.py
- orchestrator/continuous_learning.py
- orchestrator/autonomous_worker.py
- knowledge/cortex/
- tools/knowledge_graph.py

## Prompt

Wire up the multi-agent learning system that's been built but not deployed:

### 1. Learning Loop (`orchestrator/learning_loop.py`)

Continuous background process where agents teach each other:

- **Discovery phase** (every 30 min): Each worker scans its domain for new knowledge
  - Betty: product specs, installation techniques, troubleshooting patterns
  - Beatrice: proposal patterns, pricing trends, client communication templates
  - Bob: trading strategies, market patterns, operational insights

- **Sharing phase** (after discovery): New facts published to Redis `learning:new_facts`
  - Each fact tagged with: source agent, confidence score, domain, timestamp
  - Other agents subscribe and ingest relevant facts into their own context

- **Validation phase** (daily): Cross-check facts against each other
  - If Betty says "EA-5 supports 125 ZigBee devices" and Beatrice found "EA-5 max 100 devices" → flag contradiction
  - `cortex_curator.py` resolves contradictions using source reliability and recency

- **Consolidation phase** (weekly): Merge validated facts into the knowledge graph
  - `graph_learner.py` adds new nodes and relationships
  - Generate weekly "What the team learned" report via iMessage

### 2. Cortex Curator Deployment (`tools/cortex_curator.py` — deploy)

The curator exists but isn't running. Wire it up:
- Run daily via heartbeat at 2 AM
- Process all facts in `knowledge/cortex/`
- Deduplicate, score confidence, flag contradictions
- Promote high-confidence facts to `knowledge/cortex/trusted/`
- Move low-confidence facts to `knowledge/cortex/review/` for human review
- Stats published to Redis for Mission Control

### 3. Question Generator (`orchestrator/workers_question_generator.py` — deploy)

Generate questions that drive learning:
- For each product category, generate questions the team doesn't yet know the answer to
- "What is the maximum wire run distance for Cat6 to an Episode speaker?"
- "Can the Triad AMS-16 power both 4-ohm and 8-ohm speakers simultaneously?"
- Workers pick up questions, research answers, log to cortex
- Questions rotate through categories so knowledge builds evenly

### 4. Knowledge Connections (`orchestrator/workers_cortex_learn.py` — deploy)

Build cross-domain connections:
- "Control4 EA-5" connects to "Lutron RA3" via "LEAP driver integration"
- "Araknis 310 switch" connects to "Luma NVR" via "PoE power delivery on VLAN 50"
- These connections power the design validator (API-14) and troubleshooting guides

### 5. Task Filler (`orchestrator/task_filler.py` — deploy)

When no Symphony or ClawWork tasks are pending:
- Auto-generate learning tasks from the question generator
- Workers always have something productive to do
- Priority: Symphony tasks > ClawWork > Learning tasks

### 6. Overnight Learning (`tools/overnight_learner.py` — deploy)

Nightly deep learning session at 11 PM:
- Focus on one product category per night (rotate through all categories)
- Research 10 products in depth: specs, compatibility, common issues, installation tips
- Log everything to cortex with high confidence (source: manufacturer docs)
- By end of month, every product in the catalog has been deeply researched

### 7. Integration

- Publish learning events to event bus (API-11)
- Learning stats visible in Mission Control
- Weekly learning report in daily briefing (Auto-17)
- Knowledge graph stats: nodes, relationships, facts per domain

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
