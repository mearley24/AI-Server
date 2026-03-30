#!/bin/bash
# =============================================================================
# Zoho Mail Draft API Setup — Run on Bob
# =============================================================================
# This script walks you through setting up Zoho Mail OAuth so Bob can
# create email drafts and notify you via iMessage for review.
#
# One-time setup. Takes about 5 minutes.
# =============================================================================

set -e
cd "$(dirname "$0")/.."
source .env 2>/dev/null || true

echo ""
echo "========================================="
echo " Zoho Mail Draft API Setup"
echo "========================================="
echo ""
echo "Step 1: Create a Self Client in Zoho API Console"
echo "-------------------------------------------------"
echo "1. Open: https://api-console.zoho.com/"
echo "2. Click 'GET STARTED' (or 'ADD CLIENT' if you already have clients)"
echo "3. Choose 'Self Client' → click 'CREATE NOW' → click 'OK'"
echo "4. Copy the Client ID and Client Secret shown"
echo ""

read -p "Paste your Client ID: " ZOHO_CLIENT_ID
read -p "Paste your Client Secret: " ZOHO_CLIENT_SECRET

echo ""
echo "Step 2: Generate a Grant Token"
echo "------------------------------"
echo "1. In the API Console, click the 'Generate Code' tab"
echo "2. Enter these scopes (copy-paste this entire line):"
echo ""
echo "   ZohoMail.messages.CREATE,ZohoMail.accounts.READ"
echo ""
echo "3. Set Time Duration to '10 minutes'"
echo "4. Enter description: 'Bob email drafts'"
echo "5. Click 'CREATE'"
echo "6. Copy the generated code"
echo ""

read -p "Paste the Grant Token (you have 10 min): " ZOHO_GRANT_TOKEN

echo ""
echo "Step 3: Exchanging grant token for refresh token..."
echo ""

RESPONSE=$(curl -s -X POST "https://accounts.zoho.com/oauth/v2/token" \
  -d "grant_type=authorization_code" \
  -d "client_id=${ZOHO_CLIENT_ID}" \
  -d "client_secret=${ZOHO_CLIENT_SECRET}" \
  -d "code=${ZOHO_GRANT_TOKEN}")

echo "Response: $RESPONSE"
echo ""

REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('refresh_token',''))" 2>/dev/null)
ACCESS_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: No refresh token received. Check the response above."
    echo "Common issues:"
    echo "  - Grant token expired (you have 10 minutes)"
    echo "  - Wrong client ID or secret"
    echo "  - Scope not accepted"
    exit 1
fi

echo "Got refresh token: ${REFRESH_TOKEN:0:20}..."
echo "Got access token: ${ACCESS_TOKEN:0:20}..."
echo ""

# Test: get account ID
echo "Step 4: Testing API access — getting Zoho Mail account ID..."
ACCOUNT_RESPONSE=$(curl -s "https://mail.zoho.com/api/accounts" \
  -H "Authorization: Zoho-oauthtoken ${ACCESS_TOKEN}")

ACCOUNT_ID=$(echo "$ACCOUNT_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['accountId'])" 2>/dev/null)

if [ -z "$ACCOUNT_ID" ]; then
    echo "ERROR: Could not get Zoho Mail account ID."
    echo "Response: $ACCOUNT_RESPONSE"
    exit 1
fi

echo "Zoho Mail Account ID: $ACCOUNT_ID"
echo ""

# Save to .env
echo "Step 5: Saving to .env..."

# Remove old values if they exist
for KEY in ZOHO_CLIENT_ID ZOHO_CLIENT_SECRET ZOHO_REFRESH_TOKEN ZOHO_MAIL_ACCOUNT_ID; do
    sed -i '' "/^${KEY}=/d" .env 2>/dev/null || true
done

cat >> .env << EOF

ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}
ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}
ZOHO_REFRESH_TOKEN=${REFRESH_TOKEN}
ZOHO_MAIL_ACCOUNT_ID=${ACCOUNT_ID}
EOF

echo "Saved to .env"
echo ""

# Test: create a draft
echo "Step 6: Testing draft creation..."
DRAFT_RESPONSE=$(curl -s -X POST "https://mail.zoho.com/api/accounts/${ACCOUNT_ID}/messages" \
  -H "Authorization: Zoho-oauthtoken ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "fromAddress": "info@symphonysh.com",
    "toAddress": "info@symphonysh.com",
    "subject": "[TEST] Bob Draft System — Delete This",
    "content": "This is a test draft created by Bob. If you see this in your Zoho drafts, the system is working. You can delete this.",
    "mailFormat": "html"
  }')

echo "Draft response: $DRAFT_RESPONSE"

DRAFT_STATUS=$(echo "$DRAFT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('code',0))" 2>/dev/null)

if [ "$DRAFT_STATUS" = "200" ]; then
    echo ""
    echo "========================================="
    echo " SUCCESS — Zoho Draft API is working"
    echo "========================================="
    echo ""
    echo "Check your Zoho Mail drafts folder — you should see a test draft."
    echo "Delete it when you're done."
    echo ""
    echo "Bob can now:"
    echo "  1. Create email drafts in Zoho"
    echo "  2. Notify you via iMessage when a draft is ready"
    echo "  3. Update drafts based on your feedback"
    echo ""
    echo "To deploy, restart the docker stack:"
    echo "  docker compose down && docker compose up -d"
else
    echo ""
    echo "WARNING: Draft creation may have failed."
    echo "Check the response above. Common issues:"
    echo "  - fromAddress must be a configured Zoho email"
    echo "  - Scope ZohoMail.messages.CREATE may need ZohoMail.messages.ALL"
    echo ""
    echo "Credentials are saved to .env — you can retry manually."
fi
