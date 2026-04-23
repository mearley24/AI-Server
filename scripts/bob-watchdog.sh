#!/usr/bin/env bash
# bob-watchdog.sh — Self-healing watchdog for Bob (Mac Mini M4)
# Runs every 60s via LaunchDaemon (system) or LaunchAgent (user).
#
# Version marker: bump on every deploy-relevant change so a stale
# /usr/local/bin copy is easy to spot in the log ("watchdog vX starting").
WATCHDOG_VERSION="2026-04-23.4-required-source-fix"

# --- Repo root resolution ---
# The script can be invoked from three places:
#   1) /Users/bob/AI-Server/scripts/bob-watchdog.sh (user LaunchAgent)
#   2) /usr/local/bin/bob-watchdog.sh               (system LaunchDaemon copy)
#   3) arbitrary cwd (ad-hoc terminal invocation)
# Any of them must land on the AI-Server repo so `docker compose` can read
# compose files. Preference order:
#   a) $AI_SERVER_ROOT if it points at a repo (has docker-compose.yml)
#   b) legacy $BOB_REPO_DIR if it points at a repo
#   c) canonical /Users/bob/AI-Server if it exists
#   d) infer from $0 if the script lives inside a repo (…/scripts/bob-watchdog.sh)
#   e) unresolved — log with diagnostics, skip container-dependent checks
resolve_repo_root() {
    local candidate script_dir parent
    for candidate in "${AI_SERVER_ROOT:-}" "${BOB_REPO_DIR:-}" "/Users/bob/AI-Server"; do
        [[ -n "$candidate" && -f "$candidate/docker-compose.yml" ]] && { echo "$candidate"; return 0; }
    done
    # Infer from script path — works when scripts/bob-watchdog.sh is run in place.
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
    if [[ -n "$script_dir" ]]; then
        parent="$(cd "$script_dir/.." 2>/dev/null && pwd)"
        [[ -n "$parent" && -f "$parent/docker-compose.yml" ]] && { echo "$parent"; return 0; }
    fi
    return 1
}

REPO_DIR="$(resolve_repo_root || true)"
REPO_RESOLVED=1
if [[ -z "$REPO_DIR" ]]; then
    # Keep REPO_DIR pointed at the canonical path so log/state/alerts under
    # $REPO_DIR still land somewhere plausible for humans to find later.
    REPO_DIR="/Users/bob/AI-Server"
    REPO_RESOLVED=0
fi

# Use an array so word-splitting doesn't re-introduce a malformed
# `docker -d ...` invocation (see ops/verification/…-watchdog-container-
# recovery-hotfix.txt, 2026-04-23 — docker was rejecting `-d` because the
# recovery path was expanding `$COMPOSE` in a context that dropped the
# `compose` sub-command).
COMPOSE=(docker compose)
# Explicit compose files the watchdog should treat as authoritative. Only
# files that actually exist under $REPO_DIR are passed to `docker compose`.
COMPOSE_FILES=(docker-compose.yml)
MAX_LOG_BYTES=2000000

# Optional mode flags — used by install/CI to lint the script without
# executing any side-effectful checks:
#   --check       : syntax-only (bash -n)
#   --dry-run     : run the tick but skip all recovery side effects and exit
MODE=""
for arg in "$@"; do
    case "$arg" in
        --check)   MODE="check" ;;
        --dry-run) MODE="dry-run" ;;
    esac
done
if [[ "$MODE" == "check" ]]; then
    bash -n "$0" && echo "bob-watchdog.sh: syntax OK" && exit 0
    exit 1
fi

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
        local ts
        ts=$(cat "$marker")
        local now
        now=$(date +%s)
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

    if [[ "$MODE" == "dry-run" ]]; then
        log "  [dry-run] would restart Docker Desktop"
        return
    fi

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

# Optional override file — one service name per line (# comments OK). When
# present this file, not the compose config, defines the required list. Use
# this to temporarily pin the set without a code push.
REQUIRED_OVERRIDE_FILE="${BOB_WATCHDOG_REQUIRED:-$REPO_DIR/ops/bob-watchdog.required}"

# Build the compose-file flags for the current repo. Any file listed in
# $COMPOSE_FILES that actually exists under $REPO_DIR is passed with an
# explicit -f so `docker compose` never falls back to walking up from cwd.
compose_file_args() {
    local args=() f
    for f in "${COMPOSE_FILES[@]}"; do
        [[ -f "$REPO_DIR/$f" ]] && args+=(-f "$REPO_DIR/$f")
    done
    printf '%s\n' "${args[@]}"
}

# Resolve the list of required container names. Preference order:
#   1) $REQUIRED_OVERRIDE_FILE (operator-controlled, hot-editable)
#   2) `docker compose -f <repo>/docker-compose.yml config --services`
#   3) empty — skip the check (never page on a stale hard-coded list)
#
# IMPORTANT: this function is called via command substitution —
# required=$(resolve_required) — which runs it in a SUBSHELL. Any plain
# variable assignment inside is lost when the subshell exits. That is why
# source was historically logged as "none" even when the override file was
# present (REQUIRED_SOURCE was mutated only in the child shell).
#
# Fix: write the source to a small state file ($STATE_DIR/required_source)
# from inside resolve_required, then read it back in the parent shell. The
# state file is written on every tick so it always reflects the current
# resolution, not a stale value.
#
# Values written: "override:<path>", "compose", or "none".
# Uses Bash-3.2-compatible idioms (macOS system bash): no mapfile/readarray,
# no associative arrays.
REQUIRED_SOURCE="none"
REQUIRED_SOURCE_FILE="$STATE_DIR/required_source"
write_required_source() {
    # Best-effort; STATE_DIR may not be writable in some odd install modes.
    echo "$1" > "$REQUIRED_SOURCE_FILE" 2>/dev/null || true
}
resolve_required() {
    if [[ -f "$REQUIRED_OVERRIDE_FILE" && -r "$REQUIRED_OVERRIDE_FILE" ]]; then
        write_required_source "override:$REQUIRED_OVERRIDE_FILE"
        grep -vE '^[[:space:]]*(#|$)' "$REQUIRED_OVERRIDE_FILE"
        return
    fi
    if [[ -f "$REPO_DIR/docker-compose.yml" ]]; then
        local file_args=() line
        # Bash 3.2: populate array via while-read instead of mapfile.
        while IFS= read -r line; do
            [[ -n "$line" ]] && file_args+=("$line")
        done < <(compose_file_args)
        write_required_source "compose"
        ( cd "$REPO_DIR" 2>/dev/null && \
          bounded 15 "${COMPOSE[@]}" "${file_args[@]}" config --services 2>/dev/null ) \
          | grep -vE '^[[:space:]]*$'
        return
    fi
    write_required_source "none"
}

# Optional services — missing is reported but never pages. Decommissioned or
# laptop-only services go here. Keep this list in sync with STATUS_REPORT.md.
OPTIONAL_SERVICES=(
    mission-control      # decommissioned 2026 — replaced by Cortex
    knowledge-scanner    # removed from compose 2026-04-14
    openwebui            # removed from compose 2026-04-13 (Prompt N)
    remediator           # removed from compose 2026-04-14
    context-preprocessor # removed from compose 2026-04-14
    x-intake-lab         # intermittent lab container
)

is_optional() {
    local s="$1"
    for o in "${OPTIONAL_SERVICES[@]}"; do
        [[ "$s" == "$o" ]] && return 0
    done
    return 1
}

# --- CHECK 4: Missing containers ---
check_containers() {
    docker info >/dev/null 2>&1 || return
    if ! cd "$REPO_DIR" 2>/dev/null; then
        log "  container check skipped (cannot cd to REPO_DIR=$REPO_DIR; cwd=$(pwd))"
        return
    fi

    local running required
    running=$(docker ps --format '{{.Names}}' 2>/dev/null)
    required=$(resolve_required)
    # Read the source written by the subshell-invoked resolve_required.
    # Default back to "none" if the state file was not writable.
    if [[ -f "$REQUIRED_SOURCE_FILE" ]]; then
        REQUIRED_SOURCE=$(cat "$REQUIRED_SOURCE_FILE" 2>/dev/null || echo "none")
    else
        REQUIRED_SOURCE="none"
    fi
    log "  required services source=${REQUIRED_SOURCE}"

    if [[ -z "$required" ]]; then
        # No authoritative list — skip to avoid paging on a stale hard-coded set.
        # Emit actionable diagnostics so a broken deployment is obvious in logs.
        local override_exists="no" override_readable="no" override_lines=0
        if [[ -e "$REQUIRED_OVERRIDE_FILE" ]]; then
            override_exists="yes"
            [[ -r "$REQUIRED_OVERRIDE_FILE" ]] && override_readable="yes"
            override_lines=$(grep -cvE '^[[:space:]]*(#|$)' "$REQUIRED_OVERRIDE_FILE" 2>/dev/null || echo 0)
        fi
        local compose_yml="missing"
        [[ -f "$REPO_DIR/docker-compose.yml" ]] && compose_yml="present"
        local diag
        diag="resolved=${REPO_RESOLVED} repo_dir=${REPO_DIR} cwd=$(pwd)"
        diag+=" compose_yml=${compose_yml} override_path=${REQUIRED_OVERRIDE_FILE}"
        diag+=" override_exists=${override_exists} override_readable=${override_readable}"
        diag+=" override_lines=${override_lines} source=${REQUIRED_SOURCE}"
        log "  container check skipped (no compose services resolved) — $diag"
        # FOLLOWUP: if we believe we should have an override (resolved repo)
        # but the file is missing/unreadable, shout loudly so ops notices.
        if (( REPO_RESOLVED == 1 )) && [[ "$override_exists" != "yes" || "$override_readable" != "yes" ]]; then
            log_alert "[FOLLOWUP] required service override missing: $REQUIRED_OVERRIDE_FILE (exists=$override_exists readable=$override_readable)"
        fi
        return
    fi

    local missing_required=() missing_optional=()
    while IFS= read -r svc; do
        [[ -z "$svc" ]] && continue
        if ! echo "$running" | grep -q "^${svc}$"; then
            if is_optional "$svc"; then
                missing_optional+=("$svc")
            else
                missing_required+=("$svc")
            fi
        fi
    done <<< "$required"

    # Optional-only misses: log once per hour, never restart.
    if (( ${#missing_optional[@]} > 0 )); then
        if ! in_cooldown "containers_optional" 3600; then
            log "  Missing optional (ignored): ${missing_optional[*]}"
            mark_action "containers_optional"
        fi
    fi

    if (( ${#missing_required[@]} == 0 )); then
        return
    fi

    log_alert "Missing containers: ${missing_required[*]}"
    in_cooldown "containers" 300 && { log "  cooldown, skip"; return; }

    if [[ "$MODE" == "dry-run" ]]; then
        log "  [dry-run] would run: ${COMPOSE[*]} up -d --no-build ${missing_required[*]}"
        mark_action "containers"
        return
    fi

    # Recovery: bound the compose invocation and capture its exit code. Only
    # claim recovery when (a) exit 0 AND (b) every previously-missing required
    # container is now running. Pass explicit -f so the recovery never depends
    # on cwd-relative compose discovery.
    local rc=0
    local file_args=() line
    while IFS= read -r line; do
        [[ -n "$line" ]] && file_args+=("$line")
    done < <(compose_file_args)
    bounded 180 "${COMPOSE[@]}" "${file_args[@]}" up -d --no-build "${missing_required[@]}" >>"$LOG" 2>&1
    rc=$?
    mark_action "containers"

    if (( rc != 0 )); then
        log_alert "Recovery command failed (exit $rc); see log above"
        return
    fi

    # Re-probe: every service in missing_required must now appear.
    sleep 3
    running=$(docker ps --format '{{.Names}}' 2>/dev/null)
    local still_missing=()
    for svc in "${missing_required[@]}"; do
        echo "$running" | grep -q "^${svc}$" || still_missing+=("$svc")
    done

    if (( ${#still_missing[@]} > 0 )); then
        log_alert "Recovery ran exit=0 but still missing: ${still_missing[*]}"
        return
    fi

    log "  Containers recovered: ${missing_required[*]}"
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
        if [[ "$MODE" == "dry-run" ]]; then
            log "  [dry-run] would restart $c"
            continue
        fi
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
    [[ "$MODE" == "dry-run" ]] && { log "  [dry-run] would restart email-monitor"; return; }
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
    [[ "$MODE" == "dry-run" ]] && { log "  [dry-run] would restart x-intake"; return; }
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
    echo "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$REPO_DIR/data/task_runner/bob_watchdog_heartbeat.txt" 2>/dev/null || true
}

# --- MAIN ---
# Clear stale per-tick state so source=<prev> from an earlier tick cannot
# leak into this tick if resolve_required() is never entered.
rm -f "$REQUIRED_SOURCE_FILE" 2>/dev/null || true
log "--- tick --- v=${WATCHDOG_VERSION} repo=${REPO_DIR} resolved=${REPO_RESOLVED}"
[[ "$MODE" == "dry-run" ]] && log "  MODE=dry-run (no side effects)"
if (( REPO_RESOLVED == 0 )); then
    log_alert "AI-Server repo root not resolvable — set AI_SERVER_ROOT or deploy to /Users/bob/AI-Server. Skipping container/stack checks."
fi
check_tailscale
check_dns
restore_tailscale_dns
check_docker
if (( REPO_RESOLVED == 1 )); then
    check_containers
    check_unhealthy
    check_email_dns
    check_x_intake
fi
write_heartbeat
log "--- done ---"
