#!/bin/bash
# ops/cline-run-campaign.sh
#
# Run a sequence of Cline prompt files, one after another, via
# ops/cline-run-prompt.sh. Designed to be invoked by the Symphony Task
# Runner (task_type: run_cline_campaign) or by a human from the repo root.
#
# Usage:
#   ops/cline-run-campaign.sh [--dry-run] [--stop-on-fail] \
#                             [--timeout SEC] <prompt1> [prompt2 ...]
#
# Options:
#   --dry-run        Forwarded to every prompt run — no CLI invocation.
#   --stop-on-fail   Abort the campaign on the first non-zero sub-run
#                    (default: continue on "safe" blocker exits 3/4 so a
#                    missing prompt or missing CLI is a blocker report
#                    rather than a campaign-killing failure).
#   --timeout SEC    Forwarded to ops/cline-run-prompt.sh.
#
# Classification of sub-run exits (from ops/cline-run-prompt.sh):
#   0        OK
#   2        bad args (treated as UNSAFE)
#   3        missing/bad prompt file (SAFE blocker — continue unless --stop-on-fail)
#   4        Cline CLI missing in live mode (SAFE blocker — continue unless --stop-on-fail)
#   5        CLI failure / timeout (UNSAFE — always abort the campaign)
#   6        internal error (UNSAFE)
#
# Writes a campaign summary to
#   ops/verification/YYYYMMDD-HHMMSS-cline-campaign.log
# listing each prompt, its per-run log, and its exit.
#
# Exit codes:
#   0  all prompts succeeded
#   1  at least one safe blocker (but no unsafe failures)
#   5  aborted due to an unsafe failure
#   2  bad args
#   6  internal error

set -uo pipefail

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCHER="${SCRIPT_DIR}/cline-run-prompt.sh"

if [ ! -x "${LAUNCHER}" ]; then
  echo "error: launcher not found or not executable: ${LAUNCHER}" >&2
  exit 6
fi

cd "${REPO_ROOT}" || { echo "error: could not cd to ${REPO_ROOT}" >&2; exit 6; }

DRY_RUN="false"
STOP_ON_FAIL="false"
TIMEOUT_SEC=""
PROMPTS=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --stop-on-fail)
      STOP_ON_FAIL="true"
      shift
      ;;
    --timeout)
      if [ "$#" -lt 2 ]; then
        echo "error: --timeout requires a value" >&2
        exit 2
      fi
      TIMEOUT_SEC="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,40p' "$SCRIPT_PATH"
      exit 0
      ;;
    --*)
      echo "error: unknown option: $1" >&2
      exit 2
      ;;
    *)
      PROMPTS+=("$1")
      shift
      ;;
  esac
done

if [ "${#PROMPTS[@]}" -eq 0 ]; then
  echo "usage: $(basename "$0") [--dry-run] [--stop-on-fail] [--timeout SEC] <prompt1> [prompt2 ...]" >&2
  exit 2
fi

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
CAMPAIGN_LOG_REL="ops/verification/${STAMP}-cline-campaign.log"
CAMPAIGN_LOG="${REPO_ROOT}/${CAMPAIGN_LOG_REL}"
mkdir -p "$(dirname "${CAMPAIGN_LOG}")" || { echo "error: mkdir log dir failed" >&2; exit 6; }

{
  echo "=== cline-run-campaign @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="
  echo "repo_root:     ${REPO_ROOT}"
  echo "launcher:      ${LAUNCHER}"
  echo "dry_run:       ${DRY_RUN}"
  echo "stop_on_fail:  ${STOP_ON_FAIL}"
  echo "timeout_sec:   ${TIMEOUT_SEC:-<default>}"
  echo "prompt_count:  ${#PROMPTS[@]}"
  echo "prompts:"
  for p in "${PROMPTS[@]}"; do
    echo "  - ${p}"
  done
  echo
} >"${CAMPAIGN_LOG}" 2>&1

OK=0
SAFE_BLOCKERS=0
UNSAFE=0
ABORTED="false"

for p in "${PROMPTS[@]}"; do
  {
    echo "--- running: ${p} @ $(date '+%H:%M:%S') ---"
  } >>"${CAMPAIGN_LOG}" 2>&1

  ARGS=()
  if [ "${DRY_RUN}" = "true" ]; then
    ARGS+=("--dry-run")
  fi
  if [ -n "${TIMEOUT_SEC}" ]; then
    ARGS+=("--timeout" "${TIMEOUT_SEC}")
  fi
  ARGS+=("${p}")

  # Capture the last line of launcher stdout (it echoes the log path).
  LAUNCHER_OUT="$("${LAUNCHER}" "${ARGS[@]}" 2>&1)"
  RC=$?

  {
    echo "${LAUNCHER_OUT}"
    echo "exit: ${RC}"
    echo
  } >>"${CAMPAIGN_LOG}" 2>&1

  case "${RC}" in
    0)
      OK=$((OK + 1))
      ;;
    3|4)
      SAFE_BLOCKERS=$((SAFE_BLOCKERS + 1))
      if [ "${STOP_ON_FAIL}" = "true" ]; then
        ABORTED="true"
        echo "--- --stop-on-fail: halting on safe blocker rc=${RC} ---" >>"${CAMPAIGN_LOG}"
        break
      fi
      ;;
    *)
      UNSAFE=$((UNSAFE + 1))
      ABORTED="true"
      echo "--- unsafe failure rc=${RC}; aborting campaign ---" >>"${CAMPAIGN_LOG}"
      break
      ;;
  esac
done

{
  echo "=== campaign summary ==="
  echo "ok:             ${OK}"
  echo "safe_blockers:  ${SAFE_BLOCKERS}"
  echo "unsafe:         ${UNSAFE}"
  echo "aborted:        ${ABORTED}"
  echo "finished_at:    $(date '+%Y-%m-%d %H:%M:%S %z')"
} >>"${CAMPAIGN_LOG}" 2>&1

echo "campaign log: ${CAMPAIGN_LOG_REL}"
echo "ok=${OK} safe_blockers=${SAFE_BLOCKERS} unsafe=${UNSAFE} aborted=${ABORTED}"

if [ "${UNSAFE}" -gt 0 ]; then
  exit 5
fi
if [ "${SAFE_BLOCKERS}" -gt 0 ]; then
  exit 1
fi
exit 0
