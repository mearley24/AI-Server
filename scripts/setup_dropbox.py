#!/usr/bin/env python3
"""
Dropbox API Setup — Run on Bob
Replaces the bash version that doesn't work on macOS.

Usage: cd ~/AI-Server && python3 scripts/setup_dropbox.py
"""
import json
import os
import webbrowser
import requests

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")

print()
print("=" * 50)
print("  Dropbox API Setup")
print("=" * 50)
print()
print("Step 1: Create a Dropbox app at https://www.dropbox.com/developers/apps")
print("  - Choose 'Scoped access'")
print("  - Choose 'Full Dropbox'")
print("  - Name it 'Symphony Bob'")
print("  - Under Permissions tab, enable:")
print("    files.metadata.read, files.metadata.write,")
print("    files.content.read, files.content.write,")
print("    sharing.read, sharing.write")
print("  - Click Submit, then go back to Settings tab")
print()

app_key = input("Paste your App Key: ").strip()
app_secret = input("Paste your App Secret: ").strip()

print()
print("Step 2: Authorize the app")
auth_url = f"https://www.dropbox.com/oauth2/authorize?client_id={app_key}&response_type=code&token_access_type=offline"
print(f"Opening browser to: {auth_url}")

try:
    webbrowser.open(auth_url)
except Exception:
    print(f"Open this URL manually: {auth_url}")

print()
print("After clicking 'Allow', you'll get an authorization code.")
auth_code = input("Paste the authorization code: ").strip()

print()
print("Step 3: Exchanging for tokens...")

resp = requests.post(
    "https://api.dropboxapi.com/oauth2/token",
    data={
        "code": auth_code,
        "grant_type": "authorization_code",
        "client_id": app_key,
        "client_secret": app_secret,
    },
)

data = resp.json()
if "refresh_token" not in data:
    print(f"ERROR: {data}")
    exit(1)

refresh_token = data["refresh_token"]
access_token = data["access_token"]
print(f"Got refresh token: {refresh_token[:20]}...")

print()
print("Step 4: Creating /Symphony Projects folder...")

folder_resp = requests.post(
    "https://api.dropboxapi.com/2/files/create_folder_v2",
    headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    },
    json={"path": "/Symphony Projects", "autorename": False},
)

if folder_resp.status_code == 200:
    print("Created /Symphony Projects/")
elif "conflict" in folder_resp.text.lower():
    print("/Symphony Projects/ already exists")
else:
    print(f"Note: {folder_resp.json()}")

print()
print("Step 5: Saving to .env...")

env_lines = []
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        env_lines = f.readlines()

keys_to_set = {
    "DROPBOX_APP_KEY": app_key,
    "DROPBOX_APP_SECRET": app_secret,
    "DROPBOX_REFRESH_TOKEN": refresh_token,
}
env_lines = [l for l in env_lines if not any(l.startswith(f"{k}=") for k in keys_to_set)]

for k, v in keys_to_set.items():
    env_lines.append(f"{k}={v}\n")

with open(ENV_PATH, "w") as f:
    f.writelines(env_lines)

print("Saved to .env")
print()
print("=" * 50)
print("  SUCCESS — Dropbox API is ready")
print("=" * 50)
print()
