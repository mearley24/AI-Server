# Auto-14: Network Guard Daemon — Deploy on Bob

## Context Files to Read First
- tools/network_guard_daemon.py
- tools/network_dropout_watch.py
- docker-compose.yml

## Prompt

Deploy the network guard daemon so Bob monitors his own connectivity and client sites:

1. **Fix and deploy** (`tools/network_guard_daemon.py`):
   - Verify the gateway ping + packet loss + jitter checks work on macOS
   - Add Control4 controller reachability check (ping to configured IP)
   - Cooldown: max 1 alert per endpoint per 15 minutes
   - When network drops: create task board incident, send iMessage to Matt
   - When network recovers: mark incident resolved, send recovery iMessage

2. **Docker network monitoring**:
   - Add checks for Docker bridge network health
   - Verify all containers can reach Redis at 172.18.0.100
   - Verify VPN container has internet connectivity (ping 1.1.1.1 from inside VPN)
   - If VPN is down, alert immediately (Polymarket bot can't trade without VPN)

3. **Launchd service** (not Docker — runs on host):
   - Create `setup/launchd/com.symphony.network-guard.plist`
   - Run every 5 minutes
   - Log to `/tmp/network-guard.log`
   - Auto-start on boot

4. **Integration with Mission Control** (API-5):
   - Publish network status to Redis `system:network` every check
   - Include: gateway latency, packet loss, VPN status, Docker network health
   - Mission Control dashboard reads from this Redis key

Use standard logging.
