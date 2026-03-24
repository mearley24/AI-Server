#!/bin/sh
set -e

# Ensure the data directory is writable.  When Docker bind-mounts a host
# directory into /app/data, it inherits the host's ownership (usually root),
# which prevents the non-root appuser from creating the SQLite database.
# Fix ownership at runtime so the app can write regardless of host state.
if [ "$(id -u)" = "0" ]; then
  chown -R appuser:appgroup /app/data
  exec su-exec appuser "$@"
else
  exec "$@"
fi
