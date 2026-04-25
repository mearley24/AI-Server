"""Tests for self-improvement rule approval and activation.

Covers:
  - approve_rule updates JSON correctly (status, approved_at, approved_by)
  - reject_rule updates JSON correctly (status, rejected_at, rejected_reason)
  - get_active_rules returns only approved rules
  - reply drafting receives active_rules path (behavior_hints parameter)
  - triage scoring adjusts when a triage_scoring rule is active
  - no system crash when rules file missing or malformed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_rules_file(tmp_path: Path, rules: list[dict]) -> Path:
    data = {"rules": rules, "updated_at": "2026-04-25T00:00:00Z", "card_count": len(rules)}
    p = tmp_path / "promoted_rules.json"
    p.write_text(json.dumps(data))
    return p


def _sample_rule(rule_id: str = "RULE-TEST-001", status: str = "proposed") -> dict:
    return {
        "rule_id": rule_id,
        "source_card": "test-card.md",
        "summary": "Test rule summary",
        "proposed_behavior": "When a repeat contact is detected, prioritize repeat contacts in triage scoring.",
        "risk_level": "low",
        "status": status,
        "created_at": "2026-04-25T00:00:00Z",
        "card_count": 1,
        "scoring": {"relevance": 3, "actionability": 3, "safety": 4},
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_reason": None,
        "behavior_category": "triage_scoring",
    }


# ── Import engine under test (with path override) ────────────────────────────

import cortex.self_improvement_engine as _engine


# ── approve_rule ──────────────────────────────────────────────────────────────

class TestApproveRule:

    def test_approve_sets_status_approved(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-A-001")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.approve_rule("RULE-A-001", approved_by="matt")
        assert result.get("status") == "approved"

    def test_approve_sets_approved_at(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-A-002")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.approve_rule("RULE-A-002")
        assert result.get("approved_at") is not None
        assert "2026" in result["approved_at"] or "T" in result["approved_at"]

    def test_approve_sets_approved_by(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-A-003")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.approve_rule("RULE-A-003", approved_by="matt")
        assert result.get("approved_by") == "matt"

    def test_approve_persists_to_file(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-A-004")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            _engine.approve_rule("RULE-A-004")
            data = json.loads(rules_path.read_text())
        rule = next(r for r in data["rules"] if r["rule_id"] == "RULE-A-004")
        assert rule["status"] == "approved"

    def test_approve_unknown_rule_returns_error(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-A-005")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.approve_rule("RULE-DOES-NOT-EXIST")
        assert "error" in result

    def test_approve_already_approved_returns_error(self, tmp_path):
        rule = _sample_rule("RULE-A-006", status="approved")
        rules_path = _make_rules_file(tmp_path, [rule])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.approve_rule("RULE-A-006")
        assert "error" in result


# ── reject_rule ───────────────────────────────────────────────────────────────

class TestRejectRule:

    def test_reject_sets_status_rejected(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-R-001")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.reject_rule("RULE-R-001", reason="not relevant")
        assert result.get("status") == "rejected"

    def test_reject_sets_rejected_reason(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-R-002")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.reject_rule("RULE-R-002", reason="out of scope")
        assert result.get("rejected_reason") == "out of scope"

    def test_reject_sets_rejected_at(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-R-003")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.reject_rule("RULE-R-003")
        assert result.get("rejected_at") is not None

    def test_reject_persists_to_file(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-R-004")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            _engine.reject_rule("RULE-R-004", reason="test")
            data = json.loads(rules_path.read_text())
        rule = next(r for r in data["rules"] if r["rule_id"] == "RULE-R-004")
        assert rule["status"] == "rejected"
        assert rule["rejected_reason"] == "test"

    def test_reject_unknown_rule_returns_error(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-R-005")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            result = _engine.reject_rule("RULE-DOES-NOT-EXIST")
        assert "error" in result


# ── get_active_rules ──────────────────────────────────────────────────────────

class TestGetActiveRules:

    def test_only_approved_rules_returned(self, tmp_path):
        rules = [
            _sample_rule("RULE-G-001", status="proposed"),
            _sample_rule("RULE-G-002", status="approved"),
            _sample_rule("RULE-G-003", status="rejected"),
        ]
        rules[1]["approved_at"] = "2026-04-25T01:00:00Z"
        rules_path = _make_rules_file(tmp_path, rules)
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            active = _engine.get_active_rules()
        assert len(active) == 1
        assert active[0]["rule_id"] == "RULE-G-002"

    def test_returns_empty_when_no_approved(self, tmp_path):
        rules_path = _make_rules_file(tmp_path, [_sample_rule("RULE-G-004", status="proposed")])
        with patch.object(_engine, "PROMOTED_RULES_PATH", rules_path):
            active = _engine.get_active_rules()
        assert active == []

    def test_returns_empty_when_file_missing(self, tmp_path):
        missing = tmp_path / "nonexistent_rules.json"
        with patch.object(_engine, "PROMOTED_RULES_PATH", missing):
            active = _engine.get_active_rules()
        assert active == []

    def test_returns_empty_when_file_malformed(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{")
        with patch.object(_engine, "PROMOTED_RULES_PATH", bad):
            active = _engine.get_active_rules()
        assert active == []


# ── reply drafting receives behavior_hints ────────────────────────────────────

class TestReplyDraftingReceivesRules:

    def test_build_draft_accepts_behavior_hints_param(self):
        """_build_draft_with_context must accept behavior_hints without crashing."""
        from cortex.engine import _build_draft_with_context
        result = _build_draft_with_context(
            profile={"relationship_type": "client", "open_requests": [], "systems_or_topics": [], "follow_ups": []},
            accepted_by_type={},
            unverified_by_type={},
            recent_replies=[],
            behavior_hints={"prefer_short": True, "_rule_id": "RULE-TEST"},
        )
        assert "draft_reply" in result
        assert "active_rule_hints" in result

    def test_build_draft_no_crash_on_none_hints(self):
        from cortex.engine import _build_draft_with_context
        result = _build_draft_with_context(
            profile={"relationship_type": "unknown", "open_requests": [], "systems_or_topics": [], "follow_ups": []},
            accepted_by_type={},
            unverified_by_type={},
            recent_replies=[],
            behavior_hints=None,
        )
        assert "draft_reply" in result

    def test_apply_reply_hints_empty_for_no_active_rules(self):
        hints = _engine.apply_reply_hints([])
        assert hints == {}

    def test_apply_reply_hints_returns_dict_for_phrasing_rule(self):
        rule = _sample_rule("RULE-H-001", status="approved")
        rule["behavior_category"] = "reply_phrasing"
        rule["proposed_behavior"] = "Avoid generic phrasing in draft replies; prefer specific language."
        rule["approved_at"] = "2026-04-25T01:00:00Z"
        hints = _engine.apply_reply_hints([rule])
        assert isinstance(hints, dict)
        assert "_rule_id" in hints
        assert hints.get("avoid_generic") is True


# ── triage scoring adjusts with active rules ──────────────────────────────────

class TestTriageScoringWithRules:

    def test_apply_triage_boost_no_rules_returns_base(self):
        base = 0.5
        result = _engine.apply_triage_boost([], base)
        assert result == base

    def test_apply_triage_boost_prioritize_repeat_increases_score(self):
        rule = _sample_rule("RULE-T-001", status="approved")
        rule["behavior_category"] = "triage_scoring"
        rule["proposed_behavior"] = "Prioritize repeat contacts in triage scoring to surface ongoing relationships."
        rule["approved_at"] = "2026-04-25T01:00:00Z"
        base = 0.5
        result = _engine.apply_triage_boost([rule], base)
        assert result > base

    def test_apply_triage_boost_capped_at_1(self):
        rule = _sample_rule("RULE-T-002", status="approved")
        rule["behavior_category"] = "triage_scoring"
        rule["proposed_behavior"] = "Prioritize repeat contacts in triage scoring."
        rule["approved_at"] = "2026-04-25T01:00:00Z"
        result = _engine.apply_triage_boost([rule], 1.0)
        assert result <= 1.0

    def test_apply_triage_boost_ignores_non_triage_rules(self):
        rule = _sample_rule("RULE-T-003", status="approved")
        rule["behavior_category"] = "pipeline"
        rule["approved_at"] = "2026-04-25T01:00:00Z"
        base = 0.5
        result = _engine.apply_triage_boost([rule], base)
        assert result == base


# ── no crash when rules missing or bad ────────────────────────────────────────

class TestRobustness:

    def test_get_active_rules_no_crash_file_missing(self, tmp_path):
        with patch.object(_engine, "PROMOTED_RULES_PATH", tmp_path / "nope.json"):
            result = _engine.get_active_rules()
        assert result == []

    def test_approve_no_crash_file_missing(self, tmp_path):
        with patch.object(_engine, "PROMOTED_RULES_PATH", tmp_path / "nope.json"):
            result = _engine.approve_rule("ANY-ID")
        assert "error" in result

    def test_apply_triage_boost_no_crash_on_bad_rule(self):
        bad_rule = {"behavior_category": "triage_scoring", "proposed_behavior": None, "approved_at": "x"}
        result = _engine.apply_triage_boost([bad_rule], 0.5)
        assert 0.0 <= result <= 1.0

    def test_apply_reply_hints_no_crash_on_empty_list(self):
        result = _engine.apply_reply_hints([])
        assert result == {}

    def test_derive_category_pipeline(self):
        cat = _engine._derive_category("Submit to x_intake ingest endpoint via iMessage bridge")
        assert cat == "pipeline"

    def test_derive_category_triage_scoring(self):
        cat = _engine._derive_category("Adjust triage scoring weight for prioritize repeat contacts")
        assert cat == "triage_scoring"

    def test_derive_category_general_fallback(self):
        cat = _engine._derive_category("Some unrelated behavior description")
        assert cat == "general"
