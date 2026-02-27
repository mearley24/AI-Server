# Setting Up a Telegram Bot for OpenClaw (Bob the Conductor)

OpenClaw needs a Telegram bot token to receive and send messages. This guide
walks you through creating a new bot via @BotFather.

---

## Step 1: Create a new bot via @BotFather

1. Open Telegram and search for **@BotFather**
2. Start a conversation: `/start`
3. Create a new bot: `/newbot`
4. BotFather will ask:
   - **Name:** `Bob` (or `Bob the Conductor` — this is the display name)
   - **Username:** must end in `bot`, e.g. `SymphonyBobBot` or `BobConductorBot`
5. BotFather responds with your bot token:
   ```
   Done! Congratulations on your new bot. You will find it at t.me/YourBotUsername.
   Use this token to access the HTTP API:
   7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
6. **Copy this token** — you'll need it in Step 3.

---

## Step 2: Get your Telegram User ID

OpenClaw's whitelist requires your numeric Telegram user ID.

1. Search for **@userinfobot** on Telegram
2. Start a conversation: `/start`
3. It responds with your user info, including your **ID** (a number like `123456789`)
4. Copy this number.

Alternatively, forward any message to **@RawDataBot** and look for `"from": { "id": ... }`.

---

## Step 3: Add token and user ID to openclaw.json

Open your config file:
```bash
nano ~/.openclaw/openclaw.json
```

Find and replace:
```json
"bot_token": "YOUR_TELEGRAM_BOT_TOKEN"
```
With your actual bot token:
```json
"bot_token": "7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

And replace:
```json
"allowed_user_ids": ["YOUR_TELEGRAM_USER_ID"]
```
With your numeric ID:
```json
"allowed_user_ids": ["123456789"]
```

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

---

## Step 4: Start OpenClaw

```bash
openclaw start
openclaw status
```

Look for:
```
✓ Telegram bot connected (@YourBotUsername)
✓ Agents loaded: bob, proposals, dtools
✓ Listening...
```

---

## Step 5: Test

1. Open Telegram and search for your bot by username (e.g., `@SymphonyBobBot`)
2. Start a conversation: `/start`
3. Send: `Hello, Bob — are you there?`
4. Bob should respond within a few seconds.

---

## Optional: Set bot commands

In BotFather, set a command menu for convenience:
```
/setcommands → @YourBotUsername
```
Paste:
```
start - Start Bob
help - Show available commands
status - System status
proposals - Proposal mode
dtools - D-Tools mode
```

---

## Optional: Disable joining groups

To prevent your bot from being added to groups:
```
BotFather → /setjoingroups → @YourBotUsername → Disable
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Bot doesn't respond | Check `openclaw status` and `openclaw logs --tail` |
| "Unauthorized" error | Token is wrong or has spaces — re-copy from BotFather |
| "User not allowed" | Your user ID isn't in `allowed_user_ids` |
| Messages delay | Normal — Telegram long-polling has ~1-2s latency |
| Bot offline after reboot | LaunchAgent not installed — run `openclaw onboard --install-daemon` |
