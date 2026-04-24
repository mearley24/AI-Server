# Port & API Surface Audit — 20260424-182340

UTC: 2026-04-24T18:23:40Z | Host: Bobs-Mac-mini.local | Runner: Claude Code

## Counts
- Total TCP listeners: 29
- REQUIRED: 15 | OPTIONAL: 9 | STALE: 0 | UNKNOWN: 1
- LAN/wildcard bindings: 11 (7 macOS system + 4 Symphony)
- PORTS.md entries not running: 1 (x-intake-lab :8103, decommissioned)
- Running services not in PORTS.md: 6 (1234, 8088, 8199, 8421, 8801, 11434)

## Top 5 Findings

1. **[NEEDS_MATT] Unknown second listener on :8102 (LAN-wide)**
   PID 962 (com.symphony.file-watcher) has a Python process bound to `*:8102`.
   Docker also binds `127.0.0.1:8102`. A wildcard binding on the Cortex port
   is unexpected and could expose Cortex on the LAN. Verify: `lsof -p 962 -nP -iTCP`

2. **PORTS.md accuracy gap — states "loopback-only" but 4 Symphony services bind LAN-wide**
   Ports 1234 (BlueBubbles), 8199 (iMessage bridge), 8421 (trading-api),
   11434 (Ollama) all bind `*`. PORTS.md needs correction + those services
   should be reviewed for whether LAN exposure is intentional.

3. **BlueBubbles outbound send blocked on macOS 26**
   apple-script hangs; private-api helper not connecting. Inbound webhook
   confirmed live (today). Outbound needed to close x-intake reply-leg smoke.
   See: FOLLOWUP: bluebubbles-send-method (STATUS_REPORT).

4. **x-intake-lab (port 8103) still defined in docker-compose.yml but not running**
   Should be removed from compose if permanently decommissioned.

5. **6 active Symphony services not in PORTS.md**
   Registry is stale since 2026-04-14. Update recommended.

## Files
- [host-listeners.txt](host-listeners.txt) — lsof TCP+UDP output
- [docker-ports.txt](docker-ports.txt) — docker ps port table
- [launchd-ports.txt](launchd-ports.txt) — launchd agent inventory
- [bluebubbles-surface.txt](bluebubbles-surface.txt) — BlueBubbles health + routing
- [classification.md](classification.md) — full per-port table + recommendations
