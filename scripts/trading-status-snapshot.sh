#!/usr/bin/env bash
# scripts/trading-status-snapshot.sh — capture a timestamped trading
# status snapshot into ops/verification/. Read-only, bounded, safe.
#
# Usage:
#   bash scripts/trading-status-snapshot.sh         # default /status endpoint
#   BOT_URL=http://127.0.0.1:8430 bash scripts/trading-status-snapshot.sh
#
# Output: ops/verification/<stamp>-trading-status-snapshot.txt
# Contains: /status JSON (pretty-printed), /redeem/status (if reachable),
# bankroll snapshot, top-level keys.
set -euo pipefail

ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
cd "$ROOT"
BOT_URL="${BOT_URL:-http://127.0.0.1:8430}"
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="ops/verification/${STAMP}-trading-status-snapshot.txt"
mkdir -p "$(dirname "$OUT")"

STATUS_TMP="$(mktemp -t poly-status.XXXXXX.json)"
REDEEM_TMP="$(mktemp -t poly-redeem.XXXXXX.json)"
trap 'rm -f "$STATUS_TMP" "$REDEEM_TMP"' EXIT

curl -sfS --connect-timeout 5 "$BOT_URL/status" -o "$STATUS_TMP" || echo "{}" > "$STATUS_TMP"
curl -sfS --connect-timeout 5 "$BOT_URL/redeem/status" -o "$REDEEM_TMP" 2>/dev/null || echo "{}" > "$REDEEM_TMP"

{
  echo "=== polymarket-bot status snapshot ==="
  echo "when: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "url:  $BOT_URL"
  echo ""
  echo "--- /status (pretty) ---"
  /opt/homebrew/bin/python3 -m json.tool < "$STATUS_TMP" || cat "$STATUS_TMP"
  echo ""
  echo "--- /redeem/status ---"
  /opt/homebrew/bin/python3 -m json.tool < "$REDEEM_TMP" || cat "$REDEEM_TMP"
  echo ""
  echo "--- top-level summary ---"
  /opt/homebrew/bin/python3 -c "
import json
try:
    d = json.load(open('$STATUS_TMP'))
except Exception as e:
    print('status parse error:', e)
    raise SystemExit(0)
print('status:', d.get('status'))
print('wallet:', d.get('wallet'))
print('polymarket_api:', d.get('polymarket_api'))
strats = d.get('strategies', {})
print('strategies:', len(strats))
for name, info in strats.items():
    if isinstance(info, dict):
        tc = info.get('tick_count')
        state = info.get('state') or info.get('running')
        print(f'  - {name}: state={state} tick_count={tc}')
"
} > "$OUT" 2>&1

echo "wrote: $OUT"
