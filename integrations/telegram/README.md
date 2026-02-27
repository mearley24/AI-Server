# Bob the Conductor — Telegram Bot

Your primary remote interface for managing Bob from anywhere. Text Bob like
messaging your best employee — ask questions, check status, receive alerts,
and stay in control from your phone 24/7.

---

## Architecture

```
Your Phone (Telegram)
       │
       ▼
 Telegram API ───────────────────────────────────────────────┐
       │                                                     │
       ▼                                                     ▼
 telegram_bot.py                                 notification_manager.py
 (command handlers,                              (proactive alerts pushed
  natural language,                               from OpenClaw, HA,
  inline keyboards)                               ClawWork, voice system)
       │                                                     │
       ▼                                                     │
 OpenClaw API (http://openclaw:3000)  ◄────────────────────┘
       │
       ├── Bob Conductor Agent (natural language, task routing)
       ├── ClawWork Agent (side hustle tasks + earnings)
       ├── Task Manager (queue, logs)
       ├── System Monitor (node health, uptime)
       └── Voice Receptionist Agent (call logs)
       │
       ├── Home Assistant (cameras, MQTT, device states)
       ├── Maestro / Stagehand worker nodes
       └── SQLite DBs (earnings.db, calls.db)
```

**Deployment:** All services run in Docker on Bob (Mac Mini M4). The bot
uses long-polling — no public IP or domain needed.

---

## Quick Start

### 1. Create the bot on Telegram
Follow [create_telegram_bot.md](./create_telegram_bot.md) — takes about 10 minutes.

### 2. Configure environment
```bash
cp .env.example .env
nano .env   # Fill in token, chat ID, and service URLs
```

### 3. Start with Docker Compose
```bash
docker compose -f docker-compose.telegram.yml up -d
```

### 4. Verify
Open Telegram, find your bot, and send `/start`. You should see Bob's main menu.

---

## Files in This Directory

| File | Purpose |
|---|---|
| `telegram_bot.py` | Main bot — all command handlers, NL routing, media handling |
| `notification_manager.py` | Proactive notification engine — import and call from anywhere |
| `daily_digest.py` | Morning digest + weekly summary generator |
| `bot_config.json` | Non-secret config: quiet hours, notification prefs, thresholds |
| `openclaw_telegram_channel.json` | OpenClaw channel config — drop into OpenClaw setup |
| `docker-compose.telegram.yml` | Docker Compose for bot + digest daemon |
| `Dockerfile.telegram` | Container build spec |
| `requirements.telegram.txt` | Python dependencies |
| `.env.example` | Template for secrets — copy to `.env` and fill in |
| `create_telegram_bot.md` | Step-by-step BotFather walkthrough |

---

## All Commands

### System

| Command | What it does |
|---|---|
| `/start` | Welcome message + main menu keyboard |
| `/status` | Full system status: Bob, Maestro, Stagehand, OpenClaw, ClawWork |
| `/health` | Quick health check: CPU, RAM, disk for all nodes |
| `/nodes` | Detailed worker node status |

### Work & Tasks

| Command | What it does |
|---|---|
| `/tasks` | Current OpenClaw task queue with status |
| `/logs` | Last 20 activity log entries |
| `/earnings` | ClawWork earnings (today / week / month / all-time) |

### Communication

| Command | What it does |
|---|---|
| `/calls` | Recent call log from voice receptionist |

### Cameras

| Command | What it does |
|---|---|
| `/cameras` | List all cameras (tappable for snapshots) |
| `/camera front_door` | Snapshot from a specific camera |

### Control (owner only)

| Command | What it does |
|---|---|
| `/pause` | Pause ClawWork side hustle |
| `/resume` | Resume ClawWork |

### Other

| Command | What it does |
|---|---|
| `/help` | Show all commands |

---

## Natural Language

Any message without a `/` prefix is forwarded directly to Bob (OpenClaw conductor agent). Bob can:
- Answer questions about anything running on the system
- Kick off ad-hoc tasks
- Explain what he's working on
- Discuss anything else

**Examples:**
- "What are you working on right now?"
- "Has anything gone wrong today?"
- "Draft a follow-up email to the Acme client"
- "How much have I earned this week?"

---

## Media Handling

| Input | What happens |
|---|---|
| Photo | Sent to OpenClaw vision agent for analysis |
| Document (PDF, DOCX, CSV…) | Sent to document processor agent |
| Voice message | Transcribed and sent to Bob as text |

---

## Notification Types & Priorities

Notifications are sent proactively by Bob whenever events occur.

| Type | Default Priority | Quiet Hours |
|---|---|---|
| Task completed | NORMAL | Suppressed |
| Task failed | HIGH | Sent |
| ClawWork earnings | LOW | Batched |
| Incoming call | HIGH | Sent |
| Missed call | HIGH | Sent |
| Node offline | CRITICAL | Always sent |
| Node back online | NORMAL | Suppressed |
| Health warning | HIGH | Sent |
| Security event | CRITICAL | Always sent |
| Motion detected | HIGH | Sent |
| Daily digest | NORMAL | Sent at 07:30 |
| Weekly summary | NORMAL | Sent Monday 08:00 |

**Priority rules:**
- `CRITICAL` — Always delivered immediately, no suppression
- `HIGH` — Delivered unless full quiet-hours lockdown
- `NORMAL` — Suppressed during quiet hours
- `LOW` — Suppressed during quiet hours; batched and delivered when quiet hours end

**Deduplication:** Identical alerts within a 5-minute window are dropped to prevent spam. Configurable via `dedupe_ttl_seconds` in `bot_config.json`.

---

## Quiet Hours

Default: 10:00 PM – 7:00 AM (America/Denver)

Configure in `bot_config.json`:
```json
"quiet_hours": {
  "enabled": true,
  "start": "22:00",
  "end": "07:00",
  "timezone": "America/Denver"
}
```

---

## Daily Digest

Sent every morning at 7:30 AM. Contains:
- Yesterday's ClawWork earnings + task count
- Calls received (answered vs. missed)
- Node health snapshot
- Any alerts or incidents
- Today's calendar
- Node uptime stats

Change send time in `bot_config.json`:
```json
"daily_digest": {
  "send_time": "07:30",
  "timezone": "America/Denver"
}
```

---

## Integrating NotificationManager

Import and use from any Bob service:

```python
from notification_manager import NotificationManager, NotificationType, Priority

nm = NotificationManager()

# Task complete
await nm.task_complete("Proposal for Acme Corp", client="Acme Corp")

# Node offline
await nm.node_offline("Maestro", last_seen="2 minutes ago")

# Motion alert with camera snapshot
photo_bytes = await get_camera_snapshot("front_door")
await nm.motion_detected("front_door", photo=photo_bytes)

# Custom message
await nm.send(
    notif_type=NotificationType.INFO,
    message="Your custom message here",
    priority=Priority.NORMAL,
)
```

Or from the command line:
```bash
python notification_manager.py task_complete "Proposal for Acme sent" NORMAL
```

---

## OpenClaw Integration

The `openclaw_telegram_channel.json` file defines how OpenClaw routes Telegram
messages to the right agents. To activate it:

1. Merge the `channel` object into `setup/openclaw/openclaw.json` under `"channels"`:
```json
{
  "channels": [
    { ... (existing channels) ... },
    { ... (paste content of openclaw_telegram_channel.json here) ... }
  ]
}
```

2. Set the environment variables it references:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_OWNER_CHAT_ID`

3. Restart OpenClaw.

---

## Customizing

### Add a new command

In `telegram_bot.py`:

```python
@owner_only
async def cmd_mycommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Your response here")

# Register in build_application():
app.add_handler(CommandHandler("mycommand", cmd_mycommand))
```

Register with BotFather using `/setcommands`.

### Add a new notification type

In `notification_manager.py`, add to the `NotificationType` enum:
```python
MY_EVENT = "my_event"
```

Add an icon in `TYPE_ICONS` and default priority in `DEFAULT_PRIORITIES`.

Then call it anywhere:
```python
await nm.send(NotificationType.MY_EVENT, "Something happened")
```

### Add team access (read-only)

In `bot_config.json`:
```json
"allowed_user_ids": [987654321, 111222333]
```

These users can run read-only commands (`/status`, `/health`, etc.) but not
write commands (`/pause`, `/resume`).

---

## Troubleshooting

**Bot doesn't respond at all**
- Check the container is running: `docker logs bob-telegram-bot`
- Verify `TELEGRAM_BOT_TOKEN` is correct
- Make sure the bot process isn't blocked by a firewall on outbound 443

**"Access denied" on every message**
- Your `TELEGRAM_OWNER_CHAT_ID` doesn't match your actual Telegram ID
- Use @userinfobot to get your ID, then update `.env`

**Status / tasks show "unknown"**
- OpenClaw API is not reachable from the bot container
- Check that both are on the `openclaw-net` Docker network
- Test: `docker exec bob-telegram-bot curl http://openclaw:3000/api/health`

**Camera snapshots fail**
- Home Assistant is unreachable or the token is wrong
- Check `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` in `.env`

**Duplicate alerts**
- Increase `dedupe_ttl_seconds` in `bot_config.json` (default: 300 = 5 min)

**Daily digest not arriving**
- Check the digest container: `docker logs bob-telegram-digest`
- Verify `TZ=America/Denver` matches your intended timezone

---

## Security

- The bot rejects all messages from chat IDs not in the allow list
- Write commands (`/pause`, `/resume`) are owner-only
- Keep `.env` out of git (it's in `.gitignore`)
- Rotate bot tokens via BotFather's `/revoke` command if ever exposed

---

## Dependencies

- `python-telegram-bot` v21+ (async PTB)
- `aiohttp` — async HTTP client for API calls
- `python-dotenv` — environment variable loading
- `aiosqlite` — async SQLite for direct DB fallbacks

Install: `pip install -r requirements.telegram.txt`
