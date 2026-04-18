#!/usr/bin/env python3
"""
ops/tests/test_task_runner_gates.py — smoke test for the approval gate.

Keeps the gate policy honest without pulling in a full test framework.
Run directly: ``python3 ops/tests/test_task_runner_gates.py``.

Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


# Make ops/ importable so `task_runner_gates` resolves.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT / "ops"))

import task_runner_gates as gates  # noqa: E402


FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def run_tests() -> int:
    print("=== task_runner_gates smoke test ===")

    # Low-risk task passes unconditionally.
    low = {"task_id": "t1", "task_type": "run_script", "payload": {}}
    d = gates.evaluate(low)
    check(d.allowed, "low-risk task allowed")
    check(not d.high_risk, "low-risk not flagged high_risk")

    # High-risk without token and without dry_run → blocked.
    high = {
        "task_id": "t2",
        "task_type": "run_script",
        "requires_approval": True,
        "payload": {},
    }
    d = gates.evaluate(high)
    check(not d.allowed, "high-risk no-token blocked")
    check("missing required approval_token" in d.reason, "blocker reason mentions token")

    # High-risk + dry_run → allowed.
    high_dry = {
        "task_id": "t3",
        "task_type": "run_script",
        "requires_approval": True,
        "dry_run": True,
        "payload": {},
    }
    d = gates.evaluate(high_dry)
    check(d.allowed, "high-risk dry_run allowed")
    check(d.approval_source == "dry_run", "dry_run source correctly tagged")

    # High-risk risk_tier=high still triggers gate.
    high_tier = {
        "task_id": "t4",
        "task_type": "run_script",
        "risk_tier": "high",
        "payload": {},
    }
    d = gates.evaluate(high_tier)
    check(not d.allowed, "risk_tier=high blocked without token")
    check(d.high_risk, "risk_tier=high flagged high_risk")

    # High-risk + committed approval file → allowed.
    # We temporarily create an approval file in the real ops/approvals/.
    tok = "test-gate-token-please-ignore"
    approvals_dir = REPO_ROOT / "ops" / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    approval_path = approvals_dir / f"{tok}.approval"
    try:
        approval_path.write_text("test only\n", encoding="utf-8")
        approved = {
            "task_id": "t5",
            "task_type": "run_script",
            "requires_approval": True,
            "approval_token": tok,
            "payload": {},
        }
        d = gates.evaluate(approved)
        check(d.allowed, "high-risk + valid approval_token allowed")
        check(
            d.approval_source == "approval_file",
            "approval source = approval_file",
        )
    finally:
        if approval_path.exists():
            approval_path.unlink()

    # Path-traversal token rejected.
    bad = {
        "task_id": "t6",
        "task_type": "run_script",
        "requires_approval": True,
        "approval_token": "../etc/passwd",
        "payload": {},
    }
    d = gates.evaluate(bad)
    check(not d.allowed, "traversal approval_token rejected")

    # Payload-level flags honored.
    payload_high = {
        "task_id": "t7",
        "task_type": "run_script",
        "payload": {"requires_approval": True},
    }
    d = gates.evaluate(payload_high)
    check(d.high_risk, "payload.requires_approval flags high_risk")
    check(not d.allowed, "payload.requires_approval without token blocks")

    # Payload-level dry_run honored.
    payload_dry = {
        "task_id": "t8",
        "task_type": "run_script",
        "payload": {"requires_approval": True, "dry_run": True},
    }
    d = gates.evaluate(payload_dry)
    check(d.allowed, "payload.dry_run allows high-risk task")

    # Self-approval without allowlist entry is still blocked.
    self_approval = {
        "task_id": "t9-self-approved",
        "task_type": "run_script",
        "requires_approval": True,
        "approval_token": "t9-self-approved",
        "payload": {},
    }
    d = gates.evaluate(self_approval)
    # Depends on AUTO_APPROVE_IDS.txt — by default the test id isn't there.
    check(
        not d.allowed,
        "self-approval blocked when task_id not on AUTO_APPROVE_IDS",
    )

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} checks failed")
        for label in FAILURES:
            print(f"  - {label}")
        return 1
    print("all gate checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
