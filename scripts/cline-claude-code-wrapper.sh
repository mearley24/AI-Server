#!/bin/zsh

export HOME="/Users/bob"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/bob/.npm-global/bin:$PATH"
export NO_COLOR=1
export TERM=dumb

REAL_CLAUDE="/opt/homebrew/bin/claude"
LOG="${TMPDIR:-/tmp}/cline-claude-code-wrapper.log"

{
  echo "=== $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
  echo "real_claude=$REAL_CLAUDE"
  echo "home=$HOME"
  echo "pwd=$(pwd)"
  echo "args=$*"
} >> "$LOG"

i=1
while [ "$i" -le "$#" ]; do
  arg="${@[$i]}"
  if [ "$arg" = "--system-prompt-file" ]; then
    j=$((i + 1))
    file="${@[$j]}"
    if [ -f "$file" ]; then
      echo "system_prompt_file=$file" >> "$LOG"
      wc -c "$file" | awk '{print "system_prompt_bytes="$1}' >> "$LOG"
      head -1 "$file" | sed 's/./*/g' | awk '{print "system_prompt_first_line_redacted_len=" length($0)}' >> "$LOG"
    else
      echo "system_prompt_file_missing=$file" >> "$LOG"
    fi
  fi
  i=$((i + 1))
done

ERRFILE="${TMPDIR:-/tmp}/cline-claude-code-wrapper-stderr.$$"
"$REAL_CLAUDE" "$@" 2> "$ERRFILE"
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
