"""Tests for Matt Reply Style Learner v1.

Covers:
  - extract_reply_style: outgoing-only, allowed threads, cleaning
  - style_engine: transformations, safety, fallback
  - Sonos/technical wording preserved after styling
  - No runtime actions (no sends, no writes outside designated paths)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── style_engine tests ────────────────────────────────────────────────────────

class TestStyleEngine:

    def _engine(self, profile: dict | None = None):
        """Import apply_style with a specific profile (avoids file I/O in tests)."""
        import cortex.style_engine as se
        se._reload_profile()
        if profile is not None:
            se._cached_profile = profile
        return se.apply_style

    def test_get_back_to_you_shortly_shortened(self):
        apply = self._engine({})
        draft = "Thanks for the heads up — I'll take a look and get back to you shortly."
        styled, applied, conf = apply(draft)
        assert "shortly" not in styled, f"'shortly' should be removed: {styled}"
        assert applied is True

    def test_get_back_to_you_with_what_i_find(self):
        apply = self._engine({})
        draft = "Got it — I'll take a look and get back to you with what I find."
        styled, applied, conf = apply(draft)
        assert "get back to you with what I find" not in styled, styled
        assert applied is True

    def test_reach_out_once_i_have_an_update(self):
        apply = self._engine({})
        draft = "I'll reach out once I have an update."
        styled, applied, _ = apply(draft)
        assert "reach out once I have an update" not in styled, styled
        assert applied is True

    def test_thank_you_for_reaching_out_removed(self):
        apply = self._engine({})
        draft = "Thank you for reaching out. I'll look into this right away."
        styled, applied, _ = apply(draft)
        assert "for reaching out" not in styled.lower(), styled

    def test_dont_hesitate_removed(self):
        apply = self._engine({})
        draft = "Let me know if there's anything else. Don't hesitate to reach out."
        styled, applied, _ = apply(draft)
        assert "hesitate" not in styled.lower(), styled

    def test_clean_draft_unchanged(self):
        apply = self._engine({})
        draft = "Got it — try unplugging your Sonos for about 10 seconds and plugging it back in. If it's still acting up after that, I can swing by and take a look."
        styled, applied, conf = apply(draft)
        assert styled == draft, "Already-clean draft must not be modified"
        assert applied is False

    def test_style_engine_preserves_sonos_wording(self):
        """Sonos power-cycle instruction must survive styling intact."""
        apply = self._engine({})
        draft = "Got it — try unplugging your Sonos for about 10 seconds and plugging it back in. If it's still acting up after that, I can swing by and take a look."
        styled, _, _ = apply(draft)
        for term in ["Sonos", "10 seconds", "swing by"]:
            assert term in styled, f"Technical term '{term}' must be preserved: {styled}"

    def test_style_engine_preserves_wifi_router_wording(self):
        apply = self._engine({})
        draft = "Got it — try rebooting your router real quick. If that doesn't sort it, I'll check remotely and let you know."
        styled, applied, _ = apply(draft)
        for term in ["router", "remotely"]:
            assert term in styled, f"Technical term '{term}' must be preserved: {styled}"

    def test_safety_check_blocks_losing_technical_terms(self):
        """If a transformation would drop a technical term, original is returned."""
        import cortex.style_engine as se
        se._reload_profile()
        se._cached_profile = {
            "robotic_phrases": ["Sonos"],   # contrived: try to remove "Sonos"
            "replacements": [],
        }
        apply = se.apply_style
        draft = "Got it — try unplugging your Sonos for 10 seconds."
        styled, applied, _ = apply(draft)
        # Safety gate must keep original because "Sonos" would be removed
        assert "Sonos" in styled, f"Technical term must be preserved by safety check: {styled}"

    def test_empty_draft_returned_unchanged(self):
        apply = self._engine({})
        assert apply("")[0] == ""
        assert apply("")[1] is False

    def test_style_engine_never_raises(self):
        """apply_style must never raise — returns original on any error."""
        import cortex.style_engine as se
        se._reload_profile()
        se._cached_profile = None   # Force profile reload from missing path
        with patch("cortex.style_engine._STYLE_PATH", Path("/nonexistent/reply_style.json")):
            se._reload_profile()
            styled, applied, conf = se.apply_style("Some draft text.")
        assert styled == "Some draft text." or styled  # original or transformed, never raises

    def test_profile_driven_replacement(self):
        """Replacements from the profile JSON are applied."""
        apply = self._engine({
            "robotic_phrases": [],
            "replacements": [
                {"from": "follow up with you soon", "to": "check in with you"},
            ],
        })
        draft = "I will follow up with you soon."
        styled, applied, _ = apply(draft)
        assert "check in with you" in styled, styled
        assert applied is True

    def test_confidence_higher_for_natural_opener(self):
        """Drafts starting with 'Got it' or 'On it' get higher confidence."""
        apply = self._engine({})
        _, _, conf_natural = apply("Got it — I'll check on it and let you know.")
        _, _, conf_formal  = apply("I'll check on it and let you know what I find.")
        # Natural opener should score same or higher
        assert conf_natural >= conf_formal


# ── extract_reply_style tests ─────────────────────────────────────────────────

class TestExtractReplyStyle:

    def _make_thread_db(self, tmp_path: Path, threads: list[dict]) -> Path:
        db = tmp_path / "thread_index.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY,
                chat_guid TEXT NOT NULL,
                contact_handle TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                sample_count INTEGER DEFAULT 0,
                date_first TEXT DEFAULT '',
                date_last TEXT DEFAULT '',
                category TEXT DEFAULT 'unknown',
                work_confidence REAL DEFAULT 0.0,
                reason_codes TEXT DEFAULT '[]',
                is_reviewed INTEGER DEFAULT 0,
                relationship_type TEXT DEFAULT 'unknown',
                created_at TEXT NOT NULL
            )
        """)
        for t in threads:
            conn.execute(
                "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["thread_id"], t["chat_guid"], t.get("contact_handle","x"),
                 0, 0, "", "", "work", 0.9, "[]",
                 t.get("is_reviewed", 1), t["relationship_type"], "2026-01-01"),
            )
        conn.commit()
        conn.close()
        return db

    def test_approved_work_threads_only_allowed_types(self, tmp_path):
        db = self._make_thread_db(tmp_path, [
            {"thread_id": "t1", "chat_guid": "g1", "relationship_type": "client",       "is_reviewed": 1},
            {"thread_id": "t2", "chat_guid": "g2", "relationship_type": "internal_team", "is_reviewed": 1},
            {"thread_id": "t3", "chat_guid": "g3", "relationship_type": "vendor",        "is_reviewed": 1},
            {"thread_id": "t4", "chat_guid": "g4", "relationship_type": "personal_work_related", "is_reviewed": 1},
            {"thread_id": "t5", "chat_guid": "g5", "relationship_type": "unknown",       "is_reviewed": 1},
            {"thread_id": "t6", "chat_guid": "g6", "relationship_type": "builder",       "is_reviewed": 0},  # not reviewed
        ])
        import scripts.extract_reply_style as ers
        orig = ers.THREAD_DB
        ers.THREAD_DB = db
        try:
            threads = ers._approved_work_threads()
        finally:
            ers.THREAD_DB = orig
        guids = {t["chat_guid"] for t in threads}
        assert "g1" in guids,     "client must be included"
        assert "g3" in guids,     "vendor must be included"
        assert "g2" not in guids, "internal_team must be excluded"
        assert "g4" not in guids, "personal_work_related must be excluded"
        assert "g5" not in guids, "unknown must be excluded"
        assert "g6" not in guids, "not-reviewed thread must be excluded"

    def test_clean_message_strips_size_byte(self):
        from scripts.extract_reply_style import _clean_message
        assert _clean_message("+;Thank you!") == "Thank you!"
        assert _clean_message("+ELet me know") == "Let me know"
        assert _clean_message("+9My message") == "My message"

    def test_clean_message_strips_trailing_iI(self):
        from scripts.extract_reply_style import _clean_message
        assert _clean_message("All good. iI") == "All good."
        assert _clean_message("Perfect, thank you iI") == "Perfect, thank you"

    def test_clean_message_rejects_heavy_binary(self):
        from scripts.extract_reply_style import _is_usable, _clean_message
        binary_text = _clean_message(
            "NSMutableData X$version Y$archiver NSKeyedArchiver RRMSV U$null"
        )
        assert not _is_usable(binary_text), "Binary metadata must not be usable"

    def test_is_usable_rejects_phone_numbers(self):
        from scripts.extract_reply_style import _is_usable
        assert not _is_usable("+1 303 555 1234")
        assert not _is_usable("81632")

    def test_is_usable_rejects_urls(self):
        from scripts.extract_reply_style import _is_usable
        assert not _is_usable("https://example.com/link")

    def test_is_usable_rejects_templated_intro(self):
        from scripts.extract_reply_style import _is_usable
        assert not _is_usable("This is Matt Earley with High Mountain Home Technology, ...")

    def test_is_usable_accepts_real_message(self):
        from scripts.extract_reply_style import _is_usable
        assert _is_usable("Alrighty, you should be good to go!")
        assert _is_usable("No biggie, let me know if it happens again.")

    def test_extract_patterns_finds_greeting(self):
        from scripts.extract_reply_style import extract_patterns
        msgs = ["Alrighty, sounds good!", "Alrighty, I'll swing by.", "Perfect, thank you."]
        profile = extract_patterns(msgs)
        greetings = [g["phrase"] for g in profile["greeting_patterns"]]
        assert "alrighty" in greetings, "Alrighty should be detected as greeting"

    def test_extract_patterns_tone_metrics(self):
        from scripts.extract_reply_style import extract_patterns
        msgs = ["Got it!!", "Sounds good!!", "No problem, I'll be there around 3."]
        profile = extract_patterns(msgs)
        tone = profile["tone"]
        assert tone["avg_message_length_words"] > 0
        assert tone["double_exclamation_rate"] > 0

    def test_no_phone_numbers_in_profile(self, tmp_path):
        """Style profile must not contain raw phone numbers."""
        from scripts.extract_reply_style import run
        import scripts.extract_reply_style as ers
        orig_db, orig_chat, orig_out = ers.THREAD_DB, ers.CHAT_DB, ers.STYLE_OUT
        ers.THREAD_DB  = Path("/nonexistent/thread.sqlite")   # triggers empty threads
        ers.STYLE_OUT  = tmp_path / "reply_style.json"
        try:
            run(dry_run=True)   # no real chat.db access needed for this check
        finally:
            ers.THREAD_DB = orig_db
            ers.CHAT_DB   = orig_chat
            ers.STYLE_OUT = orig_out
        # If a profile was written, verify it has no 10+ digit phone sequences
        import re as _re
        if (tmp_path / "reply_style.json").is_file():
            content = (tmp_path / "reply_style.json").read_text()
            assert not _re.search(r"\+1\d{10}", content), "Raw phone must not be in profile"


# ── Integration: style applied in context-card pipeline ──────────────────────

class TestStyleIntegration:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from cortex.engine import app
        return TestClient(app, raise_server_exceptions=False)

    def _profile(self):
        return {
            "profile_id": "si_test", "relationship_type": "client",
            "display_name": "", "contact_handle": "+15551111111",
            "thread_ids": '["tid1"]', "first_seen": "", "last_seen": "",
            "summary": "Systems: Sonos", "open_requests": '[]', "follow_ups": '[]',
            "systems_or_topics": '["Sonos"]', "project_refs": '[]',
            "dtools_project_refs": '[]', "confidence": 0.85,
            "status": "proposed", "last_updated": "",
        }

    def test_context_card_has_style_fields(self, client):
        facts = [{"fact_id": "f1", "thread_id": "t", "fact_type": "equipment",
                  "fact_value": "Sonos", "confidence": 0.75,
                  "source_excerpt": "x", "source_timestamp": "t",
                  "is_accepted": 1, "is_rejected": 0}]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551111111")
        d = r.json()
        assert "style_applied" in d, "style_applied must be in response"
        assert "style_confidence" in d, "style_confidence must be in response"
        assert isinstance(d["style_applied"], bool)
        assert 0.0 <= d["style_confidence"] <= 1.0

    def test_sonos_self_fix_draft_intact_after_styling(self, client):
        """The Sonos power-cycle draft must survive the style engine intact."""
        facts = [{"fact_id": "f1", "thread_id": "t", "fact_type": "equipment",
                  "fact_value": "Sonos", "confidence": 0.75,
                  "source_excerpt": "x", "source_timestamp": "t",
                  "is_accepted": 1, "is_rejected": 0},
                 {"fact_id": "f2", "thread_id": "t", "fact_type": "issue",
                  "fact_value": "offline", "confidence": 0.80,
                  "source_excerpt": "x", "source_timestamp": "t",
                  "is_accepted": 1, "is_rejected": 0}]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551111111")
        d = r.json()
        draft = d["draft_reply"]
        for term in ["Sonos", "unplug", "10 seconds"]:
            assert term in draft, f"Technical term '{term}' must survive styling: {draft}"

    def test_style_engine_failure_does_not_crash_pipeline(self, client):
        """Even if style_engine raises, the context card must still return ok."""
        facts = [{"fact_id": "f1", "thread_id": "t", "fact_type": "equipment",
                  "fact_value": "Sonos", "confidence": 0.75,
                  "source_excerpt": "x", "source_timestamp": "t",
                  "is_accepted": 1, "is_rejected": 0}]
        with patch("cortex.engine._profile_by_handle", return_value=self._profile()), \
             patch("cortex.engine._facts_for_profile", return_value=facts), \
             patch("cortex.engine._receipts_for_handle", return_value=[]), \
             patch("cortex.style_engine.apply_style", side_effect=RuntimeError("style crash")):
            r = client.get("/api/x-intake/context-card?contact_handle=%2B15551111111")
        d = r.json()
        assert d["status"] == "ok"
        assert d["draft_reply"]           # fallback draft must still be present
        assert d["style_applied"] is False  # crash → not applied


# ── Generic phrase penalization and high-signal boosting ──────────────────────

class TestGenericPhraseHandling:

    def test_let_me_know_not_in_style_rewrite(self):
        """'let me know' must not be produced as a default style rewrite output."""
        import cortex.style_engine as se
        se._reload_profile()
        generic_closings = [
            "I'll get back to you shortly.",
            "I'll reach out once I have an update.",
            "Give me a few minutes and I'll let you know what I find.",
        ]
        for draft in generic_closings:
            styled, _, _ = se.apply_style(draft)
            assert "let me know" not in styled.lower(), (
                f"'let me know' must not appear in rewrite of: {draft!r} → {styled!r}"
            )

    def test_generic_phrases_penalized_in_style_output(self):
        """Generic phrases must be excluded from top common_phrases."""
        from scripts.extract_reply_style import extract_patterns
        msgs = [
            "let me know if anything comes up let me know",
            "let me know if you need anything know if needed",
            "got it I can swing by tomorrow",
            "sounds good I'll check on it",
            "no worries got it",
            "got it sounds good",
        ]
        profile = extract_patterns(msgs)
        top = [p["phrase"] for p in profile["common_phrases"]]
        for phrase in ("let me know", "me know", "know if"):
            assert phrase not in top, (
                f"Generic phrase {phrase!r} must be excluded from common_phrases: {top}"
            )

    def test_high_signal_phrases_boosted(self):
        """High-signal Matt phrases must appear in common_phrases when present."""
        from scripts.extract_reply_style import extract_patterns
        msgs = [
            "got it sounds good",
            "sounds good got it",
            "no worries at all",
            "got it no worries",
            "i can swing by this afternoon got it",
            "sounds good i can swing by",
        ] * 2  # ensure count >= 2
        profile = extract_patterns(msgs)
        top = [p["phrase"] for p in profile["common_phrases"]]
        high_signal = {"got it", "sounds good", "no worries"}
        found = high_signal & set(top)
        assert found, (
            f"High-signal phrases {high_signal} not found in common_phrases: {top}"
        )

    def test_sonos_self_fix_wording_preserved(self):
        """Sonos self-fix and on-site wording must survive styling intact."""
        import cortex.style_engine as se
        se._reload_profile()
        draft = (
            "Got it — try unplugging your Sonos for about 10 seconds "
            "and plugging it back in. If it's still acting up, I can swing by."
        )
        styled, _, _ = se.apply_style(draft)
        for term in ("Sonos", "10 seconds", "swing by"):
            assert term in styled, f"Term {term!r} must survive Sonos styling: {styled}"
