# Docker Restart Safety Policy
**Created:** 2026-04-25  
**Status:** ACTIVE  
**Owner:** Bob watchdog + operator

Prevents Docker Desktop zombie/lingering-process issues that have stranded Bob
(documented 2026-04-21, 2026-04-24).

---

## Rules

| Rule | Rationale |
|---|---|
| Never declare Docker unhealthy until `docker ps` fails for **30+ seconds** | Transient delays (e.g. heavy I/O) look like crashes |
| Never run `docker ps` in a loop while Docker Desktop is quitting | Flooding the socket accelerates the zombie state |
| Prefer `docker compose restart <service>` over `docker restart` | Compose respects resource limits, restart policies, and dependency order |
| Always try service-level restart before engine recovery | Restarting full Docker Desktop for one bad container is destructive |
| Graceful quit (`osascript quit app "Docker"`) before any `pkill` | Allows Docker to flush state cleanly |
| Wait for `com.docker.backend` to fully exit before `open -a Docker` | Prevents two backend instances fighting over the same socket |
| 5-minute cooldown on `docker-recover.sh` | Prevents recovery loops if Docker is cycling |

---

## Scripts

### `scripts/docker-recover.sh`
Full Docker Desktop engine recovery. Called when `docker ps` is completely
unreachable (not for single unhealthy containers).

```bash
# Normal (respects 5-min cooldown)
bash scripts/docker-recover.sh

# Operator override — skips cooldown
bash scripts/docker-recover.sh --force
```

**Flow:**
1. Probe `docker ps` 6× at 5s intervals (30s total).
2. If healthy: print status and exit 0.
3. Stamp cooldown file (`/tmp/docker-recover-cooldown`).
4. `osascript quit app "Docker"` — graceful quit.
5. Poll `pgrep com.docker.backend` every 2s up to 20s.
6. If still alive: `pkill -KILL com.docker.backend`.
7. `open -a Docker`.
8. Poll `docker ps` every 5s for up to 5 min.

### `scripts/safe-service-restart.sh <service>`
Single-container restart without touching Docker Desktop.

```bash
bash scripts/safe-service-restart.sh cortex
bash scripts/safe-service-restart.sh x-intake
```

**Flow:**
1. `docker ps` (bounded 10s, once).
2. Docker healthy → `docker compose restart <service>`.
3. Docker unhealthy → call `docker-recover.sh` first, then restart.
4. Never restarts Docker Desktop just for one unhealthy container.

### `scripts/docker-diagnose.sh`
Read-only snapshot for debugging. Safe to run at any time.

```bash
bash scripts/docker-diagnose.sh
```

Prints: `docker ps`, Docker PIDs, launchctl entries, `com.docker.socket`/`vmnetd`
status, last 50 Docker Desktop log lines.

---

## Watchdog behaviour (bob-watchdog.sh)

- `check_docker()`: 5-min cooldown (up from 180s), delegates to `docker-recover.sh`,
  falls back to graceful-quit + wait-for-exit inline logic.
- `check_unhealthy()`: uses `docker compose restart <service>` (not `docker restart`).
- `check_email_dns()`: uses `docker compose restart email-monitor`.
- `check_x_intake()`: uses `docker compose restart x-intake`.

---

## Decision tree

```
New iMessage / X-intake stops responding
        │
        ▼
bash scripts/docker-diagnose.sh
        │
        ├─ Docker healthy, service unhealthy
        │       └─ bash scripts/safe-service-restart.sh <service>
        │
        └─ docker ps fails / zombied backend
                └─ bash scripts/docker-recover.sh [--force]
```

---

## Rollback

All changes are in `scripts/` and `bob-watchdog.sh`. Revert with:

```bash
git revert HEAD    # or specific commit hash
```

No runtime state is affected; cooldown file is `/tmp/docker-recover-cooldown`
(cleared on reboot).
