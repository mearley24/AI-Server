#!/Users/bob/AI-Server/.venv/bin/python3
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
import sys
import logging
from collections import deque
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.parse import quote

import re as _re
import redis as _redis_lib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("imessage-bridge")

OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "+19705193013")
OWNER_HANDLES = os.environ.get("OWNER_HANDLES", "").split(",")
OWNER_HANDLES = [h.strip() for h in OWNER_HANDLES if h.strip()]
OWNER_HANDLES.append(OWNER_PHONE)
OWNER_HANDLES.append("mearley24@me.com")
OWNER_HANDLES.append("+16074259277")
REPLY_TO = os.environ.get("REPLY_TO", "+19705193013")
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:8099")
PORT = 8199


def _load_repo_env():
    """Load AI-Server/.env for keys not already set (e.g. APPROVAL_BRIDGE_SECRET for /internal/approval)."""
    root = Path(__file__).resolve().parent.parent / ".env"
    if not root.exists():
        return
    try:
        for line in root.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_repo_env()

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434")


def _ollama_completion(prompt: str, model: str = "qwen3:8b") -> Optional[str]:
    """Local LLM completion via Ollama (/api/chat)."""
    try:
        url = "%s/api/chat" % OLLAMA_HOST.rstrip("/")
        data = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 400},
        }).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
        return payload.get("message", {}).get("content", "") or None
    except Exception as e:
        log.info("[ollama] Failed: %s", str(e)[:100])
        return None

# Redis publish for downstream consumers (e.g. Docker x-intake on events:imessage)
#
# The bridge runs on the host under launchd. The repo .env defines REDIS_URL as
# `redis://:<password>@redis:6379/0` because that's what the Docker services need.
# On the host, the `redis` DNS alias does not resolve (NXDOMAIN / gaierror), so
# redis-py surfaces the failure as `Authentication required.` and we silently
# drop every publish to `events:imessage` — which is exactly the regression
# that broke iMessage → x-intake for every X link in the log.
#
# _host_redis_url() rewrites the Docker-network hostname to the published
# loopback port (`@redis:` → `@127.0.0.1:`, `://redis:` → `://127.0.0.1:`) when
# the bridge is running on the host. The password, port, and db path are
# preserved — no secrets or env vars are touched.
def _host_redis_url(raw_url: str) -> str:
    """Rewrite a Docker-network REDIS_URL to the host-reachable equivalent.

    The Docker service alias `redis` does not resolve on the host where
    `scripts/imessage-server.py` runs under launchd. The `redis` container
    publishes 127.0.0.1:6379 on the host, so swap the hostname while keeping
    the auth, port, and db path intact.
    """
    if not raw_url:
        return raw_url
    rewritten = raw_url.replace("@redis:", "@127.0.0.1:")
    if rewritten == raw_url:
        rewritten = raw_url.replace("://redis:", "://127.0.0.1:")
    return rewritten


_REDIS_URL = _host_redis_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"))
_redis_pub = None


def _get_redis_pub():
    global _redis_pub
    if _redis_pub is None:
        try:
            _redis_pub = _redis_lib.from_url(_REDIS_URL, decode_responses=True)
            _redis_pub.ping()
            log.info("[redis] Connected for publish (url host=%s)", _REDIS_URL.rsplit("@", 1)[-1])
        except Exception as e:
            log.warning("[redis] Publish connection failed: %s", e)
            _redis_pub = None
    return _redis_pub


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
        self.owner_handles_clean = set()
        for h in OWNER_HANDLES:
            self.owner_handles_clean.add(h.lower().strip())
            cleaned = h.replace("+", "").replace("-", "").replace(" ", "").lower().strip()
            if cleaned:
                self.owner_handles_clean.add(cleaned)

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
                handle_lower = handle_id.lower().strip()
                handle_clean = handle_id.replace("+", "").replace("-", "").replace(" ", "").lower().strip()
                is_match = (handle_lower in self.owner_handles_clean
                            or handle_clean in self.owner_handles_clean)
                log.info("[monitor] DB row %d: handle=%s match=%s text=%s",
                         rowid, handle_id, is_match, (text or "")[:50])
                if is_match:
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


def _cleanup_msg_file(path: str):
    try:
        os.remove(path)
    except Exception:
        pass


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

    Writes message to a temp file and has AppleScript read it, avoiding
    all string escaping issues with smart quotes, Unicode, etc.
    """
    global _send_failures
    if len(message) > 2000:
        message = message[:1997] + "..."

    tmp_file = os.path.join(tempfile.gettempdir(), "bob_msg_%d.txt" % os.getpid())
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(message)
    except Exception as e:
        log.error("[send] Failed to write temp file: %s", e)
        return False

    cmd_direct = """set msgText to (read POSIX file "%s" as «class utf8»)
tell application "Messages"
set targetBuddy to buddy "%s" of (1st account whose service type = iMessage)
send msgText to targetBuddy
end tell""" % (tmp_file, address)

    cmd_sms = """set msgText to (read POSIX file "%s" as «class utf8»)
tell application "Messages"
set targetService to 1st account whose service type = SMS
set targetBuddy to participant "%s" of targetService
send msgText to targetBuddy
end tell""" % (tmp_file, address)

    cmd_simple = """set msgText to (read POSIX file "%s" as «class utf8»)
tell application "Messages"
send msgText to buddy "%s"
end tell""" % (tmp_file, address)

    log.info("[send] Attempting to send to: %s", address)
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
                    _cleanup_msg_file(tmp_file)
                    return True
                log.warning("[send] %s failed (rc=%d): %s",
                            label, result.returncode, result.stderr.strip()[:200])
            except subprocess.TimeoutExpired:
                log.warning("[send] %s timed out", label)
            except Exception as e:
                log.warning("[send] %s error: %s", label, e)

        if attempt < SEND_RETRY_COUNT - 1:
            backoff = SEND_RETRY_BACKOFF[attempt]
            log.warning("[send] All methods failed for %s (attempt %d/%d) — retrying in %ds",
                        address, attempt + 1, SEND_RETRY_COUNT, backoff)
            time.sleep(backoff)

    log.error("[send] All %d iMessage attempts failed for %s — trying Twilio",
              SEND_RETRY_COUNT, address)

    if send_twilio_sms(address, message):
        _send_failures = 0
        _cleanup_msg_file(tmp_file)
        return True

    _send_failures += 1
    if _send_failures <= 3:
        log.error("[send] ALL delivery methods failed for %s (iMessage + Twilio)", address)
    _cleanup_msg_file(tmp_file)
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
    """Fetch a URL and provide a smart, context-aware analysis.
    
    For X/Twitter posts with video, downloads and transcribes the video
    using the video_transcriber module for deep analysis with emoji flags.
    """
    try:
        text = ""

        if _re.search(r'(?:twitter\.com|x\.com)/.+/status/', url):
            # Try video transcription first
            try:
                import sys as _sys
                _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'integrations', 'x_intake'))
                from video_transcriber import process_x_video
                # Extract author from URL
                author_match = _re.search(r'(?:twitter\.com|x\.com)/([^/]+)/status/', url)
                author = author_match.group(1) if author_match else ""
                result = process_x_video(
                    url,
                    author=author,
                    post_text=context,
                    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                )
                if "error" not in result and result.get("summary"):
                    log.info("[research] Video transcribed for %s", url)
                    return result["summary"]
            except Exception as ve:
                log.info("[research] Video transcription unavailable (%s), falling back to text", ve)

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

        result = _ollama_completion(prompt)
        if result:
            return result

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            if text:
                return "Link: %s\n\n%s" % (url, text[:500])
            return "Link: %s\nCan't analyze — Ollama is down and no OpenAI API key." % url

        log.warning("[research] Ollama unavailable — falling back to OpenAI")
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


def get_proposals() -> str:
    """List proposals from knowledge base."""
    try:
        resp = urlopen("%s/knowledge/proposals" % OPENCLAW_URL, timeout=10)
        data = json.loads(resp.read())
        proposals = data.get("proposals", [])
        if not proposals:
            return "No proposals found in the knowledge base."
        parts = ["Proposals (%d):" % len(proposals)]
        for p in proposals[:10]:
            size_kb = p.get("size_bytes", 0) / 1024
            parts.append("  %s (%.0f KB, modified %s)" % (
                p.get("filename", "?"), size_kb, p.get("modified_at", "?")[:10]
            ))
        return "\n".join(parts)
    except Exception as e:
        return "Proposals unavailable: %s" % e


def get_manuals() -> str:
    """List available manuals from knowledge base."""
    try:
        resp = urlopen("%s/knowledge/manuals" % OPENCLAW_URL, timeout=10)
        data = json.loads(resp.read())
        manuals = data.get("manuals", [])
        if not manuals:
            return "No manuals found in the knowledge base."
        parts = ["Manuals (%d):" % len(manuals)]
        for m in manuals[:10]:
            parts.append("  %s (%s)" % (m.get("filename", "?"), m.get("tags", "")))
        return "\n".join(parts)
    except Exception as e:
        return "Manuals unavailable: %s" % e


def get_client_profile(name: str) -> str:
    """Get client contact info + preferences."""
    try:
        resp = urlopen("%s/clients/%s/profile" % (OPENCLAW_URL, quote(name, safe="")), timeout=10)
        data = json.loads(resp.read())
        client = data.get("client_name", name)
        parts = ["Client: %s" % client.title()]

        # Contact info
        email = data.get("email", "")
        phone = data.get("phone", "")
        address = data.get("address", "")
        company = data.get("company", "")
        project_type = data.get("project_type", "")

        if email:
            parts.append("Email: %s" % email)
        if phone:
            parts.append("Phone: %s" % phone)
        if address:
            parts.append("Address: %s" % address)
        if company:
            parts.append("Company: %s" % company)
        if project_type:
            parts.append("Project: %s" % project_type)

        notes = data.get("notes", "")
        if notes:
            parts.append("Notes: %s" % notes)

        for section in ["preferences", "concerns", "requirements", "style"]:
            items = data.get(section, [])
            if items:
                parts.append("\n%s:" % section.title())
                for item in items[:5]:
                    parts.append("  \u2022 %s" % item.get("content", ""))

        if len(parts) == 1:
            return "No info tracked for %s yet." % name.title()
        return "\n".join(parts)
    except Exception as e:
        return "Client profile unavailable: %s" % e


def _ensure_openclaw_path():
    openclaw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "openclaw"))
    if os.path.isdir(openclaw_dir) and openclaw_dir not in sys.path:
        sys.path.insert(0, openclaw_dir)


def _load_project_routes() -> dict:
    try:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "email-monitor", "routing_config.json"))
        with open(path) as f:
            return json.load(f).get("project_routes", {})
    except Exception:
        return {}


def _resolve_client_email(client_ref: str) -> str:
    routes = _load_project_routes()
    ref = client_ref.lower().strip()
    for email_addr, folder in routes.items():
        if ref in email_addr.lower() or ref in str(folder).lower():
            return email_addr
    return ""


def get_follow_up_status() -> str:
    try:
        _ensure_openclaw_path()
        from follow_up_tracker import list_overdue
        overdue = list_overdue()
        if not overdue:
            return "No overdue follow-ups right now."
        lines = ["Overdue follow-ups:"]
        for row in overdue[:15]:
            lines.append("- %s — %s" % (row.get("client_email", "?"), row.get("last_client_subject", "(no subject)")))
        return "\n".join(lines)
    except Exception as e:
        return "Follow-up status unavailable: %s" % e


def get_payment_status() -> str:
    try:
        _ensure_openclaw_path()
        from payment_tracker import get_status_summary
        return get_status_summary()
    except Exception as e:
        return "Payment status unavailable: %s" % e


def summarize_latest_from_client(client_ref: str) -> str:
    client_ref = client_ref.strip()
    if not client_ref:
        return "Tell me which client to look up."
    try:
        q = quote(client_ref, safe="")
        resp = urlopen("http://127.0.0.1:8092/emails/search?q=%s&limit=5" % q, timeout=10)
        emails = json.loads(resp.read())
        if not emails:
            return "No emails found for %s." % client_ref
        latest = emails[0]
        sender = latest.get("sender_name") or latest.get("sender", "?")
        subject = latest.get("subject", "")
        summary = latest.get("summary", "") or latest.get("snippet", "")[:300]
        return "Latest from %s\nSubject: %s\n%s" % (sender, subject, summary)
    except Exception as e:
        return "Couldn't retrieve latest client email: %s" % e


def _create_walkthrough_event(contact: str) -> tuple[bool, str]:
    now = datetime.now()
    start = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    payload = {
        "title": "Walkthrough with %s" % contact,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "notes": "Auto-created from iMessage command.",
    }
    try:
        req = Request(
            "http://127.0.0.1:8094/calendar/events",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return True, "Walkthrough scheduled for %s." % start.strftime("%Y-%m-%d %I:%M %p")
    except Exception as e:
        return False, "Failed to schedule walkthrough: %s" % e


def _draft_walkthrough_email(contact: str, contact_email: str) -> str:
    try:
        _ensure_openclaw_path()
        from email_workflow import draft_email
        subject = "Walkthrough Scheduling — Symphony Smart Homes"
        body = (
            "<p>Hi %s,</p>"
            "<p>I'd like to schedule our walkthrough and confirm project details.</p>"
            "<p>Please let me know if this time works for you.</p>"
            "<p>Best regards,<br>Matt</p>"
        ) % contact
        result = draft_email(to=contact_email, subject=subject, body_html=body, notify_matthew=False)
        if result.get("status") == "draft_created":
            return "Drafted walkthrough email to %s in Zoho." % contact_email
        return "Could not draft walkthrough email: %s" % result.get("message", "unknown error")
    except Exception as e:
        return "Walkthrough email draft failed: %s" % e


def handle_draft_to_command(message: str) -> str:
    m = _re.search(r"draft to\s+(.+?)(?:\s*:\s*(.+))?$", message, _re.IGNORECASE)
    if not m:
        return "Use: draft to [client] : [what to say]"
    client_ref = (m.group(1) or "").strip()
    draft_text = (m.group(2) or "").strip()
    if not draft_text:
        return "What should I say to %s? Send: draft to %s : [message]" % (client_ref, client_ref)
    client_email = _resolve_client_email(client_ref)
    if not client_email:
        return "I couldn't match %s to an email. Use sender email directly." % client_ref
    try:
        _ensure_openclaw_path()
        from email_workflow import draft_email
        result = draft_email(
            to=client_email,
            subject="RE: %s" % client_ref.title(),
            body_html="<p>%s</p><p>Best regards,<br>Matt</p>" % draft_text,
            notify_matthew=False,
        )
        if result.get("status") == "draft_created":
            return "Draft created for %s — review in Zoho." % client_email
        return "Draft failed: %s" % result.get("message", "unknown")
    except Exception as e:
        return "Draft error: %s" % e


def handle_schedule_walkthrough(message: str) -> str:
    m = _re.search(r"schedule walkthrough with\s+(.+)$", message, _re.IGNORECASE)
    if not m:
        return "Use: schedule walkthrough with [contact]"
    contact = m.group(1).strip()
    ok, schedule_msg = _create_walkthrough_event(contact)
    if not ok:
        return schedule_msg
    contact_email = _resolve_client_email(contact)
    if contact_email:
        draft_msg = _draft_walkthrough_email(contact, contact_email)
        return "%s\n%s" % (schedule_msg, draft_msg)
    return "%s\nNo client email match found for %s." % (schedule_msg, contact)


def _read_last_approval_decision_id():
    """Numeric id from OpenClaw last approval notification (same host path as orchestrator)."""
    data_dir = os.environ.get(
        "OPENCLAW_DATA_DIR",
        str(Path.home() / "AI-Server/data/openclaw"),
    )
    p = Path(data_dir) / "last_approval_decision.txt"
    try:
        if p.exists():
            return int(p.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    return None


def try_approval_reply(message: str):
    """Match YES/NO/EDIT replies for OpenClaw decision approvals (see close-the-loop-part2)."""

    raw = message.strip()
    lower = raw.lower()
    if not lower:
        return None

    # EDIT <id> <note> | EDIT <note> — approve with optional note (granted=True)
    m_edit = _re.match(r"^edit\s*(.*)$", raw, _re.IGNORECASE | _re.DOTALL)
    if m_edit:
        tail = (m_edit.group(1) or "").strip()
        if not tail or len(tail) > 2000:
            return (
                "Use: EDIT <id> <note> or EDIT <note> — id from last approval if you omit the number."
            )
        head_num = _re.match(r"^(\d{1,8})\s+(.+)$", tail, _re.DOTALL)
        lone_num = _re.match(r"^(\d{1,8})\s*$", tail)
        if head_num:
            decision_id = int(head_num.group(1))
            edit_note = head_num.group(2).strip()
        elif lone_num:
            decision_id = int(lone_num.group(1))
            edit_note = ""
        else:
            decision_id = _read_last_approval_decision_id()
            if decision_id is None:
                return (
                    "Could not resolve EDIT — use EDIT <id> <note> or EDIT <note> after a "
                    "needs_approval notification."
                )
            edit_note = tail
        granted = True
    else:
        if len(lower) > 160:
            return None
        m = _re.match(r"^(yes|y|no|n)(\s|$|\d)", lower)
        if not m:
            return None
        granted = m.group(1) in ("yes", "y")
        num = _re.search(r"\b(\d{1,8})\b", message)
        if num:
            decision_id = int(num.group(1))
        else:
            decision_id = _read_last_approval_decision_id()
        edit_note = ""
        if decision_id is None:
            return (
                "Could not resolve approval — reply YES 123 or NO 123 with the decision ID "
                "(from the notification)."
            )

    secret = os.environ.get("APPROVAL_BRIDGE_SECRET", "")
    if not secret:
        return "Approval bridge not configured: set APPROVAL_BRIDGE_SECRET in the environment."
    payload = json.dumps(
        {
            "decision_id": decision_id,
            "granted": granted,
            "secret": secret,
            "edit_note": edit_note,
        }
    ).encode("utf-8")
    req = Request(
        "%s/internal/approval" % OPENCLAW_URL.rstrip("/"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            resp.read()
        suffix = "approved" if granted else "denied"
        if granted and edit_note:
            suffix = "approved (note saved)"
        return "Recorded: decision %d %s." % (decision_id, suffix)
    except Exception as e:
        return "Approval request failed: %s" % str(e)[:220]


def ask_openclaw(message: str) -> str:
    """Send a message to OpenClaw and get a response."""
    try:
        urls = _re.findall(r'https?://[^\s<>"]+', message)
        if urls:
            x_pattern = _re.compile(
                r"https?://(?:x\.com|twitter\.com)/.+/status/", _re.I
            )
            x_urls = [u for u in urls if x_pattern.search(u)]
            non_x_urls = [u for u in urls if not x_pattern.search(u)]

            if x_urls and not non_x_urls:
                return (
                    "Analyzing your X link(s) — detailed analysis incoming shortly via x-intake."
                )

            if non_x_urls:
                context = _re.sub(r'https?://[^\s<>"]+', "", message).strip()
                results = []
                for url in non_x_urls[:2]:
                    results.append(research_link(url, context))
                if x_urls:
                    results.append(
                        "X links are being analyzed separately — results incoming."
                    )
                return "\n\n---\n\n".join(results)

        approval_resp = try_approval_reply(message)
        if approval_resp is not None:
            return approval_resp

        lower = message.lower()

        if lower.startswith("draft to "):
            return handle_draft_to_command(message)

        if lower.strip() in ("follow ups", "followups", "overdue follow ups"):
            return get_follow_up_status()

        if lower.strip() in ("payments", "payment status", "deposits"):
            return get_payment_status()

        if lower.startswith("what did "):
            m = _re.search(r"what did\s+(.+?)\s+say", lower)
            if m:
                return summarize_latest_from_client(m.group(1).strip())

        if lower.startswith("schedule walkthrough with "):
            return handle_schedule_walkthrough(message)

        if any(w in lower for w in ["help", "commands", "what can you do"]):
            return "I respond to:\n\u2022 trades \u2014 live P&L + positions\n\u2022 status \u2014 all services health\n\u2022 restart [service] \u2014 git-reset + rebuild a service\n\u2022 restart all \u2014 rebuild everything\n\u2022 email \u2014 inbox summary\n\u2022 calendar \u2014 today's schedule\n\u2022 weather \u2014 NOAA edges\n\u2022 jobs \u2014 active job list\n\u2022 new job [name] \u2014 create a job\n\u2022 advance [name] \u2014 advance job phase\n\u2022 [name] status \u2014 specific job details\n\u2022 proposals \u2014 list proposals\n\u2022 manuals \u2014 list manuals\n\u2022 client [name] \u2014 client profile\n\u2022 help \u2014 this message\n\nAnything else, I'll think about it and respond."

        if any(w in lower for w in ["trade", "trading", "p&l", "pnl", "profit", "balance", "portfolio"]):
            return get_trading_status()

        # Knowledge base commands
        if lower.strip() in ("proposals", "proposal", "past proposals"):
            return get_proposals()

        if lower.strip() in ("manuals", "manual", "product manuals"):
            return get_manuals()

        # Client profile commands — match "client topletz" or "topletz profile"
        client_match = _re.search(r'(?:client|profile)\s+([\w\'\-]+(?:\s+[\w\'\-]+)?)', lower)
        if not client_match:
            client_match = _re.search(r'([\w\'\-]+(?:\s+[\w\'\-]+)?)\s+profile', lower)
        if client_match:
            return get_client_profile(client_match.group(1).strip().rstrip("'").rstrip("s").rstrip("'"))

        # Job commands — check BEFORE generic "status" handler
        if lower.startswith("new job ") or lower.startswith("advance ") or lower.startswith("rename "):
            return get_job_status(message)

        # "topletz status", "status on topletz", "jobs", "active jobs"
        job_status_match = _re.search(r'([\w\'\-]+(?:\s+[\w\'\-]+)?)\s+status', lower)
        if job_status_match:
            name = job_status_match.group(1).strip()
            if name not in ("system", "service", "bot", "trading", "email"):
                return get_job_status(message)

        if any(w in lower for w in ["jobs", "active jobs"]) or _re.search(r'\bstatus\s+on\s+[\w\']+', lower):
            return get_job_status(message)

        if any(w in lower for w in ["email", "inbox", "mail"]):
            return get_email_status(message)

        if any(w in lower for w in ["calendar", "schedule", "meeting"]):
            return get_calendar_status()

        if any(w in lower for w in ["weather", "edge", "noaa"]):
            return get_weather_status()

        reset_resp = handle_reset_command(message)
        if reset_resp is not None:
            return reset_resp

        # Deposit confirmation: "deposit confirmed [client]" or "deposit received [client]"
        dep_match = _re.match(r"deposit\s+(?:confirmed|received|paid|in)\s+(.+)", lower)
        if dep_match:
            return handle_deposit_confirmed(dep_match.group(1).strip())

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



# ── Service reset (iMessage: "restart email-monitor", "fix all") ──────────────

_SERVICE_MAP = {
    "email":         "email-monitor",
    "email-monitor": "email-monitor",
    "trading":       "polymarket-bot",
    "polymarket":    "polymarket-bot",
    "polymarket-bot":"polymarket-bot",
    "notifications": "notification-hub",
    "notification-hub": "notification-hub",
    "openclaw":      "openclaw",
    "calendar":      "calendar-agent",
    "voice":         "voice-receptionist",
    "knowledge":     "knowledge-base",
    "clawwork":      "clawwork",
    "mission":       "mission-control",
    "mission-control":"mission-control",
}

def handle_reset_command(message: str) -> Optional[str]:
    """Handle restart/fix/reset commands. Returns response or None if not a reset command."""
    import subprocess as _sp
    lower = message.lower().strip()

    # Detect "restart X", "fix X", "reset X", "rebuild X"
    m = _re.match(r"(?:restart|fix|reset|rebuild)\s+(.+)", lower)
    if not m:
        return None

    target = m.group(1).strip()
    root = _os.path.expanduser("~/AI-Server")

    if target in ("all", "everything", "services", "all services"):
        services = list(set(_SERVICE_MAP.values()))
        results = []
        for svc in services:
            out = _restart_service(svc, root)
            results.append(out)
        return "Reset all services:\n" + "\n".join(results)

    svc = _SERVICE_MAP.get(target)
    if not svc:
        return "Unknown service '%s'. Try: %s" % (target, ", ".join(sorted(set(_SERVICE_MAP.keys()))))

    return _restart_service(svc, root)


def handle_deposit_confirmed(client_hint: str) -> str:
    """Mark deposit received, advance Linear, notify team."""
    import subprocess as _sp, json as _json
    root = _os.path.expanduser("~/AI-Server")
    try:
        result = _sp.run(
            ["docker", "compose", "exec", "-T", "openclaw",
             "python3", "-c",
             f"""
import asyncio, json, sys
sys.path.insert(0, '/app')
import redis
r = redis.from_url('redis://redis:6379', decode_responses=True)
r.publish('events:stripe_payment', json.dumps({{
    'event': 'payment_succeeded',
    'metadata': {{'phase': 'deposit', 'client_hint': '{client_hint}'}},
    'amount': 0,
    'note': 'Manual confirmation via iMessage'
}}))
print('published')
"""],
            cwd=root, capture_output=True, text=True, timeout=30
        )
        if "published" in result.stdout:
            return f"Deposit confirmed for {client_hint}. Linear advanced, team notified."
        return f"Published deposit event — check openclaw logs if Linear didn't update."
    except Exception as e:
        return f"Deposit command error: {str(e)[:100]}"


def _restart_service(svc: str, root: str) -> str:
    import subprocess as _sp
    try:
        # 1. Git reset the service source to clean state
        _sp.run(
            ["git", "fetch", "origin"],
            cwd=root, capture_output=True, timeout=30
        )
        svc_dir = _os.path.join(root, svc)
        if _os.path.isdir(svc_dir):
            _sp.run(
                ["git", "checkout", "origin/main", "--", svc],
                cwd=root, capture_output=True, timeout=30
            )

        # 2. Rebuild and restart
        result = _sp.run(
            ["/usr/local/bin/docker", "compose", "up", "-d", "--build", svc],
            cwd=root, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return "%s: restarted OK" % svc
        else:
            return "%s: rebuild failed — %s" % (svc, (result.stderr or result.stdout)[:120])
    except Exception as e:
        return "%s: error — %s" % (svc, str(e)[:100])


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


def get_email_status(query: str = "") -> str:
    """Smart email handler — searches or summarizes based on query."""

    lower = query.lower().strip() if query else ""

    # Check for specific sender queries: "what did steve send", "emails from topletz"
    sender_match = _re.search(
        r'(?:from|did|by)\s+(\w[\w\s]*?)(?:\s+(?:send|sent|email|write|wrote|say)|\?|$)',
        lower,
    )
    search_terms = ""
    if sender_match:
        search_terms = sender_match.group(1).strip()
    elif "bid" in lower:
        # Bid-specific query
        try:
            resp = urlopen("http://127.0.0.1:8092/emails?category=BID_INVITE&unread=true&limit=10", timeout=10)
            emails = json.loads(resp.read())
            if not emails:
                return "No new bid invites."
            parts = ["Bid invites (%d):" % len(emails)]
            for e in emails[:5]:
                line = "%s: %s" % (e.get("sender_name") or e.get("sender", "?"), e.get("subject", ""))
                summary = e.get("summary", "")
                if summary and summary != "Analysis unavailable":
                    line += "\n  %s" % summary
                parts.append(line)
            return "\n\n".join(parts)
        except Exception as e:
            return "Couldn't check bids: %s" % e
    elif lower and lower not in ("email", "inbox", "mail", "emails"):
        # Use whatever they typed (minus the keyword "email") as search terms
        search_terms = _re.sub(r'\b(?:email|emails|inbox|mail|check|any|new|get|show|my)\b', '', lower).strip()

    # If we have search terms, hit the search endpoint
    if search_terms:
        try:
            url = "http://127.0.0.1:8092/emails/search?q=%s&limit=5" % quote(search_terms, safe="")
            resp = urlopen(url, timeout=10)
            emails = json.loads(resp.read())
            if not emails:
                return "No emails matching '%s'." % search_terms
            parts = ["Found %d email(s) matching '%s':" % (len(emails), search_terms)]
            for e in emails:
                sender = e.get("sender_name") or e.get("sender", "?")
                subj = e.get("subject", "")
                summary = e.get("summary", "")
                action = e.get("action_items", "")
                line = "%s: %s" % (sender, subj)
                if summary and summary not in ("Analysis unavailable", ""):
                    line += "\n  %s" % summary
                if action:
                    line += "\n  → %s" % action.replace("\n", ", ").strip("- ")
                parts.append(line)
            return "\n\n".join(parts)
        except Exception as e:
            return "Email search failed: %s" % e

    # Default: smart summary
    try:
        resp = urlopen("http://127.0.0.1:8092/emails/summary", timeout=10)
        data = json.loads(resp.read())
        unread = data.get("unread", 0)
        total = data.get("total_today", 0)
        actions = data.get("action_items", [])

        parts = []
        if unread:
            parts.append("You have %d unread email%s (%d today)." % (unread, "s" if unread != 1 else "", total))
        else:
            parts.append("Inbox clear — no unread emails. %d received today." % total)

        if actions:
            parts.append("Top priorities:")
            for a in actions[:5]:
                sender = a.get("sender", "?")
                subj = a.get("subject", "")
                parts.append("• %s — %s" % (sender, subj))

        return "\n".join(parts)
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


def get_job_status(query: str = "") -> str:
    """Get job status — list active jobs or search for specific job."""
    lower = query.lower().strip() if query else ""

    # "new job <client name>" — create a new job
    new_match = _re.search(r'new\s+job\s+(.+)', lower)
    if new_match:
        client_name = new_match.group(1).strip().title()
        try:
            data = json.dumps({"client_name": client_name}).encode()
            req = Request(
                "%s/jobs" % OPENCLAW_URL,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=10)
            job = json.loads(resp.read())
            return "Created job #%d for %s [%s]" % (
                job.get("job_id", 0), client_name, job.get("phase", "LEAD")
            )
        except Exception as e:
            return "Failed to create job: %s" % e

    # "rename <search> to <new name>" — rename a job's client
    rename_match = _re.search(r'rename\s+(.+?)\s+to\s+(.+)', lower)
    if rename_match:
        search = rename_match.group(1).strip()
        new_name = rename_match.group(2).strip().title()
        try:
            resp = urlopen(
                "%s/jobs/search?q=%s" % (OPENCLAW_URL, quote(search, safe="")),
                timeout=10,
            )
            data = json.loads(resp.read())
            jobs = data.get("jobs", [])
            if not jobs:
                return "No job found matching '%s'" % search
            job = jobs[0]
            req = Request(
                "%s/jobs/%d/rename" % (OPENCLAW_URL, job["job_id"]),
                data=json.dumps({"client_name": new_name}).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=10)
            result = json.loads(resp.read())
            return "Renamed job #%d: %s -> %s" % (job["job_id"], job.get("client_name", "?"), new_name)
        except Exception as e:
            return "Failed to rename: %s" % e

    # "advance <name>" — advance a specific job
    advance_match = _re.search(r'advance\s+(.+)', lower)
    if advance_match:
        search = advance_match.group(1).strip()
        try:
            resp = urlopen(
                "%s/jobs/search?q=%s" % (OPENCLAW_URL, quote(search, safe="")),
                timeout=10,
            )
            data = json.loads(resp.read())
            jobs = data.get("jobs", [])
            if not jobs:
                return "No job found matching '%s'" % search
            job = jobs[0]
            # Advance it
            req = Request(
                "%s/jobs/%d/advance" % (OPENCLAW_URL, job["job_id"]),
                data=json.dumps({}).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=10)
            result = json.loads(resp.read())
            new_job = result.get("job", {})
            return "Advanced %s: %s -> %s" % (
                job.get("client_name", "?"),
                result.get("phase_from", "?"),
                result.get("phase_to", new_job.get("phase", "?")),
            )
        except Exception as e:
            return "Failed to advance job: %s" % e

    # "status on <name>" or "<name> status" — specific job search
    status_match = _re.search(r'(?:status\s+(?:on\s+)?|(.+?)\s+status)', lower)
    specific_search = None
    if status_match:
        specific_search = (status_match.group(1) or "").strip()
        # Remove "status" from the search if it leaked in
        specific_search = specific_search.replace("status", "").strip()

    # If there's a specific search term (not just "jobs" or "active jobs")
    clean = _re.sub(r'\b(?:jobs?|active|status|on|show|list|get|my|all)\b', '', lower).strip()
    if specific_search or clean:
        search = specific_search or clean
        if search:
            try:
                resp = urlopen(
                    "%s/jobs/search?q=%s" % (OPENCLAW_URL, quote(search, safe="")),
                    timeout=10,
                )
                data = json.loads(resp.read())
                jobs = data.get("jobs", [])
                if not jobs:
                    return "No jobs matching '%s'" % search
                parts = ["%d job(s) matching '%s':" % (len(jobs), search)]
                for j in jobs:
                    line = "#%d %s — %s [%s]" % (
                        j["job_id"],
                        j.get("client_name", "?"),
                        j.get("project_name", "(unnamed)"),
                        j.get("phase", "?"),
                    )
                    parts.append(line)
                return "\n".join(parts)
            except Exception as e:
                return "Job search failed: %s" % e

    # Default: list active jobs
    try:
        resp = urlopen("%s/jobs" % OPENCLAW_URL, timeout=10)
        data = json.loads(resp.read())
        jobs = data.get("jobs", [])
        if not jobs:
            return "No active jobs."
        parts = ["Active jobs (%d):" % len(jobs)]
        for j in jobs:
            line = "#%d %s — %s [%s]" % (
                j["job_id"],
                j.get("client_name", "?"),
                j.get("project_name", "(unnamed)"),
                j.get("phase", "?"),
            )
            updated = j.get("updated_at", "")
            if updated:
                line += " (updated: %s)" % updated[:10]
            parts.append(line)
        return "\n".join(parts)
    except Exception as e:
        return "Jobs status unavailable: %s" % e


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
    log.info("[monitor] Watching for handles: %s", monitor.owner_handles_clean)
    log.info("[monitor] Starting from message ID: %d", monitor.last_message_id)

    while True:
        try:
            messages = monitor.check_new_messages()
            for msg in messages:
                text = msg["text"].strip()
                if not text:
                    continue

                log.info("[monitor] Received: %s", text)

                # Publish to Redis for x-intake and other downstream consumers
                _rpub = _get_redis_pub()
                if _rpub:
                    try:
                        _rpub.publish(
                            "events:imessage",
                            json.dumps(
                                {
                                    "text": text,
                                    "from": msg.get("from", REPLY_TO),
                                    "timestamp": time.time(),
                                }
                            ),
                        )
                    except Exception as _re:
                        log.warning("[redis] Publish failed: %s", _re)

                response = ask_openclaw(text)

                log.info("[monitor] Responding: %s...", response[:100])
                if send_queue:
                    send_queue.enqueue(msg.get("from", REPLY_TO), response)
                else:
                    send_imessage(msg.get("from", REPLY_TO), response)
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

        full_msg = message  # title already included by notification-hub; do not prepend again
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




# ── Trading ideas from iMessage ──────────────────────────────────────
import re as _idea_re

_IDEA_PATTERNS = [
    _idea_re.compile(r"(?:look into|research|check out|analyze)\s+(.+)", _idea_re.I),
    _idea_re.compile(r"(?:bet on|trade|buy|sell)\s+(.+)", _idea_re.I),
    _idea_re.compile(r"(?:what about|thoughts on)\s+(.+)", _idea_re.I),
]

_IDEAS_PATH = os.path.join(
    os.environ.get("DATA_DIR", "/Users/bob/AI-Server/data/polymarket"),
    "ideas.txt",
)

def _maybe_capture_idea(text: str) -> None:
    """If the message matches a trading idea pattern, append to ideas.txt."""
    for pat in _IDEA_PATTERNS:
        m = pat.search(text)
        if m:
            topic = m.group(1).strip()[:200]
            if len(topic) < 3:
                return
            from datetime import datetime, timezone
            entry = (
                f"\nIDEA: {topic}\n"
                f"DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
                f"DESCRIPTION: iMessage request: {text[:200]}\n"
                f"HYPOTHESIS: Manual trading idea from Matt\n"
                f"STATUS: pending\n"
                f"NOTES: via iMessage bridge\n"
                "---\n"
            )
            try:
                os.makedirs(os.path.dirname(_IDEAS_PATH), exist_ok=True)
                with open(_IDEAS_PATH, "a") as f:
                    f.write(entry)
                print(f"[idea captured] {topic}")
            except Exception as exc:
                print(f"[idea capture failed] {exc}")
            return

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

    log.info("========================================")
    log.info("[bridge] iMessage Bridge starting up")
    log.info("========================================")
    log.info("[bridge] OWNER_PHONE: %s", OWNER_PHONE)
    log.info("[bridge] OWNER_HANDLES: %s", OWNER_HANDLES)
    log.info("[bridge] REPLY_TO: %s", REPLY_TO)
    log.info("[bridge] CHAT_DB: %s (exists: %s)", CHAT_DB, CHAT_DB.exists())
    log.info("[bridge] OpenClaw: %s", OPENCLAW_URL)
    log.info("[bridge] Twilio fallback: %s", "configured" if TWILIO_ACCOUNT_SID else "not configured")
    log.info("[bridge] OPENAI_API_KEY: %s", "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET")

    if not CHAT_DB.exists():
        log.error("[bridge] CHAT_DB does not exist at %s — monitoring will fail", CHAT_DB)

    send_queue = SendQueue()

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    log.info("[bridge] Listening on port %d", PORT)

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
