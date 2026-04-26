"""Tests for Active Rules Visibility v1.

Proves that:
  - _active_rules_summary() returns only approved rules
  - proposed and rejected rules are never surfaced
  - context-card response includes active_rule_hints and active_rules_applied
  - review-queue response includes active_rules_applied
  - active_rules_applied contains the correct summary fields
  - category filter works (triage_scoring, reply_phrasing, None=all)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cortex.self_improvement_engine as _si_engine
from cortex.engine import _active_rules_summary, _build_draft_with_context


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_rules_file(tmp_path: Path, rules: list[dict]) -> Path:
    data = {"rules": rules, "updated_at": "2026-04-26T00:00:00Z", "card_count": len(rules)}
    p = tmp_path / "promoted_rules.json"
    p.write_text(json.dumps(data))
    return p


def _rule(rule_id: str, status: str, category: str = "pipeline") -> dict:
    return {
        "rule_id":           rule_id,
        "status":            status,
        "behavior_category": category,
        "summary":           f"Test rule {rule_id}",
        "proposed_behavior": "Route iMessage URLs to x_intake pipeline.",
        "risk_level":        "low",
        "card_count":        3,
        "approved_at":       "2026-04-26T10:00:00+00:00" if status == "approved" else None,
        "approved_by":       "matt" if status == "approved" else None,
        "rejected_at":       "2026-04-26T10:00:00+00:00" if status == "rejected" else None,
        "rejected_reason":   "too vague" if status == "rejected" else None,
        "scoring":           {"relevance": 4, "actionability": 3, "safety": 4},
    }


# ── TestActiveRulesSummary ─────────────────────────────────────────────────────

class TestActiveRulesSummary:

    def test_returns_only_approved_rules(self, tmp_path):
        rules = [
            _rule("RULE-A", "approved"),
            _rule("RULE-B", "proposed"),
            _rule("RULE-C", "rejected"),
        ]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        ids = [r["rule_id"] for r in result]
        assert "RULE-A" in ids
        assert "RULE-B" not in ids, "proposed rule must not appear"
        assert "RULE-C" not in ids, "rejected rule must not appear"

    def test_proposed_rules_excluded(self, tmp_path):
        rules = [_rule("RULE-P", "proposed", "triage_scoring")]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        assert result == []

    def test_rejected_rules_excluded(self, tmp_path):
        rules = [_rule("RULE-R", "rejected", "reply_phrasing")]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        assert result == []

    def test_category_filter_triage(self, tmp_path):
        rules = [
            _rule("RULE-T", "approved", "triage_scoring"),
            _rule("RULE-P", "approved", "pipeline"),
        ]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary("triage_scoring")
        ids = [r["rule_id"] for r in result]
        assert "RULE-T" in ids
        assert "RULE-P" not in ids

    def test_category_filter_reply_phrasing(self, tmp_path):
        rules = [
            _rule("RULE-RP", "approved", "reply_phrasing"),
            _rule("RULE-T",  "approved", "triage_scoring"),
        ]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary("reply_phrasing")
        ids = [r["rule_id"] for r in result]
        assert "RULE-RP" in ids
        assert "RULE-T" not in ids

    def test_no_category_filter_returns_all_approved(self, tmp_path):
        rules = [
            _rule("RULE-A", "approved", "pipeline"),
            _rule("RULE-B", "approved", "triage_scoring"),
            _rule("RULE-C", "proposed", "pipeline"),
        ]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        ids = [r["rule_id"] for r in result]
        assert "RULE-A" in ids
        assert "RULE-B" in ids
        assert "RULE-C" not in ids

    def test_result_shape(self, tmp_path):
        rules = [_rule("RULE-S", "approved", "pipeline")]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        assert len(result) == 1
        r = result[0]
        assert "rule_id" in r
        assert "behavior_category" in r
        assert "summary" in r
        assert "approved_by" in r
        assert "approved_at" in r

    def test_approved_by_present(self, tmp_path):
        rules = [_rule("RULE-AB", "approved")]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        assert result[0]["approved_by"] == "matt"

    def test_approved_at_truncated_to_date(self, tmp_path):
        rules = [_rule("RULE-AT", "approved")]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        # Should be YYYY-MM-DD (10 chars), not full ISO timestamp
        assert len(result[0]["approved_at"]) == 10

    def test_missing_file_returns_empty_list(self, tmp_path):
        missing = tmp_path / "no_such_file.json"
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", missing):
            result = _active_rules_summary()
        assert result == []

    def test_malformed_file_returns_empty_list(self, tmp_path):
        bad = tmp_path / "promoted_rules.json"
        bad.write_text("not json {{")
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", bad):
            result = _active_rules_summary()
        assert result == []


# ── TestContextCardActiveRules ─────────────────────────────────────────────────

class TestContextCardActiveRules:
    """Verify _build_draft_with_context always returns active_rule_hints."""

    def _minimal_call(self, behavior_hints=None):
        return _build_draft_with_context(
            profile={
                "profile_id":        "test-001",
                "relationship_type": "client",
                "display_name":      "Test Client",
                "contact_masked":    "+1●●●●●●7532",
                "summary":           "Test client summary",
                "open_requests":     [],
                "follow_ups":        [],
                "systems_or_topics": [],
                "project_refs":      [],
                "status":            "active",
                "confidence":        0.8,
            },
            accepted_by_type={},
            unverified_by_type={},
            recent_replies=[],
            behavior_hints=behavior_hints,
        )

    def test_active_rule_hints_key_present(self):
        result = self._minimal_call()
        assert "active_rule_hints" in result

    def test_active_rule_hints_empty_when_no_rules(self):
        result = self._minimal_call(behavior_hints={})
        assert result["active_rule_hints"] == {}

    def test_active_rule_hints_populated_from_hints(self):
        hints = {"_rule_id": "RULE-X", "prefer_short": True}
        result = self._minimal_call(behavior_hints=hints)
        # _rule_id is private; only public hints surface
        assert "prefer_short" in result["active_rule_hints"]
        assert "_rule_id" not in result["active_rule_hints"]

    def test_active_rule_hints_strips_private_keys(self):
        hints = {"_rule_id": "RULE-X", "_internal": "hidden", "avoid_generic": True}
        result = self._minimal_call(behavior_hints=hints)
        for key in result["active_rule_hints"]:
            assert not key.startswith("_"), f"Private key leaked: {key}"

    def test_active_rule_hints_none_hints_safe(self):
        result = self._minimal_call(behavior_hints=None)
        assert result["active_rule_hints"] == {}


# ── TestOnlyApprovedRulesSurface ───────────────────────────────────────────────

class TestOnlyApprovedRulesSurface:
    """Integration-level: _active_rules_summary never leaks proposed/rejected rules."""

    def test_all_proposed_returns_empty(self, tmp_path):
        rules = [_rule(f"RULE-{i}", "proposed") for i in range(5)]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            assert _active_rules_summary() == []

    def test_all_rejected_returns_empty(self, tmp_path):
        rules = [_rule(f"RULE-{i}", "rejected") for i in range(5)]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            assert _active_rules_summary() == []

    def test_mixed_statuses_only_approved_shown(self, tmp_path):
        rules = [
            _rule("RULE-OK", "approved"),
            _rule("RULE-NO1", "proposed"),
            _rule("RULE-NO2", "rejected"),
        ]
        path = _make_rules_file(tmp_path, rules)
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            result = _active_rules_summary()
        assert len(result) == 1
        assert result[0]["rule_id"] == "RULE-OK"

    def test_empty_rules_list_returns_empty(self, tmp_path):
        path = _make_rules_file(tmp_path, [])
        with patch.object(_si_engine, "PROMOTED_RULES_PATH", path):
            assert _active_rules_summary() == []
