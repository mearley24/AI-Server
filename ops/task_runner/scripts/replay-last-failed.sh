#!/usr/bin/env bash
# ops/task_runner/scripts/replay-last-failed.sh
# Copy the newest ops/work_queue/failed/*.json back to pending/ WITHOUT its
# signature field, so the submitter can re-sign and re-push.
#
# Gated: requires --yes to actually copy. Otherwise dry-runs.
# MEDIUM risk: moves a task back into executable state but only after a
# human / agent explicitly re-signs it. The runner will reject any unsigned
# task on the next tick, so even accidental copying without re-sign is safe.
set -euo pipefail

ROOT="${SYMPHONY_ROOT:-$HOME/AI-Server}"
FAILED="$ROOT/ops/work_queue/failed"
PENDING="$ROOT/ops/work_queue/pending"

YES=0
if [ "${1:-}" = "--yes" ]; then YES=1; fi

if [ ! -d "$FAILED" ]; then
  echo "no $FAILED"
  exit 0
fi

NEWEST="$(ls -1t "$FAILED"/*.json 2>/dev/null | head -n 1 || true)"
if [ -z "$NEWEST" ]; then
  echo "no failed tasks to replay"
  exit 0
fi

BASE="$(basename "$NEWEST")"
echo "newest failed task: $BASE"
echo ""

if [ "$YES" = "0" ]; then
  echo "(dry-run) would strip signature and copy to pending/ — pass --yes to execute"
  echo ""
  echo "--- preview (without signature) ---"
  /opt/homebrew/bin/python3 -c "
import json, sys
with open('$NEWEST') as fh:
    d = json.load(fh)
d.pop('signature', None)
print(json.dumps(d, indent=2, sort_keys=True))
" 2>&1 | head -30
  exit 0
fi

DEST="$PENDING/$BASE"
if [ -e "$DEST" ]; then
  echo "refusing: $DEST already exists in pending/"
  exit 2
fi

/opt/homebrew/bin/python3 -c "
import json, sys
with open('$NEWEST') as fh:
    d = json.load(fh)
d.pop('signature', None)
with open('$DEST', 'w') as fh:
    json.dump(d, fh, indent=2, sort_keys=True)
print('wrote: $DEST (signature stripped)')
"

echo ""
echo "Next step (manual, off-band):"
echo "  /opt/homebrew/bin/python3 scripts/task_signer.py sign \\"
echo "    --task $DEST \\"
echo "    --priv ~/.config/symphony/<your-name>.ed25519.priv"
echo "  git add $DEST && git commit -m 'ops(replay): $BASE' && git push"
