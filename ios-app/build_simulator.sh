#!/usr/bin/env bash
set -euo pipefail

# Build SymphonyOps with full Xcode toolchain even when xcode-select points at CLT.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
PROJECT_PATH="${PROJECT_PATH:-${WORKSPACE_ROOT}/ios-app/SymphonyOps/SymphonyOps.xcodeproj}"
SCHEME="${SCHEME:-SymphonyOps}"
CONFIGURATION="${CONFIGURATION:-Debug}"
SDK="${SDK:-iphonesimulator}"

if ! DEVELOPER_DIR="${DEVELOPER_DIR}" xcodebuild -version >/dev/null 2>&1; then
  echo "Unable to use xcodebuild with DEVELOPER_DIR=${DEVELOPER_DIR}"
  echo "Install Xcode.app or set DEVELOPER_DIR to a valid Developer directory."
  exit 1
fi

echo "Building ${SCHEME} (${CONFIGURATION}, ${SDK})"
echo "Project: ${PROJECT_PATH}"
echo "DEVELOPER_DIR: ${DEVELOPER_DIR}"

DEVELOPER_DIR="${DEVELOPER_DIR}" xcodebuild \
  -project "${PROJECT_PATH}" \
  -scheme "${SCHEME}" \
  -configuration "${CONFIGURATION}" \
  -sdk "${SDK}" \
  build \
  "$@"
