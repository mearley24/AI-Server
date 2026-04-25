"""Tests for rule impact scoring and recommendation engine.

Covers:
  - impact_score calculated correctly
  - confidence_score calculated correctly
  - recommendation assigned correctly
  - high-risk rules never get recommendation=approve
  - duplicate rules get low impact
  - unclassified rules get ignore recommendation
  - no changes to system behavior (only scoring fields written)
  - behavior_category derived when absent
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

from scripts.evaluate_rule_impact import (
    score_rule,
    _effective_category,
    _derive_category,
    _extract_match_keywords,
    _is_duplicate,
    _count_card_matches,
    _PIPELINE_KEYWORDS,
    _TRIAGE_KEYWORDS,
    _DEDUP_KEYWORDS,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_rule(
    rule_id="RULE-TEST-001",
    status="proposed",
    risk_level="low",
    behavior_category=None,
    proposed_behavior="When the self-improvement collector detects an X.com URL in an iMessage, submit it to x_intake.",
    summary="Route iMessage X.com URLs to x_intake pipeline automatically.",
    card_count=7,
    scoring=None,
    include_category_key=True,
) -> dict:
    rule = {
        "rule_id": rule_id,
        "status": status,
        "risk_level": risk_level,
        "proposed_behavior": proposed_behavior,
        "summary": summary,
        "card_count": card_count,
        "scoring": scoring or {"relevance": 4, "actionability": 3, "safety": 4},
    }
    if include_category_key:
        rule["behavior_category"] = behavior_category
    return rule


def _sample_cards(n_pipeline=10, n_other=5) -> list[dict]:
    cards = []
    for i in range(n_pipeline):
        cards.append({"name": f"imessage-x-com-user-card-{i}.md", "text": f"imessage x.com url https://x.com/user/status/{i}"})
    for i in range(n_other):
        cards.append({"name": f"other-card-{i}.md", "text": f"email triage review follow-up client {i}"})
    return cards


def _sample_entries(n=5) -> list[dict]:
    return [{"title": f"entry {i}", "summary": "triage review", "details": "", "source": "cortex"} for i in range(n)]


# ── TestEffectiveCategory ──────────────────────────────────────────────────────

class TestEffectiveCategory:
    def test_uses_existing_category(self):
        rule = _make_rule(behavior_category="triage_scoring")
        assert _effective_category(rule) == "triage_scoring"

    def test_derives_pipeline_when_absent(self):
        rule = _make_rule(include_category_key=False,
                          proposed_behavior="Route iMessage URLs to x_intake pipeline.")
        assert _effective_category(rule) == "pipeline"

    def test_derives_pipeline_when_none(self):
        rule = _make_rule(behavior_category=None,
                          proposed_behavior="self-improvement collector detects imessage URL.")
        assert _effective_category(rule) == "pipeline"

    def test_derives_general_for_vague(self):
        rule = _make_rule(behavior_category=None,
                          proposed_behavior="Manual review required. No clear automation pattern.")
        assert _effective_category(rule) == "general"

    def test_derives_triage_scoring(self):
        rule = _make_rule(behavior_category=None,
                          proposed_behavior="Prioritize repeat contacts in triage scoring by boosting their review value score.")
        assert _effective_category(rule) == "triage_scoring"


# ── TestDeriveCategory ─────────────────────────────────────────────────────────

class TestDeriveCategory:
    def test_pipeline_from_imessage(self):
        assert _derive_category("process imessage x_intake url") == "pipeline"

    def test_pipeline_from_self_improvement_collector(self):
        assert _derive_category("extend the self-improvement collector to batch consolidat cards") == "pipeline"

    def test_triage_from_keywords(self):
        assert _derive_category("adjust triage scoring weight for repeat clients") == "triage_scoring"

    def test_reply_phrasing(self):
        assert _derive_category("avoid generic wording in draft reply") == "reply_phrasing"

    def test_follow_up_threshold(self):
        assert _derive_category("reduce follow-up threshold for urgent items") == "follow_up_threshold"

    def test_general_fallback(self):
        assert _derive_category("no actionable pattern found here") == "general"


# ── TestExtractMatchKeywords ───────────────────────────────────────────────────

class TestExtractMatchKeywords:
    def test_pipeline_rule_returns_pipeline_keywords(self):
        rule = _make_rule(behavior_category="pipeline")
        assert _extract_match_keywords(rule) == _PIPELINE_KEYWORDS

    def test_no_category_derives_pipeline(self):
        rule = _make_rule(behavior_category=None,
                          proposed_behavior="detect imessage urls and route to x_intake")
        assert _extract_match_keywords(rule) == _PIPELINE_KEYWORDS

    def test_triage_rule_returns_triage_keywords(self):
        rule = _make_rule(behavior_category="triage_scoring")
        assert _extract_match_keywords(rule) == _TRIAGE_KEYWORDS

    def test_general_unclassified_returns_empty_or_dedup(self):
        rule = _make_rule(behavior_category="general",
                          proposed_behavior="no clear pattern here")
        kw = _extract_match_keywords(rule)
        assert kw == [] or kw == _DEDUP_KEYWORDS


# ── TestScoreRule ──────────────────────────────────────────────────────────────

class TestScoreRule:
    def setup_method(self):
        self.cards = _sample_cards(n_pipeline=20, n_other=5)
        self.entries = _sample_entries(5)

    def test_impact_score_in_range(self):
        rule = _make_rule(behavior_category="pipeline")
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert 0.0 <= result["impact_score"] <= 1.0

    def test_confidence_score_in_range(self):
        rule = _make_rule(behavior_category="pipeline")
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert 0.0 <= result["confidence_score"] <= 1.0

    def test_affected_events_counted(self):
        rule = _make_rule(behavior_category="pipeline")
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert result["impact_events"] >= 0

    def test_impact_scored_at_present(self):
        rule = _make_rule(behavior_category="pipeline")
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert "impact_scored_at" in result
        assert result["impact_scored_at"]

    def test_recommendation_field_present(self):
        rule = _make_rule()
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert result["recommendation"] in ("approve", "review", "ignore")

    def test_recommendation_reason_present(self):
        rule = _make_rule()
        result = score_rule(rule, [rule], self.cards, self.entries)
        assert result["recommendation_reason"]

    def test_pipeline_rule_high_event_count(self):
        rule = _make_rule(behavior_category="pipeline", card_count=10)
        result = score_rule(rule, [rule], self.cards, self.entries)
        # Pipeline keywords match most sample cards
        assert result["impact_events"] >= 10

    def test_empty_cards_reduces_impact(self):
        rule = _make_rule(behavior_category="pipeline")
        result_with = score_rule(rule, [rule], self.cards, self.entries)
        result_without = score_rule(rule, [rule], [], self.entries)
        assert result_without["impact_score"] <= result_with["impact_score"]

    def test_returns_dict_with_all_fields(self):
        rule = _make_rule()
        result = score_rule(rule, [rule], self.cards, self.entries)
        for field in ["impact_events", "impact_score", "confidence_score", "recommendation", "recommendation_reason", "impact_scored_at"]:
            assert field in result, f"Missing field: {field}"


# ── TestHighRiskRules ──────────────────────────────────────────────────────────

class TestHighRiskRules:
    def test_high_risk_never_approve(self):
        """High-risk rules must never get recommendation=approve regardless of scores."""
        cards = _sample_cards(n_pipeline=40, n_other=0)
        rule = _make_rule(
            risk_level="high",
            behavior_category="pipeline",
            card_count=10,
            scoring={"relevance": 5, "actionability": 5, "safety": 1},
        )
        result = score_rule(rule, [rule], cards, [])
        assert result["recommendation"] != "approve", "High-risk rule must not get approve recommendation"

    def test_high_risk_gets_review(self):
        cards = _sample_cards(n_pipeline=40, n_other=0)
        rule = _make_rule(risk_level="high", behavior_category="pipeline", card_count=10)
        result = score_rule(rule, [rule], cards, [])
        assert result["recommendation"] == "review"

    def test_medium_risk_can_approve(self):
        cards = _sample_cards(n_pipeline=40, n_other=0)
        rule = _make_rule(
            risk_level="low",
            behavior_category="pipeline",
            card_count=10,
            scoring={"relevance": 5, "actionability": 5, "safety": 4},
        )
        result = score_rule(rule, [rule], cards, [])
        # With very high scores and low risk, may get approve
        assert result["recommendation"] in ("approve", "review")


# ── TestDuplicateRules ─────────────────────────────────────────────────────────

class TestDuplicateRules:
    def test_duplicate_rule_gets_low_impact(self):
        cards = _sample_cards(n_pipeline=20)
        rule_a = _make_rule(rule_id="RULE-A", behavior_category="pipeline",
                             summary="Route iMessage X.com URLs to x_intake via the pipeline.")
        rule_b = _make_rule(rule_id="RULE-B", behavior_category="pipeline",
                             summary="Route iMessage X.com URLs to x_intake via the pipeline.")
        result = score_rule(rule_b, [rule_a, rule_b], cards, [])
        assert result["impact_score"] < 0.5, "Duplicate rule should have reduced impact"

    def test_duplicate_rule_gets_ignore(self):
        cards = _sample_cards(n_pipeline=20)
        summary = "Route iMessage X.com URLs to the intake pipeline automatically."
        rule_a = _make_rule(rule_id="RULE-A", behavior_category="pipeline", summary=summary)
        rule_b = _make_rule(rule_id="RULE-B", behavior_category="pipeline", summary=summary)
        result = score_rule(rule_b, [rule_a, rule_b], cards, [])
        assert result["recommendation"] == "ignore"

    def test_unique_rule_not_flagged_duplicate(self):
        cards = _sample_cards()
        rule_a = _make_rule(rule_id="RULE-A", behavior_category="pipeline",
                             summary="Route iMessage URLs to x_intake.")
        rule_b = _make_rule(rule_id="RULE-B", behavior_category="triage_scoring",
                             summary="Boost triage score for repeat clients.")
        result = score_rule(rule_b, [rule_a, rule_b], cards, [])
        assert result["recommendation"] != "ignore" or result["impact_score"] > 0.1


# ── TestUnclassifiedRules ──────────────────────────────────────────────────────

class TestUnclassifiedRules:
    def test_unclassified_gets_ignore(self):
        cards = _sample_cards()
        rule = _make_rule(
            behavior_category=None,
            proposed_behavior="Manual review required. No automated rule can be generated.",
            summary="Unclassified improvement cards.",
        )
        result = score_rule(rule, [rule], cards, [])
        assert result["recommendation"] == "ignore"

    def test_unclassified_has_low_confidence(self):
        cards = _sample_cards()
        rule = _make_rule(
            behavior_category=None,
            proposed_behavior="Manual review required. No clear automation pattern.",
            summary="Unclassified.",
        )
        result = score_rule(rule, [rule], cards, [])
        assert result["confidence_score"] < 0.5


# ── TestNoSystemBehaviorChange ─────────────────────────────────────────────────

class TestNoSystemBehaviorChange:
    def test_score_rule_does_not_mutate_input(self):
        """score_rule must not modify the rule dict it receives."""
        cards = _sample_cards()
        rule = _make_rule()
        original = json.dumps(rule, sort_keys=True)
        score_rule(rule, [rule], cards, [])
        after = json.dumps(rule, sort_keys=True)
        assert original == after, "score_rule must not mutate the input rule dict"

    def test_scoring_fields_are_additive(self):
        """Applying scores doesn't remove existing fields."""
        cards = _sample_cards()
        rule = _make_rule()
        scores = score_rule(rule, [rule], cards, [])
        for key in ["rule_id", "status", "risk_level", "proposed_behavior", "summary"]:
            assert key in rule, f"score_rule must not remove field: {key}"

    def test_dry_run_writes_nothing(self, tmp_path):
        """--dry-run mode must not write files."""
        import shutil
        from scripts.evaluate_rule_impact import main, PROMOTED_RULES_PATH
        # Copy current rules file to a temp location and patch the path
        tmp_rules = tmp_path / "promoted_rules.json"
        shutil.copy(str(PROMOTED_RULES_PATH), str(tmp_rules))
        original_mtime = tmp_rules.stat().st_mtime

        with patch("scripts.evaluate_rule_impact.PROMOTED_RULES_PATH", tmp_rules):
            main(apply=False, dry_run=True)

        assert tmp_rules.stat().st_mtime == original_mtime, "--dry-run must not modify the file"
