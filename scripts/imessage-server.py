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
    """Get live trading P&L and positions."""
    parts = []

    try:
        # Bot status
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())
        mode = "LIVE" if not status.get("platforms", {}).get("crypto", {}).get("dry_run") else "PAPER"
        parts.append(f"Mode: {mode}")
    except:
        parts.append("Mode: Unknown")

    try:
        # Strategies
        resp = urlopen("http://127.0.0.1:8430/strategies", timeout=10)
        strats = json.loads(resp.read()).get("strategies", {})
        running = [name for name, s in strats.items() if s.get("state") == "running"]
        parts.append(f"Strategies: {len(running)} running ({', '.join(running[:4])})")
    except:
        pass

    try:
        # Real Kraken balance via a helper endpoint or direct calculation
        # Hit the mission control trading API which reads paper_trades.jsonl
        resp = urlopen("http://127.0.0.1:8098/api/trading", timeout=10)
        data = json.loads(resp.read())
        total_trades = data.get("total_trades", 0)

        # Per-pair P&L
        pairs = data.get("pairs", {})
        for pair_name, info in pairs.items():
            display = info.get("display_name", pair_name)
            buys = info.get("buys", 0)
            sells = info.get("sells", 0)
            pnl = info.get("estimated_pnl", 0)
            spread = info.get("spread_capture", 0)
            parts.append(f"{display}: {buys}B/{sells}S spread=${spread:.4f} P&L=${pnl:.2f}")

        parts.append(f"Total trades: {total_trades}")
        total_pnl = data.get("total_pnl", 0)
        if total_pnl:
            parts.append(f"Total P&L: ${total_pnl:.2f}")
    except Exception as e:
        parts.append(f"P&L data unavailable: {e}")

    try:
        # Weather positions
        resp = urlopen("http://127.0.0.1:8430/weather/edges", timeout=10)
        data = json.loads(resp.read())
        edges = data.get("count", 0)
        positions = data.get("positions", 0)

        if positions > 0:
            open_pos = data.get("open_positions", [])
            total_weather_pnl = sum(p.get("unrealized_pnl", 0) for p in open_pos)
            parts.append(f"Weather: {edges} edges, {positions} positions, unrealized=${total_weather_pnl:.2f}")
    except:
        pass

    try:
        # Open orders
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        data = json.loads(resp.read())
        open_orders = data.get("open_orders", 0)
        parts.append(f"Open orders: {open_orders}")
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
        "OpenClaw": 8099,
        "Trading": 8430,
        "Email": 8092,
        "Calendar": 8094,
        "Proposals": 8091,
        "Voice": 8093,
        "Notifications": 8095,
        "D-Tools": 8096,
        "ClawWork": 8097,
        "Mission Ctrl": 8098,
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


def hourly_pnl_loop():
    """Send hourly P&L update via iMessage."""
    # Wait 5 minutes after startup before first alert
    time.sleep(300)

    while True:
        try:
            parts = []

            # Get trading data from mission control
            try:
                resp = urlopen("http://127.0.0.1:8098/api/trading", timeout=10)
                data = json.loads(resp.read())
                total_trades = data.get("total_trades", 0)
                total_pnl = data.get("total_pnl", 0)

                pairs = data.get("pairs", {})
                for pair_name, info in pairs.items():
                    display = info.get("display_name", pair_name)
                    pnl = info.get("estimated_pnl", 0)
                    if pnl != 0:
                        parts.append(f"{display}: ${pnl:.2f}")

                parts.insert(0, f"Hourly Update | {total_trades} trades")
                if total_pnl:
                    parts.append(f"Total P&L: ${total_pnl:.2f}")
            except:
                parts.append("Trading data unavailable")

            # Get real Kraken balance via bot
            try:
                resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
                status = json.loads(resp.read())
                mode = "LIVE" if not status.get("platforms", {}).get("crypto", {}).get("dry_run") else "PAPER"
                parts.append(f"Mode: {mode}")
            except:
                pass

            # Weather positions
            try:
                resp = urlopen("http://127.0.0.1:8430/weather/edges", timeout=10)
                data = json.loads(resp.read())
                positions = data.get("positions", 0)
                if positions > 0:
                    open_pos = data.get("open_positions", [])
                    weather_pnl = sum(p.get("unrealized_pnl", 0) for p in open_pos)
                    parts.append(f"Weather: {positions} pos, ${weather_pnl:.2f} unrealized")
            except:
                pass

            message = "\n".join(parts)
            if message:
                send_imessage(REPLY_TO, message)
                print(f"[hourly] Sent P&L update")

        except Exception as e:
            print(f"[hourly] Error: {e}")

        time.sleep(3600)  # Every hour


def daily_briefing_loop():
    """Send daily morning briefing at 6 AM MT."""
    from datetime import datetime

    last_briefing_date = None

    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # Only send between 6:00-6:05 AM, once per day
            if now.hour == 6 and now.minute < 5 and last_briefing_date != today:
                parts = ["Good morning. Here's your daily briefing:\n"]

                # Trading summary
                try:
                    resp = urlopen("http://127.0.0.1:8098/api/trading", timeout=10)
                    data = json.loads(resp.read())
                    total_trades = data.get("total_trades", 0)
                    total_pnl = data.get("total_pnl", 0)
                    parts.append(f"TRADING: {total_trades} trades, P&L: ${total_pnl:.2f}")

                    pairs = data.get("pairs", {})
                    for pair_name, info in pairs.items():
                        display = info.get("display_name", pair_name)
                        buys = info.get("buys", 0)
                        sells = info.get("sells", 0)
                        pnl = info.get("estimated_pnl", 0)
                        parts.append(f"  {display}: {buys}B/{sells}S P&L=${pnl:.2f}")
                except:
                    parts.append("TRADING: data unavailable")

                # Weather edges
                try:
                    resp = urlopen("http://127.0.0.1:8430/weather/edges", timeout=10)
                    data = json.loads(resp.read())
                    edges = data.get("count", 0)
                    positions = data.get("positions", 0)
                    parts.append(f"\nWEATHER: {edges} edges, {positions} positions")
                except:
                    pass

                # Email summary
                try:
                    resp = urlopen("http://127.0.0.1:8092/emails/summary", timeout=10)
                    email_data = json.loads(resp.read())
                    parts.append(f"\nEMAIL: {email_data}")
                except:
                    parts.append("\nEMAIL: unavailable")

                # Calendar
                try:
                    resp = urlopen("http://127.0.0.1:8094/calendar/today", timeout=10)
                    cal_data = json.loads(resp.read())
                    events = cal_data.get("events", [])
                    count = cal_data.get("count", 0)
                    parts.append(f"\nCALENDAR: {count} events today")
                    for e in events[:5]:
                        if isinstance(e, dict):
                            title = e.get("title", e.get("summary", str(e)))
                            parts.append(f"  • {title}")
                except:
                    parts.append("\nCALENDAR: unavailable")

                # System health
                services_up = 0
                services_total = 11
                for port in [8091, 8092, 8093, 8094, 8095, 8096, 8097, 8098, 8099, 8100, 8430]:
                    try:
                        urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
                        services_up += 1
                    except:
                        pass
                parts.append(f"\nSYSTEMS: {services_up}/{services_total} online")

                briefing = "\n".join(parts)
                send_imessage(REPLY_TO, briefing)
                print(f"[briefing] Morning briefing sent")
                last_briefing_date = today

        except Exception as e:
            print(f"[briefing] Error: {e}")

        time.sleep(60)  # Check every minute


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

    # Start hourly P&L alerts
    pnl_thread = threading.Thread(target=hourly_pnl_loop, daemon=True)
    pnl_thread.start()

    # Start daily briefing
    briefing_thread = threading.Thread(target=daily_briefing_loop, daemon=True)
    briefing_thread.start()

    # Start HTTP server for outbound notifications
    print(f"[bridge] iMessage bridge listening on port {PORT} (two-way)")
    print(f"[bridge] Listening for: {OWNER_PHONE}")
    print(f"[bridge] Replying to: {REPLY_TO}")
    print(f"[bridge] OpenClaw: {OPENCLAW_URL}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
