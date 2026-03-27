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


def send_imessage(address: str, message: str):
    """Send an iMessage via AppleScript."""
    message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    if len(message) > 2000:
        message = message[:1997] + "..."

    cmd = '''tell application "Messages"
set targetService to 1st account whose service type = iMessage
set targetBuddy to participant "%s" of targetService
send "%s" to targetBuddy
end tell''' % (address, message)

    result = subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        print(f"[send] AppleScript error: {result.stderr}")
    else:
        print(f"[send] Sent to {address}")


def ask_openclaw(message: str) -> str:
    """Send a message to OpenClaw and get a response."""
    try:
        # Direct service queries (skip LLM, just call the API)
        lower = message.lower()

        if any(w in lower for w in ["help", "commands", "what can you do"]):
            return "I respond to:\n• trades — live P&L + positions\n• status — all services health\n• email — inbox summary\n• calendar — today's schedule\n• weather — NOAA edges\n• help — this message\n\nAnything else, I'll think about it and respond."

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
    """Get live Polymarket trading status."""
    parts = []

    try:
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())

        # Bankroll / USDC balance
        bankroll = status.get("bankroll", 0)
        parts.append(f"USDC Balance: ${bankroll:.2f}")

        # Positions
        positions = status.get("positions", [])
        if positions:
            total_value = sum(p.get("value", 0) for p in positions)
            parts.append(f"Open positions: {len(positions)} (${total_value:.2f})")
        else:
            parts.append("Open positions: 0")

        # Open orders
        open_orders = status.get("open_orders", 0)
        parts.append(f"Open orders: {open_orders}")

        # Category P/L breakdown
        category_pnl = status.get("category_pnl", {})
        if category_pnl:
            parts.append("Category P/L:")
            for cat, pnl in category_pnl.items():
                parts.append(f"  {cat}: ${pnl:.2f}")
            total_pnl = sum(category_pnl.values())
            parts.append(f"Total P/L: ${total_pnl:.2f}")

        # Recent trades
        recent_trades = status.get("recent_trades", status.get("total_trades", 0))
        if recent_trades:
            parts.append(f"Recent trades: {recent_trades}")
    except Exception as e:
        parts.append(f"Polymarket status unavailable: {e}")

    try:
        resp = urlopen("http://127.0.0.1:8430/strategies", timeout=10)
        strats = json.loads(resp.read()).get("strategies", {})
        running = [name for name, s in strats.items() if s.get("state") == "running"]
        parts.append(f"Strategies: {len(running)} running ({', '.join(running[:4])})")
    except:
        pass

    return "\n".join(parts) if parts else "Trading status unavailable"


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
    """Get weather category P/L from Polymarket."""
    try:
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())
        category_pnl = status.get("category_pnl", {})
        weather_pnl = category_pnl.get("weather", category_pnl.get("Weather", 0))
        positions = [p for p in status.get("positions", []) if "weather" in p.get("category", "").lower()]
        parts = [f"Weather positions: {len(positions)}"]
        if weather_pnl:
            parts.append(f"Weather P/L: ${weather_pnl:.2f}")
        for p in positions[:5]:
            parts.append(f"  {p.get('title', p.get('market', 'Unknown'))}: ${p.get('value', 0):.2f}")
        return "\n".join(parts)
    except Exception as e:
        return f"Weather status unavailable: {e}"


def get_system_status() -> str:
    """Check health of all services."""
    services = {
        "OpenClaw": 8099,
        "Trading": 8430,
        "Email": 8092,
        "Calendar": 8094,
        "Proposals": 8091,
        "Voice": 8093,
        "Notifications": 8095,
        "D-Tools": 8096,
        "ClawWork": 8097,
        "Knowledge": 8100,
    }
    up = 0
    down = []
    for name, port in services.items():
        try:
            urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
            up += 1
        except:
            down.append(name)

    result = f"Systems: {up}/{len(services)} online"
    if down:
        result += f"\nDown: {', '.join(down)}"
    else:
        result += "\nAll services healthy"
    return result


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
