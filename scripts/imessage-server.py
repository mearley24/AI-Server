#!/usr/bin/env python3
"""
Bob iMessage Bridge — two-way communication
Runs natively on macOS (not Docker).
- Monitors Messages.app for incoming texts from OWNER_PHONE
- Routes messages to OpenClaw API
- Sends responses back via iMessage
- Also accepts HTTP POST /notify for outbound notifications

Requirements:
- macOS Full Disk Access for Terminal/python3 (System Settings > Privacy & Security)
- SQLite read is read-only (mode=ro) — cannot corrupt Messages database
- Messages from anyone other than OWNER_PHONE are ignored
"""

import subprocess
import json
import time
import threading
import sqlite3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "+19705193013")
REPLY_TO = os.environ.get("REPLY_TO", OWNER_PHONE)
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:8099")
PORT = 8199

# Path to the Messages chat database on macOS
CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


class MessageMonitor:
    """Monitors macOS Messages.app SQLite DB for new incoming messages."""

    def __init__(self):
        self.last_message_id = self._get_latest_message_id()
        self.owner_phone_clean = OWNER_PHONE.replace("+", "").replace("-", "").replace(" ", "")

    def _get_latest_message_id(self) -> int:
        """Get the highest ROWID from the message table."""
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            result = cursor.fetchone()[0] or 0
            conn.close()
            return result
        except Exception:
            return 0

    def check_new_messages(self) -> list:
        """Check for new messages from the owner since last check."""
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            # Query for new messages from the owner's phone number
            # is_from_me = 0 means incoming message
            query = """
                SELECT m.ROWID, m.text, m.date, h.id
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                AND m.is_from_me = 0
                AND m.text IS NOT NULL
                AND m.text != ''
                ORDER BY m.ROWID ASC
            """
            cursor = conn.execute(query, (self.last_message_id,))
            messages = []
            for row in cursor:
                rowid, text, date, handle_id = row
                # Check if this is from the owner (match phone number)
                phone_clean = handle_id.replace("+", "").replace("-", "").replace(" ", "")
                if self.owner_phone_clean in phone_clean or phone_clean in self.owner_phone_clean:
                    messages.append({"id": rowid, "text": text, "from": handle_id})
                self.last_message_id = max(self.last_message_id, rowid)
            conn.close()
            return messages
        except Exception as e:
            print(f"[monitor] Error reading messages: {e}")
            return []


def send_imessage(phone: str, message: str):
    """Send an iMessage via AppleScript."""
    # Escape special characters for AppleScript
    message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    # Truncate long messages (iMessage has limits)
    if len(message) > 2000:
        message = message[:1997] + "..."
    cmd = f'tell application "Messages" to send "{message}" to buddy "{phone}"'
    subprocess.run(["osascript", "-e", cmd], capture_output=True, timeout=10)


def ask_openclaw(message: str) -> str:
    """Send a message to OpenClaw and get a response."""
    try:
        # Direct service queries (skip LLM, just call the API)
        lower = message.lower()

        if any(w in lower for w in ["trade", "trading", "p&l", "pnl", "profit", "balance", "portfolio"]):
            return get_trading_status()

        if any(w in lower for w in ["email", "inbox", "mail"]):
            return get_email_status()

        if any(w in lower for w in ["calendar", "schedule", "meeting"]):
            return get_calendar_status()

        if any(w in lower for w in ["weather", "edge", "noaa"]):
            return get_weather_status()

        if any(w in lower for w in ["status", "health", "services"]):
            return get_system_status()

        # For everything else, route to OpenClaw's Bob Conductor
        data = json.dumps({
            "model": "bob_conductor",
            "messages": [{"role": "user", "content": message}],
        }).encode()
        req = Request(
            f"{OPENCLAW_URL}/api/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urlopen(req, timeout=60)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error processing request: {e}"


def get_trading_status() -> str:
    """Get live trading P&L from Kraken via the bot API."""
    try:
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())

        resp2 = urlopen("http://127.0.0.1:8430/strategies", timeout=10)
        strats = json.loads(resp2.read())

        mode = "LIVE" if not status.get("platforms", {}).get("crypto", {}).get("dry_run") else "PAPER"
        active = sum(1 for s in strats.get("strategies", {}).values() if s.get("state") == "running")
        total = len(strats.get("strategies", {}))

        try:
            resp3 = urlopen("http://127.0.0.1:8430/weather/edges", timeout=10)
            edges = json.loads(resp3.read())
            positions = edges.get("positions", 0)
        except Exception:
            positions = 0

        return (
            f"Trading: {mode} mode\n"
            f"{active}/{total} strategies running\n"
            f"Weather positions: {positions}\n"
            f"Platforms: Polymarket, Kalshi, Kraken"
        )
    except Exception as e:
        return f"Trading status unavailable: {e}"


def get_email_status() -> str:
    """Get email summary."""
    try:
        resp = urlopen("http://127.0.0.1:8092/emails/summary", timeout=10)
        return f"Email: {json.loads(resp.read())}"
    except Exception as e:
        return f"Email status unavailable: {e}"


def get_calendar_status() -> str:
    """Get today's calendar."""
    try:
        resp = urlopen("http://127.0.0.1:8094/calendar/today", timeout=10)
        data = json.loads(resp.read())
        events = data.get("events", [])
        if not events or (len(events) == 1 and "No events" in str(events[0])):
            return "Calendar: No events today"
        return f"Calendar: {len(events)} events today\n" + "\n".join(str(e) for e in events[:5])
    except Exception as e:
        return f"Calendar unavailable: {e}"


def get_weather_status() -> str:
    """Get weather edges."""
    try:
        resp = urlopen("http://127.0.0.1:8430/weather/edges", timeout=10)
        data = json.loads(resp.read())
        edges = data.get("edges", [])
        positions = data.get("positions", 0)
        return f"Weather: {len(edges)} edges found, {positions} open positions"
    except Exception as e:
        return f"Weather unavailable: {e}"


def get_system_status() -> str:
    """Check health of all services."""
    services = {
        "OpenClaw": "http://127.0.0.1:8099/health",
        "Trading": "http://127.0.0.1:8430/health",
        "Email": "http://127.0.0.1:8092/health",
        "Calendar": "http://127.0.0.1:8094/health",
        "Proposals": "http://127.0.0.1:8091/health",
        "Voice": "http://127.0.0.1:8093/health",
        "Notifications": "http://127.0.0.1:8095/health",
        "D-Tools": "http://127.0.0.1:8096/health",
        "ClawWork": "http://127.0.0.1:8097/health",
        "Mission Control": "http://127.0.0.1:8098/health",
        "Knowledge": "http://127.0.0.1:8100/health",
    }
    results = []
    up = 0
    for name, url in services.items():
        try:
            urlopen(url, timeout=5)
            up += 1
        except Exception:
            results.append(f"  {name}: DOWN")

    return f"Systems: {up}/{len(services)} online" + ("\n" + "\n".join(results) if results else "\nAll services healthy")


# Monitoring loop
def monitor_loop():
    """Background thread that checks for new messages every 3 seconds."""
    monitor = MessageMonitor()
    print(f"[monitor] Watching for messages from {OWNER_PHONE}")

    while True:
        try:
            messages = monitor.check_new_messages()
            for msg in messages:
                text = msg["text"].strip()
                if not text:
                    continue

                print(f"[monitor] Received: {text}")

                # Get response from Bob
                response = ask_openclaw(text)

                # Send response via iMessage
                print(f"[monitor] Responding: {response[:100]}...")
                send_imessage(REPLY_TO, response)
        except Exception as e:
            print(f"[monitor] Error: {e}")

        time.sleep(3)


# HTTP server for outbound notifications (Docker services call this)
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        message = body.get("body", body.get("text", body.get("message", "")))
        title = body.get("title", "")
        phone = body.get("phone", REPLY_TO)

        full_msg = f"{title}: {message}" if title else message
        if full_msg:
            send_imessage(phone, full_msg)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "sent", "via": "imessage"}).encode())
        else:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "no message"}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "imessage-bridge", "mode": "two-way"}).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    # Start message monitoring in background thread
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    # Start HTTP server for outbound notifications
    print(f"[bridge] iMessage bridge listening on port {PORT} (two-way)")
    print(f"[bridge] Listening for: {OWNER_PHONE}")
    print(f"[bridge] Replying to: {REPLY_TO}")
    print(f"[bridge] OpenClaw: {OPENCLAW_URL}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
