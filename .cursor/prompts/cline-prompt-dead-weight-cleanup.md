---
description: Kill Stripe dead code, clean OpenWebUI refs, migrate Supabase functions to Bob
---

# Dead Weight Cleanup — Stripe, OpenWebUI Refs, Supabase Migration

## Context

Matt is centralizing everything through Bob (AI-Server). Three external dependencies need to be eliminated:

1. **Stripe** — Replaced by FirstBank ACH. Dead code sitting in the repo.
2. **OpenWebUI** — Container already removed, but references linger in 10+ files.
3. **Supabase** — Currently handles symphonysh contact form + appointment booking. Needs to be migrated to Bob's existing services (notification-hub, calendar-agent, client-portal).

## Part 1: Kill Stripe Dead Code

### Delete the file
```
rm openclaw/stripe_billing.py
```

### Remove Stripe references from orchestrator

In `openclaw/orchestrator.py`:
1. Remove the `events:stripe_payment` Redis subscription (around line 290)
2. Remove the `handle_stripe_payment` method (around line 1130)
3. Remove the `elif channel == "events:stripe_payment"` handler (around line 303)
4. Remove the `from stripe_billing import StripeBilling` import (around line 1063)

### Remove Stripe webhook

In `openclaw/webhook_server.py`:
1. Remove the entire `stripe_webhook` endpoint (the `/webhook/stripe` route and its function, around line 142-163)
2. Remove the `from stripe_billing import stripe_billing` import

### Remove Stripe iMessage reference

In `scripts/imessage-server.py`:
1. Find and remove the `events:stripe_payment` Redis publish (around line 1024) — this was a placeholder/mock

### Remove Stripe env vars

In `.env.example`, remove:
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PUBLISHABLE_KEY`

## Part 2: Clean OpenWebUI References

OpenWebUI container was removed but config references remain. Clean these:

### mission_control/main.py (line 48)
Remove the OpenWebUI entry from the services list:
```python
{"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000, "compose": "openwebui"},
```

### cortex/dashboard.py (line 117)
Remove the OpenWebUI entry:
```python
{"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000, "optional": True},
```

### docker-compose.telegram.yml (lines 20-22)
Remove these env vars:
```yaml
- OPENWEBUI_BASE_URL=${OPENWEBUI_BASE_URL:-http://host.docker.internal:3000}
- OPENWEBUI_API_KEY=${OPENWEBUI_API_KEY:-}
- OPENWEBUI_MODEL=${OPENWEBUI_MODEL:-}
```

### setup/openclaw/openclaw.json
Remove the `open_webui` config block (lines 82-91).

### BOB_TRAINING.md (line 67)
Remove the OpenWebUI row from the port table.

### .env.example
Remove any `OPENWEBUI_*` env vars.

### DO NOT touch these (historical/docs only):
- `STATUS_REPORT.md` — historical record, leave it
- `knowledge/incidents/` — incident reports, leave them
- `AGENTS.md` — documentation, leave it
- `setup/openclaw/migration_plan.md` — historical planning doc

## Part 3: Migrate Supabase → Bob

The symphonysh website uses Supabase for:
1. **Contact form** — POSTs to `send-contact-email` edge function → sends email via Resend API
2. **Appointment booking** — POSTs to `create-appointment` → stores in Supabase DB → sends confirmation emails via Resend
3. **Available time slots** — Queries Supabase DB for booked appointments

All of this can be handled by Bob's existing services. The key insight: Supabase is just a middleman between the website and email. Bob already has notification-hub (email via Zoho), calendar-agent, and client-portal (SQLite DB).

### Step 3a: Add website API endpoints to client-portal

The `client-portal` service (port 8096) already has a FastAPI app with SQLite. Add these endpoints to `client-portal/main.py`:

```python
# ── Website Form Handlers (replaces Supabase edge functions) ─────────

class ContactSubmission(BaseModel):
    name: str
    email: str
    message: str

class AppointmentRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    date: str
    time: str
    service: str
    address: str = ""
    notes: str = ""

SERVICES = [
    {"id": "home-integration", "name": "Home Automation"},
    {"id": "audio-entertainment", "name": "Audio & Entertainment"},
    {"id": "smart-lighting", "name": "Smart Lighting"},
    {"id": "shades", "name": "Smart Shades"},
    {"id": "networking", "name": "Networking"},
    {"id": "climate-control", "name": "Climate Control"},
    {"id": "security-systems", "name": "Security Systems"},
    {"id": "maintenance", "name": "Troubleshooting & Maintenance"},
    {"id": "matterport-scan", "name": "Matterport Scan"},
]


@app.post("/api/contact")
async def handle_contact(submission: ContactSubmission):
    """Handle contact form submission — replaces Supabase send-contact-email."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO contact_submissions (name, email, message, created_at) VALUES (?, ?, ?, ?)",
            (submission.name, submission.email, submission.message, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.warning("contact_db_error: %s", e)

    # Notify Matt via notification-hub
    import httpx
    hub_url = os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{hub_url}/notify", json={
                "title": "New Contact Form Submission",
                "body": f"Name: {submission.name}\nEmail: {submission.email}\nMessage: {submission.message}",
                "priority": "normal",
                "source": "website_contact",
            })
    except Exception as e:
        logger.warning("notification_error: %s", e)

    # Send confirmation email to customer via Zoho
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{hub_url}/notify", json={
                "title": "Thank you for contacting Symphony Smart Homes",
                "body": f"Dear {submission.name},\n\nThank you for reaching out. We've received your message and will respond within 1-2 business days.\n\nBest regards,\nSymphony Smart Homes",
                "priority": "normal",
                "source": "website_contact_confirmation",
                "channel": "email",
                "recipient": submission.email,
            })
    except Exception as e:
        logger.warning("confirmation_email_error: %s", e)

    return {"success": True}


@app.post("/api/appointment")
async def handle_appointment(appt: AppointmentRequest):
    """Handle appointment booking — replaces Supabase create-appointment."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO appointments
               (name, email, phone, date, time, service, address, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (appt.name, appt.email, appt.phone, appt.date, appt.time,
             appt.service, appt.address, appt.notes,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.error("appointment_db_error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create appointment")

    service_name = next((s["name"] for s in SERVICES if s["id"] == appt.service), appt.service)

    # Notify Matt
    import httpx
    hub_url = os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{hub_url}/notify", json={
                "title": "New Appointment Booking",
                "body": f"Service: {service_name}\nName: {appt.name}\nEmail: {appt.email}\nPhone: {appt.phone}\nDate: {appt.date} at {appt.time}\nAddress: {appt.address}\nNotes: {appt.notes}",
                "priority": "high",
                "source": "website_appointment",
            })
    except Exception as e:
        logger.warning("notification_error: %s", e)

    # Send confirmation to customer
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{hub_url}/notify", json={
                "title": "Appointment Confirmed — Symphony Smart Homes",
                "body": f"Hi {appt.name},\n\nYour {service_name} appointment has been confirmed for {appt.date} at {appt.time}.\n\nAddress: {appt.address or 'TBD'}\n\nWe'll reach out if we need any additional details.\n\nSymphony Smart Homes\n(970) 519-3013",
                "priority": "normal",
                "source": "website_appointment_confirmation",
                "channel": "email",
                "recipient": appt.email,
            })
    except Exception as e:
        logger.warning("confirmation_email_error: %s", e)

    return {"success": True}


@app.get("/api/available-slots")
async def get_available_slots(date: str):
    """Return available appointment time slots for a given date."""
    all_slots = [
        "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
        "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
        "15:00", "15:30", "16:00", "16:30",
    ]
    conn = _get_conn()
    try:
        booked = conn.execute(
            "SELECT time FROM appointments WHERE date = ?", (date,)
        ).fetchall()
        booked_times = {row["time"] for row in booked}
        available = [t for t in all_slots if t not in booked_times]
        return {"date": date, "available_slots": available}
    except Exception:
        return {"date": date, "available_slots": all_slots}
```

### Step 3b: Add CORS middleware to client-portal

At the top of `client-portal/main.py`, add CORS so the Cloudflare Pages site can call it:

```python
from fastapi.middleware.cors import CORSMiddleware

# After app = FastAPI(...)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://symphonysh.com", "https://www.symphonysh.com", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Step 3c: Add database tables to client-portal init

In `client-portal/main.py`, in the `_init_db()` function, add these tables:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS contact_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT DEFAULT '',
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        service TEXT NOT NULL,
        address TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
""")
```

### Step 3d: Expose client-portal externally

In `docker-compose.yml`, the client-portal service needs to be accessible from the internet (Cloudflare Pages will call it). Check if it already has a port mapping. If not, add:

```yaml
ports:
  - "127.0.0.1:8096:8096"
```

Matt will need to set up a Cloudflare Tunnel or Tailscale Funnel to expose port 8096 to the internet with HTTPS. **Note this in a comment** — the website needs to reach Bob's API.

### Step 3e: Add httpx to client-portal requirements

If `client-portal/requirements.txt` doesn't have `httpx`, add it.

## Part 4: Update notification-hub for email routing

The notification-hub currently sends via iMessage and Zoho. The contact form confirmation emails need to go to specific recipients (the customer). Check if notification-hub's `/notify` endpoint supports a `recipient` and `channel` field. If not, add support:

In `notification-hub/main.py` or `notification-hub/hermes.py`, add handling for:
- `channel: "email"` + `recipient: "customer@example.com"` → send via Zoho to that specific address

If the Hermes email function already supports arbitrary recipients, no changes needed — just verify.

## Verification

After all changes:

1. `grep -rn "stripe_billing\|STRIPE" --include="*.py" | grep -v __pycache__ | grep -v test | grep -v ".env"` — should return nothing (except maybe .env.example if you left a comment)
2. `grep -rn "openwebui\|OPENWEBUI" --include="*.py" --include="*.yml" --include="*.json" | grep -v __pycache__ | grep -v STATUS_REPORT | grep -v AGENTS | grep -v migration_plan | grep -v incidents | grep -v BACKLOG | grep -v cursor-prompts` — should return nothing
3. `ls openclaw/stripe_billing.py` — should not exist
4. `curl -X POST http://localhost:8096/api/contact -H 'Content-Type: application/json' -d '{"name":"Test","email":"test@test.com","message":"Test"}'` — should return `{"success": true}`
5. `curl http://localhost:8096/api/available-slots?date=2026-04-15` — should return available time slots

## What This Enables

- **Zero Stripe code** — ACH is the payment method, no processor needed
- **Zero OpenWebUI references** — clean codebase, no ghost configs
- **Supabase functions replaced** — contact form and booking routed through Bob
- **After website update** (separate symphonysh PR): point the frontend at Bob's client-portal API instead of Supabase, then delete the Supabase project entirely
- **Everything runs through Bob** — one system, one location, fully centralized

## IMPORTANT: This prompt handles the AI-Server (Bob) side only

The symphonysh website still needs a separate update to point its API calls at Bob instead of Supabase. That's a symphonysh repo change — update the fetch URLs in:
- `src/pages/Contact.tsx`
- `src/utils/appointments/index.ts`
- `src/utils/appointments/googleCalendar/timeSlots.ts`
- `src/utils/appointments/dbUtils.ts`

After THIS prompt is done and verified, a follow-up prompt will update symphonysh. Then Supabase can be deleted.

Commit message: `feat: kill stripe dead code, clean openwebui refs, add website API to client-portal (supabase replacement)`
