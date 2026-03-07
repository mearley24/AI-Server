#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
PROJECT_PATH="${PROJECT_PATH:-${WORKSPACE_ROOT}/ios-app/SymphonyTrading/SymphonyTrading.xcodeproj}"
TARGET="${TARGET:-SymphonyTrading}"
CONFIGURATION="${CONFIGURATION:-Debug}"
SDK="${SDK:-iphonesimulator}"

if ! DEVELOPER_DIR="${DEVELOPER_DIR}" xcodebuild -version >/dev/null 2>&1; then
  echo "Unable to use xcodebuild with DEVELOPER_DIR=${DEVELOPER_DIR}"
  exit 1
fi

echo "Building ${TARGET} (${CONFIGURATION}, ${SDK})"
echo "Project: ${PROJECT_PATH}"
echo "DEVELOPER_DIR: ${DEVELOPER_DIR}"

DEVELOPER_DIR="${DEVELOPER_DIR}" xcodebuild \
  -project "${PROJECT_PATH}" \
  -target "${TARGET}" \
  -configuration "${CONFIGURATION}" \
  -sdk "${SDK}" \
  build \
  "$@"
