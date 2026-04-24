# Bob Port & API Surface Classification — 20260424-182340

UTC: 2026-04-24T18:23:40Z
Host: Bobs-Mac-mini.local (Mac Mini M4)
Runner: Claude Code

---

## Port Classification Table

| Port | Proto | Bind | Owner (PID/container/plist) | Service | Classification | Recommended Action |
|------|-------|------|-----------------------------|---------|----------------|--------------------|
| 1234 | TCP | LAN `*` | PID 671 / com.bluebubbles.server | BlueBubbles Server REST API | REQUIRED | Keep — inbound webhook source. Password-protected. Tailscale-only exposure preferred; confirm not reachable via WAN. |
| 5000 | TCP | LAN `*` | PID 682 / ControlCenter | AirPlay Receiver (macOS) | OPTIONAL | Keep (macOS system). Only reachable on LAN. Not a Symphony service. |
| 6379 | TCP | loopback | PID 27030 / com.docker.backend → redis container | Redis | REQUIRED | Keep — all inter-container messaging depends on this. |
| 7000 | TCP | LAN `*` | PID 682 / ControlCenter | AirPlay Sender (macOS) | OPTIONAL | Keep (macOS system). Not a Symphony service. |
| 8088 | TCP | loopback | PID 974 / com.symphony.markup-tool | Markup Tool (--port 8088) | OPTIONAL | Keep if markup pipeline is in use. Last exit=0. Loopback-only — no LAN exposure. |
| 8091 | TCP | loopback | PID 27030 / proposals container | Proposals Engine | REQUIRED | Keep — active Symphony proposal pipeline. |
| 8092 | TCP | loopback | PID 27030 / email-monitor container | Email Monitor | REQUIRED | Keep — Zoho email pipeline. |
| 8093 | TCP | loopback | PID 27030 / voice-receptionist container | Twilio Voice | REQUIRED | Keep — active Twilio voice integration. |
| 8094 | TCP | loopback | PID 27030 / calendar-agent container | Calendar Agent | REQUIRED | Keep — Zoho calendar sync. |
| 8095 | TCP | loopback | PID 27030 / notification-hub container | Notification Hub | REQUIRED | Keep — alert routing for all services. |
| 8096 | TCP | loopback | PID 27030 / dtools-bridge container | D-Tools Bridge | REQUIRED | Keep — D-Tools Cloud sync. mem_limit raised to 512m today. |
| 8097 | TCP | loopback | PID 27030 / clawwork container | ClawWork | REQUIRED | Keep — active task engine. |
| 8099 | TCP | loopback | PID 27030 / openclaw container | OpenClaw | REQUIRED | Keep — central LLM orchestration. |
| 8101 | TCP | loopback | PID 27030 / x-intake container | X-Intake | REQUIRED | Keep — reply-leg listener active, code fixes deployed today. |
| 8102 | TCP | loopback | PID 27030 / cortex container | Cortex (Docker) | REQUIRED | Keep — brain + dashboard + BlueBubbles webhook endpoint. |
| 8102 | TCP | LAN `*` | PID 962 / com.symphony.file-watcher | UNKNOWN second listener on 8102 | UNKNOWN [NEEDS_MATT] | Investigate — PID 962 (file-watcher launchd agent) should not serve on 8102. Possible PID collision or unexpected secondary binding. Run: `lsof -p 962 -nP -iTCP` to confirm. |
| 8115 | TCP | loopback | PID 27030 / cortex-autobuilder container | Cortex Autobuilder | REQUIRED | Keep — Bob/Betty research loop. |
| 8199 | TCP | LAN `*` | PID 2322 / com.symphony.imessage-bridge | iMessage AppleScript Bridge | OPTIONAL | Keep — fallback outbound iMessage path. Last exit=-15 (prior SIGTERM); currently running. BlueBubbles apple-script method broken on macOS 26 — this bridge is the outbound fallback needed to close x-intake smoke. |
| 8421 | TCP | LAN `*` | PID 62424 / com.symphony.trading-api | Trading API | REQUIRED | Keep — trading research bot uses http://127.0.0.1:8421. Last exit=-15 (prior SIGTERM); currently running. Consider binding to loopback only (currently LAN-exposed). |
| 8430 | TCP | loopback | PID 27030 / vpn container | Polymarket Bot (via VPN) | REQUIRED | Keep — WireGuard tunnel restored today. polymarket-bot routes through this. |
| 8765 | TCP | loopback | PID 27030 / intel-feeds container | Intel Feeds | REQUIRED | Keep — news/Reddit/Polymarket monitors. |
| 8801 | TCP | loopback | PID 989 / com.bob.vault-pwa | Vault PWA | OPTIONAL | Keep if Vault PWA is in use. Loopback-only — no LAN exposure. |
| 11434 | TCP | LAN `*` | PID 975 / ollama | Ollama LLM Server | REQUIRED | Keep — used by x-intake, notes-sync, and other agents. LAN-exposed; confirm not reachable via WAN. |
| 17600 | TCP | loopback | PID 1015 / Dropbox | Dropbox internal | OPTIONAL | macOS system / Dropbox. Not a Symphony service. |
| 17603 | TCP | loopback | PID 1015 / Dropbox | Dropbox internal | OPTIONAL | macOS system / Dropbox. Not a Symphony service. |
| 45670 | TCP | loopback `[::1]` | PID 671 / BlueBubbles | BlueBubbles internal (IPv6 loopback) | REQUIRED | Keep — internal BlueBubbles component. |
| 49168 | TCP | LAN `*` | PID 635 / rapportd | Rapportd (Handoff/Continuity) | OPTIONAL | macOS system. Not a Symphony service. |
| 51703 | TCP | LAN `*` | PID 635 / rapportd | Rapportd | OPTIONAL | macOS system. Not a Symphony service. |
| 51704 | TCP | LAN `*` | PID 635 / rapportd | Rapportd | OPTIONAL | macOS system. Not a Symphony service. |

---

## PORTS.md Drift

| Drift Type | Detail |
|---|---|
| In PORTS.md, not running | Port 8103 (x-intake-lab) — service defined in compose but not started; decommissioned per prior diagnostic |
| Not in PORTS.md | Port 1234 (BlueBubbles server), 8088 (markup-tool), 8199 (imessage-bridge), 8421 (trading-api), 8801 (vault-pwa), 11434 (ollama) |
| PORTS.md note inaccurate | PORTS.md states "All ports bind to 127.0.0.1 only" — FALSE. Ports 1234, 8102 (host), 8199, 8421, 11434 bind to `*` (all interfaces) |

PORTS.md requires update to reflect current reality.

---

## BlueBubbles-Specific Recommendation (§6)

1. **Inbound webhook live?** `last_inbound_event_at: null` (counters reset by container restart today). Known-quiet window — Cortex restarted at 18:23 UTC. Prior confirmed live event: `ops/verification/20260424-161534-bluebubbles-cortex-live-webhook.md` (2026-04-24 16:17 UTC, PASS-webhook-only). **STATUS: live, temporarily quiet.**

2. **Outbound leg reachable?** YES — `server_version: 1.9.9`, ping latency 369ms, `status: healthy`. BlueBubbles apple-script send method hangs on macOS 26; private-api helper not connected. Outbound delivery blocked at final leg.

3. **allowed_phones populated?** YES — `+19705193013` (owner), `+18609171850` / `18609171850` (smoke test contact), `mearley24@me.com`.

4. **Downstream skill gated on BlueBubbles outbound?** YES — x-intake reply-leg smoke (`ops/runbooks/2026-04-23-x-intake-reply-leg-live-smoke-bob-arm.md`) status PARTIAL-PASS. The outbound `send_text` path is blocked pending apple-script / private-api fix. Disabling BlueBubbles NOW would regress the inbound webhook path and kill the Cortex iMessage ingest.

**Recommendation: KEEP ENABLED.** Do not disable BlueBubbles. The outbound send issue is a BlueBubbles macOS 26 compat issue, not a reason to disable the service.

---

## Notable Findings

### [NEEDS_MATT] Unknown second listener on port 8102
`lsof` shows `Python *:8102` bound to ALL interfaces (PID 962, mapped to com.symphony.file-watcher launchd). This is in addition to Docker's `127.0.0.1:8102`. A LAN-wide binding on the Cortex port is unexpected. Verify with: `lsof -p 962 -nP -iTCP`.

### LAN-exposed services without PORTS.md entry
- Port 8199 (iMessage bridge) — LAN `*`, not in PORTS.md
- Port 8421 (trading-api) — LAN `*`, not in PORTS.md  
- Port 11434 (Ollama) — LAN `*`, not in PORTS.md
- Port 1234 (BlueBubbles) — LAN `*`, not in PORTS.md

PORTS.md states all ports are loopback-only — this is inaccurate and should be corrected.

### Launchd agents with non-zero exit codes
- `com.symphony.imessage-bridge` (PID 2322): last exit -15 (SIGTERM)
- `com.symphony.trading-api` (PID 62424): last exit -15 (SIGTERM)
- `com.symphony.network-guard`: exit 0 (historically in crash-loop per docs/audits/2026-04-23)
- `com.symphony.employee-beatrice-bot`, `com.symphony.employee-betty-bot`: exit 127 (command not found)
- Multiple agents with exit 78 (EX_CONFIG), 2, 1: likely periodic scripts that ran and exited cleanly

### x-intake-lab (port 8103) still in docker-compose.yml
Service defined but not running. Confirm removal if permanently decommissioned.

---

## Summary Counts

- Total TCP listeners: 29 (18 loopback, 11 LAN/wildcard)
- REQUIRED: 15
- OPTIONAL: 9
- STALE: 0
- UNKNOWN: 1 (port 8102 secondary binding)
- LAN-exposed non-loopback: 11 (includes macOS system services)
- Not in PORTS.md: 6 active Symphony services
