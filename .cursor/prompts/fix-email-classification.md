# Fix Email Classification — Stop Newsletter Noise, Proper Routing

## Problem
The email classifier has three issues causing noise:
1. Newsletters/marketing emails fall through to GENERAL because no keyword matches
2. Some newsletters contain "smart home" and match CLIENT_INQUIRY
3. The orchestrator flags every GENERAL email at confidence 40 as `needs_approval`, flooding the system with approval requests for junk

OpenClaw logs show "The Futurist", "Vyde", "D-Tools Cloud notifications", "Uphold", "New fiber website", "11 New properties", "sandbox expires" all being flagged as potential_lead or needs_approval. None of these should reach the orchestrator's attention.

## Fix 1: Expand routing_config.json

Edit `email-monitor/routing_config.json`:

### Add to `domain_routes`:
```json
{
  "thefuturist.co": "Marketing/Newsletter",
  "substack.com": "Marketing/Newsletter",
  "beehiiv.com": "Marketing/Newsletter",
  "mailchimp.com": "Marketing/Newsletter",
  "sendgrid.net": "Marketing/Newsletter",
  "constantcontact.com": "Marketing/Newsletter",
  "hubspot.com": "Marketing/Newsletter",
  "klaviyo.com": "Marketing/Newsletter",
  "convertkit.com": "Marketing/Newsletter",
  "drip.com": "Marketing/Newsletter",
  "brevo.com": "Marketing/Newsletter",
  "cloud.d-tools.com": "Vendor/D-Tools",
  "noreply@d-tools.com": "Vendor/D-Tools",
  "notifications@d-tools.com": "Vendor/D-Tools",
  "uphold.com": "Personal/Crypto",
  "coinbase.com": "Personal/Crypto",
  "kraken.com": "Personal/Crypto",
  "binance.com": "Personal/Crypto",
  "zillow.com": "Marketing/Real-Estate",
  "redfin.com": "Marketing/Real-Estate",
  "realtor.com": "Marketing/Real-Estate",
  "trulia.com": "Marketing/Real-Estate",
  "apartments.com": "Marketing/Real-Estate",
  "buildingconnected.com": "Bids/Active",
  "procore.com": "Bids/Active",
  "notifications@linear.app": "Notes",
  "updates@linear.app": "Notes",
  "noreply@github.com": "Notes",
  "notifications@github.com": "Notes",
  "no-reply@zapier.com": "Notes",
  "notify@stripe.com": "Banking/Payments",
  "fiberoptics.com": "Marketing",
  "newsletter": "Marketing/Newsletter"
}
```

Keep all existing domain_routes — only ADD new ones.

### Add to `marketing_patterns`:
```json
[
  "newsletter", "digest", "weekly roundup", "monthly update",
  "you might like", "recommended for you", "new properties",
  "now live on", "just launched", "introducing", "announcing",
  "sale ends", "limited time", "exclusive offer", "promo code",
  "black friday", "cyber monday", "flash sale",
  "view in browser", "email preferences", "update preferences",
  "manage subscriptions", "opt out", "manage notifications"
]
```

Again, APPEND to existing patterns, don't replace.

### Add `active_clients` section:
```json
{
  "active_clients": {
    "stopletz1@gmail.com": "Topletz - 84 Aspen Meadow"
  }
}
```

### Add `suppress_notifications` for domains that should NEVER trigger alerts:
```json
{
  "suppress_notifications": [
    "Marketing", "Marketing/Newsletter", "Marketing/Real-Estate",
    "Notes", "Personal/Crypto", "Banking", "Banking/Payments"
  ]
}
```

## Fix 2: Add MARKETING category to monitor.py

Edit `email-monitor/monitor.py` — add a MARKETING category BEFORE CLIENT_INQUIRY in the CATEGORIES dict so it matches first:

```python
CATEGORIES = {
    "BID_INVITE": { ... },  # keep existing
    "MARKETING": {
        "keywords": [
            "unsubscribe", "view in browser", "email preferences",
            "newsletter", "weekly digest", "monthly update",
            "recommended for you", "new properties", "now live on",
            "introducing", "announcing", "flash sale", "promo code",
            "manage subscriptions", "opt out", "update preferences",
            "you might like", "just launched", "limited time",
        ],
        "priority": "none",
    },
    "CLIENT_INQUIRY": { ... },  # keep existing
    ...
}
```

The key: MARKETING must be checked BEFORE CLIENT_INQUIRY so "smart home newsletter" matches MARKETING (via "newsletter" keyword) before it matches CLIENT_INQUIRY (via "smart home").

Also add a priority check in the routing — if priority is "none", skip notification entirely.

## Fix 3: Domain-route check BEFORE keyword categorization

Edit `email-monitor/monitor.py` `categorize_email()`:

```python
def categorize_email(subject: str, sender: str, body_snippet: str = "") -> tuple[str, str]:
    # 1. Active client check (highest priority)
    if sender.lower() in _ACTIVE_CLIENT_EMAILS:
        return "ACTIVE_CLIENT", "high"
    
    # 2. Domain route check — if sender domain is routed, use that category
    sender_domain = sender.lower().split("@")[-1] if "@" in sender else ""
    domain_routes = _get_domain_routes()  # load from routing_config.json
    if sender_domain in domain_routes:
        route = domain_routes[sender_domain]
        if route.startswith("Marketing") or route in ("Notes", "Personal/Crypto", "Banking", "Banking/Payments"):
            return "MARKETING", "none"
        elif route.startswith("Vendor"):
            return "VENDOR", "low"
        elif route.startswith("Bids"):
            return "BID_INVITE", "high"
    
    # 3. Marketing pattern check — body/subject contains marketing signals
    marketing_patterns = _get_marketing_patterns()
    text_lower = f"{subject} {body_snippet}".lower()
    if any(p in text_lower for p in marketing_patterns):
        return "MARKETING", "none"
    
    # 4. Keyword categorization (existing logic)
    text = f"{subject} {sender} {body_snippet}".lower()
    for category, config in CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in text:
                return category, config["priority"]
    
    return "GENERAL", "low"
```

Add helper functions to load domain_routes and marketing_patterns from routing_config.json (cache in memory, reload every 5 minutes).

## Fix 4: Orchestrator — skip MARKETING and suppress categories

Edit `openclaw/orchestrator.py` in `check_emails()`:

When processing emails, skip MARKETING emails entirely:
```python
# After fetching emails
for em in new_emails:
    category = em.get("category", "GENERAL")
    
    # Skip marketing/newsletter — don't log decisions, don't notify
    if category == "MARKETING":
        continue
    
    # Skip routed vendor emails unless they're order confirmations
    if category == "VENDOR" and not any(kw in em.get("subject","").lower() for kw in ["order", "shipping", "tracking", "invoice"]):
        continue
    
    # ... rest of email processing
```

## Fix 5: Job Worker — filter potential leads better

Edit `openclaw/job_worker.py` `scan_emails_for_leads()`:

The job worker fetches CLIENT_INQUIRY emails and flags them as potential_lead. But with the classifier fix above, fewer newsletters will reach CLIENT_INQUIRY. Add an extra guard:

```python
# In scan_emails_for_leads, after getting the email list:
for email in emails:
    sender_addr = email.get("sender", "").strip()
    sender_domain = sender_addr.split("@")[-1] if "@" in sender_addr else ""
    
    # Skip known non-client domains
    if sender_domain in domain_routes or sender_domain in marketing_domains:
        continue
    
    # Skip if sender matches any marketing pattern
    if any(p in email.get("subject","").lower() for p in ["newsletter", "unsubscribe", "digest"]):
        continue
    
    # ... existing lead detection logic
```

## Fix 6: Confidence — stop flagging GENERAL as needs_approval

Edit `openclaw/confidence.py`:

The issue is GENERAL emails get confidence 40 which triggers `needs_approval`. For GENERAL category, if the email isn't from a known client, set confidence to 60 (act but review) instead of 40 (flag for approval). Only flag at 40 if the email is from an unknown sender AND contains project-related keywords.

```python
def score_email_action(email_data, classification, known_client=False):
    if known_client:
        return 85  # High confidence for known clients
    
    if classification == "MARKETING":
        return 95  # Auto-file, never flag
    
    if classification == "VENDOR":
        return 70  # Act (route), review queue
    
    if classification == "GENERAL":
        # Check if it looks like it needs attention
        subject = email_data.get("subject", "").lower()
        project_keywords = ["84 aspen", "topletz", "proposal", "agreement", "contract", "payment", "deposit", "prewire", "install"]
        if any(kw in subject for kw in project_keywords):
            return 45  # Might be important, flag for review
        return 65  # Probably junk, file and move on
    
    if classification == "CLIENT_INQUIRY":
        return 50  # Could be real, review
    
    if classification == "ACTIVE_CLIENT":
        return 90  # Always act
    
    return 60  # Default
```

## Verification

After changes, rebuild email-monitor and restart openclaw:
```bash
docker compose up -d --build email-monitor
docker compose restart openclaw
sleep 30

echo "=== Email classification test ==="
docker exec email-monitor python3 -c "
from monitor import categorize_email
tests = [
    ('This static electricity news is shocking', 'newsletter@thefuturist.co', ''),
    ('Don\\'t Miss These April Tax Deadlines', 'support@vyde.io', ''),
    ('High Cliff TV/Receiver Update', 'cloud@d-tools.com', ''),
    ('Now live on Uphold: TRIA', 'no-reply@uphold.com', ''),
    ('RE: Updated Proposal — 84 Aspen Meadow', 'stopletz1@gmail.com', ''),
    ('New smart home consultation request', 'john@gmail.com', 'interested in home automation'),
    ('11 New properties recommended for you', 'alerts@zillow.com', ''),
    ('Scan this (you literally can\\'t)', 'newsletter@thefuturist.co', ''),
]
for subj, sender, body in tests:
    cat, pri = categorize_email(subj, sender, body)
    print(f'{cat:20s} {pri:8s} | {sender:40s} | {subj[:50]}')
"

echo ""
echo "=== Needs_approval count (should be near zero for marketing) ==="
docker exec redis redis-cli LRANGE events:log 0 50 | grep needs_approval | wc -l
```

Expected:
- The Futurist → MARKETING, none
- Vyde → VENDOR, low (or MARKETING)
- D-Tools Cloud → VENDOR, low
- Uphold → MARKETING, none
- Steve Topletz → ACTIVE_CLIENT, high
- New consultation → CLIENT_INQUIRY, high
- Zillow → MARKETING, none
- needs_approval count: 0 or near 0 for the next tick
