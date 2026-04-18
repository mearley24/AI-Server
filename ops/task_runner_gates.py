#!/usr/bin/env python3
"""
ops/task_runner_gates.py — approval-token + dry-run gates for the runner.

Small, composable helpers that ``scripts/task_runner.py`` consults before
executing a task. Split out of the runner so the policy is easy to read,
test, and extend without touching the dispatch loop.

Policy summary (see ops/AGENT_VERIFICATION_PROTOCOL.md for the full
narrative, and CLAUDE.md → "Standing Approval and Risk Tiers"):

* **Low risk**  — runs fully autonomously (the status quo).
* **Medium**    — runs autonomously but MUST emit a verification artifact.
* **High risk** — requires an explicit ``approval_token`` in the task JSON
                 that matches either a committed approval file under
                 ``ops/approvals/`` or the task's own ``task_id``
                 (self-signed standing approvals only allowed for task ids
                 that appear in an ``AUTO_APPROVE_IDS`` allowlist file —
                 see ``AUTO_APPROVAL_FILE``).

High-risk signals (any one triggers the gate):

    * ``task["requires_approval"] is True``
    * ``task["risk_tier"]`` in ``{"high", "critical"}``
    * ``task["payload"]["requires_approval"] is True``
    * ``task["payload"]["risk_tier"]`` in ``{"high", "critical"}``

Approval tokens:

    * A string at ``task["approval_token"]`` OR
      ``task["payload"]["approval_token"]``.
    * Valid if a file ``ops/approvals/<token>.approval`` exists, OR the
      token literally equals the task_id AND the task_id is listed in
      ``ops/approvals/AUTO_APPROVE_IDS.txt`` (one token per line,
      ``#`` comments allowed).
    * Approval files are plain text — their contents can record who
      approved and when, but the mere existence of the file is the gate.
      Because approval files live under version control, any approval is
      traceable in git history.

Dry-run:

    * Any task with ``dry_run=true`` (top-level OR payload) is allowed
      through the approval gate without a token — dry-run implies no
      side effects.
    * A task_type-agnostic mechanism: the runner surfaces the flag via
      ``DRY_RUN=1`` in the subprocess environment, and by appending
      ``--dry-run`` to script/launcher argv when the wrapper understands
      that flag. Handlers that cannot honor dry-run should hard-block
      the task with ``Gate.blocker("dry-run not supported for <type>")``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
APPROVALS_DIR = REPO_ROOT / "ops" / "approvals"
AUTO_APPROVAL_FILE = APPROVALS_DIR / "AUTO_APPROVE_IDS.txt"

HIGH_RISK_TIERS = {"high", "critical"}


@dataclass
class GateDecision:
    """Outcome of evaluating approval + dry-run gates on a task."""

    allowed: bool
    reason: str  # human-readable explanation (always filled)
    is_dry_run: bool = False
    high_risk: bool = False
    approval_token: str = ""
    approval_source: str = ""  # "approval_file" | "auto_allowlist" | "dry_run" | ""


def _flag(task: dict, key: str) -> Any:
    """Return task[key] or task['payload'][key], favouring the top level."""
    if key in task and task[key] is not None:
        return task[key]
    payload = task.get("payload") or {}
    return payload.get(key)


def is_dry_run(task: dict) -> bool:
    return bool(_flag(task, "dry_run"))


def is_high_risk(task: dict) -> bool:
    if bool(_flag(task, "requires_approval")):
        return True
    tier = _flag(task, "risk_tier")
    if isinstance(tier, str) and tier.lower() in HIGH_RISK_TIERS:
        return True
    return False


def _approval_token(task: dict) -> str:
    t = _flag(task, "approval_token")
    return str(t).strip() if t else ""


def _load_auto_allowlist() -> set[str]:
    """Return the set of task_ids pre-authorized for self-approval."""
    if not AUTO_APPROVAL_FILE.is_file():
        return set()
    ids: set[str] = set()
    try:
        for line in AUTO_APPROVAL_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.add(line)
    except Exception:  # noqa: BLE001
        return set()
    return ids


def _approval_file_exists(token: str) -> bool:
    """Check for ``ops/approvals/<token>.approval``. Rejects path traversal."""
    if not token or "/" in token or ".." in token or token.startswith("."):
        return False
    candidate = (APPROVALS_DIR / f"{token}.approval").resolve()
    try:
        candidate.relative_to(APPROVALS_DIR.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def evaluate(task: dict) -> GateDecision:
    """Return a :class:`GateDecision` for a task JSON dict."""
    dry = is_dry_run(task)
    high = is_high_risk(task)
    token = _approval_token(task)
    task_id = str(task.get("task_id") or task.get("id") or "").strip()

    if not high:
        # Low / medium — always allowed.
        return GateDecision(
            allowed=True,
            reason="low/medium risk — standing approval",
            is_dry_run=dry,
            high_risk=False,
            approval_token=token,
        )

    # High-risk path.
    if dry:
        return GateDecision(
            allowed=True,
            reason="high risk but dry_run=true — no side effects; allowed",
            is_dry_run=True,
            high_risk=True,
            approval_token=token,
            approval_source="dry_run",
        )

    if not token:
        return GateDecision(
            allowed=False,
            reason=(
                "high-risk task is missing required approval_token. "
                "Either add approval_token to the task JSON and commit "
                "ops/approvals/<token>.approval, or re-queue with dry_run=true."
            ),
            is_dry_run=False,
            high_risk=True,
            approval_token="",
        )

    if _approval_file_exists(token):
        return GateDecision(
            allowed=True,
            reason=f"approval_token matched file ops/approvals/{token}.approval",
            is_dry_run=False,
            high_risk=True,
            approval_token=token,
            approval_source="approval_file",
        )

    # Self-approval: token must equal task_id AND be in the allowlist.
    if token and task_id and token == task_id:
        if task_id in _load_auto_allowlist():
            return GateDecision(
                allowed=True,
                reason=(
                    "approval_token matches task_id and task_id is on "
                    "AUTO_APPROVE_IDS allowlist"
                ),
                is_dry_run=False,
                high_risk=True,
                approval_token=token,
                approval_source="auto_allowlist",
            )

    return GateDecision(
        allowed=False,
        reason=(
            f"approval_token '{token}' did not match any approval file "
            f"under ops/approvals/ or an AUTO_APPROVE_IDS allowlist entry"
        ),
        is_dry_run=False,
        high_risk=True,
        approval_token=token,
    )


def blocker_text(decision: GateDecision, task: dict) -> str:
    """Render a block report for a rejected high-risk task."""
    lines = [
        "=== high-risk task blocked by approval gate ===",
        f"task_id:        {task.get('task_id') or task.get('id') or '(unknown)'}",
        f"task_type:      {task.get('task_type') or task.get('type') or '(unknown)'}",
        f"created_by:     {task.get('created_by') or '(unknown)'}",
        f"risk_tier:      {_flag(task, 'risk_tier') or 'high'}",
        f"dry_run:        {decision.is_dry_run}",
        f"approval_token: {decision.approval_token or '(missing)'}",
        "",
        f"reason: {decision.reason}",
        "",
        "how to unblock:",
        "  1. Commit a new approval file:",
        "     echo 'approved by <name> at <ISO>' > "
        "ops/approvals/<token>.approval && \\",
        "     git add ops/approvals/<token>.approval && git commit -m \\",
        "       'approval: <task-id>' && git push",
        "  2. Or edit the task JSON to set dry_run=true and re-queue.",
        "",
        "See ops/AGENT_VERIFICATION_PROTOCOL.md → 'High-risk approval "
        "tokens' for the full policy.",
    ]
    return "\n".join(lines)
