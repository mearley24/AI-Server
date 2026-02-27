#!/usr/bin/env python3
"""
telegram_bot.py - Bob the Conductor - Telegram interface

Commands (13 total):
  /start       - Introduce Bob
  /help        - List commands
  /status      - System overview (CPU, RAM, disk, uptime)
  /health      - Detailed health check per node
  /nodes       - Worker-node roster
  /tasks       - Current task queue
  /logs [n]    - Last n log lines (default 20)
  /earnings    - Earnings summary
  /ask <q>     - One-shot question to general agent
  /chat <msg>  - Conversational turn (keeps history)
  /restart <s> - Restart a named service (owner only)
  /silence     - Mute proactive notifications
  /unsilence   - Re-enable notifications

Requires env vars:
  TELEGRAM_BOT_TOKEN      - from @BotFather
  TELEGRAM_OWNER_CHAT_ID  - your personal Telegram user/chat ID

Optional env vars:
  OPENCLAW_API_URL        - base URL for OpenClaw REST API (default http://localhost:8080)
  OPENCLAW_API_KEY        - API key if OpenClaw auth is enabled
  HISTORY_DB              - path to SQLite file for chat history (default data/telegram_history.db)
  MAX_HISTORY_TURNS       - conversation turns to keep per user (default 20)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bob.telegram")

BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER_ID: int = int(os.environ["TELEGRAM_OWNER_CHAT_ID"])
OPENCLAW_URL: str = os.getenv("OPENCLAW_API_URL", "http://localhost:8080")
OPENCLAW_KEY: Optional[str] = os.getenv("OPENCLAW_API_KEY")
HISTORY_DB: Path = Path(os.getenv("HISTORY_DB", "data/telegram_history.db"))
MAX_HISTORY: int = int(os.getenv("MAX_HISTORY_TURNS", "20"))

_silenced: bool = False

# ---------------------------------------------------------------------------
# SQLite conversation history
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  INTEGER NOT NULL,
            role     TEXT    NOT NULL,
            content  TEXT    NOT NULL,
            ts       TEXT    NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def history_append(chat_id: int, role: str, content: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO history (chat_id, role, content, ts) VALUES (?,?,?,?)",
            (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            DELETE FROM history
            WHERE chat_id = ? AND id NOT IN (
                SELECT id FROM history WHERE chat_id = ?
                ORDER BY id DESC LIMIT ?
            )
            """,
            (chat_id, chat_id, MAX_HISTORY * 2),
        )
        conn.commit()


def history_get(chat_id: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM history WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in rows]


# ---------------------------------------------------------------------------
# OpenClaw API helpers
# ---------------------------------------------------------------------------

AUTH_HEADERS: dict[str, str] = (
    {"X-API-Key": OPENCLAW_KEY} if OPENCLAW_KEY else {}
)


async def _oc_get(path: str) -> dict:
    async with aiohttp.ClientSession(headers=AUTH_HEADERS) as session:
        async with session.get(f"{OPENCLAW_URL}{path}", timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _oc_post(path: str, payload: dict) -> dict:
    async with aiohttp.ClientSession(headers=AUTH_HEADERS) as session:
        async with session.post(
            f"{OPENCLAW_URL}{path}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _chunk(text: str, size: int = 4000) -> list[str]:
    return textwrap.wrap(text, size, break_long_words=True, replace_whitespace=False)


async def _reply(update: Update, text: str, parse_mode: str = ParseMode.MARKDOWN) -> None:
    for chunk in _chunk(text):
        await update.message.reply_text(chunk, parse_mode=parse_mode)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Bob the Conductor*\n\n"
        "I'm the control interface for your AI Server.\n"
        "Type /help to see what I can do."
    )
    await _reply(update, text)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Available commands*\n\n"
        "`/status`      - System overview\n"
        "`/health`      - Detailed node health\n"
        "`/nodes`       - Worker-node roster\n"
        "`/tasks`       - Task queue\n"
        "`/logs [n]`    - Last n log lines (default 20)\n"
        "`/earnings`    - Earnings summary\n"
        "`/ask <q>`     - One-shot question\n"
        "`/chat <msg>`  - Conversation (remembers context)\n"
        "`/restart <s>` - Restart service (owner only)\n"
        "`/silence`     - Mute notifications\n"
        "`/unsilence`   - Re-enable notifications\n"
    )
    await _reply(update, text)


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_get("/api/v1/status")
        uptime = data.get("uptime", "unknown")
        cpu = data.get("cpu_percent", "?")
        ram = data.get("ram_percent", "?")
        disk = data.get("disk_percent", "?")
        tasks_running = data.get("tasks_running", 0)
        tasks_queued = data.get("tasks_queued", 0)
        text = (
            f"*System Status*\n\n"
            f"CPU: `{cpu}%` | RAM: `{ram}%` | Disk: `{disk}%`\n"
            f"Uptime: `{uptime}`\n"
            f"Tasks: `{tasks_running}` running / `{tasks_queued}` queued"
        )
    except Exception as exc:
        text = f"Could not reach OpenClaw: `{exc}`"
    await _reply(update, text)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_get("/api/v1/health")
        lines = ["*Health Check*\n"]
        for svc, info in data.get("services", {}).items():
            icon = "OK" if info.get("ok") else "FAIL"
            latency = info.get("latency_ms", "")
            lat_str = f" `{latency}ms`" if latency != "" else ""
            lines.append(f"{icon} `{svc}`{lat_str}")
        text = "\n".join(lines) or "No health data returned."
    except Exception as exc:
        text = f"Health check failed: `{exc}`"
    await _reply(update, text)


# ---------------------------------------------------------------------------
# /nodes
# ---------------------------------------------------------------------------

async def cmd_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_get("/api/v1/nodes")
        nodes = data.get("nodes", [])
        if not nodes:
            await _reply(update, "No worker nodes registered.")
            return
        lines = ["*Worker Nodes*\n"]
        for n in nodes:
            status_icon = "[online]" if n.get("online") else "[offline]"
            lines.append(
                f"{status_icon} `{n['id']}` - {n.get('role', 'unknown')} "
                f"| CPU `{n.get('cpu_percent', '?')}%`"
            )
        await _reply(update, "\n".join(lines))
    except Exception as exc:
        await _reply(update, f"Nodes unavailable: `{exc}`")


# ---------------------------------------------------------------------------
# /tasks
# ---------------------------------------------------------------------------

async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_get("/api/v1/tasks")
        tasks = data.get("tasks", [])
        if not tasks:
            await _reply(update, "Task queue is empty.")
            return
        lines = ["*Task Queue*\n"]
        for t in tasks[:20]:
            status = t.get("status", "?")
            lines.append(f"`{t['id']}` - {t.get('name', '?')} ({status})")
        if len(tasks) > 20:
            lines.append(f"...and {len(tasks) - 20} more.")
        await _reply(update, "\n".join(lines))
    except Exception as exc:
        await _reply(update, f"Task list unavailable: `{exc}`")


# ---------------------------------------------------------------------------
# /logs [n]
# ---------------------------------------------------------------------------

async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        n = int(ctx.args[0]) if ctx.args else 20
        n = max(1, min(n, 100))
    except (IndexError, ValueError):
        n = 20
    try:
        data = await _oc_get(f"/api/v1/logs?lines={n}")
        entries = data.get("entries", [])
        if not entries:
            await _reply(update, "No log entries found.")
            return
        body = "\n".join(
            f"`{e.get('ts', '')[:19]}` [{e.get('level', 'INFO'):5s}] {e.get('msg', '')}"
            for e in entries
        )
        await _reply(update, f"*Last {n} log lines*\n\n" + body)
    except Exception as exc:
        await _reply(update, f"Logs unavailable: `{exc}`")


# ---------------------------------------------------------------------------
# /earnings
# ---------------------------------------------------------------------------

async def cmd_earnings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_get("/api/v1/earnings")
        today = data.get("today_usd", "?")
        week = data.get("week_usd", "?")
        month = data.get("month_usd", "?")
        total = data.get("total_usd", "?")
        text = (
            f"*Earnings Summary*\n\n"
            f"Today:  `${today}`\n"
            f"Week:   `${week}`\n"
            f"Month:  `${month}`\n"
            f"Total:  `${total}`"
        )
    except Exception as exc:
        text = f"Earnings unavailable: `{exc}`"
    await _reply(update, text)


# ---------------------------------------------------------------------------
# /ask <question>
# ---------------------------------------------------------------------------

async def cmd_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "Usage: `/ask <your question>`")
        return
    question = " ".join(ctx.args)
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_post("/api/v1/agent/ask", {"query": question})
        answer = data.get("answer") or data.get("response") or str(data)
        await _reply(update, answer)
    except Exception as exc:
        await _reply(update, f"Agent error: `{exc}`")


# ---------------------------------------------------------------------------
# /chat <message>  (with persistent history)
# ---------------------------------------------------------------------------

async def cmd_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "Usage: `/chat <message>`")
        return
    chat_id = update.effective_chat.id
    user_msg = " ".join(ctx.args)
    history_append(chat_id, "user", user_msg)
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_post(
            "/api/v1/agent/chat",
            {"messages": history_get(chat_id)},
        )
        answer = data.get("answer") or data.get("response") or str(data)
        history_append(chat_id, "assistant", answer)
        await _reply(update, answer)
    except Exception as exc:
        await _reply(update, f"Chat error: `{exc}`")


# ---------------------------------------------------------------------------
# /restart <service>  (owner only)
# ---------------------------------------------------------------------------

async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await _reply(update, "Owner-only command.")
        return
    if not ctx.args:
        await _reply(update, "Usage: `/restart <service_name>`")
        return
    service = ctx.args[0]
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_post("/api/v1/control/restart", {"service": service})
        msg = data.get("message") or f"Restart issued for `{service}`."
        await _reply(update, msg)
    except Exception as exc:
        await _reply(update, f"Restart failed: `{exc}`")


# ---------------------------------------------------------------------------
# /silence  /unsilence
# ---------------------------------------------------------------------------

async def cmd_silence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _silenced
    _silenced = True
    await _reply(update, "Notifications silenced. Use /unsilence to re-enable.")


async def cmd_unsilence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _silenced
    _silenced = False
    await _reply(update, "Notifications re-enabled.")


# ---------------------------------------------------------------------------
# Fallback: handle plain text as /chat
# ---------------------------------------------------------------------------

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_msg = update.message.text or ""
    if not user_msg.strip():
        return
    history_append(chat_id, "user", user_msg)
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        data = await _oc_post(
            "/api/v1/agent/chat",
            {"messages": history_get(chat_id)},
        )
        answer = data.get("answer") or data.get("response") or str(data)
        history_append(chat_id, "assistant", answer)
        await _reply(update, answer)
    except Exception as exc:
        await _reply(update, f"Error: `{exc}`")


# ---------------------------------------------------------------------------
# Proactive notification helper
# ---------------------------------------------------------------------------

async def send_notification(app: Application, text: str) -> None:
    if _silenced:
        log.info("Notification suppressed (silenced): %s", text[:80])
        return
    await app.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Bot command registration
# ---------------------------------------------------------------------------

COMMANDS = [
    BotCommand("start",     "Introduce Bob"),
    BotCommand("help",      "List commands"),
    BotCommand("status",    "System overview"),
    BotCommand("health",    "Detailed node health"),
    BotCommand("nodes",     "Worker-node roster"),
    BotCommand("tasks",     "Task queue"),
    BotCommand("logs",      "Last n log lines"),
    BotCommand("earnings",  "Earnings summary"),
    BotCommand("ask",       "One-shot question"),
    BotCommand("chat",      "Conversation with history"),
    BotCommand("restart",   "Restart a service (owner)"),
    BotCommand("silence",   "Mute notifications"),
    BotCommand("unsilence", "Re-enable notifications"),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("health",    cmd_health))
    app.add_handler(CommandHandler("nodes",     cmd_nodes))
    app.add_handler(CommandHandler("tasks",     cmd_tasks))
    app.add_handler(CommandHandler("logs",      cmd_logs))
    app.add_handler(CommandHandler("earnings",  cmd_earnings))
    app.add_handler(CommandHandler("ask",       cmd_ask))
    app.add_handler(CommandHandler("chat",      cmd_chat))
    app.add_handler(CommandHandler("restart",   cmd_restart))
    app.add_handler(CommandHandler("silence",   cmd_silence))
    app.add_handler(CommandHandler("unsilence", cmd_unsilence))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def on_startup(app: Application) -> None:
        await app.bot.set_my_commands(COMMANDS)
        log.info("Bob the Conductor is online. Owner chat ID: %s", OWNER_ID)

    app.post_init = on_startup

    log.info("Starting polling loop...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
