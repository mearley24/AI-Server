#!/usr/bin/env python3
"""
Bob iMessage Bridge — two-way communication (bulletproof edition)
Runs natively on macOS (not Docker).
- Monitors Messages.app for incoming texts from OWNER_PHONE
- Routes messages to OpenClaw API
- Sends responses back via iMessage
- Also accepts HTTP POST /notify for outbound notifications
- Rate-limited send queue prevents Apple throttling
- Exponential backoff retry on failures
- Messages.app health check and auto-recovery
- Twilio SMS fallback when all iMessage methods fail

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
HEALTH_CHECK_INTERVAL = 60


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
        tmp_dir = tmp_db.parent
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
    except Exception:
        pass


class MessagesAppHealth:
    """Manages Messages.app lifecycle — checks health, launches, force-quits if hung."""

    def __init__(self):
        self._last_check = 0
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        try:
            result = subprocess.run(
                ["pgrep", "-x", "Messages"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def is_responsive(self) -> bool:
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Messages"'],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 and "true" in result.stdout.lower()
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def launch(self) -> bool:
        log.info("[health] Launching Messages.app...")
        try:
            subprocess.run(
                ["open", "-a", "Messages"],
                capture_output=True, text=True, timeout=10,
            )
            for _ in range(10):
                time.sleep(1)
                if self.is_running():
                    log.info("[health] Messages.app launched successfully")
                    time.sleep(2)
                    return True
            log.error("[health] Messages.app did not start within 10 seconds")
            return False
        except Exception as e:
            log.error("[health] Failed to launch Messages.app: %s", e)
            return False

    def force_quit(self):
        log.warning("[health] Force-quitting Messages.app...")
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Messages" to quit'],
                capture_output=True, text=True, timeout=5,
            )
            time.sleep(2)
        except Exception:
            pass
        try:
            subprocess.run(["pkill", "-9", "Messages"], capture_output=True, timeout=5)
            time.sleep(2)
        except Exception:
            pass

    def ensure_ready(self) -> bool:
        with self._lock:
            if self.is_running():
                if self.is_responsive():
                    return True
                log.warning("[health] Messages.app is running but unresponsive — restarting")
                self.force_quit()
                time.sleep(3)
                return self.launch()
            else:
                return self.launch()

    def periodic_check(self):
        now = time.time()
        if now - self._last_check < HEALTH_CHECK_INTERVAL:
            return
        self._last_check = now
        if not self.is_running():
            log.warning("[health] Periodic check: Messages.app not running — relaunching")
            self.launch()
        elif not self.is_responsive():
            log.warning("[health] Periodic check: Messages.app unresponsive — restarting")
            self.force_quit()
            time.sleep(3)
            self.launch()


messages_health = MessagesAppHealth()


def send_twilio_sms(address: str, message: str) -> bool:
    """Send SMS via Twilio as a last-resort fallback. Returns True on success."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
        log.warning("[twilio] Twilio credentials not configured — cannot fall back to SMS")
        return False

    log.info("[twilio] Falling back to Twilio SMS for %s", address)
    try:
        import base64
        url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % TWILIO_ACCOUNT_SID

        if len(message) > 1600:
            message = message[:1597] + "..."

        body = "To=%s&From=%s&Body=%s" % (
            _url_encode(address),
            _url_encode(TWILIO_FROM_NUMBER),
            _url_encode(message),
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
        sid = resp_data.get("sid", "unknown")
        log.info("[twilio] SMS sent successfully (SID: %s)", sid)
        return True
    except Exception as e:
        log.error("[twilio] SMS send failed: %s", e)
        return False


def _url_encode(s: str) -> str:
    """Minimal URL encoding for Twilio form body."""
    from urllib.parse import quote
    return quote(str(s), safe="")


def _try_applescript_send(address: str, message: str) -> str:
    """Try all AppleScript send strategies. Returns label of method that succeeded, or empty string."""
    cmd_direct = (
        'tell application "Messages"\n'
        'set targetBuddy to buddy "%s" of (1st account whose service type = iMessage)\n'
        'send "%s" to targetBuddy\n'
        'end tell'
    ) % (address, message)

    cmd_sms = (
        'tell application "Messages"\n'
        'set targetService to 1st account whose service type = SMS\n'
        'set targetBuddy to participant "%s" of targetService\n'
        'send "%s" to targetBuddy\n'
        'end tell'
    ) % (address, message)

    cmd_simple = (
        'tell application "Messages"\n'
        'send "%s" to buddy "%s"\n'
        'end tell'
    ) % (message, address)

    for label, cmd in [("iMessage", cmd_direct), ("SMS", cmd_sms), ("auto", cmd_simple)]:
        try:
            result = subprocess.run(
                ["osascript", "-e", cmd],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return label
            log.debug("[send] %s strategy failed: %s", label, result.stderr.strip())
        except subprocess.TimeoutExpired:
            log.warning("[send] %s strategy timed out", label)
        except Exception as e:
            log.warning("[send] %s strategy error: %s", label, e)

    return ""


def send_imessage(address: str, message: str) -> bool:
    """Send a message via Messages.app with retry + backoff + Twilio fallback.

    Returns True if the message was delivered by any method.
    """
    message = message.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    if len(message) > 2000:
        message = message[:1997] + "..."

    for attempt in range(SEND_RETRY_COUNT):
        messages_health.ensure_ready()

        label = _try_applescript_send(address, message)
        if label:
            log.info("[send] Sent via %s to %s (attempt %d/%d)",
                     label, address, attempt + 1, SEND_RETRY_COUNT)
            return True

        if attempt < SEND_RETRY_COUNT - 1:
            backoff = SEND_RETRY_BACKOFF[attempt]
            log.warning(
                "[send] All AppleScript methods failed for %s (attempt %d/%d) — retrying in %ds",
                address, attempt + 1, SEND_RETRY_COUNT, backoff,
            )
            messages_health.force_quit()
            time.sleep(backoff)
            messages_health.launch()
            time.sleep(2)

    log.error(
        "[send] All %d iMessage retry attempts exhausted for %s — trying Twilio SMS fallback",
        SEND_RETRY_COUNT, address,
    )

    original_message = message.replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")
    if send_twilio_sms(address, original_message):
        return True

    log.error("[send] ALL delivery methods failed for %s (iMessage + Twilio)", address)
    return False


class SendQueue:
    """Thread-safe message queue with rate limiting to prevent Apple throttling."""

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
            entry = {
                "address": address,
                "message": message,
                "queued_at": datetime.now().isoformat(),
            }
            self._queue.append(entry)
            depth = len(self._queue)
        log.info("[queue] Message queued for %s (queue depth: %d)", address, depth)
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
                wait = self._min_gap - elapsed
                log.info("[queue] Rate limiting — waiting %.1fs before next send", wait)
                time.sleep(wait)

            with self._lock:
                depth = len(self._queue)
            log.info("[queue] Processing send to %s (remaining: %d)", entry["address"], depth)

            success = send_imessage(entry["address"], entry["message"])
            self._last_send_time = time.time()

            if success:
                log.info("[queue] Delivered to %s", entry["address"])
            else:
                log.error("[queue] Failed to deliver to %s", entry["address"])

    def get_status(self) -> dict:
        with self._lock:
            return {
                "queue_depth": len(self._queue),
                "last_send": datetime.fromtimestamp(self._last_send_time).isoformat() if self._last_send_time else None,
            }


send_queue = SendQueue()


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


def research_link(url: str, context: str = "") -> str:
    """Fetch a URL and analyze it for trading profitability insights."""
    import re as _re
    try:
        from urllib.request import Request as _Req, urlopen as _urlopen
        headers = {"User-Agent": "Mozilla/5.0"}
        req = _Req(url, headers=headers)
        resp = _urlopen(req, timeout=15)
        content = resp.read().decode("utf-8", errors="ignore")[:8000]

        text = _re.sub(r'<[^>]+>', ' ', content)
        text = _re.sub(r'\s+', ' ', text).strip()[:4000]

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

        bankroll = status.get("bankroll", 0)
        parts.append(f"USDC Balance: ${bankroll:.2f}")

        positions = status.get("positions", [])
        if positions:
            total_value = sum(p.get("value", 0) for p in positions)
            parts.append(f"Open positions: {len(positions)} (${total_value:.2f})")
        else:
            parts.append("Open positions: 0")

        open_orders = status.get("open_orders", 0)
        parts.append(f"Open orders: {open_orders}")

        category_pnl = status.get("category_pnl", {})
        if category_pnl:
            parts.append("Category P/L:")
            for cat, pnl in category_pnl.items():
                parts.append(f"  {cat}: ${pnl:.2f}")
            total_pnl = sum(category_pnl.values())
            parts.append(f"Total P/L: ${total_pnl:.2f}")

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


def monitor_loop():
    """Background thread that checks for new messages every 3 seconds."""
    monitor = MessageMonitor()
    log.info("[monitor] Watching for messages from %s", OWNER_PHONE)

    while True:
        try:
            messages_health.periodic_check()

            messages = monitor.check_new_messages()
            for msg in messages:
                text = msg["text"].strip()
                if not text:
                    continue

                log.info("[monitor] Received: %s", text)

                response = ask_openclaw(text)

                log.info("[monitor] Responding: %s...", response[:100])
                send_queue.enqueue(REPLY_TO, response)
        except Exception as e:
            log.error("[monitor] Error: %s", e)

        time.sleep(3)


def health_check_loop():
    """Background thread for periodic Messages.app health checks."""
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        try:
            messages_health.periodic_check()
            queue_status = send_queue.get_status()
            log.info("[health] Messages.app: running=%s | Queue depth: %d | Last send: %s",
                     messages_health.is_running(),
                     queue_status["queue_depth"],
                     queue_status["last_send"] or "never")
        except Exception as e:
            log.error("[health] Health check error: %s", e)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        message = body.get("body", body.get("text", body.get("message", "")))
        title = body.get("title", "")
        phone = body.get("phone", REPLY_TO)

        full_msg = f"{title}: {message}" if title else message
        if full_msg:
            queue_result = send_queue.enqueue(phone, full_msg)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "queued",
                "via": "imessage-queue",
                "queue_depth": queue_result["queue_depth"],
            }).encode())
        else:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "no message"}).encode())

    def do_GET(self):
        queue_status = send_queue.get_status()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "imessage-bridge",
            "mode": "two-way",
            "messages_app_running": messages_health.is_running(),
            "queue_depth": queue_status["queue_depth"],
            "last_send": queue_status["last_send"],
            "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        }).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{PORT}"],
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

    messages_health.ensure_ready()

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    health_thread = threading.Thread(target=health_check_loop, daemon=True)
    health_thread.start()

    log.info("[bridge] iMessage bridge listening on port %d (two-way, bulletproof)", PORT)
    log.info("[bridge] Listening for: %s", OWNER_PHONE)
    log.info("[bridge] Replying to: %s", REPLY_TO)
    log.info("[bridge] OpenClaw: %s", OPENCLAW_URL)
    log.info("[bridge] Twilio fallback: %s", "configured" if TWILIO_ACCOUNT_SID else "not configured")
    log.info("[bridge] Send queue min gap: %.1fs | Retry attempts: %d | Backoff: %s",
             MIN_SEND_GAP_SECONDS, SEND_RETRY_COUNT, SEND_RETRY_BACKOFF)

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
