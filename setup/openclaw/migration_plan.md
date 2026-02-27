# Migration Plan: Telegram Proxy → OpenClaw Gateway
## Symphony Smart Homes | Mac Mini M4 (Bob)

---

## Overview

This document describes the migration from the current Docker-based Telegram proxy
to a full OpenClaw multi-agent orchestration system, while keeping all existing
Docker infrastructure intact.

---

## Current State

```
[You] ←─ Telegram ─→ [telegram-interface container]
                             │  (simple HTTP proxy)
                             ↓
                      [Open WebUI container]  ←─ single LLM, no agents
                             │
                      [Remediator container]  ←─ Docker watchdog
```

**What's running on Bob (Mac Mini M4):**

| Service | Type | Role |
|---|---|---|
| `open-webui` | Docker container | LLM web UI + API backend |
| `telegram-interface` | Docker container | Node.js Telegraf bot → Open WebUI proxy |
| `remediator` | Docker container | Docker health watchdog |
| Python/Shell tools | Native | Proposal generation scripts |

**Limitations of current setup:**
- Single-agent: one LLM, no task specialization
- No persistent agent identities or system prompts per-agent
- No agent-to-agent delegation
- Telegram bot is a dumb proxy — no routing, no tools, no memory

---

## Target State

```
[You] ←─ Telegram ─→ [OpenClaw gateway]  ←─ native macOS process (LaunchAgent)
                             │
                    ┌────────┴──────────┐
                    ↓                   ↓
             [bob agent]        [proposals agent]
             claude-sonnet       claude-haiku
                    │                   ↓
                    └──────────→ [dtools agent]
                                  gpt-4o-mini
                    │
                    ↓ (optional API fallback)
             [Open WebUI container]  ←─ still available at localhost:3000
                    │
             [Remediator container]  ←─ still running
```

**What changes:**

| Service | Before | After |
|---|---|---|
| Telegram bot | Simple proxy (telegram-interface container) | Full OpenClaw gateway |
| LLM access | Only via Open WebUI | Anthropic/OpenAI APIs directly + Open WebUI optional |
| Agent system | Single bot | Bob + Proposals + D-Tools agents |
| System prompt | Hardcoded in Node.js proxy | SOUL.md + bob_system_prompt.md |
| Tool access | None | Exec (restricted), file R/W, web browse |

**What stays the same:**

| Service | Status |
|---|---|
| Open WebUI | Stays running — web access + optional API backend |
| Remediator container | Stays running — continues watching Docker health |
| All Python/Shell tools | Stays in ~/AI-Server — Bob can call them via exec |
| Docker Compose setup | Unchanged — OpenClaw runs outside Docker |

---

## Migration Steps

### Phase 1 — Install OpenClaw alongside the existing stack

**Goal:** Get OpenClaw running without touching the current Telegram bot.

1. Run the install script:
   ```bash
   chmod +x install_openclaw.sh
   ./install_openclaw.sh
   ```

2. Confirm existing Docker services are still running:
   ```bash
   docker ps
   # Should show: open-webui, telegram-interface, remediator — all Up
   ```

3. Verify OpenClaw is installed:
   ```bash
   openclaw --version
   openclaw status  # should show "not running" at this point — that's fine
   ```

**Risk:** Zero. Nothing has changed yet.

---

### Phase 2 — Configure OpenClaw

**Goal:** Set up config files before going live.

4. Deploy configuration files (done by install script, or manually):
   ```bash
   cp openclaw.json ~/.openclaw/openclaw.json
   cp SOUL.md ~/.openclaw/workspace-bob/SOUL.md
   cp AGENTS.md ~/.openclaw/workspace-bob/AGENTS.md
   ```

5. Edit `~/.openclaw/openclaw.json` and replace all placeholders:
   - `YOUR_ANTHROPIC_API_KEY` → your Anthropic API key
   - `YOUR_OPENAI_API_KEY` → your OpenAI API key
   - `YOUR_TELEGRAM_BOT_TOKEN` → (leave blank for now, set in Phase 3)
   - `YOUR_TELEGRAM_USER_ID` → your numeric Telegram user ID (from @userinfobot)

6. Confirm Bob's system prompt file exists:
   ```bash
   ls ~/AI-Server/knowledge/standards/bob_system_prompt.md
   ```
   If it doesn't exist yet, create a placeholder:
   ```bash
   echo "# Bob System Prompt\nYou are Bob the Conductor." > \
     ~/AI-Server/knowledge/standards/bob_system_prompt.md
   ```

**Risk:** Zero. OpenClaw is configured but not started.

---

### Phase 3 — Set up the Telegram bot

**Choose one:**

#### Option A: New bot (zero downtime, recommended)

7. Follow `setup_telegram_bot.md` to create a brand-new bot via @BotFather.
8. Paste the new bot token into `openclaw.json`.
9. The old `telegram-interface` container keeps running on the original bot — no disruption.

#### Option B: Reuse existing bot (brief downtime)

7. Find your existing token:
   ```bash
   docker inspect telegram-interface | grep -i token
   # or check your .env file
   ```
8. Stop the old container:
   ```bash
   docker stop telegram-interface
   ```
9. Paste the token into `openclaw.json`.

---

### Phase 4 — Start OpenClaw and test

10. Start OpenClaw:
    ```bash
    openclaw start
    openclaw status  # should show "running"
    ```

11. Check the logs:
    ```bash
    openclaw logs --tail
    # Look for: "Telegram bot connected", "Agents loaded: bob, proposals, dtools"
    ```

12. Send a test DM to your bot:
    ```
    Hello, Bob — are you there?
    ```
    Expected: Bob responds within a few seconds.

13. Test agent delegation:
    ```
    Can you draft a proposal for a client at 123 Main St? 3 bed, 2 bath.
    ```
    Expected: Bob calls @proposals, assembles the result, returns a response.

14. Test system info:
    ```
    What tools do you have access to?
    ```

**Risk:** Low. If anything goes wrong, see rollback below.

---

### Phase 5 — Stabilize and optionally retire the old proxy

15. Run for at least 48 hours. Verify:
    - All Telegram messages reach Bob
    - Agent delegation works (proposals, dtools)
    - Logs show no errors
    - Open WebUI is still accessible at `http://localhost:3000`

16. Once stable, **optionally** remove the old `telegram-interface` container:
    ```bash
    # Only do this after Phase 4 is solid and you're using Option B (shared token)
    # If you used Option A (new bot), the old container causes no harm either way.
    docker rm telegram-interface
    ```

17. Update your Docker Compose file to remove or comment out the
    `telegram-interface` service, so it doesn't restart on reboot.

**Risk:** Low. Open WebUI and the remediator are completely unaffected.

---

## Rollback Plan

If OpenClaw misbehaves at any point during or after migration:

### If you used Option A (new bot):
The old `telegram-interface` container never stopped. Your original bot still works.
Simply stop OpenClaw:
```bash
openclaw stop
```
You're back to the original state immediately. No data loss.

### If you used Option B (reused token, stopped old container):
1. Stop OpenClaw:
   ```bash
   openclaw stop
   ```
2. Restart the old container:
   ```bash
   docker start telegram-interface
   ```
3. Your original Telegram proxy is live again within seconds.

The rollback takes under 30 seconds in either case. No data loss occurs —
conversation logs are stored in `~/.openclaw/conversations/`.

---

## Port and Resource Summary

| Service | Port | Type | Stays after migration? |
|---|---|---|---|
| Open WebUI | 3000 (default) | Docker | Yes |
| Remediator | internal | Docker | Yes |
| OpenClaw | no port (polling) | Native LaunchAgent | New |
| OpenClaw HTTP API | 4242 (disabled) | Native (optional) | Available if needed |

OpenClaw uses Telegram long-polling by default — no inbound port required.
Bob the Mac Mini doesn't need any firewall rule changes.

---

## Notes on Open WebUI as a Backend

OpenClaw is configured to call Anthropic and OpenAI APIs directly. Open WebUI
is optionally available as a third LLM backend (via its OpenAI-compatible API).

To enable it, set `providers.open_webui.enabled: true` in `openclaw.json` and
supply a valid Open WebUI API key. This is useful for:
- Running local/private models (llama, mistral) via Ollama within Open WebUI
- A fallback backend if Anthropic/OpenAI are unavailable
- Side-by-side testing of local vs. cloud model responses

Open WebUI continues to be accessible in a browser at `http://localhost:3000`
(or your configured port) regardless of whether OpenClaw uses it as a backend.
