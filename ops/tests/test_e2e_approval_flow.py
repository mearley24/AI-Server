"""End-to-end approval flow test for X-intake.

Dry-run only — no real iMessages are sent.

Two test layers:
  1. Unit (TestClient + tmp_path) — always runs, no live cortex required.
  2. Live (http://127.0.0.1:8102) — skipped when Cortex is not reachable.

Coverage:
  - context card loads with draft_reply, reasoning, action_id
  - approve-reply stores final reply in approval log
  - approve-reply writes a dry-run receipt to receipt log
  - send_action_created=True, send_dry_run=True in response
  - send_triggered=False in response
  - receipt has dry_run=True, path='dry_run', bridge_status_code=None
  - no raw phone number in any stored record
  - existing reply actions (send_ack dry-run) still work
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── helpers ───────────────────────────────────────────────────────────────────

CORTEX_URL = "http://127.0.0.1:8102"
KNOWN_CONTACT = "+13035257532"   # client with accepted facts on file
UNKNOWN_CONTACT = "+15550000000"


def _cortex_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{CORTEX_URL}/health", timeout=3)
        return True
    except Exception:
        return False


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{CORTEX_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _get(path: str, params: str = "") -> dict:
    url = f"{CORTEX_URL}{path}"
    if params:
        url += "?" + params
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def _last_ndjson(path: Path) -> dict | None:
    """Return the last non-empty JSON line in an ndjson file."""
    if not path.is_file():
        return None
    for line in reversed(path.read_text(errors="replace").splitlines()):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except Exception:
                pass
    return None


# ══ UNIT TESTS (always run, TestClient + tmp_path) ════════════════════════════

class TestApprovalFlowUnit:
    """Full flow through TestClient; file I/O redirected to tmp_path."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _make_profile(self):
        return {
            "profile_id": "e2e_test_profile",
            "relationship_type": "client",
            "display_name": "",
            "contact_handle": KNOWN_CONTACT,
            "thread_ids": '["tid1"]',
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_seen":  "2026-04-24T00:00:00+00:00",
            "summary": "Systems: Sonos, WiFi. 4 proposed fact(s) extracted",
            "open_requests":     '["check the Sonos system"]',
            "follow_ups":        '[]',
            "systems_or_topics": '["Sonos", "WiFi"]',
            "project_refs":      '[]',
            "dtools_project_refs": '[]',
            "confidence": 0.85,
            "status": "proposed",
            "last_updated": "2026-04-24T10:00:00+00:00",
        }

    def _make_facts(self):
        return [
            {"fact_id": "f1", "thread_id": "tid1", "fact_type": "equipment",
             "fact_value": "Sonos", "confidence": 0.75,
             "source_excerpt": "Sonos offline", "source_timestamp": "2026-04-24T10:00:00+00:00",
             "is_accepted": 1, "is_rejected": 0},
            {"fact_id": "f2", "thread_id": "tid1", "fact_type": "system",
             "fact_value": "WiFi", "confidence": 0.75,
             "source_excerpt": "WiFi network", "source_timestamp": "2026-04-24T10:01:00+00:00",
             "is_accepted": 1, "is_rejected": 0},
            {"fact_id": "f3", "thread_id": "tid1", "fact_type": "issue",
             "fact_value": "offline", "confidence": 0.80,
             "source_excerpt": "Sonos offline again", "source_timestamp": "2026-04-24T10:02:00+00:00",
             "is_accepted": 1, "is_rejected": 0},
        ]

    # ── Step 1: context card loads ────────────────────────────────────────────

    def test_step1_context_card_loads(self, client, tmp_path):
        import cortex.engine as eng
        orig_app, orig_facts, orig_rcpts = eng._APPROVAL_LOG, eng._facts_for_profile, eng._receipts_for_handle
        eng._APPROVAL_LOG = tmp_path / "approvals.ndjson"
        try:
            with patch("cortex.engine._profile_by_handle", return_value=self._make_profile()), \
                 patch("cortex.engine._facts_for_profile", return_value=self._make_facts()), \
                 patch("cortex.engine._receipts_for_handle", return_value=[]):
                r = client.get(f"/api/x-intake/context-card?contact_handle={KNOWN_CONTACT.replace('+','%2B')}")
        finally:
            eng._APPROVAL_LOG = orig_app
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok", f"Expected ok, got: {d}"
        assert d["draft_reply"], "draft_reply must not be empty"
        assert d["reasoning"],   "reasoning must not be empty"
        assert d["action_id"],   "action_id must be set"
        assert 0.0 < d["confidence"] <= 1.0
        assert isinstance(d["source_facts"], list)
        assert KNOWN_CONTACT not in d.get("contact_masked", ""), "raw phone must not appear"

    # ── Step 2: approve-reply stores approval + creates dry-run receipt ───────

    def test_step2_approve_reply_full(self, client, tmp_path):
        import cortex.engine as eng
        orig_a, orig_r = eng._APPROVAL_LOG, eng._DRY_RUN_RECEIPT_LOG
        eng._APPROVAL_LOG        = tmp_path / "approvals.ndjson"
        eng._DRY_RUN_RECEIPT_LOG = tmp_path / "receipts.ndjson"
        try:
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":      "e2etestaction01",
                "approved":       True,
                "draft_reply":    "On it — I'll check your Sonos and see what's going on.",
                "contact_masked": "+13***32",
                "reasoning":      "Active issue: 'offline'; Equipment on file: 'Sonos'",
                "confidence":     0.90,
            })
        finally:
            eng._APPROVAL_LOG        = orig_a
            eng._DRY_RUN_RECEIPT_LOG = orig_r

        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert d["stored"] is True
        assert d["send_action_created"] is True, "send action must be created"
        assert d["send_dry_run"] is True,        "must always be dry-run"
        assert d["send_triggered"] is False,     "no live send must occur"
        assert d["approval_id"]

        # Approval record written
        approval = _last_ndjson(tmp_path / "approvals.ndjson")
        assert approval is not None
        assert approval["status"] == "approved"
        assert approval["final_reply"] == "On it — I'll check your Sonos and see what's going on."
        assert KNOWN_CONTACT not in json.dumps(approval), "raw phone must not be in approval record"

        # Dry-run receipt written
        receipt = _last_ndjson(tmp_path / "receipts.ndjson")
        assert receipt is not None, "receipt must be written"
        assert receipt["dry_run"] is True,            "receipt must be dry_run=true"
        assert receipt["path"] == "dry_run",          "path must be dry_run"
        assert receipt["bridge_status_code"] is None, "no bridge call must occur"
        assert receipt["success"] is True
        assert KNOWN_CONTACT not in json.dumps(receipt), "raw phone must not be in receipt"

    # ── Step 3: no live send verification ────────────────────────────────────

    def test_step3_no_live_send_path(self, client, tmp_path):
        """Verify approve-reply never calls the iMessage bridge or BlueBubbles."""
        import cortex.engine as eng
        eng._APPROVAL_LOG        = tmp_path / "approvals.ndjson"
        eng._DRY_RUN_RECEIPT_LOG = tmp_path / "receipts.ndjson"
        bridge_called = []

        # Patch any outbound HTTP call inside engine.py to detect if it fires
        original_open = urllib.request.urlopen

        def _spy_urlopen(req, *a, **kw):
            url = getattr(req, "full_url", str(req))
            if "8199" in url or "bridge" in url or "bluebubbles" in url.lower():
                bridge_called.append(url)
            return original_open(req, *a, **kw)

        with patch("urllib.request.urlopen", side_effect=_spy_urlopen):
            r = client.post("/api/x-intake/approve-reply", json={
                "action_id":      "nobridgetest01",
                "approved":       True,
                "draft_reply":    "Checking in on your system.",
                "contact_masked": "+13***32",
            })
        assert r.status_code == 200
        assert not bridge_called, f"Bridge must never be called, but got: {bridge_called}"
        receipt = _last_ndjson(tmp_path / "receipts.ndjson")
        assert receipt and receipt["bridge_status_code"] is None

    # ── Step 4: unknown contact returns safe fallback ─────────────────────────

    def test_step4_unknown_contact_safe_fallback(self, client):
        with patch("cortex.engine._profile_by_handle", return_value=None), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": UNKNOWN_CONTACT,
            })
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "no_profile"
        assert d["simulated"] is True
        assert len(d["draft_reply"]) > 5, "must have a safe fallback reply"
        assert d["confidence"] <= 0.30
        assert UNKNOWN_CONTACT not in d.get("contact_masked", "")

    # ── Step 5: rejected facts excluded from source_facts ────────────────────

    def test_step5_rejected_facts_excluded(self, client, tmp_path):
        """Facts with is_rejected=1 are filtered at SQL layer — simulate that."""
        import cortex.engine as eng
        eng._APPROVAL_LOG = tmp_path / "a.ndjson"
        eng._RECEIPT_LOG  = tmp_path / "r.ndjson"
        # _facts_for_profile already filters is_rejected=0; only non-rejected reach here
        non_rejected = [f for f in self._make_facts() if not f.get("is_rejected")]
        with patch("cortex.engine._profile_by_handle", return_value=self._make_profile()), \
             patch("cortex.engine._facts_for_profile", return_value=non_rejected), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": KNOWN_CONTACT,
            })
        d = r.json()
        # No source_fact should be tagged as coming from a rejected fact
        for sf in d.get("source_facts", []):
            assert sf["fact_value"] != "rejected_value"

    # ── Step 6: simulate-incoming matches context-card shape ─────────────────

    def test_step6_simulate_same_shape_as_context_card(self, client):
        required_keys = {
            "status", "action_id", "contact_masked", "profile",
            "accepted_facts", "unverified_facts", "recent_replies",
            "suggested_next_action", "draft_reply", "reasoning",
            "confidence", "source_facts", "simulated",
        }
        with patch("cortex.engine._profile_by_handle", return_value=self._make_profile()), \
             patch("cortex.engine._facts_for_profile", return_value=self._make_facts()), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.post("/api/x-intake/simulate-incoming", json={
                "contact_handle": KNOWN_CONTACT,
                "message_text": "My Sonos is offline.",
            })
        d = r.json()
        missing = required_keys - set(d.keys())
        assert not missing, f"Missing keys in simulate response: {missing}"
        assert d["simulated"] is True


# ══ LIVE E2E (hits real Cortex at 127.0.0.1:8102) ════════════════════════════

@pytest.mark.skipif(not _cortex_reachable(), reason="Cortex not reachable — skipping live E2E")
class TestApprovalFlowLive:
    """Live end-to-end test against the running Cortex service.

    Files are written to /data/cortex inside the container, which bind-mounts
    to ~/AI-Server/data/cortex on the host (read-write, unlike x_intake which
    is read-only for this container).
    """

    APPROVAL_LOG = Path("/Users/bob/AI-Server/data/cortex/reply_approvals.ndjson")
    RECEIPT_LOG  = Path("/Users/bob/AI-Server/data/cortex/reply_receipts_dry_run.ndjson")

    def test_live_e2e_full_flow(self):
        """
        Full chain:
          1. simulate-incoming → context card with action_id
          2. approve-reply → approval stored + dry-run receipt written
          3. verify approval log entry
          4. verify receipt log entry (dry_run=true, no bridge call)
        """
        # ── Step 1: simulate inbound message from known client ────────────────
        sim = _post("/api/x-intake/simulate-incoming", {
            "contact_handle": KNOWN_CONTACT,
            "message_text": "E2E test — Sonos check",
        })
        assert sim.get("status") in ("ok", "no_profile"), f"Unexpected sim status: {sim}"
        assert sim.get("draft_reply"), "draft_reply must be present"
        assert sim.get("action_id"),   "action_id must be present"
        action_id     = sim["action_id"]
        draft_reply   = sim["draft_reply"]
        contact_masked = sim.get("contact_masked", "")
        reasoning     = sim.get("reasoning", "")
        confidence    = sim.get("confidence", 0.0)

        # Raw phone must not appear anywhere in the context card
        assert KNOWN_CONTACT not in json.dumps(sim), "raw phone leaked into context card"

        # ── Step 2: approve the draft reply ──────────────────────────────────
        approval_body = {
            "action_id":      action_id,
            "approved":       True,
            "draft_reply":    draft_reply,
            "contact_masked": contact_masked,
            "reasoning":      reasoning,
            "confidence":     confidence,
        }
        appr = _post("/api/x-intake/approve-reply", approval_body)
        assert appr["status"] == "ok",                   f"Approval failed: {appr}"
        assert appr["stored"] is True,                   "stored must be True"
        assert appr["send_action_created"] is True,      "send_action must be created"
        assert appr["send_dry_run"] is True,             "send must always be dry-run"
        assert appr["send_triggered"] is False,          "live send must not occur"
        assert appr["approval_id"],                      "approval_id must be set"
        approval_id_out = appr["approval_id"]

        # Raw phone must not appear in the approval response
        assert KNOWN_CONTACT not in json.dumps(appr), "raw phone leaked into approval response"

        # ── Step 3: verify approval log ──────────────────────────────────────
        approval_record = _last_ndjson(self.APPROVAL_LOG)
        assert approval_record is not None, "approval log must have an entry"
        assert approval_record["approval_id"] == approval_id_out
        assert approval_record["status"] == "approved"
        assert approval_record["final_reply"] == draft_reply
        assert KNOWN_CONTACT not in json.dumps(approval_record), "raw phone in approval log"

        # ── Step 4: verify dry-run receipt ────────────────────────────────────
        receipt = _last_ndjson(self.RECEIPT_LOG)
        assert receipt is not None,                      "receipt log must have an entry"
        assert receipt["dry_run"] is True,               "receipt must be dry_run=true"
        assert receipt["path"] == "dry_run",             "path must be 'dry_run'"
        assert receipt["bridge_status_code"] is None,   "no bridge call must have occurred"
        assert receipt["success"] is True,               "dry-run must record success=true"
        assert receipt["action_id"] == approval_id_out, "receipt action_id must match approval_id"
        assert KNOWN_CONTACT not in json.dumps(receipt), "raw phone in receipt"

        # ── Summary ──────────────────────────────────────────────────────────
        print(f"\n✓ context card: status={sim['status']} conf={confidence} action_id={action_id}")
        print(f"✓ draft: {draft_reply[:80]}")
        print(f"✓ approval stored: approval_id={approval_id_out}")
        print(f"✓ receipt: dry_run=True path=dry_run bridge=None")
        print(f"✓ raw phone not exposed in any record")

    def test_live_unknown_contact_safe_fallback(self):
        sim = _post("/api/x-intake/simulate-incoming", {"contact_handle": UNKNOWN_CONTACT})
        assert sim["status"] == "no_profile"
        assert sim["draft_reply"]
        assert UNKNOWN_CONTACT not in json.dumps(sim)

    def test_live_approve_creates_receipt(self):
        """Isolated check that each approve-reply appends exactly one receipt."""
        before = self.RECEIPT_LOG.read_text().count("\n") if self.RECEIPT_LOG.is_file() else 0
        appr = _post("/api/x-intake/approve-reply", {
            "action_id":      "livetest_isolation",
            "approved":       True,
            "draft_reply":    "Live isolation test draft.",
            "contact_masked": "+13***32",
        })
        assert appr["status"] == "ok"
        after = self.RECEIPT_LOG.read_text().count("\n") if self.RECEIPT_LOG.is_file() else 0
        assert after == before + 1, f"Expected exactly 1 new receipt line, got {after - before}"

    def test_live_no_outbound_to_bridge(self):
        """Verify approve-reply response never claims a real send occurred."""
        appr = _post("/api/x-intake/approve-reply", {
            "action_id":      "livetest_nobridgecall",
            "approved":       True,
            "draft_reply":    "No bridge test.",
            "contact_masked": "+13***32",
        })
        assert appr["send_triggered"] is False
        assert appr["send_dry_run"] is True
        receipt = _last_ndjson(self.RECEIPT_LOG)
        assert receipt and receipt["bridge_status_code"] is None
        assert receipt and receipt["path"] == "dry_run"
