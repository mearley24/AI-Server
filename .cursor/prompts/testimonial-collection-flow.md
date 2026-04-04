# Testimonial Collection Flow

## Context
symphonysh.com has a `src/components/Testimonials.tsx` with placeholder data (3 cards, `// TODO: Replace with real client testimonials`). We need an automated way to collect real testimonials when a project completes.

The email-monitor and notification-hub services already handle email sending via Zoho. The follow-up tracker in OpenClaw already schedules Day 3/7/14 follow-ups. We're adding a final touchpoint: when the last payment is received or when a job moves to "Complete" status, automatically send a testimonial request email.

## Task 1: Testimonial Request Email Template

Create `proposals/email_templates/testimonial_request.md`:

```
Subject: Quick question about your project — {project_address}

Hi {client_first_name},

Now that everything's up and running at {project_address}, I wanted to check in — how's it all working for you?

If you have a moment, I'd really appreciate a quick sentence or two about your experience. It helps other homeowners in the valley know what to expect when they work with us.

You can reply to this email, or if it's easier, just click here:
{testimonial_link}

Either way — thanks for trusting us with your home. We're always here if anything needs attention.

Matt Earley
Symphony Smart Homes
(970) 519-3013
```

## Task 2: Testimonial Submission Page

Add a new route to symphonysh.com at `/review`:

Create `src/pages/Review.tsx`:
- Simple form: textarea for the quote, first name field, location dropdown (Vail, Beaver Creek, Edwards, Avon, Eagle, Other)
- Optional: "What did we do for you?" dropdown (Home Theater, Whole-Home Audio, Automation, Networking, Pre-Wire, TV Mounting, Other)
- Submit button POSTs to the Zapier webhook (same as scheduling, different tag/source field so the Zap can route it)
- After submit: "Thank you" message with a subtle ask: "Mind sharing on Google too?" with a direct link to the Google Business review page (when the GBP URL is available)
- Design: same dark aesthetic as the rest of the site, minimal, mobile-friendly
- No login required — the link in the email contains a query param like `?project=topletz` so we know which project it's from

Add the route in `src/App.tsx`:
```tsx
<Route path="/review" element={<Review />} />
```

## Task 3: Wire into Job Lifecycle

Edit `openclaw/orchestrator.py` or `openclaw/follow_up_tracker.py`:

When a job status changes to "complete" or "paid_in_full":
1. Wait 3 days (don't ask for a review the same day as final invoice)
2. Send the testimonial request email via email-monitor/Zoho
3. The email includes `https://www.symphonysh.com/review?project={job_slug}`
4. Log the event: `events:clients` / `client.testimonial_requested`

If no response in 7 days, send one gentle follow-up. Never send more than 2 requests total.

Add to the follow-up tracker's schedule types:
```python
FOLLOWUP_TYPES = {
    "proposal_3day": {...},
    "proposal_7day": {...},
    "proposal_14day": {...},
    "testimonial_3day": {"template": "testimonial_request", "max_sends": 1},
    "testimonial_followup_7day": {"template": "testimonial_followup", "max_sends": 1},
}
```

## Task 4: Zapier Webhook Handling

The testimonial form POSTs to the same Zapier catch hook but with a `source: "testimonial"` field. Document the payload shape:

```json
{
  "source": "testimonial",
  "project": "topletz",
  "quote": "The whole process was seamless...",
  "first_name": "Steve",
  "location": "Beaver Creek",
  "service_type": "Whole-Home Automation",
  "timestamp": "2026-04-04T12:00:00Z"
}
```

Matt can then:
1. Review the testimonial in Zoho/email
2. Approve it
3. Update `src/components/Testimonials.tsx` with the real quote (manual for now — future: auto-populate from Supabase)

## Task 5: Future — Auto-Populate from Supabase (Optional, skip for now)

Leave a comment in `Testimonials.tsx`:
```tsx
// FUTURE: Fetch approved testimonials from Supabase
// const { data } = await supabase.from('testimonials').select('*').eq('approved', true).limit(6)
// For now, manually update the TESTIMONIALS array below
```

## Files to Create/Edit

### In symphonysh repo:
- CREATE: `src/pages/Review.tsx` — testimonial submission form
- EDIT: `src/App.tsx` — add `/review` route
- EDIT: `src/components/Testimonials.tsx` — add future Supabase comment

### In AI-Server repo:
- CREATE: `proposals/email_templates/testimonial_request.md`
- CREATE: `proposals/email_templates/testimonial_followup.md` (gentler version)
- EDIT: `openclaw/follow_up_tracker.py` — add testimonial request to schedule types
- EDIT: `openclaw/orchestrator.py` — trigger testimonial flow on job completion

## Build
symphonysh repo: `npm ci && npm run build` and push to main (Cloudflare auto-deploys)
AI-Server repo: `docker compose build --no-cache openclaw && docker compose up -d openclaw`
