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
