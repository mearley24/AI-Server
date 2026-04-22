#!/bin/bash
# task-runner-watchdog: detects runner wedge, auto-kicks it, iMessages Matt.
#
# Trigger policy:
#   - heartbeat.txt age > 300s  -> runner is stuck. Kick it.
#   - 'preflight-blocked heartbeat' commits for > 3 consecutive ticks
#     (>= 4 min in a row where no task dispatch happened even though tasks
#     are pending) -> preflight jam. Notify human, kick runner anyway so
#     the dirty working tree stashes on next bootstrap.
#
# Idempotency: uses /tmp/task-runner-watchdog.state to only notify once per
# wedge event. Resets when runner heartbeat goes fresh again.
#
# Notification path (two redundant channels):
#   1. Direct POST to imessage bridge on http://localhost:8199
#   2. Redis publish to 'notifications:ops:send' (hermes -> bridge)
# Either path reaches Matt's iMessage. Redundancy because bridge and hub
# can wedge independently.
#
# Run via launchd every 90 seconds. See
# ops/task_runner/com.symphony.task-runner-watchdog.plist.
set -uo pipefail

ROOT="/Users/bob/AI-Server"
HEARTBEAT="$ROOT/data/task_runner/heartbeat.txt"
PENDING_DIR="$ROOT/ops/work_queue/pending"
LOG_DIR="$ROOT/data/task_runner"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
WATCHDOG_HEARTBEAT="$LOG_DIR/watchdog_heartbeat.txt"
STATE_FILE="/tmp/task-runner-watchdog.state"
RUNNER_LABEL="com.symphony.task-runner"
UID_BOB="$(id -u)"
RUNNER_TARGET="gui/${UID_BOB}/${RUNNER_LABEL}"

STALE_SECONDS=300
PREFLIGHT_STUCK_TICKS=3
MATT_PHONE="${MATT_PHONE_NUMBER:-}"
BRIDGE_URL="${IMESSAGE_BRIDGE_URL:-http://localhost:8199}"
# Hard rate-limit on outbound watchdog texts, independent of the per-event
# one-shot state. Prevents a flapping heartbeat (fresh/stale oscillation)
# from repeatedly re-texting Matt about the same class of event.
NOTIFY_COOLDOWN_SECONDS="${WATCHDOG_NOTIFY_COOLDOWN_SECONDS:-3600}"

mkdir -p "$LOG_DIR"

log(){
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$now] $*" >> "$WATCHDOG_LOG"
}

publish_watchdog_heartbeat(){
  echo "last-watchdog-tick: $(date +%Y-%m-%dT%H:%M:%S%z)" > "$WATCHDOG_HEARTBEAT"
}

read_state_key(){
  local key="$1"
  [ -f "$STATE_FILE" ] || return 0
  grep "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | sed "s/^${key}=//"
}

write_state(){
  local key="$1" val="$2"
  local tmp
  tmp="$(mktemp)"
  if [ -f "$STATE_FILE" ]; then
    grep -v "^${key}=" "$STATE_FILE" > "$tmp" 2>/dev/null || true
  fi
  echo "${key}=${val}" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

clear_state_key(){
  local key="$1"
  [ -f "$STATE_FILE" ] || return 0
  local tmp
  tmp="$(mktemp)"
  grep -v "^${key}=" "$STATE_FILE" > "$tmp" 2>/dev/null || true
  mv "$tmp" "$STATE_FILE"
}

heartbeat_age_seconds(){
  [ -f "$HEARTBEAT" ] || { echo 999999; return; }
  local ts_raw
  ts_raw="$(sed -n 's/^last-heartbeat: //p' "$HEARTBEAT" | head -1)"
  [ -n "$ts_raw" ] || { echo 999999; return; }
  local hb_epoch now_epoch
  hb_epoch="$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "${ts_raw}" +%s 2>/dev/null || echo 0)"
  [ "$hb_epoch" -eq 0 ] && {
    hb_epoch="$(date -j -f "%Y-%m-%dT%H:%M:%S" "${ts_raw%[+-]*}" +%s 2>/dev/null || echo 0)"
  }
  now_epoch="$(date +%s)"
  echo $(( now_epoch - hb_epoch ))
}

pending_task_count(){
  [ -d "$PENDING_DIR" ] || { echo 0; return; }
  ls -1 "$PENDING_DIR"/*.json 2>/dev/null | wc -l | tr -d ' '
}

last_commit_msg(){
  cd "$ROOT" || return
  git log -1 --format="%s" 2>/dev/null
}

kick_runner(){
  log "kickstart: $RUNNER_TARGET"
  launchctl kickstart -k "$RUNNER_TARGET" >> "$WATCHDOG_LOG" 2>&1
  echo $?
}

notify_direct_bridge(){
  local title="$1" body="$2"
  [ -n "$MATT_PHONE" ] || { log "notify_direct_bridge: MATT_PHONE unset, skip"; return 1; }
  local payload
  payload="$(PHONE="$MATT_PHONE" BODY="$body" TITLE="$title" python3 -c "import json,os; print(json.dumps({'phone': os.environ['PHONE'], 'body': os.environ['BODY'], 'title': os.environ['TITLE']}))")"
  curl -fsS -m 15 -H 'Content-Type: application/json' -d "$payload" "$BRIDGE_URL" >> "$WATCHDOG_LOG" 2>&1
  local rc=$?
  log "bridge_direct rc=$rc"
  return $rc
}

notify_redis_hub(){
  local title="$1" body="$2"
  command -v redis-cli >/dev/null 2>&1 || { log "notify_redis_hub: redis-cli unavailable"; return 1; }
  local payload
  payload="$(TITLE="$title" BODY="$body" PHONE="${MATT_PHONE:-}" python3 -c "
import json, os
req = {
  'recipient': os.environ.get('PHONE','') or 'matt',
  'message': os.environ['BODY'],
  'subject': os.environ['TITLE'],
  'channel': 'imessage',
  'priority': 'urgent',
  'message_type': 'alert',
}
print(json.dumps(req))
")"
  redis-cli -h 127.0.0.1 -p 6379 publish 'notifications:ops:send' "$payload" >> "$WATCHDOG_LOG" 2>&1
  local rc=$?
  log "redis_publish rc=$rc (notifications:ops:send)"
  return $rc
}

notify_matt(){
  local title="$1" body="$2"
  # Rate-limit: only one outbound text per NOTIFY_COOLDOWN_SECONDS for a
  # given title class (e.g. "runner wedge"). Suppressed notifications are
  # still logged to $WATCHDOG_LOG so you can see what would have fired.
  local key_raw key last_ts now
  key_raw="$(printf '%s' "$title" | tr -cs '[:alnum:]' '_' | tr '[:upper:]' '[:lower:]' | sed 's/_*$//')"
  key="last_notify_${key_raw}"
  now="$(date +%s)"
  last_ts="$(read_state_key "$key")"
  if [ -n "$last_ts" ]; then
    local delta=$(( now - last_ts ))
    if [ "$delta" -lt "$NOTIFY_COOLDOWN_SECONDS" ]; then
      log "notify SUPPRESSED (cooldown ${delta}s < ${NOTIFY_COOLDOWN_SECONDS}s) title='${title}' body='${body:0:120}'"
      return 0
    fi
  fi
  local a=1 b=1
  notify_direct_bridge "$title" "$body" && a=0
  notify_redis_hub     "$title" "$body" && b=0
  if [ "$a" -ne 0 ] && [ "$b" -ne 0 ]; then
    log "ALL notification paths failed for: $title"
    return 1
  fi
  write_state "$key" "$now"
  return 0
}

main(){
  publish_watchdog_heartbeat

  local age pending last_msg
  age="$(heartbeat_age_seconds)"
  pending="$(pending_task_count)"
  last_msg="$(last_commit_msg)"
  log "tick age_s=$age pending=$pending last_commit='${last_msg:0:100}'"

  local wedged_since
  wedged_since="$(read_state_key wedged_since)"

  if [ "$age" -gt "$STALE_SECONDS" ]; then
    if [ -z "$wedged_since" ]; then
      wedged_since="$(date +%s)"
      write_state wedged_since "$wedged_since"
      log "NEW WEDGE detected: heartbeat ${age}s stale, pending=$pending last_msg='${last_msg:0:80}'"
      # Suppress the outbound text when the last commit was a plain
      # heartbeat tick and no work is pending: healthy idle runner, not a
      # user-actionable wedge. Still kick the runner so the heartbeat
      # refreshes. Matt should only be paged on genuine stuck-work.
      case "$last_msg" in
        *"— heartbeat"*|*"-- heartbeat"*)
          if [ "$pending" -eq 0 ]; then
            log "wedge notify SUPPRESSED: last tick was heartbeat-only and pending=0 (healthy idle)"
          else
            notify_matt "runner wedge" "task-runner heartbeat ${age}s stale. pending=${pending}. last='${last_msg:0:80}'. kicking via launchctl."
          fi
          ;;
        *)
          notify_matt "runner wedge" "task-runner heartbeat ${age}s stale. pending=${pending}. last='${last_msg:0:80}'. kicking via launchctl."
          ;;
      esac
    else
      log "wedge ongoing: age=${age}s wedged_since=${wedged_since}"
    fi
    kick_runner
    exit 0
  fi

  clear_state_key wedged_since

  if [ "$pending" -gt 0 ]; then
    local consec preflight_stuck
    consec="$(read_state_key preflight_stuck_consec)"
    consec="${consec:-0}"
    case "$last_msg" in
      *preflight-blocked*)
        consec=$(( consec + 1 ))
        write_state preflight_stuck_consec "$consec"
        log "preflight-blocked consec=$consec pending=$pending"
        if [ "$consec" -ge "$PREFLIGHT_STUCK_TICKS" ]; then
          local already
          already="$(read_state_key preflight_notified)"
          if [ -z "$already" ]; then
            write_state preflight_notified 1
            log "PREFLIGHT JAM: ${consec} consecutive preflight-blocked ticks with pending tasks"
            notify_matt "runner preflight jam" \
              "task-runner heartbeat fresh but preflight blocked for ${consec} ticks. pending=${pending}. kicking runner to force re-bootstrap."
            kick_runner
          fi
        fi
        ;;
      *)
        if [ "$consec" -ne 0 ]; then
          log "preflight_stuck_consec reset (last_msg changed)"
        fi
        write_state preflight_stuck_consec 0
        clear_state_key preflight_notified
        ;;
    esac
  else
    write_state preflight_stuck_consec 0
    clear_state_key preflight_notified
  fi

  exit 0
}

main "$@"
