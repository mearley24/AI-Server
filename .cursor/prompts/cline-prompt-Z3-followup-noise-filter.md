# Cline Prompt Z3 — Follow-Up Noise Filter

## Context
The dashboard follow-ups tile shows 25 active / 24 overdue, but most entries are marketing newsletters and vendor spam — not real client follow-ups. The root cause is the email categorizer misclassifying these, but fixing that is a larger effort. This prompt adds a noise filter at the dashboard API level to suppress non-client senders.

File to edit: `cortex/dashboard.py`

## Scope — ONLY touch the `/api/followups` endpoint in dashboard.py. No other files.

---

## 1. Add a noise filter constant

Near the top of `dashboard.py` (after the existing `FOLLOW_UPS_DB_CANDIDATES` list), add this block:

```python
# Senders that are NOT real client follow-ups — vendors, newsletters, automated systems.
# Matched case-insensitively against client_name OR client_email.
FOLLOWUP_NOISE_SENDERS = {
    "somfy", "control4", "autodesk", "phoenix marketing", "screen innovations",
    "shade innovations", "cablewholesale", "ups", "zapier", "the futurist",
    "linq", "snapone", "snap one", "netlify", "hiscox", "vyde",
    "d-tools", "billing", "no-reply", "noreply", "mailer-daemon",
    "donotreply", "do-not-reply", "unsubscribe",
}

# Subject patterns that indicate automated/marketing emails (case-insensitive substrings)
FOLLOWUP_NOISE_SUBJECTS = {
    "webinar", "unsubscribe", "newsletter", "recommended for you",
    "your order", "credit memo", "payment received", "your shipment",
    "trial has ended", "financial report", "see your business insights",
    "sandbox", "new properties recommended",
}
```

## 2. Add a helper function

Right after the constants, add:

```python
def _is_followup_noise(followup: dict) -> bool:
    """Return True if a follow-up entry looks like vendor/marketing noise."""
    name = (followup.get("client_name") or "").lower()
    email = (followup.get("client_email") or "").lower()
    subject = (followup.get("last_client_subject") or "").lower()

    for noise in FOLLOWUP_NOISE_SENDERS:
        if noise in name or noise in email:
            return True
    for noise in FOLLOWUP_NOISE_SUBJECTS:
        if noise in subject:
            return True
    return False
```

## 3. Apply the filter in the `/api/followups` endpoint

Find the line that builds `recent_followups` (the 30-day filter). Right after that list comprehension, add a second filter to remove noise:

Change:
```python
            recent_followups = [
                f for f in followups
                if (f.get("last_client_ts") or "") >= thirty_days_ago
            ]
```

To:
```python
            recent_followups = [
                f for f in followups
                if (f.get("last_client_ts") or "") >= thirty_days_ago
                and not _is_followup_noise(f)
            ]
```

## 4. Also filter the email subject list

In the `/api/emails` endpoint, the dashboard shows up to 5 email subjects even when the unread count is 0. These should only show unread emails, not all recent emails.

Find the line:
```python
            recent_emails = [
                e for e in emails
                if (e.get("received_at") or e.get("date") or "") >= seven_days_ago
            ]
```

Change it to only include unread emails in the list (the count already filters for unread):
```python
            recent_emails = [
                e for e in emails
                if (e.get("received_at") or e.get("date") or "") >= seven_days_ago
                and not e.get("read") and not e.get("processed")
            ]
```

This way when unread count is 0, the list will also be empty — no confusing stale subjects.

## 5. Verify and commit

```zsh
python3 -c "import cortex.dashboard" 2>/dev/null || python3 -c "exec(open('cortex/dashboard.py').read())"
```

Make sure there are no syntax errors.

```zsh
git add -A
git commit -m "fix: filter vendor noise from follow-ups, hide read emails from dashboard"
git push origin main
```

## DO NOT:
- Modify the follow_up_tracker.py or any OpenClaw files
- Change the follow_ups.db schema
- Change any HTML/CSS in the dashboard
- Add any new dependencies
