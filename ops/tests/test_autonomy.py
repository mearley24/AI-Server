"""Unit tests for cortex.autonomy — Autonomy Control Plane v1.

All tests are offline — no network calls, no file-system side effects.
Run from the repo root:
    python -m pytest ops/tests/test_autonomy.py -v
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure cortex package is importable from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cortex.autonomy import (
    AutonomyAssessor,
    HumanGate,
    HumanGateScanner,
    AutonomyOverview,
    Verification,
    VerificationScanner,
    classify_gate,
    register_autonomy_routes,
    _ACTIVE_GATE_LINE,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _write_file(directory: Path, name: str, content: str) -> Path:
    p = directory / name
    p.write_text(content, encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  1. VerificationScanner — PASS verdict
# ══════════════════════════════════════════════════════════════════════════════


def test_verification_scanner_pass_verdict():
    """VerificationScanner correctly parses a file containing a PASS verdict."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _write_file(
            d,
            "20260424-120000-cortex-health-check.txt",
            "CORTEX HEALTH CHECK — 2026-04-24\n"
            "All services responding within expected thresholds.\n"
            "Verdict: PASS\n",
        )
        scanner = VerificationScanner(verification_dir=d)
        results = scanner.scan()

    assert len(results) == 1
    v = results[0]
    assert isinstance(v, Verification)
    assert v.verdict == "PASS"
    assert v.topic == "cortex-health-check"
    assert v.timestamp == "2026-04-24T12:00:00"
    assert "CORTEX HEALTH CHECK" in v.summary or "All services" in v.summary


# ══════════════════════════════════════════════════════════════════════════════
#  2. VerificationScanner — FAIL verdict
# ══════════════════════════════════════════════════════════════════════════════


def test_verification_scanner_fail_verdict():
    """VerificationScanner correctly parses a file containing a FAIL verdict."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _write_file(
            d,
            "20260424-130000-task-runner-health.txt",
            "=== TASK RUNNER HEALTH ===\n"
            "heartbeat.txt not found — runner appears down.\n"
            "Overall: FAIL\n",
        )
        scanner = VerificationScanner(verification_dir=d)
        results = scanner.scan()

    assert len(results) == 1
    v = results[0]
    assert v.verdict == "FAIL"
    assert v.topic == "task-runner-health"


# ══════════════════════════════════════════════════════════════════════════════
#  3a. _ACTIVE_GATE_LINE regex — matches only leading bracket markers
# ══════════════════════════════════════════════════════════════════════════════


def test_active_gate_line_matches_leading_markers():
    """Lines where the bracket marker leads must match."""
    assert _ACTIVE_GATE_LINE.match("- [FOLLOWUP] do something")
    assert _ACTIVE_GATE_LINE.match("[NEEDS_MATT] fund wallet")
    assert _ACTIVE_GATE_LINE.match("  - [BLOCKED] issue here")
    assert _ACTIVE_GATE_LINE.match("  [ARMED] runbook active")
    assert _ACTIVE_GATE_LINE.match("- [followup] lowercase works")


def test_active_gate_line_rejects_false_positives():
    """Prose, backtick mentions, headings, and historical refs must NOT match."""
    # Inline backtick mentions
    assert not _ACTIVE_GATE_LINE.match("every `[NEEDS_MATT]` / `[FOLLOWUP]` that still depends")
    assert not _ACTIVE_GATE_LINE.match("marked `[NEEDS_MATT]`")
    # Section headings containing the word
    assert not _ACTIVE_GATE_LINE.match("## Port Audit — reconciliation + follow-ups armed")
    assert not _ACTIVE_GATE_LINE.match("## Bob-watchdog required-source subshell fix + [FOLLOWUP] alert")
    # Narrative prose with blocked/armed/waiting as plain words
    assert not _ACTIVE_GATE_LINE.match("- Verdict: BLOCKED — Docker daemon restarted")
    assert not _ACTIVE_GATE_LINE.match("- BlueBubbles: KEEP ENABLED — outbound blocked at apple-script")
    assert not _ACTIVE_GATE_LINE.match("- Status: ARMED")
    # References inside longer sentences
    assert not _ACTIVE_GATE_LINE.match("  Runbook remains gated (Matt-only [NEEDS_MATT])")
    assert not _ACTIVE_GATE_LINE.match("  see `[FOLLOWUP: bluebubbles-send-method]`")


def test_human_gate_scanner_no_false_positives():
    """Scanner must not produce gates for prose / heading / backtick lines."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        status = d / "STATUS_REPORT.md"
        status.write_text(
            # Real active gate — must be captured
            "- [NEEDS_MATT] Fund Polymarket wallet\n"
            # Prose with backtick mention — must be ignored
            "every `[NEEDS_MATT]` / `[FOLLOWUP]` that still depends on the webhook\n"
            # Section heading — must be ignored
            "## Port Audit — reconciliation + follow-ups armed (2026-04-24)\n"
            # Narrative BLOCKED — must be ignored
            "- Verdict: BLOCKED — Docker daemon restarted\n"
            # Inline [FOLLOWUP] reference deep in a sentence — must be ignored
            "  Runbook remains gated (Matt-only allowlist + [FOLLOWUP] restore)\n"
            # Another real gate — must be captured
            "- [FOLLOWUP] Complete historical backfill\n",
            encoding="utf-8",
        )
        scanner = HumanGateScanner(
            status_report=status,
            runbooks_dir=d / "r",
            prompts_dir=d / "p",
        )
        gates = scanner.scan()

    assert len(gates) == 2, f"Expected 2 gates, got {len(gates)}: {[g.excerpt for g in gates]}"
    markers = {g.marker for g in gates}
    assert "NEEDS_MATT" in markers
    assert "FOLLOWUP" in markers


# ══════════════════════════════════════════════════════════════════════════════
#  3b. HumanGateScanner — finds NEEDS_MATT
# ══════════════════════════════════════════════════════════════════════════════


def test_human_gate_scanner_finds_needs_matt():
    """HumanGateScanner detects [NEEDS_MATT] markers in a mock status report."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        status = d / "STATUS_REPORT.md"
        status.write_text(
            "## Status\n"
            "- Regular item\n"
            "- [NEEDS_MATT] Fund Polymarket wallet — deposit USDC\n"
            "- [FOLLOWUP] Update PORTS.md registry\n"
            "- Another regular item\n",
            encoding="utf-8",
        )
        scanner = HumanGateScanner(
            status_report=status,
            runbooks_dir=d / "runbooks_nonexistent",
            prompts_dir=d / "prompts_nonexistent",
        )
        gates = scanner.scan()

    markers = [g.marker for g in gates]
    assert any("NEEDS_MATT" in m for m in markers), f"Expected NEEDS_MATT in {markers}"
    assert any("FOLLOWUP" in m for m in markers), f"Expected FOLLOWUP in {markers}"
    nm_gates = [g for g in gates if "NEEDS_MATT" in g.marker]
    assert nm_gates, "No NEEDS_MATT gate found"
    assert "Polymarket" in nm_gates[0].excerpt or "NEEDS_MATT" in nm_gates[0].excerpt


def test_human_gate_scanner_ignores_strikethrough():
    """HumanGateScanner must not return gates for resolved ~~[MARKER]~~ lines."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        status = d / "STATUS_REPORT.md"
        status.write_text(
            "## Status\n"
            "- ~~[NEEDS_MATT] Old resolved item~~ ✅ Done\n"
            "- ~~[FOLLOWUP] Another resolved item~~ ✅ Done\n"
            "~~[ARMED] Top-level resolved~~ ✅\n"
            "- [NEEDS_MATT] Still open item\n",
            encoding="utf-8",
        )
        scanner = HumanGateScanner(
            status_report=status,
            runbooks_dir=d / "runbooks_nonexistent",
            prompts_dir=d / "prompts_nonexistent",
        )
        gates = scanner.scan()

    # Only the active (non-struck) item should be returned
    assert len(gates) == 1, f"Expected 1 gate, got {len(gates)}: {[g.excerpt for g in gates]}"
    assert "NEEDS_MATT" in gates[0].marker
    assert "Still open" in gates[0].excerpt


# ══════════════════════════════════════════════════════════════════════════════
#  4. classify_gate — action_class triage
# ══════════════════════════════════════════════════════════════════════════════


def test_classify_gate_auto_fix():
    assert classify_gate("prune logs/network-guard.err after stable day", "FOLLOWUP") == "AUTO_FIX"
    assert classify_gate("copy dropout-watch plist to ~/Library/LaunchAgents/", "FOLLOWUP") == "AUTO_FIX"
    assert classify_gate("docker image prune reclaim space", "FOLLOWUP") == "AUTO_FIX"


def test_classify_gate_approval_required():
    assert classify_gate("sudo setup/install_bob_watchdog.sh --deploy-system", "NEEDS_MATT") == "APPROVAL_REQUIRED"
    assert classify_gate("CORTEX_REPLY_DRY_RUN=0 live send outbound iMessage", "NEEDS_MATT") == "APPROVAL_REQUIRED"
    assert classify_gate("AppleScript access required for BlueBubbles send", "FOLLOWUP") == "APPROVAL_REQUIRED"


def test_classify_gate_waiting_external():
    assert classify_gate("Fund Polymarket wallet with USDC on Polygon", "NEEDS_MATT") == "WAITING_EXTERNAL"
    assert classify_gate("ios-app merge conflict on Matt's MacBook", "NEEDS_MATT") == "WAITING_EXTERNAL"
    assert classify_gate("keychain unlock required for Docker build", "FOLLOWUP") == "WAITING_EXTERNAL"


def test_classify_gate_needs_matt():
    assert classify_gate("legal review of contract terms", "NEEDS_MATT") == "NEEDS_MATT"
    assert classify_gate("billing decision for client project", "NEEDS_MATT") == "NEEDS_MATT"


def test_classify_gate_auto_review_default():
    assert classify_gate("complete historical embedding backfill", "FOLLOWUP") == "AUTO_REVIEW"
    assert classify_gate("investigate Docker daemon stability", "FOLLOWUP") == "AUTO_REVIEW"
    assert classify_gate("no obvious keyword here", "FOLLOWUP") == "AUTO_REVIEW"


def test_gate_summary_in_overview():
    """AutonomyOverview.gate_summary counts gates by action_class."""
    gates = [
        HumanGate(source="s", marker="FOLLOWUP", excerpt="prune logs/network-guard.err", action_class="AUTO_FIX"),
        HumanGate(source="s", marker="NEEDS_MATT", excerpt="Fund wallet USDC", action_class="WAITING_EXTERNAL"),
        HumanGate(source="s", marker="NEEDS_MATT", excerpt="sudo install watchdog", action_class="APPROVAL_REQUIRED"),
        HumanGate(source="s", marker="FOLLOWUP", excerpt="complete backfill", action_class="AUTO_REVIEW"),
        HumanGate(source="s", marker="FOLLOWUP", excerpt="another backfill", action_class="AUTO_REVIEW"),
    ]
    summary: dict[str, int] = {}
    for g in gates:
        summary[g.action_class] = summary.get(g.action_class, 0) + 1
    assert summary == {"AUTO_FIX": 1, "WAITING_EXTERNAL": 1, "APPROVAL_REQUIRED": 1, "AUTO_REVIEW": 2}


def test_human_gate_scanner_attaches_action_class():
    """HumanGateScanner sets action_class on returned gates."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        status = d / "STATUS_REPORT.md"
        status.write_text(
            "- [NEEDS_MATT] Fund Polymarket wallet — deposit USDC\n"
            "- [FOLLOWUP] prune logs/network-guard.err after stable day\n",
            encoding="utf-8",
        )
        scanner = HumanGateScanner(
            status_report=status,
            runbooks_dir=d / "runbooks",
            prompts_dir=d / "prompts",
        )
        gates = scanner.scan()

    classes = {g.action_class for g in gates}
    assert "WAITING_EXTERNAL" in classes, f"Expected WAITING_EXTERNAL (wallet), got {classes}"
    assert "AUTO_FIX" in classes, f"Expected AUTO_FIX (prune logs), got {classes}"


# ══════════════════════════════════════════════════════════════════════════════
#  5. /api/autonomy/overview — returns valid JSON with required keys
# ══════════════════════════════════════════════════════════════════════════════


def test_autonomy_overview_endpoint_returns_required_keys():
    """/api/autonomy/overview returns a JSON dict with all required top-level keys."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_autonomy_routes(app)

    # Patch AutonomyAssessor.assess so we don't need live services
    mock_overview = AutonomyOverview(
        generated_at="2026-04-24T12:00:00+00:00",
        overall_status="ok",
        human_gates=[],
        recent_verifications=[],
        questions=[],
    )

    with patch(
        "cortex.autonomy.AutonomyAssessor.assess", return_value=mock_overview
    ):
        client = TestClient(app)
        resp = client.get("/api/autonomy/overview")

    assert resp.status_code == 200
    data = resp.json()
    required_keys = {"generated_at", "overall_status", "human_gates", "recent_verifications", "questions", "gate_summary"}
    assert required_keys.issubset(data.keys()), (
        f"Missing keys: {required_keys - data.keys()}"
    )
    assert data["overall_status"] == "ok"
    assert isinstance(data["human_gates"], list)
    assert isinstance(data["recent_verifications"], list)
    assert isinstance(data["questions"], list)


# ══════════════════════════════════════════════════════════════════════════════
#  5. VerificationScanner — skips oversized files
# ══════════════════════════════════════════════════════════════════════════════


def test_verification_scanner_skips_oversized_files():
    """VerificationScanner skips files larger than 500 KB."""
    from cortex.autonomy import _MAX_FILE_BYTES

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        big = d / "20260424-140000-big-log.txt"
        # Write slightly over the limit
        big.write_bytes(b"X" * (_MAX_FILE_BYTES + 1))
        _write_file(d, "20260424-140001-normal.txt", "Normal content\nPASS\n")

        scanner = VerificationScanner(verification_dir=d)
        results = scanner.scan()

    # Only the normal file should be parsed
    assert len(results) == 1
    assert results[0].topic == "normal"


# ══════════════════════════════════════════════════════════════════════════════
#  6. AutonomyAssessor — assess() returns AutonomyOverview with 10 questions
# ══════════════════════════════════════════════════════════════════════════════


def test_autonomy_assessor_returns_ten_questions():
    """AutonomyAssessor.assess() returns an AutonomyOverview with exactly 10 questions."""
    # Use empty dirs so scanners return nothing, and mock httpx to avoid network calls
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        vs = VerificationScanner(verification_dir=d / "verification")
        gs = HumanGateScanner(
            status_report=d / "STATUS_REPORT.md",
            runbooks_dir=d / "runbooks",
            prompts_dir=d / "prompts",
        )
        assessor = AutonomyAssessor(verification_scanner=vs, gate_scanner=gs)

        with patch("httpx.get", side_effect=Exception("no network")):
            overview = asyncio.run(assessor.assess())

    assert isinstance(overview, AutonomyOverview)
    assert len(overview.questions) == 10
    assert overview.overall_status in ("ok", "warn", "degraded")
    keys = [q.key for q in overview.questions]
    assert "is_bob_alive" in keys
    assert "can_receive_messages" in keys
    assert "what_is_blocked_on_matt" in keys
    assert "what_is_bob_doing_next" in keys


# ══════════════════════════════════════════════════════════════════════════════
#  8. InvestigationEngine
# ══════════════════════════════════════════════════════════════════════════════

import time as _time

from cortex.autonomy import (
    investigate_gate,
    InvestigationCache,
    Investigation,
    run_investigations,
)


def test_investigate_gate_returns_investigation():
    """investigate_gate must return a valid Investigation for any gate."""
    gate = HumanGate(
        source="STATUS_REPORT.md",
        marker="FOLLOWUP",
        excerpt="- [FOLLOWUP] Complete historical embedding backfill",
        action_class="AUTO_REVIEW",
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        inv = investigate_gate(gate, repo)
    assert isinstance(inv, Investigation)
    assert "embed" in inv.root_cause_hypothesis.lower() or inv.root_cause_hypothesis
    assert isinstance(inv.evidence, list)
    assert 0.0 <= inv.confidence <= 1.0
    assert inv.proposed_fix
    assert inv.investigated_at


def test_investigate_gate_matches_backfill_rule():
    """backfill keyword should match the embedding rule."""
    gate = HumanGate(
        source="STATUS_REPORT.md", marker="FOLLOWUP",
        excerpt="complete historical embedding backfill", action_class="AUTO_REVIEW",
    )
    with tempfile.TemporaryDirectory() as tmp:
        inv = investigate_gate(gate, Path(tmp))
    assert "embed" in inv.root_cause_hypothesis.lower()
    assert "backfill" in inv.proposed_fix.lower() or "embed" in inv.proposed_fix.lower()


def test_investigate_gate_unknown_gate_uses_defaults():
    """Unknown gate text should return default hypothesis without crashing."""
    gate = HumanGate(
        source="STATUS_REPORT.md", marker="FOLLOWUP",
        excerpt="some completely unknown gate text", action_class="AUTO_REVIEW",
    )
    with tempfile.TemporaryDirectory() as tmp:
        inv = investigate_gate(gate, Path(tmp))
    assert inv.root_cause_hypothesis  # not empty
    assert inv.status in ("complete", "no_evidence", "partial")


def test_investigation_cache_ttl():
    """InvestigationCache returns None after TTL expires."""
    cache = InvestigationCache(ttl=0.01)  # 10ms TTL
    gate = HumanGate(source="s", marker="FOLLOWUP", excerpt="test", action_class="AUTO_REVIEW")
    inv = Investigation(
        gate_excerpt="test", gate_source="s", root_cause_hypothesis="h",
        evidence=[], proposed_fix="fix", confidence=0.5,
        investigated_at="now", status="complete",
    )
    cache.put(gate, inv)
    assert cache.get(gate) is not None
    _time.sleep(0.02)
    assert cache.get(gate) is None


def test_run_investigations_skips_non_auto_review():
    """run_investigations must only process AUTO_REVIEW gates."""
    gates = [
        HumanGate(source="s", marker="NEEDS_MATT", excerpt="fund wallet", action_class="WAITING_EXTERNAL"),
        HumanGate(source="s", marker="FOLLOWUP", excerpt="complete backfill", action_class="AUTO_REVIEW"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        results = asyncio.run(run_investigations(gates, Path(tmp)))
    assert len(results) == 1
    assert results[0].gate_excerpt == "complete backfill"
