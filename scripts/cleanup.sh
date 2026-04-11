#!/bin/zsh
echo "Removing unused Docker volumes..."
docker volume rm ai-server_openwebui 2>/dev/null
echo "Done."
