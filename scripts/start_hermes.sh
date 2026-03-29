#!/bin/bash
# Start Hermes with Bob's standing orders
# Usage: bash ~/AI-Server/scripts/start_hermes.sh

ORDERS_FILE="$HOME/AI-Server/scripts/hermes_standing_orders.md"

if ! command -v hermes &>/dev/null; then
    echo "Hermes not installed. Run: bash ~/AI-Server/scripts/setup_bob_employee.sh"
    exit 1
fi

# Check if standing orders exist
if [ ! -f "$ORDERS_FILE" ]; then
    echo "Standing orders not found at $ORDERS_FILE"
    exit 1
fi

# Read standing orders
ORDERS=$(cat "$ORDERS_FILE")

# Start Hermes with the standing orders as initial context
echo "Starting Hermes with Bob's standing orders..."
echo "$ORDERS

---
You've just started a new shift. Begin by:
1. Check service health (run the health check commands above)
2. Check trading status
3. Look for any new opportunities
4. Report your status to Matt

Go." | hermes
