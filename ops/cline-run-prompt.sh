#!/bin/bash
# ops/cline-run-prompt.sh
#
# Launcher that runs a Cline prompt file end-to-end without any manual
# copy/paste. Designed to be invoked by the Symphony Task Runner
# (scripts/task_runner.py) or by a human from the repo root.
#
# Usage:
#   ops/cline-run-prompt.sh <prompt-file> [--dry-run] [--timeout <sec>]
#
# Arguments:
#   prompt-file   Path to a Cline prompt markdown file. Repo-relative paths
#                 are resolved against the AI-Server repo root; absolute
#                 paths are used as-is.
#
# Options:
#   --dry-run     Validate prompt file + detect Cline CLI + write log, but
#                 do not actually invoke the CLI. Returns 0 if the prompt
#                 exists regardless of CLI availability (CLI availability
#                 is recorded in the log).
#   --timeout N   Seconds to cap the CLI run at (default: 1800, i.e. 30 min).
#                 Ignored in --dry-run mode.
#
# Behavior:
#   * Runs from the AI-Server repo root (derived from this script's path).
#   * Verifies the prompt file exists before doing anything else.
#   * Detects the Cline CLI via $CLINE_CLI (explicit override) or the
#     "cline" binary in PATH. If neither is available, live mode fails
#     non-zero with a clear message. Dry-run mode records the miss and
#     continues.
#   * Captures stdout+stderr to a timestamped log under
#     ops/verification/YYYYMMDD-HHMMSS-cline-run-<basename>.log.
#   * Exits non-zero on any failure (bad args, missing prompt, missing CLI
#     in live mode, CLI non-zero exit, timeout).
#
# Exit codes:
#   0   success (or successful dry-run, even if CLI missing)
#   2   bad arguments
#   3   missing / unreadable prompt file
#   4   Cline CLI not found (live mode only)
#   5   Cline CLI exited non-zero or timed out
#   6   internal error writing log / setup failure
#
# No heredocs, no inline interpreters, no multi-line quoted strings.
# Every command terminates on its own. Compatible with zsh + bash.

set -uo pipefail

# --- resolve paths -----------------------------------------------------

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}" || { echo "error: could not cd to ${REPO_ROOT}" >&2; exit 6; }

# --- parse args --------------------------------------------------------

PROMPT_ARG=""
DRY_RUN="false"
TIMEOUT_SEC="1800"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --timeout)
      if [ "$#" -lt 2 ]; then
        echo "error: --timeout requires a value (seconds)" >&2
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
      if [ -z "${PROMPT_ARG}" ]; then
        PROMPT_ARG="$1"
      else
        echo "error: unexpected extra argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [ -z "${PROMPT_ARG}" ]; then
  echo "usage: $(basename "$0") <prompt-file> [--dry-run] [--timeout SEC]" >&2
  exit 2
fi

# Resolve prompt path: absolute stays absolute, relative goes under REPO_ROOT.
case "${PROMPT_ARG}" in
  /*)
    PROMPT_PATH="${PROMPT_ARG}"
    ;;
  *)
    PROMPT_PATH="${REPO_ROOT}/${PROMPT_ARG}"
    ;;
esac

if [ ! -f "${PROMPT_PATH}" ]; then
  echo "error: prompt file not found: ${PROMPT_PATH}" >&2
  exit 3
fi

if [ ! -r "${PROMPT_PATH}" ]; then
  echo "error: prompt file not readable: ${PROMPT_PATH}" >&2
  exit 3
fi

PROMPT_BYTES=$(wc -c <"${PROMPT_PATH}" 2>/dev/null | tr -d ' ' || echo 0)
if [ "${PROMPT_BYTES:-0}" -eq 0 ]; then
  echo "error: prompt file is empty: ${PROMPT_PATH}" >&2
  exit 3
fi

# --- prepare log -------------------------------------------------------

STAMP="$(date -u '+%Y%m%d-%H%M%S')"
PROMPT_BASENAME="$(basename "${PROMPT_PATH}")"
PROMPT_STEM="${PROMPT_BASENAME%.*}"
# Sanitize for filename: keep alnum, dot, dash, underscore.
PROMPT_STEM_SAFE="$(printf '%s' "${PROMPT_STEM}" | LC_ALL=C tr -c '[:alnum:]._-' '-' | sed 's/--*/-/g')"
LOG_REL="ops/verification/${STAMP}-cline-run-${PROMPT_STEM_SAFE}.log"
LOG_PATH="${REPO_ROOT}/${LOG_REL}"

mkdir -p "$(dirname "${LOG_PATH}")" || {
  echo "error: could not create log directory $(dirname "${LOG_PATH}")" >&2
  exit 6
}

# --- detect Cline CLI --------------------------------------------------

# Priority: explicit $CLINE_CLI override, then "cline" in PATH.
CLI_BIN=""
CLI_SOURCE=""
if [ -n "${CLINE_CLI:-}" ]; then
  if [ -x "${CLINE_CLI}" ]; then
    CLI_BIN="${CLINE_CLI}"
    CLI_SOURCE="CLINE_CLI env var"
  elif command -v "${CLINE_CLI}" >/dev/null 2>&1; then
    CLI_BIN="$(command -v "${CLINE_CLI}")"
    CLI_SOURCE="CLINE_CLI env var (PATH lookup)"
  fi
fi
if [ -z "${CLI_BIN}" ]; then
  if command -v cline >/dev/null 2>&1; then
    CLI_BIN="$(command -v cline)"
    CLI_SOURCE="cline in PATH"
  fi
fi

CLI_VERSION="unknown"
if [ -n "${CLI_BIN}" ]; then
  CLI_VERSION="$("${CLI_BIN}" --version 2>/dev/null | head -1 || echo unknown)"
fi

# --- banner + open log -------------------------------------------------

{
  echo "=== cline-run-prompt @ $(date '+%Y-%m-%d %H:%M:%S %z') ==="
  echo "script:        ${SCRIPT_PATH}"
  echo "repo_root:     ${REPO_ROOT}"
  echo "prompt_arg:    ${PROMPT_ARG}"
  echo "prompt_path:   ${PROMPT_PATH}"
  echo "prompt_bytes:  ${PROMPT_BYTES}"
  echo "dry_run:       ${DRY_RUN}"
  echo "timeout_sec:   ${TIMEOUT_SEC}"
  echo "cli_bin:       ${CLI_BIN:-<none>}"
  echo "cli_source:    ${CLI_SOURCE:-<none>}"
  echo "cli_version:   ${CLI_VERSION}"
  echo "log_path:      ${LOG_PATH}"
  echo "git_head:      $(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo
  echo "--- prompt head (first 20 lines) ---"
  head -n 20 "${PROMPT_PATH}" 2>/dev/null || true
  echo
  echo "--- prompt tail (last 5 lines) ---"
  tail -n 5 "${PROMPT_PATH}" 2>/dev/null || true
  echo
} >"${LOG_PATH}" 2>&1 || {
  echo "error: could not write log: ${LOG_PATH}" >&2
  exit 6
}

# --- dry-run path ------------------------------------------------------

if [ "${DRY_RUN}" = "true" ]; then
  {
    echo "--- dry-run result ---"
    if [ -n "${CLI_BIN}" ]; then
      echo "status: OK (dry-run, CLI detected at ${CLI_BIN})"
    else
      echo "status: OK (dry-run, CLI NOT detected — live mode would fail with exit 4)"
    fi
    echo "note: CLI was not invoked; no prompt was consumed"
  } >>"${LOG_PATH}" 2>&1
  echo "dry-run OK — log: ${LOG_REL}"
  exit 0
fi

# --- live invocation ---------------------------------------------------

if [ -z "${CLI_BIN}" ]; then
  {
    echo "--- live invocation skipped ---"
    echo "status: FAIL — Cline CLI not found"
    echo "resolution: install Cline CLI and ensure 'cline' is on PATH, OR"
    echo "            set CLINE_CLI=/absolute/path/to/cline before invoking"
    echo "exit: 4"
  } >>"${LOG_PATH}" 2>&1
  echo "error: Cline CLI not found; see ${LOG_REL}" >&2
  exit 4
fi

# Safe invocation pattern.
#
# Contract: we invoke the Cline CLI with the prompt file passed as an
# argument. The exact flag is intentionally conservative — most CLI
# wrappers accept one of:
#   cline run <prompt-file>
#   cline -f <prompt-file>
#   cline --prompt-file <prompt-file>
#
# To stay wrapper-agnostic we pass the prompt path as the last positional
# argument after an optional "run" subcommand. Override by setting
# CLINE_RUN_ARGS, which is word-split into argv.

DEFAULT_ARGS="run"
EXTRA_ARGS="${CLINE_RUN_ARGS:-${DEFAULT_ARGS}}"

{
  echo "--- live invocation ---"
  echo "argv: ${CLI_BIN} ${EXTRA_ARGS} ${PROMPT_PATH}"
  echo "timeout: ${TIMEOUT_SEC}s"
  echo
} >>"${LOG_PATH}" 2>&1

# shellcheck disable=SC2086  # intentional word-splitting on EXTRA_ARGS
if command -v timeout >/dev/null 2>&1; then
  timeout --preserve-status "${TIMEOUT_SEC}" "${CLI_BIN}" ${EXTRA_ARGS} "${PROMPT_PATH}" \
    >>"${LOG_PATH}" 2>&1
  RC=$?
elif command -v gtimeout >/dev/null 2>&1; then
  gtimeout --preserve-status "${TIMEOUT_SEC}" "${CLI_BIN}" ${EXTRA_ARGS} "${PROMPT_PATH}" \
    >>"${LOG_PATH}" 2>&1
  RC=$?
else
  echo "warn: no timeout(1) / gtimeout(1) available; running without wall-clock cap" \
    >>"${LOG_PATH}" 2>&1
  # shellcheck disable=SC2086
  "${CLI_BIN}" ${EXTRA_ARGS} "${PROMPT_PATH}" >>"${LOG_PATH}" 2>&1
  RC=$?
fi

{
  echo
  echo "--- live invocation result ---"
  echo "exit: ${RC}"
  if [ "${RC}" -eq 0 ]; then
    echo "status: OK"
  elif [ "${RC}" -eq 124 ] || [ "${RC}" -eq 137 ]; then
    echo "status: TIMEOUT after ${TIMEOUT_SEC}s"
  else
    echo "status: FAIL"
  fi
} >>"${LOG_PATH}" 2>&1

if [ "${RC}" -eq 0 ]; then
  echo "cline-run OK — log: ${LOG_REL}"
  exit 0
fi

echo "cline-run FAILED rc=${RC} — log: ${LOG_REL}" >&2
exit 5
