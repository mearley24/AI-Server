# API-13: Symphony Client Lifecycle — Unified Pipeline

## The Vision

Right now, a new Symphony project requires manual steps at every stage: build the proposal, email the client, follow up, get the deposit, create Linear tickets, set up Dropbox. Three independent trackers exist — client_tracker, follow_up_tracker, payment_tracker — but nothing connects them. Wire them into a unified lifecycle pipeline: lead → proposal → follow-up → deposit → project setup → commissioning → handoff.

Read the existing code first.

## Context Files to Read First

- `openclaw/client_tracker.py` (324 lines)
- `openclaw/follow_up_tracker.py` (205 lines)
- `openclaw/payment_tracker.py` (224 lines)
- `openclaw/project_template.py` (22-issue Linear template)
- `openclaw/dropbox_integration.py`
- `openclaw/daily_briefing.py`

## Prompt

### 1. Understand Each Tracker's Interface

Before writing the coordinator, read all three trackers carefully:

**`client_tracker.py`**: How does it create and store client entries? What fields does it track? What methods does it expose for querying and updating client status?

**`follow_up_tracker.py`**: How does it schedule follow-ups? What Redis key pattern does it use? What methods exist for `get_due_today()`, `mark_sent()`, `cancel_remaining()`? If any of these methods are missing — add them now.

**`payment_tracker.py`**: How does it watch for payments? What does `watch_deposit()` do? How does it detect payment confirmation from emails? What Redis key pattern does it use?

**`project_template.py`**: What are the 22 issues? What are the 4 phases? What fields does `create_project()` take?

Map each tracker's public interface. The lifecycle coordinator will call these methods — it must not reach into their internals.

### 2. Build the Lifecycle Coordinator (`openclaw/lifecycle_coordinator.py`)

A single module that orchestrates all phases from lead to handoff:

```python
class LifecycleCoordinator:
    """
    Manages the full client lifecycle. Calls into client_tracker, follow_up_tracker,
    payment_tracker, and project_template at the right phase transitions.
    """
    
    def transition(self, project_id: str, new_phase: str, metadata: dict = {}):
        """
        Move a project to the next phase. Triggers all phase-entry actions.
        Validates the transition is legal (can't skip phases).
        
        Phases: lead → proposal_sent → follow_up_active → deposit_pending → 
                project_setup → commissioning → handoff → complete
        """
        
    def get_all_active(self) -> list[dict]:
        """Returns all projects not in 'complete' phase, with current phase and key dates."""
```

**Phase 1 — Lead** (`transition(project_id, "lead")`):
- `client_tracker.create(project_id, client_data)` — create client entry
- Create Linear ticket in "Leads" project
- Log lead source (email/voice/referral)

**Phase 2 — Proposal Sent** (`transition(project_id, "proposal_sent")`):
- `follow_up_tracker.schedule_follow_ups(project_id, client_email, today)` — Day 3, Day 7, Day 14
- Create Dropbox folder structure (see Section 3)
- Log proposal sent date in client_tracker

**Phase 3 — Follow-Up Active** (automatic — fires when proposal_sent and follow-ups are scheduled):
- No explicit action — follow_up_tracker handles this phase autonomously
- `lifecycle_coordinator` monitors for deposit receipt to trigger Phase 4

**Phase 4 — Deposit Received** (`transition(project_id, "deposit_pending")` → auto-transition to `project_setup` on payment):
- `payment_tracker.watch_deposit(project_id, client_name, expected_amount)` — start watching
- When `payment_tracker.confirm_received()` is called → lifecycle_coordinator auto-transitions to project_setup

**Phase 5 — Project Setup** (`transition(project_id, "project_setup")`):
- `follow_up_tracker.cancel_remaining(project_id)` — proposal accepted, no more follow-ups
- `project_template.create_project(project_id, client_data)` — create 22-issue Linear project
- Send kickoff email to client: "We're officially started!"
- Notify Matt via iMessage: "{client_name} deposit confirmed — project setup complete"

**Phase 6 — Commissioning** (`transition(project_id, "commissioning")`):
- Generate commissioning checklist from system design
- Track device-by-device completion (via system shell status from Auto-26)

**Phase 7 — Handoff** (`transition(project_id, "handoff")`):
- Client receives: access codes, concierge knowledge base URL, support terms PDF
- `payment_tracker.watch_final_payment(project_id, remaining_balance)` — watch for last payment
- Schedule 30-day check-in

**Phase 8 — Complete** (`transition(project_id, "complete")`):
- Archive Linear project
- Move Dropbox folder to Archive/
- Update client_tracker status to "complete"

### 3. Standardized Dropbox Folder Structure

On proposal sent (Phase 2), create this structure via `dropbox_integration.py`:

```
Symphony Smart Homes/Projects/{Client Name} — {Address}/
├── Client/          ← shared with client (one link, never changes)
│   ├── Proposals/
│   ├── Agreements/
│   └── Documents/
├── Internal/        ← Symphony-only
│   ├── Photos/
│   ├── Drawings/
│   └── Notes/
└── Archive/
```

```python
def create_project_folders(project_id: str, client_name: str, address: str) -> str:
    """
    Creates folder structure, generates share link for Client/ folder.
    Stores share link in client_tracker under project_id.
    Returns the share link URL.
    The share link must NEVER change — store it immediately and reuse it.
    """
```

Use Dropbox credentials from `.env`: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`.

### 4. Wire Follow-Up Tracker

Ensure `follow_up_tracker.py` has these methods (add if missing):

```python
def schedule_follow_ups(self, project_id: str, client_email: str, proposal_sent_date: date):
    # Schedules Day 3, Day 7, Day 14 follow-ups
    # Redis key: followup:{project_id}:{day} → {status, scheduled_date, client_email}

def get_due_today(self) -> list[dict]:
    # Returns follow-ups where scheduled_date == today and status == "pending"
    # Used by daily briefing

def mark_sent(self, project_id: str, day: int):
    # Sets followup:{project_id}:{day}.status = "sent"
    # Logs send timestamp

def cancel_remaining(self, project_id: str):
    # Sets all pending follow-ups for project to "cancelled"
    # Called when deposit is received
```

Follow-up email content (use these exact templates):
- Day 3: "Just wanted to make sure the proposal came through clearly. Happy to answer any questions."
- Day 7: Reference one specific detail from their project — pull from client_tracker project data.
- Day 14: "I want to make sure I'm not missing anything on your end. If timing has changed, no problem at all."

### 5. Wire Payment Tracker

Ensure `payment_tracker.py` has these methods (add if missing):

```python
def watch_deposit(self, project_id: str, client_name: str, expected_amount: float):
    # Stores: payment:{project_id}:deposit → {expected_amount, status: "watching", started: now}

def check_payment_email(self, email_body: str, project_id: str) -> bool:
    # Scans email for: "wire transfer", "ACH", "check", "payment sent", "deposit"
    # + amount match within 5% of expected_amount
    # Returns True if likely payment confirmation

def confirm_received(self, project_id: str, payment_type: str, amount: float):
    # Marks payment confirmed
    # Calls lifecycle_coordinator.transition(project_id, "project_setup")
    # Emits payment_received event to event bus (API-11)

def get_pending_payments(self) -> list[dict]:
    # Returns all payments with status "watching"
    # Used by daily briefing

def watch_final_payment(self, project_id: str, amount: float):
    # Same as watch_deposit but type = "final"
```

### 6. Wire into Daily Briefing (`openclaw/daily_briefing.py`)

Add a lifecycle section to the daily briefing. The briefing must include:

```python
# In daily_briefing.py — add lifecycle section
lifecycle_section = {
    "follow_ups_due_today": follow_up_tracker.get_due_today(),
    # [{project_id, client_name, day_number, project_value, client_email}]
    
    "overdue_follow_ups": follow_up_tracker.get_overdue(),
    # Follow-ups past scheduled_date, status still "pending"
    
    "pending_payments": payment_tracker.get_pending_payments(),
    # [{project_id, client_name, amount, type, days_since_proposal}]
    
    "active_projects": lifecycle_coordinator.get_all_active(),
    # [{project_id, client_name, phase, phase_start_date, next_action}]
}
```

Flag pending payments older than 3 days with a `[ATTENTION]` marker in the briefing.

### 7. Test with Topletz

Simulate the Topletz lifecycle from its current state (proposal sent, waiting on $34,609 deposit):

```python
# Topletz is currently in phase: proposal_sent
# Proposal was sent approximately 2 weeks ago
# Expected deposit: $34,609 (always derive from proposal data — do not hardcode)

# Step 1: Verify Topletz exists in client_tracker
# Step 2: Verify follow-ups are scheduled (even if some are already past due)
# Step 3: Simulate deposit receipt
payment_tracker.confirm_received("topletz", "deposit", 34609.00)

# Step 4: Verify lifecycle transitions to project_setup
# Step 5: Verify follow-ups are cancelled
# Step 6: Verify Linear project is created (or would be created — dry-run is OK)
# Step 7: Verify daily briefing includes Topletz in the lifecycle section
```

Run the simulation and verify each step produces the expected output. Fix any broken transitions.

Use standard logging. All log messages prefixed with `[lifecycle]`.
