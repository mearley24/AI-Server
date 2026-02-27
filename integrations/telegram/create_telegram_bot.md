# How to Create the Bob Telegram Bot

Step-by-step setup from zero to a working bot. Takes about 10 minutes.

---

## Step 1 — Open BotFather

On your phone or desktop, open Telegram and search for **@BotFather** (the official bot with a blue checkmark). Tap on it and hit **Start**.

---

## Step 2 — Create a New Bot

Send the command:
```
/newbot
```

BotFather will ask for:

**1. A display name** — Enter:
```
Bob the Conductor
```

**2. A username** — Must end in `bot`, must be unique globally. Try:
```
symphony_bob_bot
```
If that's taken, try variations like `bob_conductor_bot`, `myconductor_bob_bot`, etc.

BotFather will confirm with a message like:
> Done! Congratulations on your new bot. You will find it at t.me/symphony_bob_bot.

---

## Step 3 — Copy Your Bot Token

BotFather gives you a token that looks like:
```
7812345678:AAHxyz_abcDEFghiJKLmnopQRSTuvwXYZ012
```

**Copy this immediately and keep it safe.** This is your `TELEGRAM_BOT_TOKEN`. Treat it like a password.

---

## Step 4 — Set the Bot Description

Send to BotFather:
```
/setdescription
```

Select your bot, then enter:
```
Bob the Conductor — your private AI operations manager. Running 24/7 on Mac Mini M4.
```

---

## Step 5 — Set About Text (Short Bio)

Send to BotFather:
```
/setabouttext
```

Select your bot, enter:
```
Private operations interface for Bob. Commands: /status /health /earnings /cameras /calls /tasks /logs /pause /resume /help
```

---

## Step 6 — Set a Profile Photo (Optional but Recommended)

Send to BotFather:
```
/setuserpic
```

Select your bot, then upload an image. A conductor silhouette, robot icon, or your logo all work well. The image should be at least 512×512px.

---

## Step 7 — Register All Commands with BotFather

This makes commands auto-complete when you type `/` in the chat.

Send to BotFather:
```
/setcommands
```

Select your bot, then paste this entire block:
```
start - Start the bot and show main menu
status - Full system status (Bob, Maestro, Stagehand)
health - Quick health check of all nodes
earnings - ClawWork earnings summary
cameras - List cameras and get snapshots
camera - Get snapshot from a specific camera
calls - Recent voice receptionist call log
nodes - Worker node status
tasks - Current OpenClaw task queue
logs - Recent activity logs
pause - Pause ClawWork side hustle
resume - Resume ClawWork
help - Show all commands
```

---

## Step 8 — Get Your Chat ID

You need your personal Telegram chat ID so the bot only responds to you.

**Option A — Easiest:**
1. Search for **@userinfobot** in Telegram
2. Send it any message
3. It replies with your numeric ID (e.g. `123456789`)

**Option B — Via Bot API (after Step 9):**
1. Send any message to your new bot
2. Open this URL in a browser (replace YOUR_TOKEN):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Find `"from": {"id": 123456789, ...}` in the JSON

---

## Step 9 — Configure Environment Variables

On the Mac Mini (Bob), open or create the `.env` file:

```bash
nano /path/to/telegram_setup/.env
```

Add these values:
```
TELEGRAM_BOT_TOKEN=7812345678:AAHxyz_abcDEFghiJKLmnopQRSTuvwXYZ012
TELEGRAM_OWNER_CHAT_ID=123456789
OPENCLAW_API_URL=http://openclaw:3000
BOB_API_URL=http://localhost:8080
HOME_ASSISTANT_URL=http://homeassistant:8123
HOME_ASSISTANT_TOKEN=your-ha-long-lived-token
CLAWWORK_DB_PATH=/data/clawwork/earnings.db
VOICE_DB_PATH=/data/voice/calls.db
```

---

## Step 10 — Start the Bot

**Using Docker Compose (recommended):**
```bash
cd /path/to/telegram_setup
docker compose -f docker-compose.telegram.yml up -d
```

**Direct Python (for testing):**
```bash
pip install python-telegram-bot==21.* aiohttp python-dotenv
python telegram_bot.py
```

---

## Step 11 — Verify It Works

1. Open Telegram and find your bot
2. Send `/start` — you should see Bob's welcome message with an inline keyboard menu
3. Send `/status` — Bob should reply with a system status card
4. Try a natural language message: "What tasks are you working on right now?"

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Bot doesn't respond | Check `TELEGRAM_BOT_TOKEN` is correct and the bot process is running |
| "Access denied" | Your chat ID doesn't match `TELEGRAM_OWNER_CHAT_ID` — re-check Step 8 |
| Status shows "unknown" | OpenClaw API isn't reachable — verify `OPENCLAW_API_URL` |
| Camera snapshot fails | Check `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` |
| Bot spams the same alert | Adjust `dedupe_ttl_seconds` in `bot_config.json` |

---

## Security Notes

- **Never share your bot token.** If exposed, revoke it immediately via BotFather's `/revoke` command.
- The bot rejects messages from any chat ID not in the allow list.
- Rotate tokens periodically via BotFather.
