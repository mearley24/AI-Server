# Scope Tracker Pipeline — Email → Flag → Linear → Document Update

## Problem
When a client emails a question or scope change, it gets routed to the project folder but nothing happens downstream. Documents go stale. Linear issues don't update. Changes get lost until someone manually catches them.

## What This Builds
An automated pipeline where:
1. Client email arrives → email-monitor classifies it
2. If it's a **scope change**, **question**, or **dispute** → auto-creates a Linear issue tagged to the project
3. Linear issue stays **open** until explicitly resolved (via reply email, Matt approval, or manual close)
4. When resolved, the system flags which documents need updating (deliverables, agreement, TV recommendations)
5. Matt reviews and approves → Bob regenerates the documents with the change incorporated
6. Updated documents auto-publish to Dropbox Client folder (replace in place, same link)

## Architecture

### Step 1: Email Classification Enhancement

Edit `openclaw/orchestrator.py` `check_emails()`:

After the existing email classification, add scope change detection:
```python
SCOPE_CHANGE_KEYWORDS = [
    "change", "remove", "add", "instead", "swap", "replace",
    "don't want", "cancel", "upgrade", "downgrade", "reduce",
    "different", "switch to", "go with", "prefer", "revised",
    "how about", "what if", "can we", "is it possible"
]
QUESTION_KEYWORDS = [
    "question", "clarify", "explain", "what does", "how does",
    "why", "when", "will you", "can you", "does this include",
    "what's included", "pricing for", "cost of"
]

async def classify_scope_impact(self, email):
    """Determine if an email implies a scope change or open question."""
    subject = (email.get("subject", "") + " " + email.get("body", "")).lower()
    
    is_scope_change = any(kw in subject for kw in SCOPE_CHANGE_KEYWORDS)
    is_question = any(kw in subject for kw in QUESTION_KEYWORDS)
    
    if is_scope_change or is_question:
        # Use LLM for nuanced classification
        prompt = f"Email from client about a smart home project. Classify as: SCOPE_CHANGE, QUESTION, APPROVAL, INFORMATION, or NONE.\nSubject: {email.get('subject')}\nBody: {email.get('body','')[:500]}"
        classification = await self._llm_classify(prompt)
        return classification
    return "NONE"
```

### Step 2: Auto-Create Linear Issues from Scope Changes

Create `openclaw/scope_tracker.py`:
```python
"""
Scope Tracker — creates Linear issues when client emails contain 
scope changes or open questions.

Each scope item is tracked as a Linear issue with:
- Title: "[SCOPE] Client request: {summary}"
- Label: "scope-change" or "client-question"  
- Project: linked to the client's Linear project
- Status: "Todo" until resolved
- Description: email excerpt + what documents may need updating
"""
```

Methods:
- `create_scope_issue(project_id, email, classification, summary)` → creates Linear issue via `linear_sync.py`
- `get_open_scope_issues(project_id)` → returns all unresolved scope items
- `resolve_scope_issue(issue_id, resolution, docs_to_update)` → marks resolved, flags docs
- `check_for_resolutions(project_id)` → scans recent emails for confirmations that resolve open issues

### Step 3: Document Update Flags

When a scope issue is resolved, determine which documents need regeneration:

```python
DOC_IMPACT_MAP = {
    "pricing": ["agreement", "deliverables"],
    "lighting": ["deliverables"],
    "mounting": ["tv_recommendations"],
    "network": ["deliverables"],
    "audio": ["deliverables"],
    "payment": ["agreement"],
    "timeline": ["agreement"],
    "tv": ["tv_recommendations"],
    "security": ["deliverables"],
    "warranty": ["agreement"],
}
```

When docs need updating, publish an event:
```python
await self.bus.publish("events:documents", {
    "type": "doc.update_needed",
    "employee": "bob",
    "title": f"Document update needed: {doc_name}",
    "data": {
        "project": project_name,
        "document": doc_name,
        "reason": resolution,
        "scope_issue_id": issue_id
    }
})
```

And send Matt a notification:
```python
# Via notification-hub
"[Topletz] Scope change resolved: {summary}. Documents needing update: {docs}. Reply UPDATE to regenerate, or handle manually."
```

### Step 4: Wire into Orchestrator Tick

Edit `openclaw/orchestrator.py`:

In `check_emails()`, after classification:
```python
# After classifying email
scope_impact = await self.classify_scope_impact(email)
if scope_impact in ("SCOPE_CHANGE", "QUESTION"):
    # Find the client's project
    project = self._find_project_for_sender(email.get("from", ""))
    if project:
        from scope_tracker import ScopeTracker
        tracker = ScopeTracker(self._linear_sync, self._job_mgr)
        await tracker.create_scope_issue(
            project_id=project["linear_project_id"],
            email=email,
            classification=scope_impact,
            summary=email.get("subject", "")[:100]
        )
        await self.bus.publish("events:clients", {
            "type": "client.scope_change_detected",
            "employee": "bob",
            "title": f"Scope change from {email.get('from')}: {email.get('subject')[:60]}",
        })
```

### Step 5: Project Association

The scope tracker needs to map email senders to projects. Use the client_tracker:

```python
def _find_project_for_sender(self, sender_email):
    """Look up which project this sender belongs to."""
    # Check routing config
    # Check jobs DB for client_email match
    # Check knowledge/topletz/project-config.yaml for email mapping
    # Return {project_name, linear_project_id, job_id}
```

### Step 6: Linear Sync Enhancement

Edit `openclaw/linear_sync.py` — add methods for creating scope issues:
```python
async def create_issue(self, project_id, title, description, labels=None):
    """Create a Linear issue in the project."""
    # Use Linear API
    
async def update_issue_status(self, issue_id, status):
    """Update issue status (Todo, In Progress, Done)."""
    
async def get_project_issues(self, project_id, label=None, status=None):
    """Get issues filtered by label and status."""
```

Check `linear_sync.py` for existing methods and adapt. The Linear connector is available at `linear_alt`.

## Verification

After implementation:
```bash
docker compose build --no-cache openclaw
docker compose up -d openclaw
sleep 30

# Check scope tracker exists
docker exec openclaw python3 -c "from scope_tracker import ScopeTracker; print('OK')"

# Check orchestrator has scope classification
docker logs openclaw 2>&1 | grep "scope_change\|classify_scope\|SCOPE" | tail -5
```

## Standard Going Forward
Every Symphony project gets:
1. Email routing to project folder (already works)
2. Scope change detection on every client email (this prompt)
3. Auto-Linear issue for unresolved items (this prompt)
4. Document update flags when resolved (this prompt)
5. Matt's approval before any regeneration (notification-hub)
6. Replace-in-place Dropbox publish (existing workflow)
