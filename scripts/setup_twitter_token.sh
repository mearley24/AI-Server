#!/usr/bin/env zsh

printf "=== Twitter Auth Token Setup ===\n\n"
printf "To get your auth_token cookie from X/Twitter:\n"
printf "  1. Open x.com in your browser and log in\n"
printf "  2. Open DevTools (Cmd+Option+I on Mac)\n"
printf "  3. Go to Application tab -> Cookies -> x.com\n"
printf "  4. Find the cookie named 'auth_token'\n"
printf "  5. Copy the value\n\n"

if [ -f .env ]; then
    if grep -q "TWITTER_AUTH_TOKEN" .env; then
        printf "TWITTER_AUTH_TOKEN already exists in .env\n"
        printf "Current value: %s\n" "$(grep TWITTER_AUTH_TOKEN .env | cut -d= -f2 | cut -c1-8)..."
        printf "\nReplace it? (y/n): "
        read -r answer
        if [ "$answer" != "y" ]; then
            printf "Keeping existing token.\n"
            exit 0
        fi
        sed -i '' '/TWITTER_AUTH_TOKEN/d' .env
    fi
else
    touch .env
fi

printf "Paste your auth_token value: "
read -r token

if [ -z "$token" ]; then
    printf "Error: No token provided.\n"
    exit 1
fi

echo "TWITTER_AUTH_TOKEN=$token" >> .env
printf "\nToken saved to .env\n"
printf "Now run: docker compose up -d rsshub x-alpha-collector\n"
