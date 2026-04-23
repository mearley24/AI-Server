#!/bin/zsh

export HOME="/Users/bob"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/bob/.npm-global/bin:$PATH"
export NO_COLOR=1
export TERM=dumb

REAL_CLAUDE="/opt/homebrew/bin/claude"
LOG="${TMPDIR:-/tmp}/cline-claude-code-wrapper.log"
MODEL_FILE="$HOME/.cline-claude-model"

DEFAULT_MODEL="claude-sonnet-4-20250514"
TARGET_MODEL="$DEFAULT_MODEL"

if [ -f "$MODEL_FILE" ]; then
  RAW_MODEL="$(cat "$MODEL_FILE" | tr -d "[:space:]")"
  if [ -n "$RAW_MODEL" ]; then
    TARGET_MODEL="$RAW_MODEL"
  fi
fi

case "$TARGET_MODEL" in
  sonnet|sonnet4|sonnet-4)
    TARGET_MODEL="claude-sonnet-4-20250514"
    ;;
  sonnet46|sonnet-4-6|claude-sonnet-4-6)
    TARGET_MODEL="claude-sonnet-4-6"
    ;;
  sonnet46-1m|sonnet-4-6-1m|claude-sonnet-4-6-1m|claude-sonnet-4-6[1m])
    TARGET_MODEL="claude-sonnet-4-6[1m]"
    ;;
  opus47|opus-4-7|claude-opus-4-7)
    TARGET_MODEL="claude-opus-4-7"
    ;;
  opus47-1m|opus-4-7-1m|claude-opus-4-7-1m|claude-opus-4-7[1m])
    TARGET_MODEL="claude-opus-4-7[1m]"
    ;;
esac

ARGS=()
SKIP_NEXT=0

while [ "$#" -gt 0 ]; do
  if [ "$SKIP_NEXT" = "1" ]; then
    SKIP_NEXT=0
    shift
    continue
  fi

  if [ "$1" = "--model" ]; then
    ARGS+=("--model" "$TARGET_MODEL")
    SKIP_NEXT=1
    shift
    continue
  fi

  ARGS+=("$1")
  shift
done

HAS_MODEL=0
for arg in "${ARGS[@]}"; do
  if [ "$arg" = "--model" ]; then
    HAS_MODEL=1
    break
  fi
done

if [ "$HAS_MODEL" = "0" ]; then
  ARGS=("--model" "$TARGET_MODEL" "${ARGS[@]}")
fi

{
  echo "=== $(date "+%Y-%m-%dT%H:%M:%S%z") ==="
  echo "real_claude=$REAL_CLAUDE"
  echo "target_model=$TARGET_MODEL"
  echo "home=$HOME"
  echo "pwd=$(pwd)"
  echo "args_redacted=${ARGS[*]}"
} >> "$LOG"

ERRFILE="${TMPDIR:-/tmp}/cline-claude-code-wrapper-stderr.$$"
"$REAL_CLAUDE" "${ARGS[@]}" 2> "$ERRFILE"
CODE=$?

{
  echo "exit=$CODE"
  if [ -s "$ERRFILE" ]; then
    echo "--- stderr ---"
    cat "$ERRFILE"
    echo "--- end stderr ---"
  fi
} >> "$LOG"

rm -f "$ERRFILE"
exit "$CODE"
