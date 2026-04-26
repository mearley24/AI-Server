"""Tests for the Reply Suggestion Engine (cortex/reply_suggest.py).

Covers:
  - build_suggestion returns expected shape
  - applied_rules contains only approved rules (reply_phrasing / triage_scoring)
  - avoid_generic + prefer_short hints are reflected in prompt
  - prefer_short enforced in scoring
  - no external API usage (Ollama is mocked)
  - graceful failure when Ollama is unavailable
  - _build_prompt includes message_text and relationship context
  - _clean_response strips <think> tokens
  - _contains_generic detects filler phrases
  - _score_confidence range and fields
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.reply_suggest import (
    build_suggestion,
    _build_prompt,
    _clean_response,
    _contains_generic,
    _score_confidence,
    _GENERIC_PHRASES,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _profile(rel_type="client", name="Test Client") -> dict:
    return {
        "profile_id":        "p-001",
        "relationship_type": rel_type,
        "display_name":      name,
        "summary":           "Installed Control4 system in 2024.",
        "systems_or_topics": ["Control4", "Lutron"],
        "open_requests":     ["shades calibration"],
    }


def _rule(rule_id="RULE-X", category="reply_phrasing", status="approved") -> dict:
    return {
        "rule_id":           rule_id,
        "status":            status,
        "behavior_category": category,
        "summary":           f"Test rule {category}",
        "approved_by":       "matt",
    }


def _mock_ollama_response(text: str) -> MagicMock:
    """Return a mock httpx response that yields the given text."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"response": text})
    return mock_resp


# ── TestBuildSuggestion ────────────────────────────────────────────────────────

class TestBuildSuggestion:
    """End-to-end shape and behavior tests with Ollama mocked."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _make_mock_client(self, reply_text: str):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"response": reply_text})
        mock_client.post = AsyncMock(return_value=mock_resp)
        return mock_client

    def _call(self, reply_text="Got it — I'll check on it.", **kwargs):
        defaults = dict(
            contact_handle="+13035557532",
            message_text="My shades aren't responding.",
            profile=_profile(),
            accepted_by_type={"equipment": [{"fact_type": "equipment", "fact_value": "Lutron", "is_accepted": 1}]},
            recent_replies=[],
            active_rules=[_rule("RULE-A", "reply_phrasing")],
            behavior_hints={"avoid_generic": True, "prefer_short": True},
            ollama_host="http://localhost:11434",
            ollama_model="qwen3:8b",
        )
        defaults.update(kwargs)
        mock_client = self._make_mock_client(reply_text)
        with patch("httpx.AsyncClient", return_value=mock_client):
            return self._run(build_suggestion(**defaults))

    def test_returns_ok_status(self):
        result = self._call()
        assert result["status"] == "ok"

    def test_returns_draft_string(self):
        result = self._call("Got it, checking now.")
        assert isinstance(result["draft"], str)
        assert len(result["draft"]) > 0

    def test_confidence_in_range(self):
        result = self._call()
        assert 0.0 <= result["confidence"] <= 1.0

    def test_applied_rules_present(self):
        result = self._call()
        assert "applied_rules" in result
        assert isinstance(result["applied_rules"], list)

    def test_reasoning_present(self):
        result = self._call()
        assert "reasoning" in result
        assert result["reasoning"]

    def test_applied_rules_only_reply_phrasing_and_triage(self):
        rules = [
            _rule("RULE-A", "reply_phrasing"),
            _rule("RULE-B", "triage_scoring"),
            _rule("RULE-C", "pipeline"),    # pipeline should be excluded
            _rule("RULE-D", "general"),     # general should be excluded
        ]
        result = self._call(active_rules=rules)
        ids = [r["rule_id"] for r in result["applied_rules"]]
        assert "RULE-A" in ids
        assert "RULE-B" in ids
        assert "RULE-C" not in ids, "pipeline rules must not surface in applied_rules"
        assert "RULE-D" not in ids, "general rules must not surface in applied_rules"

    def test_no_profile_returns_ok_with_lower_confidence(self):
        result = self._call(profile=None, accepted_by_type={})
        assert result["status"] == "ok"
        assert result["confidence"] < 0.8

    def test_no_message_text_still_returns_draft(self):
        result = self._call(message_text="")
        assert result["status"] == "ok"
        assert isinstance(result["draft"], str)

    def test_think_tags_stripped_from_draft(self):
        raw = "<think>I should be brief here.</think>On it — I'll check now."
        result = self._call(reply_text=raw)
        assert "<think>" not in result["draft"]
        assert "On it" in result["draft"]

    def test_no_external_api_called(self):
        """Verify Ollama is called at localhost only — no external URL used."""
        captured_urls = []
        original = __import__("httpx").AsyncClient

        class TrackingClient:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, url, **kwargs):
                captured_urls.append(url)
                mock = MagicMock()
                mock.raise_for_status = MagicMock()
                mock.json = MagicMock(return_value={"response": "ok"})
                return mock

        with patch("httpx.AsyncClient", TrackingClient):
            result = self._run(build_suggestion(
                contact_handle="+13035557532",
                message_text="test",
                profile=_profile(),
                accepted_by_type={},
                recent_replies=[],
                active_rules=[],
                behavior_hints={},
                ollama_host="http://localhost:11434",
                ollama_model="qwen3:8b",
            ))

        assert len(captured_urls) == 1
        url = captured_urls[0]
        assert "localhost" in url or "127.0.0.1" in url or "host.docker.internal" in url, \
            f"Unexpected external URL: {url}"
        assert "openai.com" not in url
        assert "anthropic.com" not in url

    def test_ollama_failure_returns_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = self._run(build_suggestion(
                contact_handle="+13035557532",
                message_text="test",
                profile=_profile(),
                accepted_by_type={},
                recent_replies=[],
                active_rules=[],
                behavior_hints={},
                ollama_host="http://localhost:11434",
                ollama_model="qwen3:8b",
            ))
        assert result["status"] == "error"
        assert "Ollama" in result["error"]
        assert result["confidence"] == 0.0
        assert result["draft"] == ""


# ── TestBuildPrompt ────────────────────────────────────────────────────────────

class TestBuildPrompt:

    def _prompt(self, **kwargs) -> str:
        defaults = dict(
            message_text="My lights won't turn on.",
            relationship_type="client",
            display_name="Test Client",
            summary="Control4 install 2024.",
            systems=["Control4"],
            open_requests=[],
            recent_replies=[],
            behavior_hints={},
        )
        defaults.update(kwargs)
        return _build_prompt(**defaults)

    def test_includes_message_text(self):
        p = self._prompt(message_text="Thermostat is offline.")
        assert "Thermostat is offline" in p

    def test_includes_relationship_type(self):
        p = self._prompt(relationship_type="trade_partner")
        assert "trade partner" in p.lower()

    def test_includes_systems(self):
        p = self._prompt(systems=["Control4", "Lutron"])
        assert "Control4" in p
        assert "Lutron" in p

    def test_avoid_generic_rule_appears_in_prompt(self):
        p = self._prompt(behavior_hints={"avoid_generic": True})
        assert "generic filler" in p.lower() or "let me know" in p.lower()

    def test_prefer_short_rule_adds_length_constraint(self):
        p = self._prompt(behavior_hints={"prefer_short": True})
        assert "shorter is better" in p.lower() or "one or two" in p.lower()

    def test_no_hints_no_filler_restriction(self):
        p = self._prompt(behavior_hints={})
        # Without avoid_generic, the filler-phrase rule line is absent
        assert "Do NOT use generic filler" not in p

    def test_display_name_included_when_not_unknown(self):
        p = self._prompt(display_name="Sarah Jones")
        assert "Sarah Jones" in p

    def test_no_think_prefix_present(self):
        p = self._prompt()
        assert "/no_think" in p


# ── TestCleanResponse ──────────────────────────────────────────────────────────

class TestCleanResponse:

    def test_strips_think_block(self):
        raw = "<think>Let me reason through this carefully.</think>Got it, I'll check."
        assert _clean_response(raw) == "Got it, I'll check."

    def test_strips_multiline_think_block(self):
        raw = "<think>\nReasoning line 1.\nReasoning line 2.\n</think>\nOn it."
        assert _clean_response(raw) == "On it."

    def test_strips_surrounding_quotes(self):
        assert _clean_response('"Hello there."') == "Hello there."

    def test_strips_whitespace(self):
        assert _clean_response("  Got it.  ") == "Got it."

    def test_passthrough_clean_text(self):
        assert _clean_response("On it — I'll check now.") == "On it — I'll check now."

    def test_empty_string(self):
        assert _clean_response("") == ""


# ── TestContainsGeneric ────────────────────────────────────────────────────────

class TestContainsGeneric:

    def test_detects_let_me_know(self):
        assert _contains_generic("Please let me know if you need anything.")

    def test_detects_feel_free(self):
        assert _contains_generic("Feel free to reach out anytime.")

    def test_detects_hope_this_helps(self):
        assert _contains_generic("Hope this helps!")

    def test_clean_reply_not_flagged(self):
        assert not _contains_generic("On it — I'll check the system now.")

    def test_case_insensitive(self):
        # "please let me know" is in _GENERIC_PHRASES; check uppercased input matches
        assert _contains_generic("PLEASE LET ME KNOW if you need anything.")


# ── TestScoreConfidence ────────────────────────────────────────────────────────

class TestScoreConfidence:

    def test_all_signals_high_confidence(self):
        score = _score_confidence(True, True, True, {"prefer_short": True}, True)
        assert score >= 0.9

    def test_no_profile_reduces_confidence(self):
        with_profile    = _score_confidence(True,  True, True, {}, True)
        without_profile = _score_confidence(False, True, True, {}, True)
        assert without_profile < with_profile

    def test_ollama_unavailable_returns_zero(self):
        assert _score_confidence(True, True, True, {}, False) == 0.0

    def test_score_in_range(self):
        for has_p in [True, False]:
            for has_m in [True, False]:
                score = _score_confidence(has_p, has_m, False, {}, True)
                assert 0.0 <= score <= 1.0

    def test_hints_add_small_boost(self):
        base  = _score_confidence(True, True, True, {}, True)
        boosted = _score_confidence(True, True, True, {"prefer_short": True}, True)
        assert boosted >= base
