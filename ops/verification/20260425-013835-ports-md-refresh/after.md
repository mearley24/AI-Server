# Symphony AI-Server Port Registry

Quick reference for all active services. Update this file when adding or removing services.

Last updated: 2026-04-25

## Active Services

| Port | Service | Bind | Container/Process | Purpose | Category |
|------|---------|------|-------------------|---------|----------|
| 1234 | BlueBubbles Server | LAN `*` | host / com.bluebubbles.server | REST API + inbound webhook receiver for iMessage | Infrastructure |
| 6379 | Redis | loopback | redis | Central data store, pub/sub, caching | Infrastructure |
| 8088 | Markup Tool | loopback | host / com.symphony.markup-tool | File markup utility | Tools |
| 8091 | Proposals | loopback | proposals | Symphony proposal generation engine | Business |
| 8092 | Email Monitor | loopback | email-monitor | Zoho email pipeline monitoring | Communication |
| 8093 | Voice Receptionist | loopback | voice-receptionist | Twilio voice call handling | Communication |
| 8094 | Calendar Agent | loopback | calendar-agent | Zoho calendar integration | Business |
| 8095 | Notification Hub | loopback | notification-hub | Alert routing and delivery | Infrastructure |
| 8096 | D-Tools Bridge | loopback | dtools-bridge | D-Tools project/inventory sync | Business |
| 8097 | ClawWork | loopback | clawwork | Side-hustle task engine | Business |
| 8099 | OpenClaw | loopback | openclaw | Central LLM orchestration + routing | Core AI |
| 8101 | X-Intake | loopback | x-intake | X/Twitter link analysis + bookmarks | Intelligence |
| 8102 | Cortex | loopback | cortex | Brain, memory, dashboard (1582+ memories) | Core AI |
| 8103 | File Watcher | loopback | host / com.symphony.file-watcher | Native file-change monitor + Cortex intake | Tools |
| 8115 | Cortex Autobuilder | loopback | cortex-autobuilder | Bob/Betty research loop + topic scanning | Core AI |
| 8199 | iMessage Bridge | loopback | host / com.symphony.imessage-bridge | AppleScript iMessage bridge (outbound fallback) | Communication |
| 8421 | Trading API | loopback | host / com.symphony.trading-api | Trading research bot API | Trading |
| 8430 | Polymarket Bot | loopback | polymarket-bot | Prediction market trading (via VPN) | Trading |
| 8765 | Intel Feeds | loopback | intel-feeds | News, Reddit, Polymarket monitors | Intelligence |
| 8801 | Vault PWA | loopback | host / com.bob.vault-pwa | Local vault web app/API | Security |
| 11434 | Ollama | loopback | host / homebrew.mxcl.ollama | Local LLM inference server | Core AI |

## Removed Services

| Port | Service | Reason | Date |
|------|---------|--------|------|
| 8028 | Context Preprocessor | Merged into openclaw as context_cleaner.py utility | 2026-04-14 |
| 8090 | Remediator | Docker restart policies handle this natively | 2026-04-14 |
| 8100 | Knowledge Scanner | Merged into cortex-autobuilder topic scanner | 2026-04-14 |
| 8103 | X-Intake Lab | Decommissioned — container not running, port freed | 2026-04-24 |

## Notes

- **Docker container services** bind to `127.0.0.1` (loopback only) — not reachable from LAN.
- **Host launchd services:** BlueBubbles (:1234) binds `*` (LAN-accessible, not WAN-exposed). All other host services now bind `127.0.0.1` — markup-tool, file-watcher, iMessage bridge, trading-api, vault-pwa, and Ollama are loopback-only.
- Live listener source of truth: run `lsof -nP -iTCP -sTCP:LISTEN` on Bob to verify current bindings.
- Redis password and all secrets live in `.env` (never hardcode in source files)
- To check service health: `curl http://127.0.0.1:<port>/health`
- `com.ollama` is disabled; `homebrew.mxcl.ollama` is the active Ollama launcher.
