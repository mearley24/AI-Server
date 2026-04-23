"""BlueBubbles integration module for Cortex.

Provides:
- ``BlueBubblesClient`` — outbound HTTP client for sending iMessage replies
  via the BlueBubbles Server REST API.
- ``Routing`` — inbound/outbound allowlist enforcement with hot-reload from
  ``config/bluebubbles_routing.json``.
- ``normalize_webhook_payload`` — maps a BlueBubbles webhook body into the
  internal "message event" shape (see ``MessageEvent`` TypedDict-style dict).
- ``register_bluebubbles_routes`` — attaches ``POST /hooks/bluebubbles`` and
  ``GET /api/bluebubbles/health`` onto the Cortex FastAPI app.

Design notes
~~~~~~~~~~~~
- Module is deliberately small, stateless and side-effect-free outside of
  (a) optional Redis publish (``events:bluebubbles``, ``events:imessage``)
  and (b) a small in-memory health tracker (``_HEALTH``).
- Secrets (``BLUEBUBBLES_API_PASSWORD``) never land in logs.
- Outbound sends are rate-limited indirectly by BlueBubbles itself; we do not
  add complex retry/backoff in this first pass (per prompt).
- Follows the existing pattern of ``cortex/dashboard.py`` — functions wrapped
  in try/except with short timeouts so downstream issues never crash Cortex.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

BLUEBUBBLES_SERVER_URL = os.environ.get("BLUEBUBBLES_SERVER_URL", "").rstrip("/")
BLUEBUBBLES_API_PASSWORD = os.environ.get("BLUEBUBBLES_API_PASSWORD", "")
# Optional shared secret (HTTP header) set on both BlueBubbles webhook config
# and AI-Server to authenticate webhooks. If unset, we fall back to source-host
# allowlist + payload sanity checks.
BLUEBUBBLES_WEBHOOK_SECRET = os.environ.get("BLUEBUBBLES_WEBHOOK_SECRET", "")

# Routing config is bind-mounted read-only into Cortex at /app/config/…
ROUTING_CONFIG_CANDIDATES = [
    Path("/app/config/bluebubbles_routing.json"),
    Path(__file__).resolve().parent.parent / "config" / "bluebubbles_routing.json",
    Path("config/bluebubbles_routing.json"),
]

# Outbound redis channel used by downstream consumers (cortex/remember,
# openclaw, x-intake) that already listen on the generic imessage lane.
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
REDIS_IMESSAGE_CHANNEL = "events:imessage"
REDIS_BLUEBUBBLES_CHANNEL = "events:bluebubbles"


# ── Attachment constants ─────────────────────────────────────────────────────

ATTACHMENT_MIME_ALLOWLIST: frozenset[str] = frozenset(
    [
        "image/png", "image/jpeg", "image/gif", "image/heic",
        "application/pdf", "text/plain", "text/vtt",
        "audio/m4a", "audio/mp4",
    ]
)
ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024   # 5 MiB per attachment
ATTACHMENT_TOTAL_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB total per event

_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
    "image/heic": "heic", "application/pdf": "pdf",
    "text/plain": "txt", "text/vtt": "vtt",
    "audio/m4a": "m4a", "audio/mp4": "m4a",
}

_ATTACHMENT_BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "bluebubbles" / "attachments"


# ── Event / attachment types ─────────────────────────────────────────────────

class AttachmentRef(TypedDict, total=False):
    guid: str
    mime_type: str
    filename: str
    byte_size: int
    body_path: str | None   # repo-relative path to stored body; None if not fetched
    sha256: str | None
    size: int | None


class MessageEvent(TypedDict, total=False):
    # Canonical fields
    event_id: str
    thread_guid: str
    author_handle: str
    text: str
    attachments: list[AttachmentRef]
    received_at_utc: str
    source: str
    # Legacy compat fields kept for existing consumers
    id: str
    timestamp: str
    channel: str
    raw_event_type: str
    chat_id: str
    sender_id: str
    sender_display: str
    direction: str
    body_text: str
    in_reply_to: str


# ── In-memory health state ───────────────────────────────────────────────────

_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, Any] = {
    "last_ping_ok_at": None,         # ISO timestamp
    "last_ping_error": None,         # str or None
    "last_ping_latency_ms": None,    # float or None
    "last_inbound_event_at": None,   # ISO timestamp
    "last_outbound_send_at": None,   # ISO timestamp
    "last_outbound_error": None,     # str or None
    "inbound_count": 0,
    "outbound_count": 0,
    "outbound_failure_count": 0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(key: str, value: Any) -> None:
    with _HEALTH_LOCK:
        _HEALTH[key] = value


def _bump(key: str) -> None:
    with _HEALTH_LOCK:
        _HEALTH[key] = int(_HEALTH.get(key, 0) or 0) + 1


# ── Routing / allowlist ──────────────────────────────────────────────────────


class Routing:
    """Allowlist enforcement with JSON hot-reload.

    The config file is re-read at most every ``_reload_interval`` seconds to
    avoid a disk hit per webhook.
    """

    def __init__(self, reload_interval: float = 15.0) -> None:
        self._lock = threading.Lock()
        self._cfg: dict[str, Any] = {}
        self._loaded_at = 0.0
        self._reload_interval = reload_interval
        self._path: Path | None = None

    def _find_path(self) -> Path | None:
        for p in ROUTING_CONFIG_CANDIDATES:
            if p.exists():
                return p
        return None

    def _maybe_reload(self) -> None:
        now = time.time()
        if now - self._loaded_at < self._reload_interval and self._cfg:
            return
        path = self._find_path()
        if path is None:
            with self._lock:
                self._cfg = {}
                self._loaded_at = now
            return
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            with self._lock:
                self._cfg = data or {}
                self._loaded_at = now
                self._path = path
        except Exception as exc:
            logger.warning("bluebubbles_routing_reload_failed path=%s error=%s", path, exc)

    @property
    def config_path(self) -> str:
        self._maybe_reload()
        return str(self._path) if self._path else "(none)"

    @staticmethod
    def _norm_phone(v: str) -> str:
        if not v:
            return ""
        return "".join(ch for ch in v if ch.isdigit() or ch == "+").lower()

    @staticmethod
    def _norm_email(v: str) -> str:
        return (v or "").strip().lower()

    def summary(self) -> dict[str, Any]:
        self._maybe_reload()
        with self._lock:
            cfg = self._cfg
        inbound = cfg.get("inbound", {}) or {}
        outbound = cfg.get("outbound", {}) or {}
        return {
            "policy": cfg.get("default_policy", "allow_owner_only"),
            "inbound_allowed_phones": list(inbound.get("allowed_phones", []) or []),
            "inbound_allowed_emails": list(inbound.get("allowed_emails", []) or []),
            "inbound_allowed_chat_guids": list(inbound.get("allowed_chat_guids", []) or []),
            "inbound_blocked_phones": list(inbound.get("blocked_phones", []) or []),
            "outbound_allowed_phones": list(outbound.get("allowed_phones", []) or []),
            "outbound_allowed_chat_guids": list(outbound.get("allowed_chat_guids", []) or []),
            "config_path": str(self._path) if self._path else "(none)",
            "loaded": bool(cfg),
        }

    def is_inbound_allowed(
        self,
        *,
        source_host: str | None,
        chat_guid: str | None,
        sender_id: str | None,
    ) -> tuple[bool, str]:
        """Return (allowed, reason). Reason is logged on deny."""
        self._maybe_reload()
        with self._lock:
            cfg = self._cfg
        if not cfg:
            # No config file at all: fall through to allow-owner-only against env.
            env_owner = self._norm_phone(os.environ.get("OWNER_PHONE_NUMBER", ""))
            sid = self._norm_phone(sender_id or "")
            if env_owner and sid and sid == env_owner:
                return True, "owner_phone_env"
            return False, "no_routing_config"

        policy = cfg.get("default_policy", "allow_owner_only")
        inbound = cfg.get("inbound", {}) or {}

        # Source-host allowlist (if configured)
        allowed_hosts = inbound.get("allowed_webhook_source_hosts") or []
        if allowed_hosts and source_host:
            host_ok = any(source_host == h or source_host.startswith(h) for h in allowed_hosts)
            if not host_ok:
                return False, f"source_host_not_allowed:{source_host}"

        # Explicit block first
        blocked_phones = {self._norm_phone(p) for p in inbound.get("blocked_phones", []) or []}
        sid_phone = self._norm_phone(sender_id or "")
        if sid_phone and sid_phone in blocked_phones:
            return False, "sender_blocked"

        if policy == "allow_all":
            return True, "policy_allow_all"

        guid_ok = bool(chat_guid) and chat_guid in set(inbound.get("allowed_chat_guids") or [])
        phone_ok = bool(sid_phone) and sid_phone in {
            self._norm_phone(p) for p in inbound.get("allowed_phones", []) or []
        }
        email_ok = False
        sender_email = self._norm_email(sender_id or "")
        if sender_email and "@" in sender_email:
            email_ok = sender_email in {
                self._norm_email(e) for e in inbound.get("allowed_emails", []) or []
            }

        if guid_ok or phone_ok or email_ok:
            return True, "sender_allowlisted"

        return False, f"sender_not_allowed:policy={policy}"

    def is_outbound_allowed(
        self,
        *,
        chat_guid: str | None,
        phone: str | None,
    ) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        self._maybe_reload()
        with self._lock:
            cfg = self._cfg
        if not cfg:
            env_owner = self._norm_phone(os.environ.get("OWNER_PHONE_NUMBER", ""))
            dst = self._norm_phone(phone or "")
            if env_owner and dst and dst == env_owner:
                return True, "owner_phone_env"
            return False, "no_routing_config"

        outbound = cfg.get("outbound", {}) or {}
        allowed_guids = set(outbound.get("allowed_chat_guids") or [])
        allowed_phones = {self._norm_phone(p) for p in outbound.get("allowed_phones") or []}

        if chat_guid and chat_guid in allowed_guids:
            return True, "chat_guid_allowed"
        dst = self._norm_phone(phone or "")
        if dst and dst in allowed_phones:
            return True, "phone_allowed"
        return False, "recipient_not_allowed"


# Singleton
_ROUTING = Routing()


def get_routing() -> Routing:
    return _ROUTING


# ── Attachment body helpers ──────────────────────────────────────────────────


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store_attachment_body(data: bytes, sha256: str, mime: str, base_dir: Path) -> Path:
    """Write bytes to base_dir/<yyyy>/<mm>/<sha256>.<ext> atomically.

    Skips the write if the destination already exists with a matching digest.
    Returns the destination path.
    """
    ext = _MIME_TO_EXT.get(mime, "bin")
    now = datetime.now(timezone.utc)
    dest_dir = base_dir / f"{now.year:04d}" / f"{now.month:02d}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{sha256}.{ext}"
    if dest.exists() and _sha256_hex(dest.read_bytes()) == sha256:
        return dest
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return dest


async def _fetch_attachment_body(guid: str, client: "BlueBubblesClient") -> bytes | None:
    """Download raw attachment bytes from BlueBubbles. Returns None on any error."""
    if not client.configured or not guid:
        return None
    url = f"{client.base_url}/api/v1/attachment/{guid}/download"
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=client.timeout) as c:
            resp = await c.get(url, params=client._params())
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


async def _enrich_attachments(
    event: dict[str, Any],
    client: "BlueBubblesClient",
    base_dir: Path | None = None,
) -> None:
    """Fetch + store attachment bodies in-place on the event dict.

    Respects ATTACHMENT_MIME_ALLOWLIST, ATTACHMENT_MAX_BYTES, and
    ATTACHMENT_TOTAL_MAX_BYTES. Bodies that fail any gate remain None;
    metadata is always preserved.
    """
    atts: list[dict[str, Any]] = event.get("attachments") or []
    if not atts:
        return
    store_dir = base_dir or _ATTACHMENT_BASE_DIR
    total_bytes = 0
    for att in atts:
        mime = att.get("mime_type") or ""
        if mime not in ATTACHMENT_MIME_ALLOWLIST:
            att["body_path"] = None
            att["sha256"] = None
            att["size"] = None
            continue
        if total_bytes >= ATTACHMENT_TOTAL_MAX_BYTES:
            att["body_path"] = None
            att["sha256"] = None
            att["size"] = None
            continue
        guid = att.get("guid") or ""
        raw = await _fetch_attachment_body(guid, client)
        if raw is None:
            att["body_path"] = None
            att["sha256"] = None
            att["size"] = None
            continue
        if len(raw) > ATTACHMENT_MAX_BYTES:
            logger.warning("bluebubbles_attachment_too_large guid=%s size=%d", guid, len(raw))
            att["body_path"] = None
            att["sha256"] = None
            att["size"] = len(raw)
            continue
        if total_bytes + len(raw) > ATTACHMENT_TOTAL_MAX_BYTES:
            att["body_path"] = None
            att["sha256"] = None
            att["size"] = None
            continue
        sha = _sha256_hex(raw)
        dest = _store_attachment_body(raw, sha, mime, store_dir)
        att["body_path"] = str(dest)
        att["sha256"] = sha
        att["size"] = len(raw)
        total_bytes += len(raw)


# ── Event normalization ──────────────────────────────────────────────────────

CHANNEL_NAME = "bluebubbles-imessage"


def normalize_webhook_payload(payload: dict[str, Any]) -> MessageEvent:
    """Normalize a BlueBubbles webhook body into the internal message event.

    BlueBubbles sends a variety of event shapes (see
    https://docs.bluebubbles.app/server/api/webhooks). We flatten the common
    ``new-message`` / ``updated-message`` cases into a stable schema.

    Unknown or sparse payloads still return a structurally-valid event with
    empty strings — callers should check ``event["body_text"]`` and
    ``event["chat_id"]`` before routing.
    """
    if not isinstance(payload, dict):
        payload = {}

    raw_type = payload.get("type") or payload.get("event") or "unknown"
    data = payload.get("data") or payload
    if not isinstance(data, dict):
        data = {}

    # Chat identifier — BlueBubbles uses ``chats[0].guid`` (array) or ``chatGuid``
    chat_guid = ""
    chats = data.get("chats") or []
    if isinstance(chats, list) and chats:
        first = chats[0] or {}
        if isinstance(first, dict):
            chat_guid = first.get("guid") or ""
    if not chat_guid:
        chat_guid = data.get("chatGuid") or data.get("chat_guid") or ""

    # Sender identity
    handle = data.get("handle") or {}
    sender_id = ""
    sender_display = ""
    if isinstance(handle, dict):
        sender_id = handle.get("address") or handle.get("id") or ""
        sender_display = handle.get("displayName") or handle.get("formattedAddress") or ""
    if not sender_id:
        sender_id = data.get("senderAddress") or data.get("from") or ""

    # Direction — BlueBubbles uses ``isFromMe`` (True => outbound)
    is_from_me = bool(data.get("isFromMe"))
    direction = "outbound" if is_from_me else "inbound"

    body_text = data.get("text") or data.get("body") or ""
    guid = data.get("guid") or data.get("messageGuid") or ""

    # in_reply_to — BlueBubbles sometimes sets ``threadOriginatorGuid``
    in_reply_to = data.get("threadOriginatorGuid") or ""

    # Timestamp — BlueBubbles uses ms since epoch in ``dateCreated``
    ts_ms = data.get("dateCreated") or data.get("date") or 0
    try:
        ts_ms = int(ts_ms)
    except (TypeError, ValueError):
        ts_ms = 0
    if ts_ms > 0:
        ts_iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()
    else:
        ts_iso = _utc_now_iso()

    # Attachments — metadata only; bodies filled later by _enrich_attachments
    attachments: list[AttachmentRef] = []
    raw_atts = data.get("attachments") or []
    if isinstance(raw_atts, list):
        for a in raw_atts:
            if not isinstance(a, dict):
                continue
            attachments.append(
                AttachmentRef(
                    guid=a.get("guid", ""),
                    mime_type=a.get("mimeType") or a.get("uti", ""),
                    filename=a.get("transferName") or str(a.get("originalROWID", "")),
                    byte_size=int(a.get("totalBytes") or 0),
                    body_path=None,
                    sha256=None,
                    size=None,
                )
            )

    event_id = guid or f"bb-{int(time.time() * 1000)}"
    return MessageEvent(
        # Canonical fields
        event_id=event_id,
        thread_guid=chat_guid,
        author_handle=sender_id,
        text=body_text,
        attachments=attachments,
        received_at_utc=ts_iso,
        source="bluebubbles",
        # Legacy compat fields
        id=event_id,
        timestamp=ts_iso,
        channel=CHANNEL_NAME,
        raw_event_type=raw_type,
        chat_id=chat_guid,
        sender_id=sender_id,
        sender_display=sender_display,
        direction=direction,
        body_text=body_text,
        in_reply_to=in_reply_to,
    )


# ── Outbound client ──────────────────────────────────────────────────────────


class BlueBubblesClient:
    """Minimal BlueBubbles REST client.

    Reads ``BLUEBUBBLES_SERVER_URL`` + ``BLUEBUBBLES_API_PASSWORD`` from env
    and authenticates via query-string ``password=…`` (the style BlueBubbles
    accepts on every endpoint).
    """

    def __init__(
        self,
        base_url: str = BLUEBUBBLES_SERVER_URL,
        password: str = BLUEBUBBLES_API_PASSWORD,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._password = password or ""
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self._password)

    def _params(self) -> dict[str, str]:
        return {"password": self._password} if self._password else {}

    async def ping(self) -> dict[str, Any]:
        """Return a small health dict. Never raises."""
        t0 = time.time()
        if not self.configured:
            _record("last_ping_error", "not_configured")
            return {"ok": False, "error": "not_configured"}
        url = f"{self.base_url}/api/v1/server/info"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                resp = await c.get(url, params=self._params())
            latency_ms = (time.time() - t0) * 1000.0
            _record("last_ping_latency_ms", round(latency_ms, 1))
            if resp.status_code != 200:
                _record("last_ping_error", f"http_{resp.status_code}")
                return {"ok": False, "http_status": resp.status_code}
            info = resp.json().get("data", {}) or {}
            _record("last_ping_ok_at", _utc_now_iso())
            _record("last_ping_error", None)
            return {
                "ok": True,
                "latency_ms": round(latency_ms, 1),
                "server_version": info.get("server_version"),
                "private_api": bool(info.get("private_api")),
                "macos_version": info.get("os_version"),
            }
        except Exception as exc:
            _record("last_ping_error", str(exc)[:200])
            return {"ok": False, "error": str(exc)[:200]}

    async def send_text(
        self,
        *,
        chat_guid: str = "",
        phone: str = "",
        body: str,
        method: str = "apple-script",
    ) -> dict[str, Any]:
        """Send a text message. Provide ``chat_guid`` OR ``phone``.

        BlueBubbles endpoint: ``POST /api/v1/message/text``. With Private API
        enabled you can set ``method='private-api'`` for reactions; we default
        to ``apple-script`` because SIP is enabled on Bob.
        """
        if not self.configured:
            return {"ok": False, "error": "not_configured"}
        if not body:
            return {"ok": False, "error": "empty_body"}
        if not chat_guid and not phone:
            return {"ok": False, "error": "need_chat_guid_or_phone"}

        payload: dict[str, Any] = {
            "message": body,
            "method": method,
            "tempGuid": f"ai-server-{int(time.time() * 1000)}",
        }
        if chat_guid:
            payload["chatGuid"] = chat_guid
        else:
            # BlueBubbles will look up / create a chat from an address list.
            payload["addresses"] = [phone]

        url = f"{self.base_url}/api/v1/message/text"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                resp = await c.post(url, params=self._params(), json=payload)
            if resp.status_code // 100 != 2:
                _record("last_outbound_error", f"http_{resp.status_code}")
                _bump("outbound_failure_count")
                return {
                    "ok": False,
                    "http_status": resp.status_code,
                    "body_preview": resp.text[:200],
                }
            _record("last_outbound_send_at", _utc_now_iso())
            _record("last_outbound_error", None)
            _bump("outbound_count")
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:200]}
            return {"ok": True, "response": data}
        except Exception as exc:
            _record("last_outbound_error", str(exc)[:200])
            _bump("outbound_failure_count")
            return {"ok": False, "error": str(exc)[:200]}


# ── Redis publishing (best-effort) ───────────────────────────────────────────


def _publish_event(event: dict[str, Any]) -> None:
    """Fire-and-forget publish to the generic imessage lane + bluebubbles lane.

    Never raises — Redis failures are logged at DEBUG level only.
    """
    try:
        import redis  # sync client is fine here

        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        blob = json.dumps(event, default=str)
        r.publish(REDIS_BLUEBUBBLES_CHANNEL, blob)
        # Only publish inbound events to the shared imessage lane so downstream
        # x-intake does not re-ingest our own outbound replies.
        if event.get("direction") == "inbound" and event.get("body_text"):
            imsg_event = {
                "text": event.get("body_text", ""),
                "from": event.get("sender_id", ""),
                "chat_guid": event.get("chat_id", ""),
                "source": "bluebubbles-webhook",
                "message_id": event.get("id", ""),
                "timestamp": event.get("timestamp", ""),
            }
            r.publish(REDIS_IMESSAGE_CHANNEL, json.dumps(imsg_event))
    except Exception as exc:
        logger.debug("bluebubbles_redis_publish_failed error=%s", exc)


# ── FastAPI route registration ───────────────────────────────────────────────


def register_bluebubbles_routes(app: FastAPI) -> None:
    """Attach the BlueBubbles inbound webhook + health endpoint.

    Safe to call from ``cortex.engine`` — this is additive to the existing
    ``/api/symphony/bluebubbles/health`` route in ``dashboard.py``.
    """
    routing = get_routing()
    client = BlueBubblesClient()

    @app.post("/hooks/bluebubbles", tags=["bluebubbles"])
    async def bluebubbles_webhook(
        request: Request,
        x_bb_webhook_secret: str | None = Header(default=None, alias="X-BB-Webhook-Secret"),
    ):
        # Secret gate (optional)
        if BLUEBUBBLES_WEBHOOK_SECRET:
            if (x_bb_webhook_secret or "") != BLUEBUBBLES_WEBHOOK_SECRET:
                raise HTTPException(status_code=401, detail="invalid webhook secret")

        # Parse payload
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid json body")

        event = normalize_webhook_payload(payload)
        _record("last_inbound_event_at", _utc_now_iso())
        _bump("inbound_count")

        # Host allowlist check
        client_host = getattr(request.client, "host", None) if request.client else None
        ok, reason = routing.is_inbound_allowed(
            source_host=client_host,
            chat_guid=event.get("chat_id") or None,
            sender_id=event.get("sender_id") or None,
        )

        # Minimal structured log line — body truncated, never log password
        body_preview = (event.get("body_text") or "")[:80].replace("\n", " ")
        logger.info(
            "bluebubbles_webhook "
            "type=%s direction=%s chat=%s sender=%s allowed=%s reason=%s body=%r",
            event.get("raw_event_type"),
            event.get("direction"),
            (event.get("chat_id") or "")[:40],
            (event.get("sender_id") or "")[:40],
            ok,
            reason,
            body_preview,
        )

        if not ok:
            return {
                "status": "rejected",
                "reason": reason,
                "event_id": event["id"],
            }

        # Only forward inbound user messages into the pipeline.
        if event.get("direction") == "inbound" and event.get("body_text"):
            await _enrich_attachments(event, client)
            _publish_event(event)
            return {
                "status": "accepted",
                "event_id": event["id"],
                "chat_id": event["chat_id"],
                "forwarded_to": [REDIS_BLUEBUBBLES_CHANNEL, REDIS_IMESSAGE_CHANNEL],
            }

        return {
            "status": "ignored",
            "reason": "non_inbound_or_empty_body",
            "event_id": event["id"],
        }

    @app.get("/api/bluebubbles/health", tags=["bluebubbles"])
    async def bluebubbles_health():
        """Enriched BlueBubbles bridge health — ping + last-event timestamps."""
        ping = await client.ping()
        with _HEALTH_LOCK:
            snapshot = dict(_HEALTH)
        healthy = bool(ping.get("ok"))
        reason = None
        if not healthy:
            reason = ping.get("error") or f"http_{ping.get('http_status')}"
        return {
            "status": "healthy" if healthy else "unhealthy",
            "reason": reason,
            "ping": ping,
            "configured": client.configured,
            "server_url_configured": bool(BLUEBUBBLES_SERVER_URL),
            "webhook_endpoint": "/hooks/bluebubbles",
            "routing": routing.summary(),
            "counters": {
                "inbound_count": snapshot.get("inbound_count", 0),
                "outbound_count": snapshot.get("outbound_count", 0),
                "outbound_failure_count": snapshot.get("outbound_failure_count", 0),
            },
            "last_inbound_event_at": snapshot.get("last_inbound_event_at"),
            "last_outbound_send_at": snapshot.get("last_outbound_send_at"),
            "last_outbound_error": snapshot.get("last_outbound_error"),
            "last_ping_ok_at": snapshot.get("last_ping_ok_at"),
            "last_ping_error": snapshot.get("last_ping_error"),
            "last_ping_latency_ms": snapshot.get("last_ping_latency_ms"),
        }

    @app.post("/api/bluebubbles/send", tags=["bluebubbles"])
    async def bluebubbles_send(body: dict):
        """Send an iMessage via BlueBubbles. Used by internal services.

        Body:
          {
            "chat_guid": "iMessage;-;+19705193013",   # optional
            "phone":     "+19705193013",              # optional (alternative)
            "body":      "Hello from Symphony"         # required
          }
        """
        chat_guid = (body or {}).get("chat_guid", "") or ""
        phone = (body or {}).get("phone", "") or ""
        text = (body or {}).get("body", "") or ""

        if not text:
            raise HTTPException(status_code=400, detail="body required")
        if not chat_guid and not phone:
            raise HTTPException(status_code=400, detail="chat_guid or phone required")

        ok, reason = routing.is_outbound_allowed(chat_guid=chat_guid or None, phone=phone or None)
        if not ok:
            logger.warning(
                "bluebubbles_send_rejected reason=%s chat=%s phone=%s",
                reason,
                (chat_guid or "")[:40],
                (phone or "")[:20],
            )
            raise HTTPException(status_code=403, detail=f"outbound blocked: {reason}")

        result = await client.send_text(chat_guid=chat_guid, phone=phone, body=text)
        if not result.get("ok"):
            # Always return 200 with {ok:false, error} so the caller can decide
            # whether to fall back to another channel.
            return {"ok": False, "error": result.get("error") or result}
        return result
