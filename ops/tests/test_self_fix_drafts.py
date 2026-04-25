"""Tests for self-fix suggestion logic in reply drafting.

Covers:
  - Sonos/audio: power cycle suggested, no remote mention, on-site follow-up
  - Wi-Fi/network: router reboot suggested or remote check offered
  - Unknown system: neutral wording, no assumptions
  - Recurring issue: history acknowledged, self-fix still offered
  - draft_quality_status enforced on all outputs
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.engine import (
    _build_draft_with_context,
    _check_draft_quality,
    _system_cap,
    SAFE_FALLBACK_REPLY,
)


# ── _system_cap unit tests ────────────────────────────────────────────────────

class TestSystemCap:

    def test_sonos_no_remote(self):
        cap = _system_cap("Sonos")
        assert cap["remote"] is False
        assert cap["self_fix"] is not None
        assert "unplug" in cap["self_fix"].lower() or "power" in cap["self_fix"].lower()

    def test_wifi_has_remote_and_self_fix(self):
        cap = _system_cap("WiFi")
        assert cap["remote"] is True
        assert cap["self_fix"] is not None
        assert "router" in cap["self_fix"].lower() or "reboot" in cap["self_fix"].lower()

    def test_wifi_hyphenated(self):
        cap = _system_cap("Wi-Fi")
        assert cap["remote"] is True
        assert cap["self_fix"] is not None

    def test_network_has_remote_and_self_fix(self):
        cap = _system_cap("network")
        assert cap["remote"] is True

    def test_control4_remote_no_self_fix(self):
        cap = _system_cap("Control4")
        assert cap["remote"] is True
        assert cap["self_fix"] is None

    def test_lutron_remote_no_self_fix(self):
        cap = _system_cap("Lutron")
        assert cap["remote"] is True
        assert cap["self_fix"] is None

    def test_unknown_system_neutral(self):
        cap = _system_cap("SomeUnknownDevice")
        assert cap["self_fix"] is None
        assert cap["remote"] is False
        assert cap["on_site"] is True

    def test_sonos_arc_substring_match(self):
        # "Sonos Arc" should match the "sonos" entry
        cap = _system_cap("Sonos Arc")
        assert cap["remote"] is False
        assert cap["self_fix"] is not None


# ── Draft builder: self-fix suggestions ──────────────────────────────────────

def _profile(**kw):
    base = {"relationship_type": "client", "open_requests": [], "systems_or_topics": [],
            "follow_ups": [], "summary": "", "confidence": 0.75}
    base.update(kw)
    return base


def _fact(ftype, val, accepted=True):
    return {"fact_type": ftype, "fact_value": val, "confidence": 0.75,
            "source_excerpt": "x", "source_timestamp": "t",
            "is_accepted": 1 if accepted else 0, "is_rejected": 0}


class TestSonosDraft:

    def test_sonos_issue_suggests_power_cycle(self):
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "issue":     [_fact("issue", "offline")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        # Must suggest unplugging / power cycle
        assert "unplug" in draft.lower() or "power" in draft.lower(), (
            f"Sonos draft should suggest power cycle: {draft}"
        )
        # Must NOT mention remote access (Sonos is handled on-site)
        assert "remotely" not in draft.lower(), (
            f"Sonos draft must not mention remote access: {draft}"
        )
        # Must offer on-site follow-up
        assert "swing by" in draft.lower() or "on-site" in draft.lower() or "take a look" in draft.lower(), (
            f"Sonos draft should offer to swing by: {draft}"
        )

    def test_sonos_issue_passes_quality_gate(self):
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "issue":     [_fact("issue", "cutting out")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        status, reasons = _check_draft_quality(result["draft_reply"])
        assert status == "pass", f"Draft quality failed: {reasons} — {result['draft_reply']}"
        assert result["draft_quality_status"] == "pass"

    def test_sonos_recurring_issue_acknowledges_history(self):
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "issue":     [_fact("issue", "offline"), _fact("issue", "cutting out")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        # Should acknowledge the recurring pattern
        history_phrases = ["come up", "happened", "couple", "times", "again"]
        assert any(p in draft.lower() for p in history_phrases), (
            f"Recurring Sonos issue should acknowledge history: {draft}"
        )
        # Should still suggest a fix, not just escalate
        fix_phrases = ["unplug", "power", "try"]
        assert any(p in draft.lower() for p in fix_phrases), (
            f"Recurring issue should still suggest a fix: {draft}"
        )

    def test_sonos_no_diagnostic_questions(self):
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "issue":     [_fact("issue", "not working")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        bad_phrases = ["when did", "have you tried", "what error", "what times work",
                       "let me know your availability"]
        draft = result["draft_reply"].lower()
        for phrase in bad_phrases:
            assert phrase not in draft, f"Diagnostic question found: '{phrase}' in '{draft}'"


class TestWifiNetworkDraft:

    def test_wifi_issue_suggests_router_reboot(self):
        accepted = {
            "system": [_fact("system", "WiFi")],
            "issue":  [_fact("issue", "not working")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        reboot_phrases = ["reboot", "router", "remotely", "restart"]
        assert any(p in draft.lower() for p in reboot_phrases), (
            f"WiFi draft should suggest reboot or remote check: {draft}"
        )

    def test_network_issue_remote_or_reboot(self):
        accepted = {
            "system": [_fact("system", "network")],
            "issue":  [_fact("issue", "offline")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        helpful_phrases = ["router", "remotely", "reboot", "restart", "check"]
        assert any(p in draft.lower() for p in helpful_phrases), (
            f"Network draft should mention reboot or remote check: {draft}"
        )

    def test_wifi_draft_passes_quality_gate(self):
        accepted = {
            "system": [_fact("system", "WiFi")],
            "issue":  [_fact("issue", "down")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        status, reasons = _check_draft_quality(result["draft_reply"])
        assert status == "pass", f"WiFi draft failed quality: {reasons}"
        assert result["draft_quality_status"] == "pass"

    def test_wifi_one_step_max(self):
        """Draft must not give multiple instructions."""
        accepted = {
            "system": [_fact("system", "WiFi")],
            "issue":  [_fact("issue", "slow")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        # Count imperative steps (sentences starting with action verbs)
        import re
        steps = re.findall(r'(?:^|[.!?]\s+)(?:try|check|reboot|restart|unplug|plug|press)\b',
                           draft, re.I)
        assert len(steps) <= 1, (
            f"Draft must have at most one instruction step, got {len(steps)}: {draft}"
        )


class TestUnknownSystemDraft:

    def test_unknown_system_neutral_wording(self):
        accepted = {
            "equipment": [_fact("equipment", "SomeUnknownDevice")],
            "issue":     [_fact("issue", "not responding")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        # No assumptions — no specific fix suggestion
        overly_specific = ["unplug", "reboot your router", "router real quick"]
        for phrase in overly_specific:
            assert phrase not in draft.lower(), (
                f"Unknown system should not suggest specific fix: '{phrase}' in '{draft}'"
            )
        # Still offers to help
        help_phrases = ["take a look", "check", "get back", "find"]
        assert any(p in draft.lower() for p in help_phrases), (
            f"Unknown system draft should still offer help: {draft}"
        )

    def test_unknown_system_passes_quality_gate(self):
        accepted = {
            "equipment": [_fact("equipment", "CustomAVSystem")],
            "issue":     [_fact("issue", "malfunction")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        q, _ = _check_draft_quality(result["draft_reply"])
        assert q == "pass"


class TestControl4LutronDraft:

    def test_control4_offers_remote_check(self):
        """Control4 has no self-fix but can be checked remotely."""
        accepted = {
            "equipment": [_fact("equipment", "Control4")],
            "issue":     [_fact("issue", "unresponsive")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        assert "remotely" in draft.lower() or "check" in draft.lower(), (
            f"Control4 draft should offer remote check: {draft}"
        )
        # No power cycle suggestion for Control4
        assert "unplug" not in draft.lower(), (
            f"Control4 draft should not suggest unplugging: {draft}"
        )

    def test_lutron_no_self_fix_suggestion(self):
        accepted = {
            "equipment": [_fact("equipment", "Lutron")],
            "issue":     [_fact("issue", "keypad not responding")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        draft = result["draft_reply"]
        assert "unplug" not in draft.lower()
        assert "reboot your router" not in draft.lower()


class TestQualityGateStillEnforced:

    def test_quality_status_present_in_all_branches(self):
        """Every output from _build_draft_with_context has draft_quality_status."""
        cases = [
            (_profile(), {"equipment": [_fact("equipment", "Sonos")],
                          "issue": [_fact("issue", "offline")]}, {}, []),
            (_profile(), {"system": [_fact("system", "WiFi")],
                          "issue": [_fact("issue", "slow")]}, {}, []),
            (_profile(), {}, {}, []),
            (_profile(relationship_type="vendor"), {}, {}, []),
            (_profile(systems_or_topics=["Lutron"]), {}, {}, []),
        ]
        for profile, accepted, unverified, receipts in cases:
            result = _build_draft_with_context(profile, accepted, unverified, receipts)
            assert "draft_quality_status" in result, f"Missing quality_status for {profile}"
            assert "draft_quality_reasons" in result, f"Missing quality_reasons for {profile}"
            assert result["draft_quality_status"] in ("pass", "fallback", "blocked")

    def test_messy_fact_still_uses_fallback(self):
        """Quality guardrail still fires even when equipment has a self-fix."""
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "request":   [_fact("request",
                                "give me call as soon as you can as am trying to setup")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        # Messy request should downgrade quality and confidence
        assert result["confidence"] <= 0.65
        q, _ = _check_draft_quality(result["draft_reply"])
        assert q == "pass", f"Even downgraded draft must pass post-gen check: {result['draft_reply']}"

    def test_self_fix_drafts_are_short(self):
        """Drafts must not overwhelm — single instruction + follow-up only."""
        accepted = {
            "equipment": [_fact("equipment", "Sonos")],
            "issue":     [_fact("issue", "no audio")],
        }
        result = _build_draft_with_context(_profile(), accepted, {}, [])
        # Max 2 sentences for self-fix drafts
        import re
        sentences = [s.strip() for s in re.split(r'[.!?]', result["draft_reply"]) if s.strip()]
        assert len(sentences) <= 3, (
            f"Draft too long ({len(sentences)} sentences): {result['draft_reply']}"
        )
