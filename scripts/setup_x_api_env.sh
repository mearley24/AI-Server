#!/bin/bash
set -euo pipefail

ENV_FILE=".env"

echo "=== X API setup helper ==="

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found"
  exit 1
fi

cp "$ENV_FILE" ".env.backup.$(date +%Y%m%d-%H%M%S)"

read -r -p "Enter your X username without @: " X_USERNAME

python3 - "$X_USERNAME" <<'PY'
import sys, re, json, urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent if "__file__" in dir() else Path.cwd()
sys.path.insert(0, str(REPO_ROOT))

username = sys.argv[1].strip().lstrip("@")
env = Path(".env")
text = env.read_text()

def get_env(key):
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    return m.group(1).strip() if m else ""

def resolve(value):
    """Resolve VAULT_REF:<name> to the plaintext secret; pass through otherwise."""
    if not value.startswith("VAULT_REF:"):
        return value
    try:
        from integrations.vault.crypto import resolve_vault_ref
        return resolve_vault_ref(value)
    except Exception as e:
        raise SystemExit(f"ERROR: could not resolve {value!r} from vault — {e}")

bearer_raw = get_env("X_API_BEARER_TOKEN")
if not bearer_raw or "PASTE_" in bearer_raw:
    raise SystemExit("ERROR: X_API_BEARER_TOKEN is missing in .env")
bearer = resolve(bearer_raw)

url = f"https://api.x.com/2/users/by/username/{username}"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})

try:
    with urllib.request.urlopen(req, timeout=15) as r:
        payload = json.loads(r.read().decode())
except Exception as e:
    raise SystemExit(f"ERROR: Could not resolve X user ID via API: {e}")

user_id = payload.get("data", {}).get("id")
if not user_id:
    raise SystemExit(f"ERROR: No user ID returned: {payload}")

updates = {
    "X_ENABLED": "1",
    "X_USER_ID": user_id,
    "X_DAILY_READ_LIMIT": "25",
}

for key, value in updates.items():
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text += f"\n{key}={value}\n"

env.write_text(text)
print(f"Updated .env with X_USER_ID={user_id}")
PY

echo "=== Restarting Cortex and x-intake safely ==="
scripts/safe-service-restart.sh cortex || true
scripts/safe-service-restart.sh x-intake || true

echo "=== Testing X API dry-run ==="
python3 scripts/x_api_intake.py --dry-run --limit 5

echo "=== X API status ==="
curl -sS "http://127.0.0.1:8102/api/x-api/status" | python3 -m json.tool

echo "=== Done ==="
