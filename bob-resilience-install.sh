#!/usr/bin/env bash
# =============================================================================
# bob-resilience-install.sh
# One-shot: installs watchdog, fixes docker-compose, hardens Redis,
# fixes email-monitor import, adds healthchecks, sets up LaunchDaemon.
#
# Run from AI-Server repo root on Bob:
#   sudo bash bob-resilience-install.sh
# =============================================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root for LaunchDaemon + DNS. Run with sudo."
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BOB_USER="bob"
LOG_DIR="/usr/local/var/log"
STATE_DIR="/usr/local/var/bob-watchdog"
SCRIPT_DEST="/usr/local/bin/bob-watchdog.sh"
PLIST_DEST="/Library/LaunchDaemons/com.symphony.bob-watchdog.plist"

echo "========================================"
echo "Bob Resilience Install — $(date)"
echo "Repo: $REPO_DIR"
echo "========================================"

# ------------------------------------------------------------------
# 1. Create directories
# ------------------------------------------------------------------
mkdir -p "$LOG_DIR" "$STATE_DIR" "$REPO_DIR/scripts" "$REPO_DIR/redis"
echo "[1/8] Directories created"

# ------------------------------------------------------------------
# 2. Write the watchdog script
# ------------------------------------------------------------------
cat > "$REPO_DIR/scripts/bob-watchdog.sh" << 'WATCHDOG_EOF'
#!/usr/bin/env bash
# bob-watchdog.sh — Self-healing watchdog for Bob (Mac Mini M4)
# Runs every 60s via LaunchDaemon.

REPO_DIR="${BOB_REPO_DIR:-/Users/bob/AI-Server}"
LOG="/usr/local/var/log/bob-watchdog.log"
STATE_DIR="/usr/local/var/bob-watchdog"
COMPOSE="docker compose"
MAX_LOG_BYTES=2000000

mkdir -p "$STATE_DIR" "$(dirname "$LOG")" 2>/dev/null

if [[ -f "$LOG" ]] && [[ $(stat -f%z "$LOG" 2>/dev/null || echo 0) -gt $MAX_LOG_BYTES ]]; then
    mv "$LOG" "${LOG}.1"
fi

log()       { echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $*" >> "$LOG"; }
log_alert() { echo "$(date '+%Y-%m-%d %H:%M:%S') [ALERT]    $*" >> "$LOG"; }

mark_action() {
    echo "$(date +%s)" > "$STATE_DIR/$1"
}

in_cooldown() {
    local cooldown="${2:-300}"
    local marker="$STATE_DIR/$1"
    if [[ -f "$marker" ]]; then
        local ts=$(cat "$marker")
        local now=$(date +%s)
        (( now - ts < cooldown )) && return 0
    fi
    return 1
}

get_net_service() {
    local iface
    iface=$(route -n get default 2>/dev/null | grep interface | awk '{print $2}')
    case "$iface" in
        en0) echo "Ethernet" ;;
        en1) echo "Wi-Fi" ;;
        *)   networksetup -listallhardwareports 2>/dev/null | grep -B1 "$iface" | grep "Hardware Port" | sed 's/Hardware Port: //' ;;
    esac
}

# --- CHECK 1: Tailscale ---
check_tailscale() {
    command -v tailscale &>/dev/null || return
    local state
    state=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('BackendState',''))" 2>/dev/null || echo "unknown")
    [[ "$state" == "Running" ]] && return

    log_alert "Tailscale not running (state: $state)"
    in_cooldown "tailscale" 120 && { log "  cooldown, skip"; return; }

    [[ -d "/Applications/Tailscale.app" ]] && open -a Tailscale 2>/dev/null
    tailscale up 2>/dev/null || true
    mark_action "tailscale"
    log "  Tailscale restart triggered"
}

# --- CHECK 2: DNS ---
check_dns() {
    python3 -c "import socket; socket.getaddrinfo('imap.zoho.com', 993)" 2>/dev/null && return

    log_alert "DNS resolution failed"
    in_cooldown "dns_fix" 180 && { log "  cooldown, skip"; return; }

    dscacheutil -flushcache 2>/dev/null
    killall -HUP mDNSResponder 2>/dev/null
    log "  DNS cache flushed"

    sleep 5
    python3 -c "import socket; socket.getaddrinfo('google.com', 443)" 2>/dev/null && {
        log "  DNS recovered after flush"
        mark_action "dns_fix"
        return
    }

    local svc
    svc=$(get_net_service)
    if [[ -n "$svc" ]]; then
        local cur
        cur=$(networksetup -getdnsservers "$svc" 2>/dev/null | head -1)
        [[ "$cur" != "1.1.1.1" ]] && echo "$cur" > "$STATE_DIR/original_dns"
        networksetup -setdnsservers "$svc" 1.1.1.1 8.8.8.8 8.8.4.4 2>/dev/null
        log_alert "Set fallback DNS (1.1.1.1/8.8.8.8) on $svc"
        sleep 2
        dscacheutil -flushcache 2>/dev/null
        killall -HUP mDNSResponder 2>/dev/null
    fi
    mark_action "dns_fix"
}

# --- CHECK 2b: Restore Tailscale DNS when it's back ---
restore_tailscale_dns() {
    command -v tailscale &>/dev/null || return
    [[ ! -f "$STATE_DIR/original_dns" ]] && return

    local state
    state=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('BackendState',''))" 2>/dev/null || echo "")
    [[ "$state" != "Running" ]] && return

    nslookup google.com 100.100.100.100 >/dev/null 2>&1 || return

    local svc
    svc=$(get_net_service)
    if [[ -n "$svc" ]]; then
        networksetup -setdnsservers "$svc" empty 2>/dev/null
        log "Restored DNS to automatic (Tailscale back)"
    fi
    rm -f "$STATE_DIR/original_dns"
}

# --- CHECK 3: Docker Desktop ---
check_docker() {
    docker info >/dev/null 2>&1 && return

    log_alert "Docker Desktop is down"
    in_cooldown "docker" 180 && { log "  cooldown, skip"; return; }

    killall -9 com.docker.backend 2>/dev/null || true
    sleep 2
    sudo -u "$BOB_USER" open -a Docker 2>/dev/null || open -a Docker 2>/dev/null

    local waited=0
    while (( waited < 90 )); do
        sleep 5; waited=$((waited + 5))
        docker info >/dev/null 2>&1 && {
            log "  Docker ready after ${waited}s"
            mark_action "docker"
            sleep 10
            return
        }
    done
    log_alert "Docker failed to start in 90s"
    mark_action "docker"
}

BOB_USER="bob"

# --- CHECK 4: Missing containers ---
check_containers() {
    docker info >/dev/null 2>&1 || return
    cd "$REPO_DIR" 2>/dev/null || return

    local running missing=""
    running=$(docker ps --format '{{.Names}}' 2>/dev/null)

    for svc in openclaw email-monitor redis notification-hub calendar-agent proposals dtools-bridge mission-control knowledge-scanner clawwork voice-receptionist openwebui remediator vpn polymarket-bot intel-feeds context-preprocessor; do
        echo "$running" | grep -q "^${svc}$" || missing="$missing $svc"
    done

    [[ -z "$missing" ]] && return

    log_alert "Missing containers:$missing"
    in_cooldown "containers" 120 && { log "  cooldown, skip"; return; }

    $COMPOSE up -d --no-build 2>>"$LOG"
    mark_action "containers"
    log "  Containers recovered"
}

# --- CHECK 5: Unhealthy containers ---
check_unhealthy() {
    docker info >/dev/null 2>&1 || return
    local uhc
    uhc=$(docker ps --filter "health=unhealthy" --format '{{.Names}}' 2>/dev/null)
    [[ -z "$uhc" ]] && return

    for c in $uhc; do
        in_cooldown "uh_${c}" 300 && continue
        log_alert "Unhealthy: $c — restarting"
        docker restart "$c" 2>>"$LOG"
        mark_action "uh_${c}"
    done
}

# --- CHECK 6: Email monitor stale DNS ---
check_email_dns() {
    docker info >/dev/null 2>&1 || return
    [[ ! -f "$STATE_DIR/dns_fix" ]] && return
    docker exec email-monitor python3 -c "import socket; socket.getaddrinfo('imap.zoho.com', 993)" >/dev/null 2>&1 && return

    in_cooldown "email_dns" 120 && return
    log_alert "Email monitor stale DNS — restarting"
    docker restart email-monitor 2>>"$LOG"
    mark_action "email_dns"
}

# --- MAIN ---
log "--- tick ---"
check_tailscale
check_dns
restore_tailscale_dns
check_docker
check_containers
check_unhealthy
check_email_dns
log "--- done ---"
WATCHDOG_EOF

chmod 755 "$REPO_DIR/scripts/bob-watchdog.sh"
echo "[2/8] Watchdog script written"

# ------------------------------------------------------------------
# 3. Write the LaunchDaemon plist
# ------------------------------------------------------------------
cat > "$REPO_DIR/scripts/com.symphony.bob-watchdog.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.bob-watchdog</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/usr/local/bin/bob-watchdog.sh</string>
    </array>

    <key>StartInterval</key>
    <integer>60</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>/usr/local/var/log/bob-watchdog.log</string>

    <key>StandardErrorPath</key>
    <string>/usr/local/var/log/bob-watchdog.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>BOB_REPO_DIR</key>
        <string>/Users/bob/AI-Server</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
PLIST_EOF

echo "[3/8] LaunchDaemon plist written"

# ------------------------------------------------------------------
# 4. Fix docker-compose.yml
# ------------------------------------------------------------------
echo "[4/8] Patching docker-compose.yml..."

cd "$REPO_DIR"

# 4a. Port bindings (may already be done — idempotent)
sed -i '' 's|"0.0.0.0:6379:6379"|"127.0.0.1:6379:6379"|g' docker-compose.yml
sed -i '' 's|"0.0.0.0:8098:8098"|"127.0.0.1:8098:8098"|g' docker-compose.yml
sed -i '' 's|"0.0.0.0:8028:8028"|"127.0.0.1:8028:8028"|g' docker-compose.yml

# 4b. Fix SYMPHONY_DOCS_PATH default (SymphonySH → Symphony SH)
sed -i '' 's|com~apple~CloudDocs/SymphonySH}|com~apple~CloudDocs/Symphony SH}|g' docker-compose.yml

# Verify no 0.0.0.0 ports remain (except env vars like ZOHO_ACCOUNT_ID)
if grep "0.0.0.0:" docker-compose.yml | grep -v "ZOHO" | grep -q .; then
    echo "  WARNING: Some 0.0.0.0 port bindings still present"
else
    echo "  All ports locked to 127.0.0.1"
fi

echo "  SYMPHONY_DOCS_PATH default fixed"

# ------------------------------------------------------------------
# 5. Redis hardening
# ------------------------------------------------------------------
echo "[5/8] Setting up Redis authentication..."

REDIS_PASS=$(openssl rand -hex 16)

cat > "$REPO_DIR/redis/redis.conf" << REDIS_EOF
# Redis security config — generated $(date)
bind 127.0.0.1 172.18.0.100
protected-mode yes
requirepass ${REDIS_PASS}

rename-command FLUSHALL ""
rename-command FLUSHDB ""
rename-command DEBUG ""

appendonly yes
save 900 1
save 300 10
save 60 10000

maxmemory 512mb
maxmemory-policy allkeys-lru
loglevel notice
REDIS_EOF

# Update all REDIS_URL in docker-compose.yml
REDIS_URL_NEW="redis://:${REDIS_PASS}@redis:6379"
sed -i '' "s|REDIS_URL=redis://redis:6379|REDIS_URL=${REDIS_URL_NEW}|g" docker-compose.yml

# Update hardcoded fallback Redis URLs in Python files
find "$REPO_DIR/openclaw" "$REPO_DIR/email-monitor" -name "*.py" 2>/dev/null | while read pyfile; do
    if grep -q "redis://localhost:6379\|redis://172.18.0.100:6379" "$pyfile" 2>/dev/null; then
        sed -i '' "s|redis://localhost:6379|${REDIS_URL_NEW}|g" "$pyfile"
        sed -i '' "s|redis://172.18.0.100:6379|${REDIS_URL_NEW}|g" "$pyfile"
        echo "  Updated Redis URL in: $(basename "$pyfile")"
    fi
done

# Save password to .env
if [[ -f .env ]]; then
    grep -v "^REDIS_PASSWORD=" .env > .env.tmp && mv .env.tmp .env
fi
echo "REDIS_PASSWORD=${REDIS_PASS}" >> .env
echo "  Redis password: ${REDIS_PASS}"
echo "  Saved to .env and redis/redis.conf"

# ------------------------------------------------------------------
# 6. Fix email-monitor import path
# ------------------------------------------------------------------
echo "[6/8] Fixing email-monitor follow_up_tracker import..."

python3 << 'FIX_IMPORT'
import os

path = os.environ.get("REPO_DIR", ".") + "/email-monitor/monitor.py"
with open(path, "r") as f:
    content = f.read()

old_line = '_openclaw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "openclaw"))'
new_line = '_openclaw_dir = "/app/openclaw"  # volume mount: ./openclaw:/app/openclaw'

if old_line in content:
    content = content.replace(old_line, new_line)
    with open(path, "w") as f:
        f.write(content)
    print("  Fixed openclaw import path in monitor.py")
else:
    print("  Import path already fixed or not found")
FIX_IMPORT

# ------------------------------------------------------------------
# 7. Install watchdog + LaunchDaemon
# ------------------------------------------------------------------
echo "[7/8] Installing watchdog..."

cp "$REPO_DIR/scripts/bob-watchdog.sh" "$SCRIPT_DEST"
chmod 755 "$SCRIPT_DEST"

# Unload old version if exists
launchctl unload "$PLIST_DEST" 2>/dev/null || true

cp "$REPO_DIR/scripts/com.symphony.bob-watchdog.plist" "$PLIST_DEST"
chown root:wheel "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

launchctl load "$PLIST_DEST"

if launchctl list 2>/dev/null | grep -q "com.symphony.bob-watchdog"; then
    echo "  Watchdog daemon loaded and running"
else
    echo "  WARNING: Daemon may not have loaded — check: launchctl list | grep symphony"
fi

# ------------------------------------------------------------------
# 8. Git commit
# ------------------------------------------------------------------
echo "[8/8] Committing changes..."

cd "$REPO_DIR"
git add -A scripts/ redis/ docker-compose.yml email-monitor/monitor.py .env 2>/dev/null
sudo -u "$BOB_USER" git commit -m "resilience: watchdog, Redis auth, port lockdown, DNS auto-recovery

- LaunchDaemon watchdog: Tailscale → DNS → Docker → containers (60s cycle)
- Redis: password auth, dangerous commands disabled, protected-mode on
- All ports locked to 127.0.0.1 (was 0.0.0.0 on Redis/mission-control/preprocessor)
- SYMPHONY_DOCS_PATH default fixed (space in folder name)
- email-monitor: fixed follow_up_tracker import path
- Fallback DNS (1.1.1.1/8.8.8.8) auto-set when Tailscale DNS fails
- Auto-restore Tailscale DNS when it recovers" 2>/dev/null || echo "  (nothing new to commit)"

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
echo ""
echo "========================================"
echo "INSTALL COMPLETE"
echo "========================================"
echo ""
echo "Redis password: ${REDIS_PASS}"
echo ""
echo "Next steps:"
echo "  1. Restart the stack to apply all changes:"
echo "     cd ~/AI-Server && docker compose down && docker compose up -d"
echo ""
echo "  2. Verify:"
echo "     docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
echo "     docker ps --format '{{.Ports}}' | grep '0.0.0.0' || echo 'All ports safe'"
echo "     tail -5 /usr/local/var/log/bob-watchdog.log"
echo ""
echo "  3. Test Redis auth:"
echo "     redis-cli -h 127.0.0.1 ping          (should fail — no auth)"
echo "     redis-cli -h 127.0.0.1 -a '${REDIS_PASS}' ping   (should PONG)"
echo ""
echo "To uninstall watchdog:"
echo "  sudo launchctl unload $PLIST_DEST"
echo "  sudo rm $PLIST_DEST $SCRIPT_DEST"
echo "========================================"
