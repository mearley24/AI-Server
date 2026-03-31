#!/usr/bin/env python3
"""
Zoho Mail Draft API Setup — Run on Bob
Replaces the bash version that doesn't work on macOS.

Usage: cd ~/AI-Server && python3 scripts/setup_zoho_drafts.py
"""
import json
import os
import requests

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")

print()
print("=" * 50)
print("  Zoho Mail Draft API Setup")
print("=" * 50)
print()
print("Step 1: Create a Self Client at https://api-console.zoho.com/")
print("  - Click 'ADD CLIENT' → 'Self Client' → 'CREATE NOW'")
print("  - Copy the Client ID and Client Secret")
print()

client_id = input("Paste your Client ID: ").strip()
client_secret = input("Paste your Client Secret: ").strip()

print()
print("Step 2: Generate a Grant Token")
print("  - Click the 'Generate Code' tab")
print("  - Scope: ZohoMail.messages.CREATE,ZohoMail.accounts.READ")
print("  - Time Duration: 10 minutes")
print("  - Click 'CREATE' and copy the code")
print()

grant_code = input("Paste the Grant Token: ").strip()

print()
print("Step 3: Exchanging for tokens...")

resp = requests.post(
    "https://accounts.zoho.com/oauth/v2/token",
    data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": grant_code,
    },
)

data = resp.json()
if "refresh_token" not in data:
    print(f"ERROR: {data}")
    print("Common issues: expired grant code, wrong client ID/secret")
    exit(1)

refresh_token = data["refresh_token"]
access_token = data["access_token"]
print(f"Got refresh token: {refresh_token[:30]}...")

print()
print("Step 4: Getting Zoho Mail account ID...")

acct_resp = requests.get(
    "https://mail.zoho.com/api/accounts",
    headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
)
acct_data = acct_resp.json()
account_id = acct_data["data"][0]["accountId"]
print(f"Account ID: {account_id}")

print()
print("Step 5: Testing draft creation...")

draft_resp = requests.post(
    f"https://mail.zoho.com/api/accounts/{account_id}/messages",
    headers={
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    },
    json={
        "fromAddress": acct_data["data"][0]["primaryEmailAddress"],
        "toAddress": acct_data["data"][0]["primaryEmailAddress"],
        "subject": "[TEST] Bob Draft System — Delete This",
        "content": "Test draft. If this is in Drafts (not Sent), the system works.",
        "mode": "draft",
        "mailFormat": "html",
    },
)

print()
print("Step 6: Saving to .env...")

# Read existing .env
env_lines = []
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        env_lines = f.readlines()

# Remove old values
keys_to_set = {
    "ZOHO_CLIENT_ID": client_id,
    "ZOHO_CLIENT_SECRET": client_secret,
    "ZOHO_REFRESH_TOKEN": refresh_token,
    "ZOHO_MAIL_ACCOUNT_ID": account_id,
}
env_lines = [l for l in env_lines if not any(l.startswith(f"{k}=") for k in keys_to_set)]

# Add new values
for k, v in keys_to_set.items():
    env_lines.append(f"{k}={v}\n")

with open(ENV_PATH, "w") as f:
    f.writelines(env_lines)

print("Saved to .env")
print()
print("=" * 50)
print("  SUCCESS — Check Zoho Mail drafts for test draft")
print("=" * 50)
print()
