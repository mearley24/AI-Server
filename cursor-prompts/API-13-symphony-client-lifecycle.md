# API-13: Symphony Client Lifecycle — Zero-Touch Project Management

## The Vision

Right now, a new Symphony project requires manual steps at every stage: build the proposal, email the client, follow up, get the deposit, create Linear tickets, order equipment, schedule the GC walkthrough, coordinate install, commission, hand off. Bob should own this entire lifecycle end-to-end, with Matt only stepping in for site visits and hands-on install work.

## Context Files to Read First
- openclaw/job_lifecycle.py
- openclaw/project_template.py (22-issue Linear template)
- openclaw/email_workflow.py
- openclaw/follow_up_tracker.py  ← wire up the existing tracker
- openclaw/payment_tracker.py    ← wire up the existing tracker
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
- Bob creates standardized Dropbox folder structure (see Section 9)
- Bob schedules follow-ups: Day 3, Day 7, Day 14 via `follow_up_tracker.py`
- Bob logs the outbound email in the client communication tracker (see Section 10)

### 3. Follow-Up Tracker (trigger: proposal sent — wire up `openclaw/follow_up_tracker.py`)

After a proposal is sent, Bob automatically tracks follow-up cadence. **Do not let these fall through the cracks.**

- **Day 3**: Send a brief check-in — "Just wanted to make sure the proposal came through clearly. Happy to answer any questions."
- **Day 7**: Send a value-reinforcing follow-up — reference one specific detail from their project (e.g., "The Savant system we spec'd for your main living area is particularly well-suited for...")
- **Day 14**: Final follow-up — "I want to make sure I'm not missing anything on your end. If timing has changed, no problem at all."

**Implementation:**
```python
# follow_up_tracker.py — wire up to lifecycle events
class FollowUpTracker:
    def schedule_follow_ups(self, project_id: str, client_email: str, proposal_sent_date: date):
        self.schedule(project_id, client_email, proposal_sent_date + timedelta(days=3), "day_3")
        self.schedule(project_id, client_email, proposal_sent_date + timedelta(days=7), "day_7")
        self.schedule(project_id, client_email, proposal_sent_date + timedelta(days=14), "day_14")
    
    def get_due_today(self) -> list[dict]:
        # Returns list of follow-ups due today — used by daily briefing (Auto-17)
        ...
    
    def mark_sent(self, follow_up_id: str):
        # Mark sent, log in communication tracker
        ...
    
    def cancel_remaining(self, project_id: str):
        # Called when proposal is accepted — cancel outstanding follow-ups
        ...
```

- Follow-up state stored in Redis: `followup:{project_id}:{day}` → `{status, scheduled_date, sent_date}`
- Daily briefing (Auto-17) reads `follow_up_tracker.get_due_today()` and includes them in the morning summary
- If a follow-up is overdue (scheduled date passed, not sent) → emit `follow_up_overdue` event to event bus (API-11) with priority `high`

### 4. Payment Watcher (trigger: proposal accepted — wire up `openclaw/payment_tracker.py`)

After a proposal is accepted, Bob watches for the deposit and final payment. **Never let a payment go unnoticed or unconfirmed.**

- **Deposit**: typically 50% of project total (example: $34,609 for Topletz on a $69,218 project — always derive from the actual proposal, do not hardcode)
- **Final payment**: remaining balance at project completion

**Implementation:**
```python
# payment_tracker.py — wire up to lifecycle events
class PaymentTracker:
    def watch_deposit(self, project_id: str, client_name: str, expected_amount: float):
        # Register expected payment — store in Redis: payment:{project_id}:deposit
        # Watch: bank notification emails, Zoho, iMessage mentions of wire/check
        ...
    
    def check_payment_email(self, email_body: str, project_id: str) -> bool:
        # Parse email for payment confirmation keywords + amount match
        # Keywords: "wire transfer", "ACH", "check", "payment sent", "deposit"
        ...
    
    def confirm_received(self, project_id: str, payment_type: str, amount: float):
        # Mark confirmed → emit payment_received event to event bus (API-11)
        # Cancel follow-ups, trigger kickoff workflow
        ...
    
    def get_pending_payments(self) -> list[dict]:
        # Returns all pending payments — used by daily briefing (Auto-17)
        ...
```

- Payment state in Redis: `payment:{project_id}:{type}` → `{expected_amount, status, confirmed_date}`
- Daily briefing (Auto-17) reads `payment_tracker.get_pending_payments()` and surfaces any that have been pending >3 days
- When deposit confirmed → emit `deposit_confirmed` event → triggers kickoff workflow (Section 5 below)
- When final payment confirmed → emit `payment_received` → triggers project archive

### 5. Acceptance → Kickoff (trigger: signed agreement + deposit confirmed)

- Dropbox watcher detects signed agreement upload in `Client/` folder
- Bob verifies deposit received via `payment_tracker.confirm_received()`
- Bob cancels remaining follow-ups via `follow_up_tracker.cancel_remaining(project_id)`
- Bob creates Linear project from 22-issue template (4 phases)
- Bob creates D-Tools project and imports equipment list
- Bob generates SOW from scope blocks
- Bob emails client: "We're officially started! Here's your project timeline."
- Bob schedules GC coordination meeting (if GC is involved)
- Bob orders long-lead equipment (needs Matt's approval via iMessage)
- Bob logs kickoff email in client communication tracker

### 6. Pre-Wire Phase (trigger: Linear phase 2 starts)

- Bob tracks GC construction schedule (from calendar events or email updates)
- Bob sends Matt pre-wire checklist 48 hours before scheduled pre-wire date
- Bob generates wire pull list from system design (room by room, cable types, quantities)
- Bob sends GC the low-voltage requirements document
- Bob monitors for schedule changes and adjusts Linear tickets

### 7. Trim & Install Phase (trigger: Linear phase 3 starts)

- Bob generates daily install schedule based on room priority and equipment availability
- Bob tracks equipment delivery status (from email order confirmations)
- Bob alerts Matt if equipment is delayed and affects install schedule
- Bob sends client weekly progress updates with photos (from iCloud sync)

### 8. Commission & Handoff (trigger: Linear phase 4 starts)

- Bob generates commissioning checklist from system design
- Bob runs system verification against the original proposal (every device accounted for)
- Bob builds the client knowledge base for the AI Concierge (API-9)
- Bob sends client final documentation package: network map, device list, warranty info, support contacts
- Bob schedules 30-day check-in
- Bob sends final invoice for remaining balance; `payment_tracker.watch_final_payment(project_id, amount)`
- Bob archives project in Linear, moves Dropbox folder to `Projects/[Client]/Archive/`

### 9. Standardized Dropbox Folder Structure

On proposal acceptance (or earlier if Bob creates the folder at proposal-send time), create this structure:

```
Symphony Smart Homes/
└── Projects/
    └── [Client Name] — [Address]/
        ├── Client/          ← shared with client (stable share link, never changes)
        │   ├── Proposals/
        │   ├── Agreements/
        │   └── Documents/
        ├── Internal/        ← Symphony-only, never shared
        │   ├── Photos/
        │   ├── Drawings/
        │   └── Notes/
        └── Archive/         ← old versions, superseded files
```

**Rules:**
- `Client/` is shared with the client via a Dropbox folder-level share link. This link is generated once and stored in the project record — **it never changes**, so the client always has the same bookmark.
- When a new proposal version is generated → new PDF goes into `Client/Proposals/`, old version moves to `Archive/`
- When the client uploads a signed agreement → it lands in `Client/Agreements/` and triggers the acceptance workflow
- `Internal/` is never shared — photos, wire diagrams, internal notes go here
- Use Dropbox API credentials from `.env`: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`

**Folder creation:**
```python
def create_project_folder(client_name: str, address: str) -> str:
    base = f"Symphony Smart Homes/Projects/{client_name} — {address}"
    for subfolder in ["Client/Proposals", "Client/Agreements", "Client/Documents",
                      "Internal/Photos", "Internal/Drawings", "Internal/Notes",
                      "Archive"]:
        dropbox_client.files_create_folder_v2(f"/{base}/{subfolder}")
    # Create and store share link for Client/ folder
    share_link = dropbox_client.sharing_create_shared_link_with_settings(f"/{base}/Client/")
    store_share_link(project_id, share_link.url)
    return share_link.url
```

### 10. Client Communication Tracker

Every email or message sent or received related to a project must be logged. This is the source of truth for "what did we tell this client and when."

```python
# communication_tracker.py
class CommunicationTracker:
    def log(self, project_id: str, direction: str, channel: str, subject: str, 
            summary: str, timestamp: datetime):
        # direction: "sent" | "received"
        # channel: "email" | "imessage" | "phone"
        # Stored in Redis list: comms:{project_id} (LPUSH, keep last 200)
        # Also appended to knowledge/projects/{project_id}/comms_log.jsonl
        ...
    
    def get_history(self, project_id: str) -> list[dict]:
        # Returns full comms history for a project — used for meeting prep, context
        ...
```

- Email monitor (API-2) calls `communication_tracker.log()` on every inbound/outbound email matched to a project
- Follow-up tracker calls `communication_tracker.log()` when a follow-up is sent
- Communication log surfaces in daily briefing for any project with recent activity
- When Matt asks "what's the last thing we said to Topletz?" → context engine queries the comms log

### 11. Post-Project (ongoing)

- 30-day check-in: Bob texts client asking if everything is working
- 90-day: Bob emails a satisfaction survey
- Annual: Bob sends maintenance reminder and system health check offer
- If client emails support@ → route to Bob for first-pass troubleshooting before escalating to Matt

### 12. Daily Briefing Integration (Auto-17)

The daily briefing (Auto-17) must include:
- **Follow-ups due today**: list from `follow_up_tracker.get_due_today()` — client name, day number, project value
- **Overdue follow-ups**: any follow-ups past their scheduled date that weren't sent
- **Pending payments**: list from `payment_tracker.get_pending_payments()` — client name, amount, days since proposal accepted
- **Payments pending >3 days**: flagged with priority (these need attention)
- **Recent client communications**: any inbound emails from clients in the last 24 hours

### 13. Integration Points

- Publishes lifecycle events to the event bus (API-11): `proposal_sent`, `follow_up_due`, `payment_received`, `project_created`, `project_phase_changed`
- Updates treasury (API-12) when deposits and final payments arrive
- Feeds context store (`bob:context:project`) so the daily briefing knows project status
- Linear sync keeps tickets updated as phases progress
- Auto-18 (Dropbox/iCloud Sync) handles file routing into the standardized folder structure

Use standard logging.
