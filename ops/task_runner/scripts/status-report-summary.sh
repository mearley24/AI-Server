#!/usr/bin/env bash
# status-report-summary.sh — run the STATUS_REPORT.md summarizer via the
# Symphony Task Runner.
#
# Queue a run_script task with payload:
#   {"script": "status-report-summary", "args": []}
#
# The task runner wraps this script and captures all output into
# ops/verification/<task_id>-result.txt. The summarizer itself also writes
# its digest to ops/verification/<stamp>-status-report-summary.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SUMMARIZER="${REPO_ROOT}/ops/status_report_summarizer.py"

if [[ ! -f "${SUMMARIZER}" ]]; then
  echo "ERROR: summarizer missing at ${SUMMARIZER}" >&2
  exit 3
fi

echo "=== STATUS_REPORT summarizer wrapper ==="
echo "repo_root=${REPO_ROOT}"
echo "summarizer=${SUMMARIZER}"
echo "started=$(date +%Y-%m-%dT%H:%M:%S%z)"
echo ""

cd "${REPO_ROOT}"
python3 "${SUMMARIZER}" --write "$@"

echo ""
echo "=== finished $(date +%Y-%m-%dT%H:%M:%S%z) ==="
