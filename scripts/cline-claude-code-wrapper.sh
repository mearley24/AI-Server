#!/bin/zsh
export HOME="/Users/bob"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/bob/.npm-global/bin:$PATH"
LOG="${TMPDIR:-/tmp}/cline-claude-code-wrapper.log"
echo "=== $(date "+%Y-%m-%dT%H:%M:%S%z") ===" >> "$LOG"
echo "real_claude=/opt/homebrew/bin/claude" >> "$LOG"
echo "home=$HOME" >> "$LOG"
echo "args=$*" >> "$LOG"
"/opt/homebrew/bin/claude" "$@" 2>> "$LOG"
CODE=$?
echo "exit=$CODE" >> "$LOG"
exit $CODE
