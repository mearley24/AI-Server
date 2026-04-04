# Bob 24/7 Always-On Runbook

## Setup
Run once: `./setup/nodes/configure_bob_always_on.sh`

## Manual Checks
- Screen Time: OFF
- Software Update: Manual only (no auto-restart)
- Focus/DND: No schedules
- Energy Saver: Never sleep when plugged in

## Monitoring
- VPN guard: every 5 min via launchd
- Smoke test: weekly via launchd (`com.symphony.smoke-test`)
- Backup: nightly via `scripts/backup-data.sh`
- Maintenance: weekly via `tools/bob_maintenance.py`

## Recovery
If Bob restarts (power outage, update):
1. Docker Desktop auto-starts (configure in Docker settings)
2. `cd ~/AI-Server && docker compose up -d`
3. `launchctl load ~/Library/LaunchAgents/com.symphony.*.plist`
4. Verify: `./scripts/smoke-test.sh`
