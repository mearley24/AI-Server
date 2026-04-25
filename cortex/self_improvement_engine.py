"""Self-improvement rule engine.

Manages the lifecycle of promoted self-improvement rules:
  - load / save (atomic write)
  - approve / reject
  - get_active_rules()
  - derive behavior hints for reply drafting, triage scoring, follow-up thresholds

Import-safe: works inside the cortex container (reading /data/cortex/) and
from host scripts (reading ~/AI-Server/data/cortex/) via the same fallback
path logic used throughout cortex/engine.py.

Rules are never auto-approved. All status changes require an explicit API call.
If the rules file is missing or malformed, every public function returns a safe
empty/default value so callers never crash.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Path resolution (mirrors cortex/engine.py pattern) ────────────────────────

_CORTEX_DATA_DIR = Path(os.environ.get("CORTEX_DATA_DIR", "/data/cortex"))
if not _CORTEX_DATA_DIR.is_dir():
    _CORTEX_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cortex"

PROMOTED_RULES_PATH = _CORTEX_DATA_DIR / "promoted_rules.json"

# Behaviour categories derived from rule text
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("reply_phrasing",      ["phrasing", "draft reply", "wording", "response style", "avoid generic", "prefer short", "self-fix before"]),
    ("triage_scoring",      ["triage", "scoring", "review value", "prioritize repeat", "deprioritize unnamed", "scoring weight"]),
    ("follow_up_threshold", ["follow-up", "follow up", "threshold", "urgency", "overdue"]),
    ("pipeline",            ["imessage", "x_intake", "bridge", "batch consolidat", "dedup", "card pipeline", "self-improvement collector"]),
]


# ── I/O helpers ────────────────────────────────────────────────────────────────

def _load_data() -> dict[str, Any]:
    """Return parsed JSON from PROMOTED_RULES_PATH, or empty structure on error."""
    try:
        return json.loads(PROMOTED_RULES_PATH.read_text())
    except Exception:
        return {"rules": [], "updated_at": "", "card_count": 0}


def _save_data(data: dict[str, Any]) -> None:
    """Atomically write data dict to PROMOTED_RULES_PATH."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = PROMOTED_RULES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, PROMOTED_RULES_PATH)


def _derive_category(proposed_behavior: str) -> str:
    text = proposed_behavior.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return "general"


# ── Public API ─────────────────────────────────────────────────────────────────

def get_active_rules() -> list[dict[str, Any]]:
    """Return all approved rules. Returns [] if file missing or malformed."""
    try:
        data = _load_data()
        return [r for r in data.get("rules", []) if r.get("status") == "approved"]
    except Exception:
        return []


def get_all_rules() -> list[dict[str, Any]]:
    """Return all rules regardless of status."""
    try:
        return _load_data().get("rules", [])
    except Exception:
        return []


def approve_rule(rule_id: str, approved_by: str = "matt") -> dict[str, Any]:
    """Set a rule's status to approved. Returns the updated rule or error dict."""
    data = _load_data()
    rules = data.get("rules", [])
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            if rule.get("status") == "approved":
                return {"error": f"{rule_id} is already approved"}
            rule["status"] = "approved"
            rule["approved_at"] = datetime.now(timezone.utc).isoformat()
            rule["approved_by"] = approved_by
            rule.pop("rejected_at", None)
            rule.pop("rejected_reason", None)
            rule["behavior_category"] = _derive_category(rule.get("proposed_behavior", ""))
            data["rules"] = rules
            _save_data(data)
            return dict(rule)
    return {"error": f"rule_id {rule_id!r} not found"}


def reject_rule(rule_id: str, reason: str = "") -> dict[str, Any]:
    """Set a rule's status to rejected. Returns the updated rule or error dict."""
    data = _load_data()
    rules = data.get("rules", [])
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            if rule.get("status") == "rejected":
                return {"error": f"{rule_id} is already rejected"}
            rule["status"] = "rejected"
            rule["rejected_at"] = datetime.now(timezone.utc).isoformat()
            rule["rejected_reason"] = reason
            rule.pop("approved_at", None)
            rule.pop("approved_by", None)
            data["rules"] = rules
            _save_data(data)
            return dict(rule)
    return {"error": f"rule_id {rule_id!r} not found"}


def get_active_rules_by_category(category: str) -> list[dict[str, Any]]:
    """Return active rules filtered by behavior_category.

    At most one rule per category is returned — the most recently approved one.
    This prevents conflicting rules from stacking.
    """
    candidates = [
        r for r in get_active_rules()
        if r.get("behavior_category") == category
    ]
    if not candidates:
        return []
    # Keep only the most recently approved rule (conflict prevention)
    candidates.sort(key=lambda r: r.get("approved_at", ""), reverse=True)
    return [candidates[0]]


# ── Behavior application helpers ───────────────────────────────────────────────

def apply_reply_hints(active_rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive reply-drafting behavior hints from approved reply_phrasing rules.

    Returns a dict of hint flags; empty dict means no active influence.
    Callers should wrap in try/except so a broken rule never crashes a reply.
    """
    rules = [r for r in active_rules if r.get("behavior_category") == "reply_phrasing"]
    if not rules:
        return {}
    # Most-recently-approved rule wins
    rule = sorted(rules, key=lambda r: r.get("approved_at", ""), reverse=True)[0]
    behavior = rule.get("proposed_behavior", "").lower()

    hints: dict[str, Any] = {"_rule_id": rule["rule_id"]}
    if "avoid generic" in behavior or "specific phrasing" in behavior:
        hints["avoid_generic"] = True
    if "short response" in behavior or "prefer short" in behavior or "concise" in behavior:
        hints["prefer_short"] = True
    if "self-fix before" in behavior or "self_fix" in behavior:
        hints["prefer_self_fix_first"] = True
    return hints


def apply_triage_boost(active_rules: list[dict[str, Any]], base_score: float) -> float:
    """Adjust review_value_score based on approved triage_scoring rules.

    Additive adjustment capped at ±0.15 per rule. Returns base_score unchanged
    if no relevant active rules or if adjustment would push score out of [0, 1].
    """
    rules = [r for r in active_rules if r.get("behavior_category") == "triage_scoring"]
    if not rules:
        return base_score
    rule = sorted(rules, key=lambda r: r.get("approved_at", ""), reverse=True)[0]
    behavior = (rule.get("proposed_behavior") or "").lower()

    adjustment = 0.0
    if "prioritize repeat" in behavior:
        adjustment += 0.05
    if "deprioritize unnamed" in behavior:
        adjustment -= 0.05
    if "high value" in behavior and "boost" in behavior:
        adjustment += 0.05

    return round(min(1.0, max(0.0, base_score + adjustment)), 3)


def apply_followup_adjustments(active_rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Return follow-up threshold adjustments from approved follow_up_threshold rules.

    Returns empty dict if no relevant active rules.
    """
    rules = [r for r in active_rules if r.get("behavior_category") == "follow_up_threshold"]
    if not rules:
        return {}
    rule = sorted(rules, key=lambda r: r.get("approved_at", ""), reverse=True)[0]
    behavior = rule.get("proposed_behavior", "").lower()

    adjustments: dict[str, Any] = {"_rule_id": rule["rule_id"]}
    if ("urgent" in behavior and ("reduce" in behavior or "lower" in behavior or "faster" in behavior)):
        adjustments["urgent_threshold_hours_multiplier"] = 0.75
    if "client" in behavior and "priority" in behavior:
        adjustments["client_priority_boost"] = True
    return adjustments


def log_applied_rules(rule_ids: list[str], context: str = "") -> None:
    """Write a one-line audit entry for rules applied in a given action.

    Does nothing if the log directory isn't writable — never crashes callers.
    """
    if not rule_ids:
        return
    try:
        log_path = _CORTEX_DATA_DIR / "rule_application_log.ndjson"
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "rule_ids": rule_ids,
        })
        with log_path.open("a") as fh:
            fh.write(entry + "\n")
    except Exception:
        pass


def migrate_existing_rules() -> int:
    """Add new schema fields to rules that pre-date the approval system.

    Idempotent — safe to call multiple times. Returns count of rules migrated.
    """
    data = _load_data()
    rules = data.get("rules", [])
    changed = 0
    for rule in rules:
        dirty = False
        if "approved_at" not in rule:
            rule["approved_at"] = None
            dirty = True
        if "approved_by" not in rule:
            rule["approved_by"] = None
            dirty = True
        if "rejected_at" not in rule:
            rule["rejected_at"] = None
            dirty = True
        if "rejected_reason" not in rule:
            rule["rejected_reason"] = None
            dirty = True
        if "behavior_category" not in rule:
            rule["behavior_category"] = _derive_category(rule.get("proposed_behavior", ""))
            dirty = True
        if dirty:
            changed += 1
    if changed:
        data["rules"] = rules
        _save_data(data)
    return changed
