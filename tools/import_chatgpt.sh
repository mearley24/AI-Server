#!/bin/zsh
# Import ChatGPT conversations into Cortex
# Usage: zsh tools/import_chatgpt.sh /path/to/conversations.json

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_SERVER_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -z "$1" ]]; then
    echo "Usage: zsh tools/import_chatgpt.sh /path/to/conversations.json"
    echo ""
    echo "How to get conversations.json:"
    echo "  1. Go to chatgpt.com -> Settings -> Data Controls -> Export Data"
    echo "  2. Click Export and confirm"
    echo "  3. Check your email for the download link"
    echo "  4. Download and unzip the file"
    echo "  5. Run: zsh tools/import_chatgpt.sh ~/Downloads/conversations.json"
    exit 1
fi

JSON_FILE="$1"

if [[ ! -f "$JSON_FILE" ]]; then
    echo "Error: File not found: $JSON_FILE"
    exit 1
fi

echo "Importing ChatGPT conversations from: $JSON_FILE"
echo "Target: Cortex memory system"

# Run inside the cortex container (which has Redis access)
docker cp "$JSON_FILE" cortex:/tmp/conversations.json
docker cp "$AI_SERVER_DIR/tools/chatgpt_to_cortex.py" cortex:/tmp/chatgpt_to_cortex.py

docker exec cortex pip install redis -q 2>/dev/null

docker exec -e REDIS_URL="redis://:d1fff1065992d132b000c01d6012fa52@redis:6379" \
    cortex python3 /tmp/chatgpt_to_cortex.py /tmp/conversations.json

echo ""
echo "Import complete. Check Cortex at http://localhost:8102/memories"
