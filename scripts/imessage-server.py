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
import shutil
import tempfile
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "+19705193013")
REPLY_TO = os.environ.get("REPLY_TO", OWNER_PHONE)
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:8099")
PORT = 8199

# Path to the Messages chat database on macOS
# Use env var if set, otherwise Path.home(), with hardcoded fallback for launchd/tmux
CHAT_DB = Path(os.environ.get(
    "IMESSAGE_DB_PATH",
    str(Path.home() / "Library" / "Messages" / "chat.db")
))
if not CHAT_DB.exists():
    CHAT_DB = Path("/Users/bob/Library/Messages/chat.db")

def _copy_db_to_temp() -> Path:
    """Copy live Messages DB + WAL/SHM to a unique temp dir. Returns path to temp DB. Raises on failure."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="imsg_"))
    tmp_db = tmp_dir / "chat.db"
    shutil.copy2(str(CHAT_DB), str(tmp_db))
    wal = CHAT_DB.parent / "chat.db-wal"
    shm = CHAT_DB.parent / "chat.db-shm"
    if wal.exists():
        shutil.copy2(str(wal), str(tmp_dir / "chat.db-wal"))
    if shm.exists():
        shutil.copy2(str(shm), str(tmp_dir / "chat.db-shm"))
    return tmp_db


def _cleanup_temp(tmp_db: Path):
    """Remove the temp directory after use."""
    try:
        tmp_dir = tmp_db.parent
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
    except Exception:
        pass


class MessageMonitor:
    """Monitors macOS Messages.app SQLite DB for new incoming messages."""

    def __init__(self):
        self.last_message_id = self._get_latest_message_id()
        self.owner_phone_clean = OWNER_PHONE.replace("+", "").replace("-", "").replace(" ", "")

    def _get_latest_message_id(self) -> int:
        """Get the highest ROWID from the message table."""
        tmp_db = None
        try:
            tmp_db = _copy_db_to_temp()
            conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True, timeout=5)
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            result = cursor.fetchone()[0] or 0
            conn.close()
            return result
        except Exception as e:
            print(f"[monitor] _get_latest_message_id error: {e}")
            return 0
        finally:
            if tmp_db:
                _cleanup_temp(tmp_db)

    def check_new_messages(self) -> list:
        """Check for new messages from the owner since last check."""
        tmp_db = None
        try:
            tmp_db = _copy_db_to_temp()
            conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True, timeout=5)
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
        finally:
            if tmp_db:
                _cleanup_temp(tmp_db)


# Track consecutive send failures to avoid log spam
_send_failures = 0
_MAX_SPAM_ERRORS = 3


def send_imessage(address: str, message: str):
    """Send a message via Messages.app AppleScript.

    Tries iMessage first, falls back to SMS, then direct buddy send.
    Suppresses repeated error logs after _MAX_SPAM_ERRORS consecutive failures.
    """
    global _send_failures
    message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    if len(message) > 2000:
        message = message[:1997] + "..."

    # Strategy 1: Direct send to buddy (most compatible — works with any service)
    cmd_direct = '''tell application "Messages"
set targetBuddy to buddy "%s" of (1st account whose service type = iMessage)
send "%s" to targetBuddy
end tell''' % (address, message)

    # Strategy 2: SMS fallback
    cmd_sms = '''tell application "Messages"
set targetService to 1st account whose service type = SMS
set targetBuddy to participant "%s" of targetService
send "%s" to targetBuddy
end tell''' % (address, message)

    # Strategy 3: Just send to the address (let Messages.app figure it out)
    cmd_simple = '''tell application "Messages"
send "%s" to buddy "%s"
end tell''' % (message, address)

    for label, cmd in [("iMessage", cmd_direct), ("SMS", cmd_sms), ("auto", cmd_simple)]:
        try:
            result = subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                _send_failures = 0
                print(f"[send] Sent via {label} to {address}")
                return
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            continue

    # All strategies failed
    _send_failures += 1
    if _send_failures <= _MAX_SPAM_ERRORS:
        print(f"[send] All send methods failed for {address} (attempt {_send_failures})")
        print(f"[send] Check: Messages.app open? Apple ID signed in? iMessage enabled?")
    elif _send_failures == _MAX_SPAM_ERRORS + 1:
        print(f"[send] Suppressing further send errors until a send succeeds.")


def research_link(url: str, context: str = "") -> str:
    """Fetch a URL and analyze it for trading profitability insights."""
    import re as _re
    try:
        from urllib.request import Request as _Req, urlopen as _urlopen
        # Fetch the page
        headers = {"User-Agent": "Mozilla/5.0"}
        req = _Req(url, headers=headers)
        resp = _urlopen(req, timeout=15)
        content = resp.read().decode("utf-8", errors="ignore")[:8000]

        # Strip HTML tags for a rough text extraction
        text = _re.sub(r'<[^>]+>', ' ', content)
        text = _re.sub(r'\s+', ' ', text).strip()[:4000]

        # Send to OpenAI for analysis
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return f"Link: {url}\nCan't analyze — no OpenAI API key configured."

        import json as _json
        prompt = f"""Analyze this content for a Polymarket prediction market copy-trader.
The bot copies high win-rate wallets on Polymarket. We need to know:

1. SUMMARY (2 sentences max)
2. PROS — how could this improve our trading profits?
3. CONS — risks or downsides
4. ACTION — specific steps to implement (if applicable)

Keep it short and direct. No fluff.

User context: {context}

Content from {url}:
{text[:3000]}"""

        data = _json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }).encode()
        req = _Req(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        resp = _urlopen(req, timeout=30)
        result = _json.loads(resp.read())
        analysis = result["choices"][0]["message"]["content"]
        return analysis
    except Exception as e:
        return f"Couldn't analyze link: {e}"


def ask_openclaw(message: str) -> str:
    """Send a message to OpenClaw and get a response."""
    try:
        # Check for URLs first — research any links sent
        import re as _re
        urls = _re.findall(r'https?://[^\s<>"]+', message)
        if urls:
            # Strip the URL from the message to get context
            context = _re.sub(r'https?://[^\s<>"]+', '', message).strip()
            results = []
            for url in urls[:2]:  # max 2 links per message
                results.append(research_link(url, context))
            return "\n\n---\n\n".join(results)

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
    # Kill any existing process on our port before starting
    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{PORT}"],
            capture_output=True, text=True, timeout=5
        )
        for pid in result.stdout.strip().split("\n"):
            pid = pid.strip()
            if pid and pid.isdigit() and int(pid) != os.getpid():
                print(f"[bridge] Killing old process on port {PORT}: PID {pid}")
                os.kill(int(pid), signal.SIGKILL)
        time.sleep(1)
    except Exception:
        pass

    # Start message monitoring in background thread
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    # Start HTTP server for outbound notifications
    print(f"[bridge] iMessage bridge listening on port {PORT} (two-way)")
    print(f"[bridge] Listening for: {OWNER_PHONE}")
    print(f"[bridge] Replying to: {REPLY_TO}")
    print(f"[bridge] OpenClaw: {OPENCLAW_URL}")

    import socket
    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True
        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            super().server_bind()

    server = ReusableHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
