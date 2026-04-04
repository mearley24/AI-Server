---
name: symphony-docker-ship
description: One-command rebuild/restart and verify for Symphony AI-Server Docker stack (OpenClaw, polymarket-bot, Mission Control, Redis). Use when the user wants to ship changes, verify the close-the-loop stack, or needs copy-paste commands for Bob’s Mac Mini.
---

# Symphony Docker — all-in-one ship & verify

## When to use

- After editing `openclaw/`, `polymarket-bot/`, `mission_control/`, or compose.
- When validating **Redis `events:log`**, OpenClaw **8099**, Mission Control **8098**, bot **8430**.

## Preferred: repo script

From the repo root (`~/AI-Server`):

```bash
chmod +x scripts/symphony-ship.sh   # once
./scripts/symphony-ship.sh          # default = ship (build + up + verify)
./scripts/symphony-ship.sh verify   # checks only
./scripts/symphony-ship.sh restart  # fast restart after bind-mount code edits
./scripts/symphony-ship.sh full     # entire docker compose up -d
```

Override repo path: `SYMPHONY_ROOT=/path/to/AI-Server ./scripts/symphony-ship.sh`

## One-liner (copy-paste)

Same as `ship` without creating a file:

```bash
cd "$HOME/AI-Server" && docker compose build openclaw polymarket-bot && docker compose up -d redis vpn polymarket-bot openclaw mission-control && sleep 3 && docker exec redis redis-cli PING && docker exec redis redis-cli LRANGE events:log 0 2 && curl -sS http://127.0.0.1:8099/health && echo "" && curl -sS http://127.0.0.1:8098/health && echo "" && curl -sS "http://127.0.0.1:8099/intelligence/events-log?limit=5" && echo "" && curl -sS http://127.0.0.1:8430/health && echo "" && echo "OK"
```

## Notes

- **OpenClaw** code is bind-mounted at `./openclaw:/app` — Python-only changes often need **`./scripts/symphony-ship.sh restart`** (or `docker compose restart openclaw`) instead of a full build.
- **Polymarket bot** uses **`network_mode: service:vpn`** — health is on **127.0.0.1:8430** (published via the `vpn` service).
- Requires `.env` / secrets as already configured for compose; this skill does not manage keys.

## Related paths

- Compose: `docker-compose.yml`
- Close-the-loop checklist: `.cursor/prompts/close-the-loop-part2.md`
