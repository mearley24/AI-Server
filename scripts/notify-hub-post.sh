#!/usr/bin/env bash
# scripts/notify-hub-post.sh — thin helper to send a message via
# notification-hub without inlining JSON in curl (zsh rule).
#
# Usage:
#   bash scripts/notify-hub-post.sh "<channel>" "<title>" "<body>"
#
# channel: one of imessage | telegram | email (depends on hub config)
# title:   short headline
# body:    message body (first line of detail)
#
# The hub endpoint defaults to http://127.0.0.1:8095/dispatch; override
# via NOTIFY_URL env. This script writes a temp JSON file, posts it with
# `scripts/api-post.sh`, and prints the HTTP body + status.
set -euo pipefail

ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
URL="${NOTIFY_URL:-http://127.0.0.1:8095/dispatch}"
APIPOST="$ROOT/scripts/api-post.sh"

if [ $# -lt 3 ]; then
  echo "usage: $0 <channel> <title> <body>" >&2
  exit 2
fi

CHANNEL="$1"
TITLE="$2"
BODY="$3"

if [ ! -x "$APIPOST" ]; then
  echo "missing or non-executable: $APIPOST" >&2
  exit 2
fi

TMP="$(mktemp -t notifyhub.XXXXXX.json)"
trap 'rm -f "$TMP"' EXIT

/opt/homebrew/bin/python3 -c "
import json, os, sys
payload = {
    'channel':  os.environ['CHANNEL'],
    'title':    os.environ['TITLE'],
    'body':     os.environ['BODY'],
    'priority': os.environ.get('NOTIFY_PRIORITY', 'normal'),
    'source':   os.environ.get('NOTIFY_SOURCE', 'cli:notify-hub-post'),
}
open(os.environ['TMP'], 'w').write(json.dumps(payload))
" CHANNEL="$CHANNEL" TITLE="$TITLE" BODY="$BODY" TMP="$TMP"

bash "$APIPOST" "$URL" "@$TMP"
