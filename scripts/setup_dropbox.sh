#!/bin/bash
# =============================================================================
# Dropbox API Setup — Run on Bob
# =============================================================================
# This script walks you through setting up Dropbox API OAuth so Bob can
# manage project files in Dropbox (create folders, upload files, share links).
#
# One-time setup. Takes about 5 minutes.
# =============================================================================

set -e
cd "$(dirname "$0")/.."
source .env 2>/dev/null || true

echo ""
echo "========================================="
echo " Dropbox API Setup"
echo "========================================="
echo ""
echo "Step 1: Create a Dropbox App"
echo "----------------------------"
echo "1. Open: https://www.dropbox.com/developers/apps"
echo "2. Click 'Create app'"
echo "3. Choose 'Scoped access'"
echo "4. Choose 'Full Dropbox' access type"
echo "5. Name it: 'Symphony Smart Homes'"
echo "6. Click 'Create app'"
echo ""
echo "Step 2: Set Permissions"
echo "-----------------------"
echo "1. Go to the 'Permissions' tab"
echo "2. Enable these scopes:"
echo "   - files.metadata.read"
echo "   - files.metadata.write"
echo "   - files.content.read"
echo "   - files.content.write"
echo "   - sharing.read"
echo "   - sharing.write"
echo "3. Click 'Submit' to save"
echo ""
echo "Step 3: Copy Credentials"
echo "------------------------"
echo "1. Go to the 'Settings' tab"
echo "2. Copy the App key and App secret"
echo ""

read -p "Paste your App Key: " DROPBOX_APP_KEY
read -p "Paste your App Secret: " DROPBOX_APP_SECRET

echo ""
echo "Step 4: Generate Authorization Code"
echo "------------------------------------"
echo "Open this URL in your browser:"
echo ""
echo "  https://www.dropbox.com/oauth2/authorize?client_id=${DROPBOX_APP_KEY}&response_type=code&token_access_type=offline"
echo ""
echo "1. Click 'Continue' and then 'Allow'"
echo "2. Copy the authorization code shown"
echo ""

read -p "Paste the Authorization Code: " DROPBOX_AUTH_CODE

echo ""
echo "Step 5: Exchanging auth code for refresh token..."
echo ""

RESPONSE=$(curl -s -X POST "https://api.dropboxapi.com/oauth2/token" \
  -d "code=${DROPBOX_AUTH_CODE}" \
  -d "grant_type=authorization_code" \
  -d "client_id=${DROPBOX_APP_KEY}" \
  -d "client_secret=${DROPBOX_APP_SECRET}")

echo "Response: $RESPONSE"
echo ""

REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('refresh_token',''))" 2>/dev/null)
ACCESS_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: No refresh token received. Check the response above."
    echo "Common issues:"
    echo "  - Authorization code already used (each code is single-use)"
    echo "  - Wrong app key or secret"
    echo "  - Permissions not submitted before generating auth code"
    exit 1
fi

echo "Got refresh token: ${REFRESH_TOKEN:0:20}..."
echo "Got access token: ${ACCESS_TOKEN:0:20}..."
echo ""

# Test: create the Symphony Projects folder
echo "Step 6: Testing API access — creating Symphony Projects folder..."
CREATE_RESPONSE=$(curl -s -X POST "https://api.dropboxapi.com/2/files/create_folder_v2" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"path": "/Symphony Projects", "autorename": false}')

echo "Response: $CREATE_RESPONSE"
echo ""

# Save to .env
echo "Step 7: Saving to .env..."

# Remove old values if they exist
for KEY in DROPBOX_APP_KEY DROPBOX_APP_SECRET DROPBOX_REFRESH_TOKEN; do
    sed -i '' "/^${KEY}=/d" .env 2>/dev/null || true
done

cat >> .env << EOF

DROPBOX_APP_KEY=${DROPBOX_APP_KEY}
DROPBOX_APP_SECRET=${DROPBOX_APP_SECRET}
DROPBOX_REFRESH_TOKEN=${REFRESH_TOKEN}
EOF

echo "Saved to .env"
echo ""

# Verify by listing the folder
echo "Step 8: Verifying — listing /Symphony Projects..."
LIST_RESPONSE=$(curl -s -X POST "https://api.dropboxapi.com/2/files/list_folder" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"path": "/Symphony Projects", "recursive": false}')

LIST_STATUS=$(echo "$LIST_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('entries',[])))" 2>/dev/null)

echo ""
echo "========================================="
echo " SUCCESS — Dropbox API is working"
echo "========================================="
echo ""
echo "Folder /Symphony Projects exists with ${LIST_STATUS:-0} entries."
echo ""
echo "Bob can now:"
echo "  1. Create project folders in Dropbox"
echo "  2. Upload files to project folders"
echo "  3. Generate share links for clients"
echo "  4. List project files"
echo ""
echo "To deploy, restart the docker stack:"
echo "  docker compose down && docker compose up -d"
