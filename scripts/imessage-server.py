#!/usr/bin/env python3
"""
Bob iMessage Bridge — two-way communication (v2)
Runs natively on macOS (not Docker).
- Monitors Messages.app for incoming texts from OWNER_PHONE
- Routes messages to OpenClaw API
- Sends responses back via iMessage
- Also accepts HTTP POST /notify for outbound notifications
- Rate-limited send queue prevents Apple throttling
- Retry with backoff on send failures
- Twilio SMS fallback when iMessage fails
- Twitter oEmbed for reading tweets

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
import logging
from collections import deque
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("imessage-bridge")

OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "+19705193013")
REPLY_TO = os.environ.get("REPLY_TO", OWNER_PHONE)
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:8099")
PORT = 8199

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

CHAT_DB = Path(os.environ.get(
    "IMESSAGE_DB_PATH",
    str(Path.home() / "Library" / "Messages" / "chat.db")
))
if not CHAT_DB.exists():
    CHAT_DB = Path("/Users/bob/Library/Messages/chat.db")

SEND_RETRY_COUNT = 3
SEND_RETRY_BACKOFF = [2, 4, 8]
MIN_SEND_GAP_SECONDS = 2.5


def _copy_db_to_temp() -> Path:
    """Copy live Messages DB + WAL/SHM to a unique temp dir. Returns path to temp DB."""
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
        shutil.rmtree(str(tmp_db.parent), ignore_errors=True)
    except Exception:
        pass


class MessageMonitor:
    """Monitors macOS Messages.app SQLite DB for new incoming messages."""

    def __init__(self):
        self.last_message_id = self._get_latest_message_id()
        self.owner_phone_clean = OWNER_PHONE.replace("+", "").replace("-", "").replace(" ", "")

    def _get_latest_message_id(self) -> int:
        tmp_db = None
        try:
            tmp_db = _copy_db_to_temp()
            conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True, timeout=5)
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            result = cursor.fetchone()[0] or 0
            conn.close()
            return result
        except Exception as e:
            log.error("[monitor] _get_latest_message_id error: %s", e)
            return 0
        finally:
            if tmp_db:
                _cleanup_temp(tmp_db)

    def check_new_messages(self) -> list:
        tmp_db = None
        try:
            tmp_db = _copy_db_to_temp()
            conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True, timeout=5)
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
                phone_clean = handle_id.replace("+", "").replace("-", "").replace(" ", "")
                if self.owner_phone_clean in phone_clean or phone_clean in self.owner_phone_clean:
                    messages.append({"id": rowid, "text": text, "from": handle_id})
                self.last_message_id = max(self.last_message_id, rowid)
            conn.close()
            return messages
        except Exception as e:
            log.error("[monitor] Error reading messages: %s", e)
            return []
        finally:
            if tmp_db:
                _cleanup_temp(tmp_db)


_send_failures = 0


def send_twilio_sms(address: str, message: str) -> bool:
    """Send SMS via Twilio as a last-resort fallback."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
        log.warning("[twilio] Twilio not configured — cannot fall back to SMS")
        return False

    log.info("[twilio] Falling back to Twilio SMS for %s", address)
    try:
        import base64
        url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % TWILIO_ACCOUNT_SID

        if len(message) > 1600:
            message = message[:1597] + "..."

        body = "To=%s&From=%s&Body=%s" % (
            quote(address, safe=""),
            quote(TWILIO_FROM_NUMBER, safe=""),
            quote(message, safe=""),
        )
        auth = base64.b64encode(("%s:%s" % (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)).encode()).decode()
        req = Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic %s" % auth,
            },
        )
        resp = urlopen(req, timeout=15)
        resp_data = json.loads(resp.read())
        log.info("[twilio] SMS sent (SID: %s)", resp_data.get("sid", "unknown"))
        return True
    except Exception as e:
        log.error("[twilio] SMS send failed: %s", e)
        return False


def send_imessage(address: str, message: str) -> bool:
    """Send a message via Messages.app AppleScript with retry + Twilio fallback.

    Uses the exact same AppleScript format as the original working version.
    Does NOT touch Messages.app lifecycle — no launching, no killing.
    """
    global _send_failures
    message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    if len(message) > 2000:
        message = message[:1997] + "..."

    cmd_direct = '''tell application "Messages"
set targetBuddy to buddy "%s" of (1st account whose service type = iMessage)
send "%s" to targetBuddy
end tell''' % (address, message)

    cmd_sms = '''tell application "Messages"
set targetService to 1st account whose service type = SMS
set targetBuddy to participant "%s" of targetService
send "%s" to targetBuddy
end tell''' % (address, message)

    cmd_simple = '''tell application "Messages"
send "%s" to buddy "%s"
end tell''' % (message, address)

    for attempt in range(SEND_RETRY_COUNT):
        for label, cmd in [("iMessage", cmd_direct), ("SMS", cmd_sms), ("auto", cmd_simple)]:
            try:
                result = subprocess.run(
                    ["osascript", "-e", cmd],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    _send_failures = 0
                    log.info("[send] Sent via %s to %s (attempt %d/%d)",
                             label, address, attempt + 1, SEND_RETRY_COUNT)
                    return True
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                continue

        if attempt < SEND_RETRY_COUNT - 1:
            backoff = SEND_RETRY_BACKOFF[attempt]
            log.warning("[send] All methods failed for %s (attempt %d/%d) — retrying in %ds",
                        address, attempt + 1, SEND_RETRY_COUNT, backoff)
            time.sleep(backoff)

    log.error("[send] All %d iMessage attempts failed for %s — trying Twilio",
              SEND_RETRY_COUNT, address)

    original_message = message.replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")
    if send_twilio_sms(address, original_message):
        _send_failures = 0
        return True

    _send_failures += 1
    if _send_failures <= 3:
        log.error("[send] ALL delivery methods failed for %s (iMessage + Twilio)", address)
    return False


class SendQueue:
    """Thread-safe message queue with rate limiting."""

    def __init__(self, min_gap: float = MIN_SEND_GAP_SECONDS):
        self._queue = deque()
        self._lock = threading.Lock()
        self._min_gap = min_gap
        self._last_send_time = 0.0
        self._running = True
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()
        log.info("[queue] Send queue started (min gap: %.1fs)", self._min_gap)

    def enqueue(self, address: str, message: str) -> dict:
        with self._lock:
            self._queue.append({"address": address, "message": message})
            depth = len(self._queue)
        log.info("[queue] Queued for %s (depth: %d)", address, depth)
        return {"status": "queued", "queue_depth": depth}

    def _process_loop(self):
        while self._running:
            entry = None
            with self._lock:
                if self._queue:
                    entry = self._queue.popleft()

            if entry is None:
                time.sleep(0.5)
                continue

            elapsed = time.time() - self._last_send_time
            if elapsed < self._min_gap:
                time.sleep(self._min_gap - elapsed)

            send_imessage(entry["address"], entry["message"])
            self._last_send_time = time.time()

    @property
    def depth(self):
        with self._lock:
            return len(self._queue)


send_queue = None


def _fetch_tweet_text(url: str) -> str:
    """Extract tweet text via Twitter's oEmbed API (no auth needed)."""
    import re as _re

    if not _re.search(r'(?:twitter\.com|x\.com)/.+/status/', url):
        return ""

    clean_url = _re.sub(r'[?#].*$', '', url)
    try:
        oembed_url = "https://publish.twitter.com/oembed?url=%s&omit_script=true" % quote(clean_url, safe="")
        req = Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read())

        html = data.get("html", "")
        text = _re.sub(r'<[^>]+>', ' ', html)
        text = _re.sub(r'\s+', ' ', text).strip()

        author = data.get("author_name", "")
        if author and text:
            return "Tweet by @%s: %s" % (author, text)
        return text
    except Exception as e:
        log.warning("[research] oEmbed failed for %s: %s", url, e)
        return ""


def research_link(url: str, context: str = "") -> str:
    """Fetch a URL and provide a smart, context-aware analysis."""
    import re as _re
    try:
        text = ""

        if _re.search(r'(?:twitter\.com|x\.com)/.+/status/', url):
            text = _fetch_tweet_text(url)
            if not text:
                text = "(Tweet from %s — could not fetch content)" % url
        else:
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                resp = urlopen(req, timeout=15)
                content = resp.read().decode("utf-8", errors="ignore")[:8000]
                text = _re.sub(r'<[^>]+>', ' ', content)
                text = _re.sub(r'\s+', ' ', text).strip()[:4000]
            except Exception:
                text = "(Could not fetch content from %s)" % url

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            if text:
                return "Link: %s\n\n%s" % (url, text[:500])
            return "Link: %s\nCan't analyze — no OpenAI API key." % url

        context_line = "\nAdditional context from sender: %s" % context if context else ""
        prompt = """You are Bob, an AI assistant for a smart home business owner who also runs automated trading bots.

Analyze this content and give a useful, natural response. Adapt to what the content is:
- Tweet or social media: summarize what it says and why it matters
- Trading, crypto, markets: assess relevance and actionability
- Tool, product, or project: evaluate usefulness
- News: key takeaway
- Code or technical: explain what it does

Be direct and conversational. 3-5 sentences max. No bullet points or numbered lists.
%s

Content from %s:
%s""" % (context_line, url, text[:3000])

        data = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
        }).encode()

        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % api_key},
        )
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return "Couldn't analyze link: %s" % e


def ask_openclaw(message: str) -> str:
    """Send a message to OpenClaw and get a response."""
    try:
        import re as _re
        urls = _re.findall(r'https?://[^\s<>"]+', message)
        if urls:
            context = _re.sub(r'https?://[^\s<>"]+', '', message).strip()
            results = []
            for url in urls[:2]:
                results.append(research_link(url, context))
            return "\n\n---\n\n".join(results)

        lower = message.lower()

        if any(w in lower for w in ["help", "commands", "what can you do"]):
            return "I respond to:\n\u2022 trades \u2014 live P&L + positions\n\u2022 status \u2014 all services health\n\u2022 email \u2014 inbox summary\n\u2022 calendar \u2014 today's schedule\n\u2022 weather \u2014 NOAA edges\n\u2022 help \u2014 this message\n\nAnything else, I'll think about it and respond."

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

        data = json.dumps({
            "model": "bob_conductor",
            "messages": [{"role": "user", "content": message}],
        }).encode()
        req = Request(
            "%s/api/chat/completions" % OPENCLAW_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urlopen(req, timeout=60)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return "Error processing request: %s" % e


def get_trading_status() -> str:
    """Get live Polymarket trading status."""
    parts = []

    try:
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())

        bankroll = status.get("bankroll", 0)
        parts.append("USDC Balance: $%.2f" % bankroll)

        positions = status.get("positions", [])
        if positions:
            total_value = sum(p.get("value", 0) for p in positions)
            parts.append("Open positions: %d ($%.2f)" % (len(positions), total_value))
        else:
            parts.append("Open positions: 0")

        open_orders = status.get("open_orders", 0)
        parts.append("Open orders: %s" % open_orders)

        category_pnl = status.get("category_pnl", {})
        if category_pnl:
            parts.append("Category P/L:")
            for cat, pnl in category_pnl.items():
                parts.append("  %s: $%.2f" % (cat, pnl))
            total_pnl = sum(category_pnl.values())
            parts.append("Total P/L: $%.2f" % total_pnl)

        recent_trades = status.get("recent_trades", status.get("total_trades", 0))
        if recent_trades:
            parts.append("Recent trades: %s" % recent_trades)
    except Exception as e:
        parts.append("Polymarket status unavailable: %s" % e)

    try:
        resp = urlopen("http://127.0.0.1:8430/strategies", timeout=10)
        strats = json.loads(resp.read()).get("strategies", {})
        running = [name for name, s in strats.items() if s.get("state") == "running"]
        parts.append("Strategies: %d running (%s)" % (len(running), ", ".join(running[:4])))
    except Exception:
        pass

    return "\n".join(parts) if parts else "Trading status unavailable"


def get_email_status() -> str:
    """Get email summary."""
    try:
        resp = urlopen("http://127.0.0.1:8092/emails/summary", timeout=10)
        return "Email: %s" % json.loads(resp.read())
    except Exception as e:
        return "Email status unavailable: %s" % e


def get_calendar_status() -> str:
    """Get today's calendar."""
    try:
        resp = urlopen("http://127.0.0.1:8094/calendar/today", timeout=10)
        data = json.loads(resp.read())
        events = data.get("events", [])
        if not events or (len(events) == 1 and "No events" in str(events[0])):
            return "Calendar: No events today"
        return "Calendar: %d events today\n%s" % (len(events), "\n".join(str(e) for e in events[:5]))
    except Exception as e:
        return "Calendar unavailable: %s" % e


def get_weather_status() -> str:
    """Get weather category P/L from Polymarket."""
    try:
        resp = urlopen("http://127.0.0.1:8430/status", timeout=10)
        status = json.loads(resp.read())
        category_pnl = status.get("category_pnl", {})
        weather_pnl = category_pnl.get("weather", category_pnl.get("Weather", 0))
        positions = [p for p in status.get("positions", []) if "weather" in p.get("category", "").lower()]
        parts = ["Weather positions: %d" % len(positions)]
        if weather_pnl:
            parts.append("Weather P/L: $%.2f" % weather_pnl)
        for p in positions[:5]:
            parts.append("  %s: $%.2f" % (p.get("title", p.get("market", "Unknown")), p.get("value", 0)))
        return "\n".join(parts)
    except Exception as e:
        return "Weather status unavailable: %s" % e


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
            urlopen("http://127.0.0.1:%d/health" % port, timeout=3)
            up += 1
        except Exception:
            down.append(name)

    result = "Systems: %d/%d online" % (up, len(services))
    if down:
        result += "\nDown: %s" % ", ".join(down)
    else:
        result += "\nAll services healthy"
    return result


def monitor_loop():
    """Background thread that checks for new messages every 3 seconds."""
    monitor = MessageMonitor()
    log.info("[monitor] Watching for messages from %s", OWNER_PHONE)

    while True:
        try:
            messages = monitor.check_new_messages()
            for msg in messages:
                text = msg["text"].strip()
                if not text:
                    continue

                log.info("[monitor] Received: %s", text)

                response = ask_openclaw(text)

                log.info("[monitor] Responding: %s...", response[:100])
                if send_queue:
                    send_queue.enqueue(REPLY_TO, response)
                else:
                    send_imessage(REPLY_TO, response)
        except Exception as e:
            log.error("[monitor] Error: %s", e)

        time.sleep(3)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        message = body.get("body", body.get("text", body.get("message", "")))
        title = body.get("title", "")
        phone = body.get("phone", REPLY_TO)

        full_msg = "%s: %s" % (title, message) if title else message
        if full_msg:
            if send_queue:
                result = send_queue.enqueue(phone, full_msg)
                depth = result["queue_depth"]
            else:
                send_imessage(phone, full_msg)
                depth = 0
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "queued", "queue_depth": depth}).encode())
        else:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "no message"}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "imessage-bridge",
            "mode": "two-way",
            "queue_depth": send_queue.depth if send_queue else 0,
            "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        }).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", ":%d" % PORT],
            capture_output=True, text=True, timeout=5
        )
        for pid in result.stdout.strip().split("\n"):
            pid = pid.strip()
            if pid and pid.isdigit() and int(pid) != os.getpid():
                log.info("[bridge] Killing old process on port %d: PID %s", PORT, pid)
                os.kill(int(pid), signal.SIGKILL)
        time.sleep(1)
    except Exception:
        pass

    send_queue = SendQueue()

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    log.info("[bridge] iMessage bridge listening on port %d", PORT)
    log.info("[bridge] Listening for: %s", OWNER_PHONE)
    log.info("[bridge] Replying to: %s", REPLY_TO)
    log.info("[bridge] OpenClaw: %s", OPENCLAW_URL)
    log.info("[bridge] Twilio fallback: %s", "configured" if TWILIO_ACCOUNT_SID else "not configured")

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
