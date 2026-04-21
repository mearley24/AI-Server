You are working on AI-Server on Bob.

Goal
Finish the BlueBubbles → AI-Server integration so that:
- inbound BlueBubbles webhooks reliably become normalized message events,
- AI-Server can send replies back through BlueBubbles into the correct iMessage chats,
- routing/identity rules are explicit,
- there is basic monitoring/health for the BlueBubbles bridge,
- and a verification artifact + STATUSREPORT update capture the current state.

Assumptions
- BlueBubbles Server is already installed and running on a Mac associated with Bob’s iMessage account.
- AI-Server is the orchestration repo; if OpenClaw is involved, treat it as a downstream consumer only.
- There is an existing iMessage bridge lane (via launchd / Redis) that can serve as a reference, but this task is about the BlueBubbles HTTP/API bridge.

Rules
- No heredocs
- No inline interpreters
- No docker logs -f, docker compose logs -f, tail -f, watch
- No interactive editors
- Operate only on Bob’s AI-Server repo (and any clearly referenced companion repos)
- Do not touch secrets, API keys, or wallet funding
- Prefer bounded diagnostics and small, composable changes
- Use existing patterns (logging, HTTP, configuration) rather than inventing new frameworks

High-level outcomes
1) A single, stable inbound HTTP endpoint that accepts BlueBubbles webhooks and normalizes them.
2) A minimal outbound client that can send replies via BlueBubbles to the correct chat.
3) Clear routing/identity rules for which chats are allowed and how they map into AI-Server.
4) A basic health/monitoring surface for the BlueBubbles bridge.
5) A verification file and STATUSREPORT entry describing what is now IN PLACE vs still missing.

Steps

1. Recon: locate any existing BlueBubbles/OpenClaw hooks
   - cd ~/AI-Server
   - search for code that references:
     - “BlueBubbles”
     - bluebubbles
     - iMessage bridge
     - SMS / iMessage channels in OpenClaw docs
   - Identify:
     - any existing BlueBubbles-specific modules or configuration,
     - any generic “message webhook” endpoints that may already be used by other channels (Twilio, etc.),
     - where the current iMessage/bridge lane is handled (Redis events, imessage-bridge launchd, etc.).
   - Write down:
     - the main candidate module/file for webhook handling,
     - the main candidate for outbound messaging (if any).

2. Design the normalized message event shape
   - Define (or confirm) a single internal “message event” structure that BlueBubbles events will map into, e.g.:
     - id
     - timestamp
     - channel (bluebubbles-imessage)
     - chat_id (stable chat GUID / conversation identifier)
     - sender_id / sender_display
     - direction (inbound/outbound)
     - body_text
     - in_reply_to (if available)
     - attachments (list of objects with type/url/metadata)
   - Use an existing internal event schema if one already exists (for SMS, email, or other chat channels); otherwise, define one in a central place that fits with current patterns.

3. Implement the inbound webhook endpoint
   - In the appropriate HTTP service inside AI-Server (whichever currently handles external webhooks), add a new endpoint such as:
     - POST /hooks/bluebubbles
   - Parse the incoming BlueBubbles payload according to their documented webhook format and map it into the normalized event shape from Step 2.
   - Extract and preserve:
     - a stable chat identifier (chat GUID or equivalent) from BlueBubbles,
     - sender identity,
     - the raw message body,
     - any attachment metadata you care about (even if you don’t yet process the binary content).
   - Apply basic routing:
     - only accept events from known/whitelisted BlueBubbles hosts (configurable),
     - optionally allowlist certain chats or phone numbers so that not every personal conversation becomes automation input.
   - Log minimally:
     - one structured log per event (e.g. info-level with chat_id, direction, truncated body).
   - Forward the normalized event into AI-Server’s existing intake pipeline:
     - either publish to Redis, enqueue into a queue DB, or call an internal handler, depending on the existing pattern.

4. Implement the outbound BlueBubbles client
   - Create a small, dedicated client module for BlueBubbles API calls that:
     - reads configuration (BlueBubbles base URL, auth token) from environment or config files,
     - exposes a function like:
       - send_text(chat_id, body_text)
       - optionally send_attachments(chat_id, attachment_descriptors)
   - Implement the HTTP logic according to BlueBubbles’ REST API (e.g. POST /api/v1/message/text or equivalent endpoint), respecting:
     - required headers,
     - JSON payload fields (chat ID vs phone number),
     - error handling and retries kept simple (log and fail, no complex backoff in this first pass).
   - Ensure the client does not leak secrets into logs.

5. Wire replies from AI-Server through BlueBubbles
   - Identify where AI-Server currently decides to send iMessage replies (for example, in the X intake reply leg, daily briefing notifications, or alerting).
   - For the cases that should use BlueBubbles:
     - replace or augment the existing “send iMessage / SMS” behavior with calls to the BlueBubbles client from Step 4.
     - ensure the correct chat_id is available when replies are generated:
       - pass the chat_id through the pipeline from the inbound event,
       - store it alongside any task or context that may later generate a reply.
   - Keep the initial scope tight:
     - focus on one or two key reply paths (e.g. “X link analysis reply” and “simple alerts”) rather than trying to rewrite every channel at once.

6. Identity and routing rules
   - Implement a small routing/allowlist module that:
     - determines which BlueBubbles chat IDs are permitted to:
       - trigger automation (e.g. Bob’s personal lane for X intake),
       - receive automated replies,
       - be ignored entirely.
   - Back this with:
     - a simple configuration file (YAML/JSON) or an environment variable pattern that can enumerate allowed chat IDs or phone numbers.
   - Ensure the routing rules are applied both:
     - when processing inbound webhooks,
     - when sending outbound replies (to prevent accidental messages into unintended threads).

7. Basic health and monitoring
   - Add a simple health check for the BlueBubbles bridge, such as:
     - an internal endpoint or CLI that:
       - calls the BlueBubbles API ping/health endpoint,
       - verifies expected status and minimal latency,
       - reports “healthy” or “unhealthy” with a short reason.
   - If AI-Server already has a general health dashboard or status endpoint, add a single BlueBubbles section summarizing:
     - last successful ping,
     - most recent inbound event timestamp,
     - any recent send failures.

8. Verification pass
   - With code wired, perform a bounded live test:
     - From the BlueBubbles-connected iMessage account, send a test message that matches an allowed lane (e.g. Bob sending a specific keyword or X link).
     - Wait a short, fixed time (60–120 seconds).
   - Collect evidence (bounded commands only):
     - docker compose ps (to confirm relevant services are up)
     - docker compose logs --tail=80 <service that handles /hooks/bluebubbles>
     - logs or DB entries showing:
       - the inbound webhook was received,
       - the normalized event was created,
       - any reply or downstream processing happened,
       - any outbound BlueBubbles API call was made and whether it succeeded.
   - If possible within scope, validate that:
     - the test message produced an expected reply in the original iMessage chat,
     - or at least that the outbound API call succeeded.

9. Write a BlueBubbles verification file
   - Create a new file:
     - ops/verification/YYYYMMDD-HHMMSS-bluebubbles-integration.txt
   - Capture:
     - the current AI-Server Git commit hash on Bob,
     - the configured BlueBubbles base URL (redacted if needed),
     - the name/path of the inbound webhook endpoint,
     - the name/path of the outbound client module and functions,
     - a brief description of the routing/allowlist rules,
     - the test steps performed and observed results (including whether a reply appeared in iMessage),
     - any known limitations or TODOs left after this pass.

10. Update STATUSREPORT.md
   - Add or update a short “BlueBubbles integration” section that clearly states:
     - IN PLACE:
       - inbound webhook endpoint,
       - normalized message event path,
       - outbound BlueBubbles client,
       - basic health check.
     - PARTIAL or MISSING:
       - any unimplemented reply paths,
       - advanced routing/approval flows,
       - attachment handling beyond simple text,
       - migration/backup runbooks.
   - Reference the new ops/verification/*-bluebubbles-integration.txt file as the evidence for this state.

11. Commit and push
   - If you changed code or docs, run:
     - git status
     - git add .
     - git commit -m "Wire BlueBubbles into AI-Server (webhook + reply path + health) and document integration"
     - git push

Output
- A working BlueBubbles → AI-Server inbound webhook that normalizes events into the existing pipeline.
- A minimal, tested outbound client for sending iMessage replies via BlueBubbles into the correct chats.
- Clear routing/identity rules for which chats are allowed and how they map into AI-Server.
- A basic health check for the BlueBubbles bridge.
- ops/verification/*-bluebubbles-integration.txt documenting the integration.
- STATUSREPORT.md updated to reflect the current BlueBubbles state (what’s done vs still missing).