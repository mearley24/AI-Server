# API-13: Symphony Client Lifecycle — Zero-Touch Project Management

## The Vision

Right now, a new Symphony project requires manual steps at every stage: build the proposal, email the client, follow up, get the deposit, create Linear tickets, order equipment, schedule the GC walkthrough, coordinate install, commission, hand off. Bob should own this entire lifecycle end-to-end, with Matt only stepping in for site visits and hands-on install work.

## Context Files to Read First
- openclaw/job_lifecycle.py
- openclaw/project_template.py (22-issue Linear template)
- openclaw/email_workflow.py
- proposals/proposal_engine.py
- knowledge/proposal_library/
- PLAYBOOK_TOPLETZ.md
- docs/SYMPHONY_PROJECT_WORKFLOW.md

## Prompt

Build the complete client lifecycle automation:

### 1. Lead Intake (trigger: new email or voice call)

- Email from unknown address mentioning "smart home", "automation", "speakers", "lighting" → auto-classify as lead
- Voice receptionist (API-8) qualifies the lead: project type, budget range, timeline, address
- Auto-create Linear ticket in "Leads" project
- Auto-respond with availability and consultation scheduling link
- If lead mentions a specific address → auto-pull Zillow/county data for home size, year built, lot details

### 2. Consultation → Proposal (trigger: walkthrough completed)

- After site visit, Matt drops notes into Apple Notes or sends voice memo via iMessage
- Bob parses notes into structured room list + requirements
- Bob generates three-tier proposal using proposal_engine.py + room packages
- Bob runs preflight check (pricing validation, VersaBox at every TV, network sizing)
- Bob emails proposal to client with cover letter (hyperlinked products, payment terms)
- Bob creates Dropbox folder: `Symphony Smart Homes/[Client Name] — [Address]/`
- Bob schedules follow-ups: Day 3, Day 7, Day 14

### 3. Acceptance → Kickoff (trigger: signed agreement + deposit)

- Dropbox watcher detects signed agreement upload
- Bob verifies deposit received (match amount in email or bank notification)
- Bob creates Linear project from 22-issue template (4 phases)
- Bob creates D-Tools project and imports equipment list
- Bob generates SOW from scope blocks
- Bob emails client: "We're officially started! Here's your project timeline."
- Bob schedules GC coordination meeting (if GC is involved)
- Bob orders long-lead equipment (needs Matt's approval via iMessage)

### 4. Pre-Wire Phase (trigger: Linear phase 2 starts)

- Bob tracks GC construction schedule (from calendar events or email updates)
- Bob sends Matt pre-wire checklist 48 hours before scheduled pre-wire date
- Bob generates wire pull list from system design (room by room, cable types, quantities)
- Bob sends GC the low-voltage requirements document
- Bob monitors for schedule changes and adjusts Linear tickets

### 5. Trim & Install Phase (trigger: Linear phase 3 starts)

- Bob generates daily install schedule based on room priority and equipment availability
- Bob tracks equipment delivery status (from email order confirmations)
- Bob alerts Matt if equipment is delayed and affects install schedule
- Bob sends client weekly progress updates with photos (from iCloud sync)

### 6. Commission & Handoff (trigger: Linear phase 4 starts)

- Bob generates commissioning checklist from system design
- Bob runs system verification against the original proposal (every device accounted for)
- Bob builds the client knowledge base for the AI Concierge (API-9)
- Bob sends client final documentation package: network map, device list, warranty info, support contacts
- Bob schedules 30-day check-in
- Bob sends final invoice for remaining balance
- Bob archives project in Linear, moves Dropbox folder to "Completed"

### 7. Post-Project (ongoing)

- 30-day check-in: Bob texts client asking if everything is working
- 90-day: Bob emails a satisfaction survey
- Annual: Bob sends maintenance reminder and system health check offer
- If client emails support@ → route to Bob for first-pass troubleshooting before escalating to Matt

### 8. Integration Points

- Publishes lifecycle events to the event bus (API-11)
- Updates treasury (API-12) when deposits and final payments arrive
- Feeds context store so the daily briefing knows project status
- Linear sync keeps tickets updated as phases progress

Use standard logging.
