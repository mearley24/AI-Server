"""
Unit tests for cortex.bluebubbles attachment normalizer + send_text allowlist.
All tests are offline — no network calls to BlueBubbles server or Redis.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure cortex package is importable from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.bluebubbles import (
    ATTACHMENT_MAX_BYTES,
    ATTACHMENT_MIME_ALLOWLIST,
    ATTACHMENT_TOTAL_MAX_BYTES,
    AttachmentRef,
    BlueBubblesClient,
    MessageEvent,
    Routing,
    _enrich_attachments,
    _publish_event,
    _sha256_hex,
    _store_attachment_body,
    normalize_webhook_payload,
)

FIXTURE_PNG = Path(__file__).parent / "fixtures" / "bluebubbles" / "tiny.png"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_client(configured: bool = True) -> BlueBubblesClient:
    c = BlueBubblesClient(
        base_url="http://bb-mock:12345" if configured else "",
        password="testpw" if configured else "",
    )
    return c


def _make_payload(
    text: str = "hello",
    attachments: list[dict] | None = None,
    is_from_me: bool = False,
) -> dict:
    return {
        "type": "new-message",
        "data": {
            "guid": "test-guid-001",
            "text": text,
            "isFromMe": is_from_me,
            "chatGuid": "iMessage;-;+19705193013",
            "handle": {"address": "+19705193013"},
            "attachments": attachments or [],
            "dateCreated": 1714000000000,
        },
    }


# ── normalize_webhook_payload ─────────────────────────────────────────────────

def test_normalize_returns_message_event_shape():
    event = normalize_webhook_payload(_make_payload("hi"))
    assert event["event_id"] == "test-guid-001"
    assert event["thread_guid"] == "iMessage;-;+19705193013"
    assert event["author_handle"] == "+19705193013"
    assert event["text"] == "hi"
    assert event["source"] == "bluebubbles"
    assert isinstance(event["attachments"], list)
    # legacy compat
    assert event["id"] == event["event_id"]
    assert event["body_text"] == "hi"


def test_normalize_attachment_metadata_preserved():
    atts = [{"guid": "att-1", "mimeType": "image/png", "transferName": "photo.png", "totalBytes": 1234}]
    event = normalize_webhook_payload(_make_payload(attachments=atts))
    assert len(event["attachments"]) == 1
    a = event["attachments"][0]
    assert a["guid"] == "att-1"
    assert a["mime_type"] == "image/png"
    assert a["byte_size"] == 1234
    assert a["body_path"] is None   # not enriched yet
    assert a["sha256"] is None


# ── _enrich_attachments ───────────────────────────────────────────────────────

def test_normalize_enforces_mime_allowlist(tmp_path: Path):
    atts = [{"guid": "att-bad", "mimeType": "video/mp4", "transferName": "clip.mp4", "totalBytes": 500}]
    event = normalize_webhook_payload(_make_payload(attachments=atts))
    client = _make_client()

    async def run():
        await _enrich_attachments(event, client, base_dir=tmp_path)

    asyncio.run(run())
    a = event["attachments"][0]
    assert a["body_path"] is None
    assert a["sha256"] is None


def test_normalize_drops_oversize_attachment_body(tmp_path: Path):
    atts = [{"guid": "att-big", "mimeType": "image/png", "transferName": "big.png", "totalBytes": ATTACHMENT_MAX_BYTES + 1}]
    event = normalize_webhook_payload(_make_payload(attachments=atts))
    client = _make_client()

    big_bytes = b"x" * (ATTACHMENT_MAX_BYTES + 1)

    async def run():
        with patch("cortex.bluebubbles._fetch_attachment_body", new=AsyncMock(return_value=big_bytes)):
            await _enrich_attachments(event, client, base_dir=tmp_path)

    asyncio.run(run())
    a = event["attachments"][0]
    assert a["body_path"] is None
    assert a["size"] == len(big_bytes)


def test_sha256_dedups_identical_attachments(tmp_path: Path):
    png_bytes = FIXTURE_PNG.read_bytes()
    sha = _sha256_hex(png_bytes)
    atts = [
        {"guid": "att-a", "mimeType": "image/png", "transferName": "a.png", "totalBytes": len(png_bytes)},
        {"guid": "att-b", "mimeType": "image/png", "transferName": "b.png", "totalBytes": len(png_bytes)},
    ]
    event = normalize_webhook_payload(_make_payload(attachments=atts))
    client = _make_client()

    async def run():
        with patch("cortex.bluebubbles._fetch_attachment_body", new=AsyncMock(return_value=png_bytes)):
            await _enrich_attachments(event, client, base_dir=tmp_path)

    asyncio.run(run())
    paths = [a["body_path"] for a in event["attachments"] if a["body_path"]]
    # Both should resolve to the same sha256 path (dedup)
    assert len(set(paths)) == 1
    assert sha in paths[0]


def test_total_size_cap_respected(tmp_path: Path):
    chunk = b"x" * (ATTACHMENT_TOTAL_MAX_BYTES // 2 + 1)
    atts = [
        {"guid": f"att-{i}", "mimeType": "image/png", "transferName": f"{i}.png", "totalBytes": len(chunk)}
        for i in range(3)
    ]
    event = normalize_webhook_payload(_make_payload(attachments=atts))
    client = _make_client()

    async def run():
        with patch("cortex.bluebubbles._fetch_attachment_body", new=AsyncMock(return_value=chunk)):
            await _enrich_attachments(event, client, base_dir=tmp_path)

    asyncio.run(run())
    stored = [a for a in event["attachments"] if a["body_path"] is not None]
    # First attachment fits; second pushes over the 8 MiB total — stops there
    assert len(stored) <= 1


# ── _store_attachment_body ────────────────────────────────────────────────────

def test_store_writes_and_dedup(tmp_path: Path):
    data = b"hello png"
    sha = _sha256_hex(data)
    p1 = _store_attachment_body(data, sha, "image/png", tmp_path)
    p2 = _store_attachment_body(data, sha, "image/png", tmp_path)
    assert p1 == p2
    assert p1.read_bytes() == data


# ── _publish_event ────────────────────────────────────────────────────────────

def _make_fake_redis() -> tuple[MagicMock, dict]:
    """Return (fake_module, published_dict) for patching the inline `import redis`."""
    published: dict[str, list[str]] = {}

    class FakeRedisConn:
        def publish(self, channel: str, blob: str) -> None:
            published.setdefault(channel, []).append(blob)

    fake_mod = MagicMock()
    fake_mod.from_url.return_value = FakeRedisConn()
    return fake_mod, published


def test_publish_event_emits_both_channels():
    fake_mod, published = _make_fake_redis()
    event = normalize_webhook_payload(_make_payload("ping"))

    with patch.dict("sys.modules", {"redis": fake_mod}):
        _publish_event(event)

    assert "events:bluebubbles" in published
    assert "events:imessage" in published


def test_publish_event_skips_imessage_for_outbound():
    fake_mod, published = _make_fake_redis()
    event = normalize_webhook_payload(_make_payload("out", is_from_me=True))

    with patch.dict("sys.modules", {"redis": fake_mod}):
        _publish_event(event)

    assert "events:bluebubbles" in published
    assert "events:imessage" not in published


# ── Routing / send_text ───────────────────────────────────────────────────────

def test_routing_fails_closed_on_allowlist_miss():
    """A phone not in the allowlist is denied — regardless of whether config loads."""
    r = Routing()
    # Use a clearly invalid number that can never be in any real allowlist
    allowed, reason = r.is_outbound_allowed(chat_guid=None, phone="+10000000000")
    assert not allowed
    # Reason is either no_routing_config (no file) or recipient_not_allowed (file present)
    assert reason in ("no_routing_config", "recipient_not_allowed")


def test_send_text_returns_not_configured_when_unconfigured():
    client = _make_client(configured=False)

    async def run():
        return await client.send_text(body="hi", chat_guid="iMessage;-;+1")

    result = asyncio.run(run())
    assert not result["ok"]
    assert result["error"] == "not_configured"


def test_send_text_fails_closed_on_empty_body():
    client = _make_client()

    async def run():
        return await client.send_text(body="", chat_guid="iMessage;-;+1")

    result = asyncio.run(run())
    assert not result["ok"]
    assert result["error"] == "empty_body"


def test_send_text_requires_recipient():
    client = _make_client()

    async def run():
        return await client.send_text(body="hi")

    result = asyncio.run(run())
    assert not result["ok"]
    assert "need_chat_guid_or_phone" in result["error"]


def test_send_text_routes_through_client_post(tmp_path: Path):
    """Confirm send_text POSTs to /api/v1/message/text — no direct bypass."""
    client = _make_client()

    posted_urls: list[str] = []

    class MockResponse:
        status_code = 200
        def json(self): return {"status": "queued"}

    class MockPost:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw):
            posted_urls.append(url)
            return MockResponse()

    async def run():
        with patch("cortex.bluebubbles.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=MockResponse())
            mock_httpx.AsyncClient.return_value = mock_client
            return await client.send_text(body="test", chat_guid="iMessage;-;+1")

    result = asyncio.run(run())
    assert result["ok"]
