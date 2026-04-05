# Incident Report: Docker Crash Cascade

**Date:** 2026-04-04 ~6:35 PM MDT
**Severity:** High — full system outage for ~45 minutes
**Resolved:** 2026-04-04 ~7:22 PM MDT
**Root Cause:** Docker Desktop crash → Tailscale DNS failure → full network loss

---

## Timeline

| Time (MDT) | Event |
|---|---|
| ~6:35 PM | Docker Desktop crashes — logo shows `?` instead of whale |
| ~6:35 PM | All 16 containers go down simultaneously |
| ~6:35 PM | Tailscale DNS proxy (100.100.100.100) stops responding |
| ~6:35 PM | Host DNS dies — `nslookup` returns "connection timed out; no servers could be reached" |
| ~6:35 PM | Browser shows DNS_PROBE_FINISHED_NXDOMAIN on all sites |
| ~7:05 PM | Docker Desktop relaunched — `open -a Docker` — 15/16 containers come back |
| ~7:05 PM | OpenClaw fails to start: `mkdir /host_mnt/Volumes/Symphony SH: permission denied` |
| ~7:07 PM | Port audit reveals 3 services on 0.0.0.0 (Redis, Mission Control, Context Preprocessor) |
| ~7:09 PM | Ports locked to 127.0.0.1 via `sed` on docker-compose.yml |
| ~7:10 PM | `SYMPHONY_DOCS_PATH` identified as wrong default (`SymphonySH` vs `Symphony SH`) |
| ~7:11 PM | Fixed `SYMPHONY_DOCS_PATH` in `.env`, OpenClaw starts |
| ~7:12 PM | All 16 containers up, ports locked down |
| ~7:16 PM | Email monitor still failing: `[Errno -2] Name or service not known` — stale DNS inside container |
| ~7:17 PM | `docker exec email-monitor` DNS test confirms container DNS dead |
| ~7:18 PM | Host `nslookup` fails — DNS still dead system-wide |
| ~7:18 PM | `networksetup -setdnsservers Ethernet 1.1.1.1 8.8.8.8` — DNS resolves via Cloudflare |
| ~7:18 PM | Discovered DNS was routing through Tailscale (100.100.100.100) the whole time |
| ~7:22 PM | Tailscale reconnects, DNS restores, email-monitor restarted — full recovery |

## Root Cause Analysis

### Primary: Docker Desktop crash
Docker Desktop on macOS periodically crashes with no clear trigger. When it dies, it takes down the entire container fleet. The Mac Mini has `restart: unless-stopped` on all containers, but this only helps if the Docker daemon is running.

### Secondary: Tailscale DNS dependency
Bob's network routes ALL DNS through Tailscale's MagicDNS resolver at `100.100.100.100`. When Docker crashed, Tailscale's network integration was disrupted, killing DNS for the entire Mac — not just Docker containers. This meant:
- No web browsing
- No IMAP connections
- No API calls
- No git operations

### Tertiary: Stale container DNS
Even after Docker and Tailscale recovered, the email-monitor container retained its old (broken) DNS resolver. Containers don't automatically refresh DNS when the host's DNS changes. Required a `docker restart email-monitor` to pick up working DNS.

### Contributing: Exposed ports
Three services were bound to `0.0.0.0` instead of `127.0.0.1`:
- **Redis 6379** — NO authentication, reachable from LAN. Critical vulnerability (CVE-2025-49844, CVSS 10.0 RCE via Lua scripts).
- **Mission Control 8098** — dashboard exposed to LAN
- **Context Preprocessor 8028** — web app exposed to LAN

### Contributing: Wrong volume mount path
`SYMPHONY_DOCS_PATH` defaulted to `SymphonySH` but the actual iCloud folder is `Symphony SH` (with a space). This prevented OpenClaw from starting after the crash.

### Contributing: Broken import path
`email-monitor/monitor.py` used `os.path.join(os.path.dirname(__file__), "..", "openclaw")` to find `follow_up_tracker.py`. Inside the container this resolves to `/openclaw` but the volume mount is at `/app/openclaw`. Result: `No module named 'follow_up_tracker'` on every poll cycle.

## Impact

- **Email monitoring:** Down for ~45 minutes. No emails classified, no notifications sent.
- **All AI services:** Down for ~30 minutes. No orchestrator ticks, no job processing.
- **Trading bot:** Down for ~30 minutes. No Polymarket monitoring.
- **Calendar/notifications:** Down for ~30 minutes.
- **Security exposure:** Redis was accessible from LAN with no password for an unknown period prior to this incident.

## Fixes Applied

### Immediate (during incident)
1. Docker Desktop relaunched manually
2. `SYMPHONY_DOCS_PATH` corrected in `.env`
3. All three `0.0.0.0` ports changed to `127.0.0.1` in `docker-compose.yml`
4. Manual DNS set to `1.1.1.1 / 8.8.8.8` as Tailscale fallback
5. `docker restart email-monitor` after DNS recovered

### Permanent (post-incident)
1. **Watchdog daemon** (`/usr/local/bin/bob-watchdog.sh`) — runs every 60s via macOS LaunchDaemon, auto-recovers: Tailscale → DNS → Docker → containers → email-monitor. Target: 60-120s recovery.
2. **Redis authentication** — password required, dangerous commands disabled (`FLUSHALL`, `FLUSHDB`, `DEBUG`), `protected-mode yes`, bind restricted.
3. **Port lockdown** — all services bound to `127.0.0.1` only.
4. **DNS fallback** — watchdog auto-sets 1.1.1.1/8.8.8.8 when Tailscale DNS fails, auto-restores when Tailscale recovers.
5. **SYMPHONY_DOCS_PATH** — corrected default in docker-compose.yml.
6. **Import path fix** — email-monitor `follow_up_tracker` import changed to `/app/openclaw`.
7. **Missing healthchecks** — added to openwebui, remediator, context-preprocessor.

## Prevention Checklist

- [ ] Verify watchdog is running: `launchctl list | grep symphony`
- [ ] Verify Redis requires auth: `redis-cli -h 127.0.0.1 ping` should fail
- [ ] Verify no 0.0.0.0 ports: `docker ps --format '{{.Ports}}' | grep 0.0.0.0`
- [ ] Check watchdog logs weekly: `tail -50 /usr/local/var/log/bob-watchdog.log`
- [ ] Verify Redis version patched for CVE-2025-49844 (need 7.2.11+, 7.4.6+, 8.0.4+, or 8.2.2+)
- [ ] Check router for port forwarding rules pointing to Bob's IP
- [ ] Verify macOS firewall is enabled

## Files Changed

| File | Change |
|------|--------|
| `docker-compose.yml` | Port bindings, SYMPHONY_DOCS_PATH, Redis auth URL, healthchecks |
| `redis/redis.conf` | Created — password, bind, protected-mode, disabled commands |
| `email-monitor/monitor.py` | Fixed openclaw import path |
| `scripts/bob-watchdog.sh` | Created — self-healing watchdog |
| `scripts/com.symphony.bob-watchdog.plist` | Created — LaunchDaemon |
| `scripts/bob-watchdog-install.sh` | Created — one-command installer |
| `.env` | Added REDIS_PASSWORD, fixed SYMPHONY_DOCS_PATH |

## Recovery Commands (if this happens again)

```bash
# 1. If Docker is down
open -a Docker
# Wait 60s, then:
cd ~/AI-Server && docker compose up -d

# 2. If DNS is dead
networksetup -setdnsservers Ethernet 1.1.1.1 8.8.8.8
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# 3. If email monitor has stale DNS after recovery
docker restart email-monitor

# 4. If OpenClaw won't start (volume mount error)
grep SYMPHONY_DOCS_PATH .env
ls ~/Library/Mobile\ Documents/com~apple~CloudDocs/
# Fix the path in .env if needed

# 5. Nuclear option — full restart
docker compose down && docker compose up -d

# 6. Check watchdog is handling it
tail -f /usr/local/var/log/bob-watchdog.log
```

## Lessons Learned

1. **Tailscale as sole DNS is a single point of failure.** The watchdog now provides automatic fallback to 1.1.1.1/8.8.8.8.
2. **Docker Desktop on macOS crashes without warning.** The LaunchDaemon watchdog detects this within 60s and relaunches.
3. **Container DNS doesn't auto-refresh.** The watchdog detects stale DNS in email-monitor and restarts it.
4. **Never bind to 0.0.0.0.** All Docker ports must use `127.0.0.1:` prefix. Redis without auth on 0.0.0.0 is an active RCE risk.
5. **Volume mount paths with spaces need testing.** The `SYMPHONY_DOCS_PATH` default was never tested with the actual folder name.
6. **Import paths must use absolute container paths**, not relative joins that break depending on WORKDIR.
