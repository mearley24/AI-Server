# Symphony AI-Server Port Registry

Quick reference for all active services. Update this file when adding or removing services.

Last updated: 2026-04-14

## Active Services

| Port | Service | Container | Purpose | Category |
|------|---------|-----------|---------|----------|
| 6379 | Redis | redis | Central data store, pub/sub, caching | Infrastructure |
| 8091 | Proposals | proposals | Symphony proposal generation engine | Business |
| 8092 | Email Monitor | email-monitor | Zoho email pipeline monitoring | Communication |
| 8093 | Voice Receptionist | voice-receptionist | Twilio voice call handling | Communication |
| 8094 | Calendar Agent | calendar-agent | Zoho calendar integration | Business |
| 8095 | Notification Hub | notification-hub | Alert routing and delivery | Infrastructure |
| 8096 | D-Tools Bridge | dtools-bridge | D-Tools project/inventory sync | Business |
| 8097 | ClawWork | clawwork | Side-hustle task engine | Business |
| 8099 | OpenClaw | openclaw | Central LLM orchestration + routing | Core AI |
| 8101 | X-Intake | x-intake | X/Twitter link analysis + bookmarks | Intelligence |
| 8102 | Cortex | cortex | Brain, memory, dashboard (1582+ memories) | Core AI |
| 8115 | Cortex Autobuilder | cortex-autobuilder | Bob/Betty research loop + topic scanning | Core AI |
| 8430 | Polymarket Bot | polymarket-bot | Prediction market trading (via VPN) | Trading |
| 8765 | Intel Feeds | intel-feeds | News, Reddit, Polymarket monitors | Intelligence |

## Removed Services

| Port | Service | Reason | Date |
|------|---------|--------|------|
| 8028 | Context Preprocessor | Merged into openclaw as context_cleaner.py utility | 2026-04-14 |
| 8090 | Remediator | Docker restart policies handle this natively | 2026-04-14 |
| 8100 | Knowledge Scanner | Merged into cortex-autobuilder topic scanner | 2026-04-14 |

## Notes

- All ports bind to `127.0.0.1` only (no external exposure)
- Redis password and all secrets live in `.env` (never hardcode in source files)
- To check service health: `curl http://127.0.0.1:<port>/health`
- Host service (imessage-server.py) runs outside Docker on the Mac Mini
