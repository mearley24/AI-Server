#!/bin/bash
# Idempotently pin Bob's SSH host key in Bert's known_hosts.
# Runs on Bert via the ssh_and_run task type.
set -euo pipefail

BOB_FQDN="bobs-mac-mini.tailbcf3fe.ts.net"
BOB_IP="100.89.1.51"

mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/known_hosts && chmod 600 ~/.ssh/known_hosts

for h in "$BOB_FQDN" "$BOB_IP"; do
  if ! ssh-keygen -F "$h" >/dev/null 2>&1; then
    ssh-keyscan -T 5 -t ed25519 "$h" 2>/dev/null >> ~/.ssh/known_hosts
  fi
done

awk '!seen[$1" "$2" "$3]++' ~/.ssh/known_hosts > ~/.ssh/known_hosts.dedup \
  && mv ~/.ssh/known_hosts.dedup ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts

echo "bert known_hosts pinned:"
ssh-keygen -lf ~/.ssh/known_hosts | grep -E "bobs-mac-mini|100\\.89\\.1\\.51" \
  || echo "WARN no entries"
