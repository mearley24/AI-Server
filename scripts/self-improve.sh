#!/usr/bin/env bash
# self-improve.sh — capture X/Twitter links and automation ideas into
# a bounded, repo-safe self-improvement inbox, and route processing
# through the existing ai-dispatch.sh gates.
#
# Modes:
#   add-url <url> [note...]  Write a timestamped inbox item with URL + note.
#   add-note <text...>       Write a timestamped inbox item with free text.
#   list                     Show inbox/card/archive counts and recent items.
#   process                  Run the process-inbox prompt via ai-dispatch.sh
#                            (falls back to `claude` direct if dispatcher
#                            is absent).
#   promote <card-file>      Print the proposed next command for a card.
#                            Never executes anything.
#
# Safety:
#   - Does not read, print, or log secrets.
#   - Does not browse the web.
#   - Does not send external communications.
#   - `promote` is print-only; it does not run the proposed command.

set -euo pipefail

MODE="${1:-}"
shift || true

# --- locate repo root -----------------------------------------------------
resolve_repo_root() {
  if [ -d "${HOME}/AI-Server/.git" ]; then
    echo "${HOME}/AI-Server"
    return 0
  fi
  local here dir
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  dir="$here"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/.git" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

REPO_ROOT="$(resolve_repo_root)" || {
  echo "[self-improve] ERROR: could not locate AI-Server repo root" >&2
  exit 1
}
cd "$REPO_ROOT"

INBOX_DIR="ops/self_improvement/inbox"
CARDS_DIR="ops/self_improvement/cards"
ARCHIVE_DIR="ops/self_improvement/archive"
PROMPT_PATH=".cursor/prompts/self-improvement/process-inbox.md"

mkdir -p "$INBOX_DIR" "$CARDS_DIR" "$ARCHIVE_DIR"

ts() { date -u +%Y%m%dT%H%M%SZ; }

slugify() {
  # Bounded filename-safe slug (lowercase alnum + dashes), capped at 48 chars.
  local s="${1:-item}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | tr -s '-' | sed 's/^-//;s/-$//')"
  if [ -z "$s" ]; then s="item"; fi
  echo "${s:0:48}"
}

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/self-improve.sh add-url <url> [note...]
  scripts/self-improve.sh add-note <text...>
  scripts/self-improve.sh list
  scripts/self-improve.sh process
  scripts/self-improve.sh promote <card-file>
EOF
  exit 2
}

cmd_add_url() {
  local url="${1:-}"
  if [ -z "$url" ]; then
    echo "[self-improve] add-url requires a URL" >&2
    usage
  fi
  shift || true
  local note="$*"
  local stamp slug fname
  stamp="$(ts)"
  # Derive a short slug from the URL path / host.
  local host_or_path
  host_or_path="$(printf '%s' "$url" | sed -E 's#^https?://##; s#[?#].*##')"
  slug="$(slugify "$host_or_path")"
  fname="$INBOX_DIR/${stamp}-url-${slug}.md"

  {
    echo "---"
    echo "captured: $stamp"
    echo "kind: url"
    echo "source: $url"
    echo "---"
    echo
    echo "# Inbox item"
    echo
    echo "- **Source URL:** $url"
    if [ -n "$note" ]; then
      echo "- **Why this matters (Matt):** $note"
    else
      echo "- **Why this matters (Matt):** _(no note)_"
    fi
    echo
    echo "_Raw capture only. Do not execute anything referenced here._"
  } > "$fname"

  echo "[self-improve] wrote $fname"
}

cmd_add_note() {
  if [ "$#" -eq 0 ]; then
    echo "[self-improve] add-note requires text" >&2
    usage
  fi
  local text="$*"
  local stamp slug fname
  stamp="$(ts)"
  slug="$(slugify "$text")"
  fname="$INBOX_DIR/${stamp}-note-${slug}.md"

  {
    echo "---"
    echo "captured: $stamp"
    echo "kind: note"
    echo "---"
    echo
    echo "# Inbox item"
    echo
    echo "- **Note (Matt):**"
    echo
    echo "> $text"
    echo
    echo "_Raw capture only. Do not execute anything referenced here._"
  } > "$fname"

  echo "[self-improve] wrote $fname"
}

cmd_list() {
  local inbox_count card_count archive_count
  inbox_count="$(find "$INBOX_DIR" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
  card_count="$(find "$CARDS_DIR" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"
  archive_count="$(find "$ARCHIVE_DIR" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')"

  echo "inbox:   $inbox_count md file(s) in $INBOX_DIR"
  echo "cards:   $card_count md file(s) in $CARDS_DIR"
  echo "archive: $archive_count md file(s) in $ARCHIVE_DIR"
  echo
  echo "Recent inbox (last 10):"
  find "$INBOX_DIR" -maxdepth 1 -type f -name '*.md' | sort | tail -10 | sed 's/^/  /'
  echo
  echo "Recent cards (last 10):"
  find "$CARDS_DIR" -maxdepth 1 -type f -name '*.md' | sort | tail -10 | sed 's/^/  /'
}

cmd_process() {
  if [ ! -f "$PROMPT_PATH" ]; then
    echo "[self-improve] ERROR: prompt not found at $PROMPT_PATH" >&2
    exit 1
  fi

  if [ -x "scripts/ai-dispatch.sh" ] || [ -f "scripts/ai-dispatch.sh" ]; then
    echo "[self-improve] dispatching via scripts/ai-dispatch.sh run-prompt"
    exec bash scripts/ai-dispatch.sh run-prompt "$PROMPT_PATH"
  fi

  if command -v claude >/dev/null 2>&1; then
    echo "[self-improve] ai-dispatch.sh not found; falling back to direct claude 1M"
    local model="${CLAUDE_MODEL:-claude-sonnet-4-6[1m]}"
    exec claude --model "$model" -p "$(cat "$PROMPT_PATH")"
  fi

  echo "[self-improve] ERROR: no ai-dispatch.sh and no claude CLI on PATH" >&2
  exit 1
}

cmd_promote() {
  local card="${1:-}"
  if [ -z "$card" ]; then
    echo "[self-improve] promote requires a card file" >&2
    usage
  fi
  if [ ! -f "$card" ]; then
    echo "[self-improve] ERROR: $card not found" >&2
    exit 1
  fi

  echo "[self-improve] promote is print-only. It does NOT execute."
  echo
  echo "Card:         $card"
  echo

  # Try to extract the proposed prompt path from the card.
  local proposed
  proposed="$(grep -Eo '\.cursor/prompts/self-improvement/[A-Za-z0-9._/-]+\.md' "$card" | head -1 || true)"

  if [ -n "$proposed" ] && [ -f "$proposed" ]; then
    echo "Proposed prompt:  $proposed"
    echo
    echo "Suggested next command (review the card and the prompt first, then run manually):"
    echo "  bash scripts/ai-dispatch.sh run-prompt $proposed"
  elif [ -n "$proposed" ]; then
    echo "Proposed prompt path (NOT YET DRAFTED): $proposed"
    echo
    echo "Next step: draft the prompt at that path, review it, then run:"
    echo "  bash scripts/ai-dispatch.sh run-prompt $proposed"
  else
    echo "This card does not include a proposed implementation prompt."
    echo "It is likely 'needs Matt', 'reject/defer', 'needs fetch', or"
    echo "'external connector follow-up'. Review the card before acting."
  fi

  echo
  echo "Nothing was executed. No files were modified. No messages were sent."
}

case "$MODE" in
  add-url)   cmd_add_url "$@" ;;
  add-note)  cmd_add_note "$@" ;;
  list)      cmd_list ;;
  process)   cmd_process ;;
  promote)   cmd_promote "$@" ;;
  ""|-h|--help|help) usage ;;
  *) echo "[self-improve] unknown mode: $MODE" >&2; usage ;;
esac
