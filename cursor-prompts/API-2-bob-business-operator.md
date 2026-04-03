# API-2: Bob as Full Business Operator

## Context Files to Read First
- scripts/imessage-server.py (the full iMessage bridge — read ALL of it)
- email-monitor/monitor.py
- email-monitor/router.py
- email-monitor/routing_config.json
- openclaw/auto_responder.py
- openclaw/proposal_checker.py

## Prompt

Build Bob into a full autonomous business operator:

1. Smart Auto-Responder (upgrade openclaw/auto_responder.py):
   - When an active client emails, Bob reads the full email (not just snippet)
   - Checks the email against the project's confirmed decisions (use proposal_checker.CONFIRMED_DECISIONS)
   - If the client is asking about something already decided: draft a response referencing the decision
   - If the client is asking something new: draft a response flagging it for Matt's review
   - If the client sent a file/attachment: note it and flag for Matt
   - All drafts go to Zoho (mode: draft) and Bob sends Matt an iMessage: "[DRAFT] Response to [client] re: [subject] — review in Zoho"
   - Every product/SKU in the draft must be hyperlinked to its product page
   - No version numbers in client-facing content

2. Follow-Up Tracker (new file: openclaw/follow_up_tracker.py):
   - Track all client emails and responses
   - If a client email goes unanswered for 4+ hours during business hours (8am-6pm MDT): iMessage Matt "[OVERDUE] No response to [client] — [subject] from [time]"
   - If Matt sends an email to a client and gets no reply in 48 hours: iMessage Matt "[FOLLOW UP] [client] hasn't replied to [subject] sent [date]"
   - Store tracking data in SQLite at /data/email-monitor/follow_ups.db
   - Run as part of the email-monitor scan cycle

3. Invoice/Payment Tracker (new file: openclaw/payment_tracker.py):
   - Track deposit status per project from routing_config.json pricing data
   - When a deposit is due (agreement signed but no payment received in 7 days): alert Matt
   - When payment arrives (detect in email from bank/payment processor): update status
   - iMessage Matt with payment confirmations

4. Enhance imessage-server.py commands:
   - "draft to [client]" — Bob drafts an email to the client, asks Matt what to say
   - "follow ups" — lists all overdue follow-ups
   - "payments" — lists payment status per project
   - "what did [client] say" — searches emails and summarizes latest from that client
   - "schedule walkthrough with [contact]" — creates calendar event and sends email

Commit each piece. Push to origin main.
