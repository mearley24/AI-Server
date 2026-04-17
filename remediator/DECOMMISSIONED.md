# DECOMMISSIONED — remediator/

**Status:** no longer deployed. **Do not add new code here.**

Replaced by `scripts/bob-watchdog.sh` + per-service watchdogs.

Container-level remediation is now handled by:

- `scripts/bob-watchdog.sh` — system-level (Tailscale, DNS, Docker
  daemon, Redis auth, openclaw, disk pressure) with per-check
  cooldowns.
- Per-service watchdogs inside each container where appropriate, e.g.
  `integrations/x_intake/main.py::_listener_watchdog()` for the Redis
  pubsub listener.

STATUS_REPORT.md Reference: Stack Health still lists this service as
"Up" from the 2026-04-12 snapshot; reality is it was removed from the
compose file.

Files in this directory are retained for historical reference only.
Removal is tracked as a future MEDIUM-risk cleanup task (deletion waits
until this marker has been in place >= one week).
