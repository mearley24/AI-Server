#!/usr/bin/env python3
"""
notification_manager.py — Bob the Conductor Proactive Notification System

Sends structured, prioritized Telegram notifications from any part of the
Bob ecosystem. Import and call from OpenClaw hooks, cron jobs, HA automations, etc.

Usage:
    from notification_manager import NotificationManager, NotificationType, Priority

    nm = NotificationManager()
    await nm.send(
        notif_type=NotificationType.TASK_COMPLETE,
        message="Finished processing proposal for Acme Corp",
        priority=Priority.NORMAL,
    )
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, time as dtime
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import aiohttp
from dotenv import load_dotenv
from telegram import Bot, InputFile
from telegram.constants import ParseMode
from telegram.error import TelegramError

load_dotenv()

logger = logging.getLogger("bob.notifications")

# ─────────────────────────────────────────────
class Priority(Enum):
    CRITICAL = 0
    HIGH     = 1
    NORMAL   = 2
    LOW      = 3


class NotificationType(Enum):
    TASK_COMPLETE    = "task_complete"
    TASK_FAILED      = "task_failed"
    CLAWWORK_EARNINGS = "clawwork_earnings"
    CLAWWORK_PAUSED   = "clawwork_paused"
    CLAWWORK_RESUMED  = "clawwork_resumed"
    CALL_RECEIVED    = "call_received"
    CALL_MISSED      = "call_missed"
    SYSTEM_ALERT     = "system_alert"
    SYSTEM_UP        = "system_up"
    NODE_OFFLINE     = "node_offline"
    NODE_ONLINE      = "node_online"
    HEALTH_WARNING   = "health_warning"
    SECURITY_EVENT   = "security_event"
    MOTION_DETECTED  = "motion_detected"
    DAILY_DIGEST     = "daily_digest"
    WEEKLY_SUMMARY   = "weekly_summary"
    INFO             = "info"
    WARNING          = "warning"
    ERROR            = "error"


DEFAULT_PRIORITIES = {
    NotificationType.TASK_COMPLETE:     Priority.NORMAL,
    NotificationType.TASK_FAILED:       Priority.HIGH,
    NotificationType.CLAWWORK_EARNINGS: Priority.LOW,
    NotificationType.CLAWWORK_PAUSED:   Priority.NORMAL,
    NotificationType.CLAWWORK_RESUMED:  Priority.NORMAL,
    NotificationType.CALL_RECEIVED:     Priority.HIGH,
    NotificationType.CALL_MISSED:       Priority.HIGH,
    NotificationType.SYSTEM_ALERT:      Priority.CRITICAL,
    NotificationType.SYSTEM_UP:         Priority.NORMAL,
    NotificationType.NODE_OFFLINE:      Priority.CRITICAL,
    NotificationType.NODE_ONLINE:       Priority.NORMAL,
    NotificationType.HEALTH_WARNING:    Priority.HIGH,
    NotificationType.SECURITY_EVENT:    Priority.CRITICAL,
    NotificationType.MOTION_DETECTED:   Priority.HIGH,
    NotificationType.DAILY_DIGEST:      Priority.NORMAL,
    NotificationType.WEEKLY_SUMMARY:    Priority.NORMAL,
    NotificationType.INFO:              Priority.LOW,
    NotificationType.WARNING:           Priority.HIGH,
    NotificationType.ERROR:             Priority.CRITICAL,
}

TYPE_ICONS = {
    NotificationType.TASK_COMPLETE:     "✅",
    NotificationType.TASK_FAILED:       "❌",
    NotificationType.CLAWWORK_EARNINGS: "💰",
    NotificationType.CLAWWORK_PAUSED:   "⏸",
    NotificationType.CLAWWORK_RESUMED:  "▶️",
    NotificationType.CALL_RECEIVED:     "📞",
    NotificationType.CALL_MISSED:       "📵",
    NotificationType.SYSTEM_ALERT:      "🚨",
    NotificationType.SYSTEM_UP:         "🟢",
    NotificationType.NODE_OFFLINE:      "🔴",
    NotificationType.NODE_ONLINE:       "🟢",
    NotificationType.HEALTH_WARNING:    "⚠️",
    NotificationType.SECURITY_EVENT:    "🔒",
    NotificationType.MOTION_DETECTED:   "👀",
    NotificationType.DAILY_DIGEST:      "☀️",
    NotificationType.WEEKLY_SUMMARY:    "📈",
    NotificationType.INFO:              "ℹ️",
    NotificationType.WARNING:           "⚠️",
    NotificationType.ERROR:             "🔴",
}


class DedupeCache:
    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict = {}
        self.ttl = ttl_seconds

    def _key(self, notif_type: NotificationType, message: str) -> str:
        raw = f"{notif_type.value}::{message[:100]}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_duplicate(self, notif_type: NotificationType, message: str) -> bool:
        key = self._key(notif_type, message)
        now = time.time()
        if key in self._cache:
            if now - self._cache[key] < self.ttl:
                return True
        return False

    def mark_sent(self, notif_type: NotificationType, message: str):
        key = self._key(notif_type, message)
        self._cache[key] = time.time()
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items() if now - v < self.ttl}


class NotificationManager:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        owner_chat_id: Optional[int] = None,
        config_path=None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.owner_chat_id = owner_chat_id or int(os.getenv("TELEGRAM_OWNER_CHAT_ID", "0"))

        config_path = config_path or (Path(__file__).parent / "bot_config.json")
        try:
            with open(config_path) as f:
                self._config = json.load(f)
        except FileNotFoundError:
            self._config = {}

        self._quiet_start = self._parse_time(self._config.get("quiet_hours", {}).get("start", "22:00"))
        self._quiet_end   = self._parse_time(self._config.get("quiet_hours", {}).get("end",   "07:00"))
        self._quiet_enabled = self._config.get("quiet_hours", {}).get("enabled", True)
        self._dedupe = DedupeCache(ttl_seconds=self._config.get("dedupe_ttl_seconds", 300))
        self._retry_attempts = self._config.get("retry_attempts", 3)
        self._retry_delay    = self._config.get("retry_delay_seconds", 5)
        self._batch_queue: list = []
        self._bot = None

    def _get_bot(self) -> Bot:
        if not self._bot:
            self._bot = Bot(token=self.bot_token)
        return self._bot

    @staticmethod
    def _parse_time(t: str) -> dtime:
        try:
            h, m = t.split(":")
            return dtime(int(h), int(m))
        except Exception:
            return dtime(22, 0)

    def _in_quiet_hours(self) -> bool:
        if not self._quiet_enabled:
            return False
        now = datetime.now().time().replace(second=0, microsecond=0)
        qs, qe = self._quiet_start, self._quiet_end
        if qs > qe:
            return now >= qs or now < qe
        return qs <= now < qe

    def _should_suppress(self, priority: Priority) -> bool:
        if priority == Priority.CRITICAL:
            return False
        if priority == Priority.HIGH and not self._in_quiet_hours():
            return False
        if self._in_quiet_hours() and priority in (Priority.NORMAL, Priority.LOW):
            return True
        return False

    def _format_message(
        self,
        notif_type: NotificationType,
        message: str,
        priority: Priority,
        title: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> str:
        icon = TYPE_ICONS.get(notif_type, "\u2022")
        ts = datetime.now().strftime("%H:%M")
        badge = ""
        if priority == Priority.CRITICAL:
            badge = "🚨 *CRITICAL* "
        elif priority == Priority.HIGH:
            badge = "⚠️ "
        header = f"{badge}{icon} *{title}*" if title else f"{badge}{icon}"
        body = f"{header}\n{message}"
        if context:
            extras = "\n".join(f"  `{k}`: {v}" for k, v in context.items())
            body += f"\n\n{extras}"
        body += f"\n\n_Bob \u00b7 {ts}_"
        return body

    async def send(
        self,
        notif_type: NotificationType,
        message: str,
        priority: Optional[Priority] = None,
        title: Optional[str] = None,
        context: Optional[dict] = None,
        photo_bytes: Optional[bytes] = None,
        chat_id: Optional[int] = None,
        deduplicate: bool = True,
    ) -> bool:
        if not self.bot_token:
            logger.error("No bot token set — cannot send notification.")
            return False

        priority = priority or DEFAULT_PRIORITIES.get(notif_type, Priority.NORMAL)
        target_chat_id = chat_id or self.owner_chat_id

        if deduplicate and self._dedupe.is_duplicate(notif_type, message):
            logger.debug(f"Deduplicated {notif_type.value}: {message[:60]}")
            return False

        if self._should_suppress(priority):
            logger.debug(f"Suppressed during quiet hours: {notif_type.value}")
            if priority == Priority.LOW:
                self._batch_queue.append({
                    "type": notif_type, "message": message, "priority": priority,
                    "title": title, "context": context,
                })
            return False

        formatted = self._format_message(notif_type, message, priority, title, context)

        for attempt in range(1, self._retry_attempts + 1):
            try:
                bot = self._get_bot()
                if photo_bytes:
                    await bot.send_photo(
                        chat_id=target_chat_id,
                        photo=InputFile(photo_bytes, filename="snapshot.jpg"),
                        caption=formatted,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await bot.send_message(
                        chat_id=target_chat_id,
                        text=formatted,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                self._dedupe.mark_sent(notif_type, message)
                logger.info(f"Sent [{priority.name}] {notif_type.value}: {message[:80]}")
                return True
            except TelegramError as e:
                logger.warning(f"Telegram send attempt {attempt}/{self._retry_attempts} failed: {e}")
                if attempt < self._retry_attempts:
                    await asyncio.sleep(self._retry_delay * attempt)
            except Exception as e:
                logger.error(f"Unexpected error sending notification: {e}")
                break

        logger.error(f"Failed to send notification after {self._retry_attempts} attempts.")
        return False

    async def task_complete(self, task_name: str, client: Optional[str] = None, duration: Optional[str] = None):
        ctx = {}
        if client: ctx["Client"] = client
        if duration: ctx["Duration"] = duration
        await self.send(notif_type=NotificationType.TASK_COMPLETE, message=f"Finished: *{task_name}*", context=ctx if ctx else None)

    async def task_failed(self, task_name: str, error: str):
        await self.send(notif_type=NotificationType.TASK_FAILED, message=f"*{task_name}* failed", context={"Error": error}, priority=Priority.HIGH)

    async def earnings(self, amount: float, task_name: str, running_total: Optional[float] = None):
        ctx = {"Task": task_name}
        if running_total is not None: ctx["Running total"] = f"${running_total:.2f}"
        await self.send(notif_type=NotificationType.CLAWWORK_EARNINGS, message=f"Earned *${amount:.2f}*", context=ctx)

    async def call_received(self, caller: str, number: str, outcome: str):
        await self.send(notif_type=NotificationType.CALL_RECEIVED, message=f"Incoming call from *{caller}*", context={"Number": number, "Outcome": outcome}, priority=Priority.HIGH)

    async def node_offline(self, node_name: str, last_seen: Optional[str] = None):
        ctx = {}
        if last_seen: ctx["Last seen"] = last_seen
        await self.send(notif_type=NotificationType.NODE_OFFLINE, message=f"*{node_name}* is not responding", title="Node Offline", context=ctx, priority=Priority.CRITICAL)

    async def node_online(self, node_name: str):
        await self.send(notif_type=NotificationType.NODE_ONLINE, message=f"*{node_name}* is back online")

    async def health_warning(self, node: str, metric: str, value: str, threshold: str):
        await self.send(notif_type=NotificationType.HEALTH_WARNING, message=f"*{node}*: {metric} is {value} (threshold: {threshold})", title="Health Warning", context={"Node": node, metric: value})

    async def security_event(self, description: str, camera: Optional[str] = None, photo: Optional[bytes] = None):
        ctx = {}
        if camera: ctx["Camera"] = camera
        await self.send(notif_type=NotificationType.SECURITY_EVENT, message=description, title="Security Alert", context=ctx if ctx else None, priority=Priority.CRITICAL, photo_bytes=photo)

    async def motion_detected(self, camera: str, photo: Optional[bytes] = None):
        await self.send(notif_type=NotificationType.MOTION_DETECTED, message=f"Motion detected at *{camera}*", context={"Camera": camera, "Time": datetime.now().strftime("%H:%M:%S")}, photo_bytes=photo)

    async def system_alert(self, description: str, context: Optional[dict] = None):
        await self.send(notif_type=NotificationType.SYSTEM_ALERT, message=description, title="System Alert", context=context, priority=Priority.CRITICAL)

    async def send_daily_digest(self, digest_text: str):
        bot = self._get_bot()
        try:
            await bot.send_message(chat_id=self.owner_chat_id, text=digest_text, parse_mode=ParseMode.MARKDOWN)
            logger.info("Daily digest sent.")
        except TelegramError as e:
            logger.error(f"Failed to send daily digest: {e}")

    async def flush_batch(self):
        if not self._batch_queue:
            return
        logger.info(f"Flushing {len(self._batch_queue)} batched notifications.")
        summary_lines = ["📦 *Held notifications from quiet hours:*\n"]
        for item in self._batch_queue:
            icon = TYPE_ICONS.get(item["type"], "\u2022")
            summary_lines.append(f"{icon} {item['message']}")
        summary_lines.append(f"\n_Total: {len(self._batch_queue)} notifications_")
        bot = self._get_bot()
        try:
            await bot.send_message(chat_id=self.owner_chat_id, text="\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            logger.error(f"Failed to flush batch: {e}")
        finally:
            self._batch_queue.clear()


async def _cli_send(notif_type: str, message: str, priority_str: str = "NORMAL"):
    nm = NotificationManager()
    try:
        nt = NotificationType(notif_type)
    except ValueError:
        nt = NotificationType.INFO
    try:
        p = Priority[priority_str.upper()]
    except KeyError:
        p = Priority.NORMAL
    success = await nm.send(nt, message, priority=p)
    print("Sent." if success else "Failed.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python notification_manager.py <type> <message> [priority]")
        print("Types:", [t.value for t in NotificationType])
        sys.exit(1)
    asyncio.run(_cli_send(*sys.argv[1:4]))
