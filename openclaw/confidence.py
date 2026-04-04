"""Confidence scoring — autonomous vs review vs flag Matt (symphony-next-level)."""

from __future__ import annotations

import re
from typing import Any, Literal

Band = Literal["flag_human", "review_queue", "autonomous"]
ActMode = Literal["autonomous", "act_and_review", "flag_for_approval"]

# Rolling positive rates from decision_journal (set by calibrate_from_journal)
_category_positive_rate: dict[str, float] = {}


def band_from_score(score: float) -> Band:
    """Map 0–100 confidence to orchestrator policy."""
    if score < 50:
        return "flag_human"
    if score < 80:
        return "review_queue"
    return "autonomous"


def should_act(confidence: float) -> ActMode:
    """Alias for orchestrator gating."""
    b = band_from_score(confidence)
    if b == "flag_human":
        return "flag_for_approval"
    if b == "review_queue":
        return "act_and_review"
    return "autonomous"


def calibrate_from_journal(journal: Any) -> None:
    """Update rolling accuracy baselines from journal outcomes (fast DB read each tick)."""
    global _category_positive_rate
    for cat in ("email", "trading", "jobs", "followup", "client"):
        try:
            acc = journal.get_accuracy(category=cat, days=30)
            n = int(acc.get("with_outcome", 0) or 0)
            if n >= 3:
                _category_positive_rate[cat] = float(acc.get("positive_rate", 0.7))
        except Exception:
            continue


def _heuristic_email(email_data: dict[str, Any], classification: str, known_client: bool) -> int:
    score = 60
    cat = (classification or "").upper()
    if cat in ("BID_INVITE", "CLIENT_INQUIRY"):
        score += 15
    if email_data.get("priority") == "high":
        score += 10
    if known_client:
        score += 10
    subj = (email_data.get("subject") or "") + " " + (email_data.get("snippet") or "")
    if re.search(r"\$\s*[\d,]+|\b\d{4,}\b", subj):
        score -= 15
    if len(subj) > 800:
        score -= 5
    return max(0, min(100, score))


def score_email_action(
    email_data: dict[str, Any],
    classification: str,
    known_client: bool = False,
) -> int:
    """Heuristic 0–100, adjusted by rolling email category positive rate."""
    base = _heuristic_email(email_data, classification, known_client)
    historical = _category_positive_rate.get("email", 0.7)
    adjustment = (historical - 0.7) * 20.0
    return max(0, min(100, int(base + adjustment)))


def score_trade_alert(trade_data: dict[str, Any]) -> int:
    """Heuristic for trading-related orchestrator actions."""
    loss = float(trade_data.get("unrealized_pnl", 0) or 0)
    base = 65
    if loss < -50:
        base = 85
    elif loss < -20:
        base = 75
    historical = _category_positive_rate.get("trading", 0.7)
    adjustment = (historical - 0.7) * 15.0
    return max(0, min(100, int(base + adjustment)))
