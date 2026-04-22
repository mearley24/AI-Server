#!/usr/bin/env bash
# self-improvement-collect.sh — stream-driven collector for the
# self-improvement loop. Reads items from already-wired local intake
# streams (x_intake, BlueBubbles/iMessage) and normalizes them into
# bounded markdown files under ops/self_improvement/inbox/.
#
# Modes:
#   scan                Run every available scan-<lane> in order.
#   scan-x              Read x_intake local SQLite queue.
#   scan-bluebubbles    Read BlueBubbles / iMessage events + DB (when present).
#   sources             Print detected sources and what is missing.
#   daemon-once         Run scan, then scripts/self-improve.sh process once.
#
# Safety invariants:
#   - Read-only everywhere. Never modifies stream-side data.
#   - Never opens a network connection.
#   - Never reads, prints, or logs secrets (.env, *.key, *.pem, ssh dirs).
#   - Only uses config / env values already consumed by existing repo
#     scripts. Missing config is reported, not substituted.
#   - Bounded: per-source row cap and per-item byte cap.
#   - Idempotent: dedupes by content hash against inbox/, archive/, cards/.
#
# Exit codes:
#   0 success (including "no items found")
#   1 fatal error (repo root missing, invalid mode)
#   2 usage
#
# This script is intentionally conservative. If an expected data source
# is not present on this host, the corresponding scan becomes a no-op
# with a one-line note in the summary.

set -euo pipefail

MODE="${1:-}"
shift || true

# ── Config (all overridable via env; defaults are conservative) ───────────

# Per-source row cap (x_intake rows / iMessage rows / BlueBubbles events).
ROW_CAP="${SELF_IMPROVE_ROW_CAP:-200}"
# Per-item raw_excerpt byte cap after normalization.
BYTE_CAP="${SELF_IMPROVE_BYTE_CAP:-10240}"
# Lookback window in hours for rows/events. 24h default.
LOOKBACK_HOURS="${SELF_IMPROVE_LOOKBACK_HOURS:-24}"

# x_intake SQLite queue (matches integrations/x_intake/queue_db.py).
# Can be overridden via env if Matt moves the data dir.
X_INTAKE_DB="${X_INTAKE_DB:-/data/x_intake/queue.db}"
X_INTAKE_ACTION_DB="${X_INTAKE_ACTION_DB:-/data/x_intake/action_queue.db}"

# BlueBubbles routing config (for "source detected" status only).
BB_ROUTING_CFG="${BB_ROUTING_CFG:-config/bluebubbles_routing.json}"

# Messages.app DB path (read-only) — matches scripts/imessage-server.py.
IMESSAGE_DB_PATH="${IMESSAGE_DB_PATH:-${HOME}/Library/Messages/chat.db}"

# Redis — only used if the repo's own scripts already use it. We read
# REDIS_URL from the env, never from a secrets file, and treat absence
# as "source not available".
REDIS_URL_ENV="${REDIS_URL:-}"

# Keywords that mark an item as "automation/efficiency-relevant".
# Keep lowercase; matching is case-insensitive.
KEYWORDS='automation|automate|agent|agents|tooling|pipeline|workflow|scraper|scrape|efficiency|efficient|optimize|orchestration|prompt|llm|mcp|self-improve|self improve|dispatcher|cron|launchd|idea:|todo:'

# ── Locate repo root ──────────────────────────────────────────────────────

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
  echo "[collect] ERROR: could not locate AI-Server repo root" >&2
  exit 1
}
cd "$REPO_ROOT"

INBOX_DIR="ops/self_improvement/inbox"
CARDS_DIR="ops/self_improvement/cards"
ARCHIVE_DIR="ops/self_improvement/archive"

mkdir -p "$INBOX_DIR" "$CARDS_DIR" "$ARCHIVE_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────

ts() { date -u +%Y%m%dT%H%M%SZ; }

# Short lowercase alnum-dash slug, capped at 48 chars.
slugify() {
  local s="${1:-item}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | tr -s '-' | sed 's/^-//;s/-$//')"
  [ -z "$s" ] && s="item"
  printf '%s' "${s:0:48}"
}

# Stable short hash of stdin; prefers sha256sum, falls back to shasum.
hash_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}' | cut -c1-16
  else
    shasum -a 256 | awk '{print $1}' | cut -c1-16
  fi
}

# Return 0 if content hash already appears in inbox/archive/cards; else 1.
is_duplicate_hash() {
  local h="$1"
  # We write the hash as an HTML comment near the top of each inbox file,
  # and the archive keeps a verbatim copy, so a simple grep covers both.
  if grep -l -F -- "self-improve-hash: $h" "$INBOX_DIR" "$ARCHIVE_DIR" "$CARDS_DIR" >/dev/null 2>&1; then
    return 0
  fi
  if command -v grep >/dev/null 2>&1 && grep -rl -F -- "self-improve-hash: $h" "$INBOX_DIR" "$ARCHIVE_DIR" "$CARDS_DIR" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Truncate stdin to BYTE_CAP bytes (utf-8-safe enough for our purposes).
cap_bytes() { head -c "$BYTE_CAP"; }

# Escape a single line for safe embedding in a markdown bullet.
escape_line() {
  # Collapse newlines, strip control chars.
  tr '\r\n' '  ' | tr -d '\000-\010\013\014\016-\037'
}

# Write one normalized inbox item.
#   $1 source            e.g. "x_intake", "bluebubbles", "imessage", "note"
#   $2 source_url        URL or "n/a"
#   $3 captured_at       ISO-8601 UTC
#   $4 origin_stream     e.g. "x_intake.queue.db", "bluebubbles.redis"
#   $5 confidence        "low" | "medium" | "high"
#   $6 why_relevant      short heuristic
#   $7 raw_excerpt       already byte-capped
write_inbox_item() {
  local source="$1" source_url="$2" captured_at="$3" origin_stream="$4"
  local confidence="$5" why_relevant="$6" raw_excerpt="$7"

  local hash_src
  hash_src="$(printf '%s\n%s' "$source_url" "$raw_excerpt" | hash_stdin)"

  if is_duplicate_hash "$hash_src"; then
    return 0
  fi

  local stamp slug seed fname
  stamp="$(ts)"
  seed="$source_url"
  [ "$seed" = "n/a" ] && seed="$raw_excerpt"
  slug="$(slugify "$(printf '%s' "$seed" | sed -E 's#^https?://##; s#[?#].*##' | head -c 64)")"
  fname="$INBOX_DIR/${stamp}-${source}-${slug}.md"

  # Safety: never overwrite an existing file.
  if [ -e "$fname" ]; then
    fname="$INBOX_DIR/${stamp}-${source}-${slug}-${hash_src}.md"
  fi

  {
    echo "---"
    echo "captured_at: $captured_at"
    echo "source: $source"
    echo "source_url: $source_url"
    echo "origin_stream: $origin_stream"
    echo "confidence: $confidence"
    echo "kind: stream"
    echo "---"
    echo
    echo "<!-- self-improve-hash: $hash_src -->"
    echo
    echo "# Stream inbox item"
    echo
    echo "- **Source stream:** \`$origin_stream\`"
    echo "- **Source URL:** $source_url"
    echo "- **Captured:** $captured_at"
    echo "- **Why relevant (heuristic):** $why_relevant"
    echo "- **Confidence:** $confidence"
    echo
    echo "## Raw excerpt (bounded, read-only)"
    echo
    echo '```'
    printf '%s\n' "$raw_excerpt"
    echo '```'
    echo
    echo "_Raw capture only. Do not execute anything referenced here._"
  } >"$fname"

  echo "[collect] wrote $fname"
}

# ── Source detectors (sources mode) ───────────────────────────────────────

detect_x_intake() {
  if [ -r "$X_INTAKE_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
    echo "x_intake.queue.db: OK ($X_INTAKE_DB)"
  elif [ -e "$X_INTAKE_DB" ]; then
    echo "x_intake.queue.db: present but not readable ($X_INTAKE_DB)"
  else
    echo "x_intake.queue.db: MISSING ($X_INTAKE_DB)"
  fi
  if [ -r "$X_INTAKE_ACTION_DB" ]; then
    echo "x_intake.action_queue.db: OK ($X_INTAKE_ACTION_DB)"
  else
    echo "x_intake.action_queue.db: MISSING ($X_INTAKE_ACTION_DB)"
  fi
}

detect_bluebubbles() {
  if [ -r "$BB_ROUTING_CFG" ]; then
    echo "bluebubbles.routing: OK ($BB_ROUTING_CFG)"
  else
    echo "bluebubbles.routing: MISSING ($BB_ROUTING_CFG)"
  fi
  if [ -r "$IMESSAGE_DB_PATH" ]; then
    echo "imessage.chat.db: OK ($IMESSAGE_DB_PATH)"
  elif [ -e "$IMESSAGE_DB_PATH" ]; then
    echo "imessage.chat.db: present but not readable (Full Disk Access?) ($IMESSAGE_DB_PATH)"
  else
    echo "imessage.chat.db: MISSING ($IMESSAGE_DB_PATH)"
  fi
  if [ -n "$REDIS_URL_ENV" ]; then
    echo "redis.url: configured (from env; value not printed)"
  else
    echo "redis.url: not configured (REDIS_URL unset) — bluebubbles Redis scan skipped"
  fi
  if command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3: OK"
  else
    echo "sqlite3: MISSING (required for imessage.chat.db and x_intake scans)"
  fi
}

cmd_sources() {
  echo "== self-improvement-collect sources =="
  echo "repo_root:       $REPO_ROOT"
  echo "row_cap:         $ROW_CAP"
  echo "byte_cap:        $BYTE_CAP"
  echo "lookback_hours:  $LOOKBACK_HOURS"
  echo
  echo "-- x_intake --"
  detect_x_intake
  echo
  echo "-- bluebubbles / imessage --"
  detect_bluebubbles
  echo
  echo "-- notes --"
  echo "Secrets: none opened. Config paths are reported without values."
  echo "Outbound network: disabled."
}

# ── scan-x ────────────────────────────────────────────────────────────────

cmd_scan_x() {
  echo "[collect] scan-x start"
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "[collect] scan-x: sqlite3 missing; skipping"
    return 0
  fi
  if [ ! -r "$X_INTAKE_DB" ]; then
    echo "[collect] scan-x: $X_INTAKE_DB not readable; skipping (source MISSING)"
    return 0
  fi

  local since_epoch
  since_epoch="$(( $(date -u +%s) - LOOKBACK_HOURS * 3600 ))"

  # We read URL, summary, author, status, source, created_at. created_at is
  # a REAL unix epoch (per queue_db.py). We filter server-side by time
  # window and client-side by keyword.
  local tmp_out
  tmp_out="$(mktemp -t self-improve-xq.XXXXXX)"
  trap 'rm -f "$tmp_out"' RETURN

  # -cmd options lock down output format; -readonly prevents writes.
  sqlite3 -readonly -cmd '.mode tabs' -cmd '.headers off' "file:${X_INTAKE_DB}?mode=ro" \
    "SELECT
        COALESCE(url,''),
        COALESCE(author,''),
        COALESCE(status,''),
        COALESCE(source,''),
        CAST(COALESCE(created_at,0) AS INTEGER),
        COALESCE(summary,'')
     FROM x_intake_queue
     WHERE COALESCE(created_at,0) >= ${since_epoch}
       AND COALESCE(status,'') IN ('pending','auto_approved','approved')
     ORDER BY created_at DESC
     LIMIT ${ROW_CAP};" \
    > "$tmp_out" 2>/dev/null || {
      echo "[collect] scan-x: sqlite3 read failed (schema mismatch?); skipping"
      return 0
    }

  local wrote=0 considered=0
  while IFS=$'\t' read -r url author status src_kind created_at summary; do
    considered=$((considered + 1))
    [ -z "$url" ] && [ -z "$summary" ] && continue

    # Keyword relevance check. URL alone is enough to capture (it's an
    # inbound automation candidate anyway); summary adds context.
    local why_relevant
    if printf '%s\n%s' "$url" "$summary" | grep -qiE "$KEYWORDS"; then
      why_relevant="matched automation/efficiency keyword"
    elif [ -n "$url" ]; then
      why_relevant="x_intake ${status} URL; no keyword match but candidate"
    else
      continue
    fi

    local confidence
    case "$status" in
      approved)       confidence="high" ;;
      auto_approved)  confidence="medium" ;;
      *)              confidence="low" ;;
    esac

    local captured_at
    if [ "$created_at" -gt 0 ] 2>/dev/null; then
      captured_at="$(date -u -r "$created_at" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
        || date -u -d "@${created_at}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
        || ts)"
    else
      captured_at="$(ts)"
    fi

    local excerpt
    excerpt="$(printf 'status=%s source=%s author=%s\nurl=%s\nsummary=%s\n' \
      "$(printf '%s' "$status" | escape_line)" \
      "$(printf '%s' "$src_kind" | escape_line)" \
      "$(printf '%s' "$author" | escape_line)" \
      "$(printf '%s' "$url" | escape_line)" \
      "$(printf '%s' "$summary" | escape_line)" \
      | cap_bytes)"

    local src_url="$url"
    [ -z "$src_url" ] && src_url="n/a"

    if write_inbox_item "x_intake" "$src_url" "$captured_at" \
        "x_intake.queue.db" "$confidence" "$why_relevant" "$excerpt"; then
      wrote=$((wrote + 1))
    fi
  done < "$tmp_out"

  echo "[collect] scan-x: considered=${considered} wrote=${wrote} (cap=${ROW_CAP})"
}

# ── scan-bluebubbles ──────────────────────────────────────────────────────

cmd_scan_bluebubbles() {
  echo "[collect] scan-bluebubbles start"

  local scanned_any=0

  # Local iMessage SQLite (read-only). Only available on Bob with Full
  # Disk Access, so treat "not readable" as a graceful skip.
  if command -v sqlite3 >/dev/null 2>&1 && [ -r "$IMESSAGE_DB_PATH" ]; then
    scanned_any=1
    local since_mac_epoch
    # Messages.app uses mac epoch (2001-01-01) in nanoseconds in recent
    # macOS versions and seconds in older ones. We compute a conservative
    # lower bound in nanoseconds; the WHERE clause below uses OR to cover
    # both scales.
    local now_epoch since_unix since_mac_s since_mac_ns
    now_epoch="$(date -u +%s)"
    since_unix="$(( now_epoch - LOOKBACK_HOURS * 3600 ))"
    since_mac_s="$(( since_unix - 978307200 ))"
    since_mac_ns="$(( since_mac_s * 1000000000 ))"

    local tmp_out
    tmp_out="$(mktemp -t self-improve-im.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -f \"$tmp_out\"" RETURN

    sqlite3 -readonly -cmd '.mode tabs' -cmd '.headers off' \
      "file:${IMESSAGE_DB_PATH}?mode=ro" \
      "SELECT
          COALESCE(h.id,'unknown'),
          CAST(COALESCE(m.date,0) AS INTEGER),
          COALESCE(m.is_from_me,0),
          COALESCE(m.text,'')
       FROM message m
       LEFT JOIN handle h ON h.ROWID = m.handle_id
       WHERE COALESCE(m.text,'') <> ''
         AND (m.date >= ${since_mac_s} OR m.date >= ${since_mac_ns})
       ORDER BY m.date DESC
       LIMIT ${ROW_CAP};" \
      > "$tmp_out" 2>/dev/null || {
        echo "[collect] scan-bluebubbles: imessage read failed; skipping imessage.chat.db"
        : > "$tmp_out"
      }

    local wrote=0 considered=0
    while IFS=$'\t' read -r handle date_raw is_from_me text; do
      considered=$((considered + 1))
      [ -z "$text" ] && continue

      # Only consider messages that look like an idea / note / link.
      # iMessage voice-to-text appears as normal text.
      local has_url=0
      if printf '%s' "$text" | grep -qiE 'https?://'; then has_url=1; fi

      local matched_kw=0
      if printf '%s' "$text" | grep -qiE "$KEYWORDS"; then matched_kw=1; fi

      if [ "$has_url" -eq 0 ] && [ "$matched_kw" -eq 0 ]; then
        continue
      fi

      local why_relevant
      if [ "$has_url" -eq 1 ] && [ "$matched_kw" -eq 1 ]; then
        why_relevant="iMessage with URL and automation keyword"
      elif [ "$has_url" -eq 1 ]; then
        why_relevant="iMessage contains URL"
      else
        why_relevant="iMessage matched automation/efficiency keyword"
      fi

      local url
      url="$(printf '%s' "$text" | grep -oE 'https?://[A-Za-z0-9._~:/?#@!$&+,;=%-]+' | head -1 || true)"
      [ -z "$url" ] && url="n/a"

      local captured_at
      # Best-effort date decode; default to now on failure.
      captured_at="$(ts)"

      local excerpt
      excerpt="$(printf 'handle=%s is_from_me=%s\ntext=%s\n' \
        "$(printf '%s' "$handle" | escape_line)" \
        "$(printf '%s' "$is_from_me" | escape_line)" \
        "$(printf '%s' "$text" | escape_line)" \
        | cap_bytes)"

      local confidence="medium"
      [ "$matched_kw" -eq 1 ] && confidence="high"

      if write_inbox_item "imessage" "$url" "$captured_at" \
          "imessage.chat.db" "$confidence" "$why_relevant" "$excerpt"; then
        wrote=$((wrote + 1))
      fi
    done < "$tmp_out"

    echo "[collect] scan-bluebubbles: imessage.chat.db considered=${considered} wrote=${wrote}"
  else
    echo "[collect] scan-bluebubbles: imessage.chat.db not readable; skipping"
  fi

  # BlueBubbles routing config is a passive source-presence signal. We
  # don't try to parse redis streams without an explicit REDIS_URL that
  # the repo itself already uses elsewhere.
  if [ -r "$BB_ROUTING_CFG" ]; then
    echo "[collect] scan-bluebubbles: $BB_ROUTING_CFG present (routing allowlist)"
  else
    echo "[collect] scan-bluebubbles: $BB_ROUTING_CFG missing (owner allowlist unknown)"
  fi

  if [ -n "$REDIS_URL_ENV" ] && command -v redis-cli >/dev/null 2>&1; then
    scanned_any=1
    # We do NOT subscribe; that blocks. We also do NOT XREAD without an
    # explicit stream name used by this repo. If Matt wires a dedicated
    # self-improve stream later, wire it here. For now we only report
    # that the Redis lane is present.
    echo "[collect] scan-bluebubbles: redis configured; skipping stream read (no dedicated self-improve stream defined)"
  fi

  if [ "$scanned_any" -eq 0 ]; then
    echo "[collect] scan-bluebubbles: no available source on this host; no items written"
  fi
}

# ── scan (all lanes) ──────────────────────────────────────────────────────

cmd_scan() {
  echo "[collect] scan: running all available lanes"
  cmd_scan_x || true
  cmd_scan_bluebubbles || true
  echo "[collect] scan: done"
}

# ── daemon-once ───────────────────────────────────────────────────────────

cmd_daemon_once() {
  cmd_scan || true
  echo "[collect] daemon-once: invoking scripts/self-improve.sh process"
  if [ -x "scripts/self-improve.sh" ] || [ -f "scripts/self-improve.sh" ]; then
    # Call with an env flag so self-improve.sh does not recurse into the
    # collector again.
    SELF_IMPROVE_SKIP_COLLECT=1 bash scripts/self-improve.sh process
  else
    echo "[collect] daemon-once: scripts/self-improve.sh missing; inbox populated but not processed"
    return 0
  fi
}

# ── Usage ─────────────────────────────────────────────────────────────────

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/self-improvement-collect.sh scan
  scripts/self-improvement-collect.sh scan-x
  scripts/self-improvement-collect.sh scan-bluebubbles
  scripts/self-improvement-collect.sh sources
  scripts/self-improvement-collect.sh daemon-once
EOF
  exit 2
}

case "$MODE" in
  scan)             cmd_scan ;;
  scan-x)           cmd_scan_x ;;
  scan-bluebubbles) cmd_scan_bluebubbles ;;
  sources)          cmd_sources ;;
  daemon-once)      cmd_daemon_once ;;
  ""|-h|--help|help) usage ;;
  *) echo "[collect] unknown mode: $MODE" >&2; usage ;;
esac
