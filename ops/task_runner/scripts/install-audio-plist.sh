#!/bin/bash
# Install the com.symphony.audio-intake plist with OPENAI_API_KEY + Ollama
# env vars injected from /Users/bob/AI-Server/.env (Bob-local, gitignored).
#
# Why: the git-tracked plist template has NO secrets. We copy it to
# ~/Library/LaunchAgents/ and patch in the secret env vars using PlistBuddy
# so the daemon's inherited environment actually contains the OpenAI key.
# launchd does NOT inherit the user's shell env — secrets must be in the
# plist's <EnvironmentVariables> dict (or loaded by the program itself).
#
# Idempotent: re-running re-copies the template and re-patches the env.
# Safe to call from the task-runner daemon — this label is different from
# the runner's label, so no self-bootout fork-bomb risk.
set -uo pipefail

LABEL="com.symphony.audio-intake"
SRC="/Users/bob/AI-Server/scripts/launchd/${LABEL}.plist"
DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
ENV_FILE="/Users/bob/AI-Server/.env"
UID_BOB="$(id -u bob)"
TARGET="gui/${UID_BOB}/${LABEL}"

[ -f "$SRC" ] || { echo "missing src: $SRC"; exit 2; }
[ -f "$ENV_FILE" ] || { echo "missing env: $ENV_FILE"; exit 3; }

echo "copying plist: $SRC -> $DST"
cp "$SRC" "$DST"
chmod 644 "$DST"

# Source .env safely — ignore shell-hostile lines, only pick up KEY=value.
# We deliberately don't `source` the whole file because .env can contain
# values with embedded spaces/quotes that break `set -u` or re-export PATH.
get_env() {
  local key="$1"
  # first match wins; strip surrounding quotes; ignore commented lines
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null \
    | head -1 \
    | sed -E "s/^${key}=//; s/^[\"']//; s/[\"']$//"
}

OPENAI_API_KEY="$(get_env OPENAI_API_KEY)"
# Model override: honor .env if set, else default to qwen3:8b (will work after
# pull-qwen3-8b.sh runs). Fallback to llama3.2:3b if explicitly set there.
OLLAMA_MEETING_MODEL="$(get_env OLLAMA_MEETING_MODEL)"
[ -z "$OLLAMA_MEETING_MODEL" ] && OLLAMA_MEETING_MODEL="qwen3:8b"
OLLAMA_HOST_VAL="$(get_env OLLAMA_HOST)"
[ -z "$OLLAMA_HOST_VAL" ] && OLLAMA_HOST_VAL="http://192.168.1.189:11434"

if [ -z "$OPENAI_API_KEY" ]; then
  echo "WARN: OPENAI_API_KEY not found in $ENV_FILE — OpenAI fallback will remain disabled."
  echo "      Ollama primary will still work if qwen3:8b is pulled."
else
  keylen=${#OPENAI_API_KEY}
  keytail="${OPENAI_API_KEY: -4}"
  echo "OPENAI_API_KEY: loaded (len=$keylen, tail=****$keytail)"
fi
echo "OLLAMA_HOST: $OLLAMA_HOST_VAL"
echo "OLLAMA_MEETING_MODEL: $OLLAMA_MEETING_MODEL"

# Patch the copied plist with PlistBuddy.
# Add-or-set pattern: try Set; if that fails the key doesn't exist, so Add.
PB="/usr/libexec/PlistBuddy"

set_env_var() {
  local k="$1" v="$2"
  if $PB -c "Print :EnvironmentVariables:$k" "$DST" >/dev/null 2>&1; then
    $PB -c "Set :EnvironmentVariables:$k $v" "$DST"
  else
    $PB -c "Add :EnvironmentVariables:$k string $v" "$DST"
  fi
}

if [ -n "$OPENAI_API_KEY" ]; then
  set_env_var OPENAI_API_KEY "$OPENAI_API_KEY"
fi
set_env_var OLLAMA_HOST "$OLLAMA_HOST_VAL"
set_env_var OLLAMA_MEETING_MODEL "$OLLAMA_MEETING_MODEL"

echo
echo "bootout (ignore not-loaded error):"
launchctl bootout "$TARGET" 2>&1 || true

echo
echo "bootstrap:"
launchctl bootstrap "gui/${UID_BOB}" "$DST"

echo
echo "verify env keys in installed plist (values masked):"
$PB -c "Print :EnvironmentVariables" "$DST" 2>/dev/null | \
  awk '
    /^Dict \{/ { next }
    /^\}/ { next }
    /OPENAI_API_KEY|OLLAMA/ {
      key = $1
      sub(/ =.*/, "", key)
      if (key == "OPENAI_API_KEY") {
        line = $0
        sub(/.* = /, "", line)
        n = length(line)
        tail = substr(line, n-3, 4)
        printf "  %s = ****%s (len=%d)\n", key, tail, n
      } else {
        print "  " $0
      }
    }
    /AI_SERVER_ROOT|CORTEX_URL|PATH/ {
      print "  " $0
    }
  '

echo
echo "launchctl state:"
launchctl print "$TARGET" 2>/dev/null | awk '/state|path|WatchPaths|StartInterval|ThrottleInterval/ {print}' | head -10 || true

echo
echo "ok: audio-intake plist installed with secrets injected."
