"""Unit tests for cortex.autonomy — Autonomy Control Plane v1.

All tests are offline — no network calls, no file-system side effects.
Run from the repo root:
    python -m pytest ops/tests/test_autonomy.py -v
"""

from __future__ import annotations

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
    register_autonomy_routes,
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
#  3. HumanGateScanner — finds NEEDS_MATT
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
    # The NEEDS_MATT gate should contain the excerpt
    nm_gates = [g for g in gates if "NEEDS_MATT" in g.marker]
    assert nm_gates, "No NEEDS_MATT gate found"
    assert "Polymarket" in nm_gates[0].excerpt or "NEEDS_MATT" in nm_gates[0].excerpt


# ══════════════════════════════════════════════════════════════════════════════
#  4. /api/autonomy/overview — returns valid JSON with required keys
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
    required_keys = {"generated_at", "overall_status", "human_gates", "recent_verifications", "questions"}
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
            overview = assessor.assess()

    assert isinstance(overview, AutonomyOverview)
    assert len(overview.questions) == 10
    assert overview.overall_status in ("ok", "warn", "degraded")
    keys = [q.key for q in overview.questions]
    assert "is_bob_alive" in keys
    assert "can_receive_messages" in keys
    assert "what_is_blocked_on_matt" in keys
    assert "what_is_bob_doing_next" in keys
