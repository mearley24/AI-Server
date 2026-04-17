# telegram-interface/

Node.js Telegram bridge. Purpose unclear from the repo alone — there is
a second Telegram surface in `telegram-bob-remote/` (Python + its own
docker-compose.yml) which is the one called out in AGENTS.md.

## Relationship with telegram-bob-remote

| Dir | Language | Compose | AGENTS.md reference |
|---|---|---|---|
| `telegram-interface/` | Node.js | none in this repo | none found |
| `telegram-bob-remote/` | Python | `telegram-bob-remote/docker-compose.yml` | primary bot surface |

The canonical Telegram bot is **telegram-bob-remote** (Python). It runs
via its own compose file and is what @SymphonyBobBot and the employee
bots (Betty, Beatrice) connect to.

If this directory (`telegram-interface/`) is still in use, it should be:

1. Referenced from a compose file or launchd plist.
2. Documented in AGENTS.md or ops/INTEGRATIONS.md.

As of 2026-04-17 neither is present, which makes this directory a
candidate for retirement.

## Before deleting

- `grep -r telegram-interface --include='*.py' --include='*.js'
  --include='*.yml' --include='*.yaml' --include='*.md'` to find
  callers.
- If the Node bridge is used by the PWA in `apps/vault-pwa/` or
  another external client, move documentation here first.
- Otherwise, add a DECOMMISSIONED.md marker like mission_control/ et
  al., and plan deletion for a MEDIUM-risk cleanup pass.
