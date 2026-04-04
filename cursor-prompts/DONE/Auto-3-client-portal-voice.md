# Auto-3: Client Portal + Voice Receptionist Enhancement

## Context Files to Read First
- voice-receptionist/ directory
- docker-compose.yml

## Prompt

Build a simple client portal and enhance the voice receptionist:

1. Client Portal (new directory: client-portal/):
   - Simple static HTML + JS site (no framework needed)
   - Reads project data from a JSON API endpoint
   - Shows: project name, phase, next steps, recent documents (Dropbox links), timeline
   - Password-protected per client (simple bcrypt hash)
   - Mobile-friendly
   - Add a docker-compose service for it (nginx or python http.server)

2. Voice Receptionist Enhancement (voice-receptionist/):
   - Read the existing voice-receptionist code
   - Add capabilities:
     - "What's the status of my project?" — looks up caller's phone number, returns project status
     - "I need to schedule a walkthrough" — creates a calendar event request, notifies Matt
     - "Can I speak with Matt?" — forwards to Matt's phone if available, takes message if not
   - Connect to the email-monitor's client database for caller identification
   - Log all calls and outcomes

Commit each separately. Push to origin main.
