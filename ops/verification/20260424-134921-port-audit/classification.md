# Port Exposure Classification

## Should be localhost-only unless intentionally shared
- 11434 Ollama
- 8199 iMessage bridge
- 8421 trading-api
- 8103 file-watcher
- 8088 markup-tool
- 8801 vault-pwa
- 3000 OpenWebUI
- 3001 Uptime Kuma

## Okay if intentionally LAN-facing
- None by default. Prefer Tailscale/localhost proxy instead.

## Needs review
- Any listener showing `*:<port>` or `0.0.0.0:<port>`
- Any Docker mapping not starting with `127.0.0.1:`
