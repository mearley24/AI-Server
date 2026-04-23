#!/usr/bin/env bash
# bob-watchdog.sh — Self-healing watchdog for Bob (Mac Mini M4)
# Runs every 60s via LaunchDaemon.

REPO_DIR="${BOB_REPO_DIR:-/Users/bob/AI-Server}"
COMPOSE="docker compose"
MAX_LOG_BYTES=2000000

# Prefer the system log path when writable (LaunchDaemon install), otherwise
# fall back to the repo-local path (user LaunchAgent install — no sudo needed).
DEFAULT_LOG="/usr/local/var/log/bob-watchdog.log"
DEFAULT_STATE="/usr/local/var/bob-watchdog"
FALLBACK_LOG="$REPO_DIR/data/task_runner/bob-watchdog.log"
FALLBACK_STATE="$REPO_DIR/data/task_runner/bob-watchdog-state"

if mkdir -p "$(dirname "$DEFAULT_LOG")" 2>/dev/null && [ -w "$(dirname "$DEFAULT_LOG")" ]; then
    LOG="$DEFAULT_LOG"
    STATE_DIR="$DEFAULT_STATE"
else
    LOG="$FALLBACK_LOG"
    STATE_DIR="$FALLBACK_STATE"
fi

mkdir -p "$STATE_DIR" "$(dirname "$LOG")" 2>/dev/null

if [[ -f "$LOG" ]] && [[ $(stat -f%z "$LOG" 2>/dev/null || echo 0) -gt $MAX_LOG_BYTES ]]; then
    mv "$LOG" "${LOG}.1"
fi

log()       { echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $*" >> "$LOG"; }
log_alert() { echo "$(date '+%Y-%m-%d %H:%M:%S') [ALERT]    $*" >> "$LOG"; }

# Resolve a bounded-runner. Prefer GNU `timeout` (coreutils) or `gtimeout`
# (brew's coreutils) when available; otherwise fall back to a background+kill
# helper so a zombie Docker daemon (documented 2026-04-21) can never wedge
# the watchdog. Both paths return 124 on timeout.
if command -v timeout >/dev/null 2>&1; then
    BOUNDED_RUN=(timeout)
elif command -v gtimeout >/dev/null 2>&1; then
    BOUNDED_RUN=(gtimeout)
else
    BOUNDED_RUN=()
fi

bounded() {
    # Usage: bounded <seconds> <cmd...>
    # Runs cmd with a wall-clock cap; exits 124 on timeout (coreutils convention).
    local secs="$1"; shift
    if (( ${#BOUNDED_RUN[@]} > 0 )); then
        "${BOUNDED_RUN[@]}" "$secs" "$@"
        return $?
    fi
    # Fallback: no `timeout` binary — use a background job + watcher.
    "$@" &
    local pid=$!
    local waited=0
    while (( waited < secs )); do
        kill -0 "$pid" 2>/dev/null || { wait "$pid"; return $?; }
        sleep 1
        waited=$((waited + 1))
    done
    kill -TERM "$pid" 2>/dev/null
    sleep 1
    kill -KILL "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    return 124
}

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
#
# Two failure modes to detect:
#   a) "Cannot connect to the Docker daemon" — docker info fails outright
#   b) "EOF" / zombie backend — docker info or docker ps returns EOF on stderr
#      with exit 1 even though the socket file exists. This mode is what
#      stranded Bob on 2026-04-21; we explicitly test for it now.
docker_healthy() {
    # Bound every docker probe at 10s so a zombie daemon can't wedge the tick.
    local out err rc
    out=$(bounded 10 docker info --format '{{.ServerVersion}}' 2>/tmp/docker_info.err)
    rc=$?
    err=$(cat /tmp/docker_info.err 2>/dev/null)
    rm -f /tmp/docker_info.err 2>/dev/null
    if (( rc != 0 )); then
        # rc=124 means the probe hit the timeout — still "unhealthy"; recovery
        # logic below handles it the same way as a hard failure.
        return 1
    fi
    # Exit 0 but empty ServerVersion or EOF in stderr = zombie daemon.
    if [[ -z "$out" || "$err" == *"EOF"* || "$err" == *"Cannot connect"* ]]; then
        return 1
    fi
    # Final smoke: must be able to list containers without EOF.
    if ! bounded 10 docker ps -q >/dev/null 2>/tmp/docker_ps.err; then
        return 1
    fi
    err=$(cat /tmp/docker_ps.err 2>/dev/null)
    rm -f /tmp/docker_ps.err 2>/dev/null
    [[ "$err" == *"EOF"* ]] && return 1
    return 0
}

check_docker() {
    docker_healthy && return

    log_alert "Docker Desktop is down or in zombie state"
    in_cooldown "docker" 180 && { log "  cooldown, skip"; return; }

    # Kill lingering helpers so the new Docker Desktop has a clean backend.
    pkill -9 -x docker 2>/dev/null || true
    pkill -9 -f 'com.docker.backend' 2>/dev/null || true
    pkill -9 -f 'Docker Desktop Helper' 2>/dev/null || true
    sleep 3

    # Reopen Docker Desktop. open(1) will relaunch Docker.app if not running.
    open -a Docker 2>/dev/null

    local waited=0
    while (( waited < 120 )); do
        sleep 5; waited=$((waited + 5))
        docker_healthy && {
            log "  Docker ready after ${waited}s"
            mark_action "docker"
            sleep 10
            return
        }
    done
    log_alert "Docker failed to recover in 120s — escalating"
    # Escalate: touch a breadcrumb the notification-hub / task-runner picks up
    mkdir -p "$REPO_DIR/ops/alerts" 2>/dev/null
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z') docker_recover_failed" \
        >> "$REPO_DIR/ops/alerts/bob_watchdog.alerts"
    mark_action "docker"
}

BOB_USER="bob"

# --- CHECK 4: Missing containers ---
check_containers() {
    docker info >/dev/null 2>&1 || return
    cd "$REPO_DIR" 2>/dev/null || return

    local running missing=""
    running=$(docker ps --format '{{.Names}}' 2>/dev/null)

    for svc in openclaw email-monitor redis notification-hub calendar-agent proposals dtools-bridge mission-control knowledge-scanner clawwork voice-receptionist openwebui remediator vpn polymarket-bot intel-feeds context-preprocessor x-intake client-portal; do
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

# --- CHECK 7: X-intake HTTP health (lane listener can wedge even when container is "healthy") ---
# A healthcheck that exercises the FastAPI /health endpoint the iPhone / iPad
# shortcut ultimately depends on. Two strikes restarts the container.
check_x_intake() {
    docker info >/dev/null 2>&1 || return
    local strike_file="$STATE_DIR/x_intake_strike"
    if curl -fsS --max-time 5 http://127.0.0.1:8101/health >/dev/null 2>&1; then
        rm -f "$strike_file" 2>/dev/null
        return
    fi

    # Increment strike counter
    local strikes=1
    [[ -f "$strike_file" ]] && strikes=$(( $(cat "$strike_file") + 1 ))
    echo "$strikes" > "$strike_file"
    log_alert "x-intake /health failed (strike $strikes/2)"

    (( strikes < 2 )) && return

    in_cooldown "x_intake" 180 && { log "  x-intake cooldown, skip"; return; }

    log_alert "Restarting x-intake container"
    docker restart x-intake 2>>"$LOG"
    mark_action "x_intake"
    rm -f "$strike_file" 2>/dev/null

    # Give listener 20s to reattach to Redis, then re-probe.
    sleep 20
    if curl -fsS --max-time 5 http://127.0.0.1:8101/health >/dev/null 2>&1; then
        log "  x-intake recovered after restart"
    else
        log_alert "x-intake still failing after restart — escalating"
        mkdir -p "$REPO_DIR/ops/alerts" 2>/dev/null
        echo "$(date '+%Y-%m-%dT%H:%M:%S%z') x_intake_recover_failed" \
            >> "$REPO_DIR/ops/alerts/bob_watchdog.alerts"
    fi
}

# Heartbeat file so we can see from the outside the watchdog is actually
# running, even when the stack is otherwise silent.
write_heartbeat() {
    mkdir -p "$REPO_DIR/data/task_runner" 2>/dev/null
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$REPO_DIR/data/task_runner/bob_watchdog_heartbeat.txt"
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
check_x_intake
write_heartbeat
log "--- done ---"
