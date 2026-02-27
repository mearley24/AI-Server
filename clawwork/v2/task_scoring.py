#!/usr/bin/env python3
"""
task_scoring.py
===============
Intelligent task scoring and selection algorithm for Bob's ClawWork side hustle.

Evaluates each available task on five dimensions:
  1. Pay rate ($/hour effective)
  2. Completion speed (inverse of time required)
  3. Skill match (Bob's domain expertise alignment)
  4. Reputation impact (review likelihood and quality)
  5. Client quality (repeat client, enterprise, reliable payer)

Applies configurable weights to produce a composite score (0.0–1.0).
Tasks below threshold are auto-declined. Prioritizes Symphony queue check
before accepting any task.

Usage:
    from task_scoring import TaskScorer, TaskCandidate
    
    scorer = TaskScorer(config)
    scored = scorer.evaluate(task_candidate)
    if scored.accept:
        # proceed with task
"""

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("clawwork.scorer")

# ── Default scoring weights ───────────────────────────────────────────────────────
DEFAULT_WEIGHTS = {
    "pay_rate":          0.35,   # $/hour effective rate
    "completion_speed":  0.20,   # inverse of time required
    "skill_match":       0.25,   # Bob's domain expertise alignment (1–5 → normalized)
    "reputation_impact": 0.10,   # review likelihood and quality
    "client_quality":    0.10,   # repeat client, enterprise, reliable
}

# Minimum effective $/hr to even consider a task
MINIMUM_EFFECTIVE_HOURLY = 40.0

# Normalisation caps (values beyond these are treated as max)
PAY_RATE_CAP      = 200.0   # $/hour
SPEED_CAP_MINUTES = 120.0   # tasks longer than 2h score 0 on speed


# ── Data classes ─────────────────────────────────────────────────────────────────────

@dataclass
class TaskCandidate:
    """
    Represents a single available task from any ClawWork platform.

    All monetary values are in USD.
    """
    task_id:             str
    title:               str
    platform:            str          # 'upwork' | 'fiverr' | 'gdpval' | 'codementor' | 'direct'
    sector:              str          # e.g. 'research_reports'
    estimated_value_usd: float        # gross payout before platform fees
    estimated_minutes:   int          # estimated completion time
    skill_match_score:   int          # 1–5, Bob's self-assessment of fit
    client_id:           Optional[str] = None
    client_history:      dict         = field(default_factory=dict)
    # Optional enrichment
    has_review_history:  bool         = False  # True if client has left reviews before
    is_enterprise_client:bool         = False
    is_repeat_client:    bool         = False
    brief:               str          = ""
    required_skills:     list         = field(default_factory=list)
    deadline_hours:      Optional[int] = None
    posted_at:           Optional[datetime] = None


@dataclass
class ScoredTask:
    """
    Result of scoring a TaskCandidate.
    """
    task:             TaskCandidate
    composite_score:  float
    pay_rate_score:   float
    speed_score:      float
    skill_score:      float
    reputation_score: float
    client_score:     float
    effective_hourly: float
    accept:           bool
    action:           str    # 'accept' | 'decline' | 'queue'
    decline_reason:   str    = ""
    notes:            list   = field(default_factory=list)


# ── TaskScorer ────────────────────────────────────────────────────────────────────────────

class TaskScorer:
    """
    Scores and ranks available tasks using a weighted multi-criteria algorithm.

    Weights sum to 1.0. Composite score is in the range [0.0, 1.0].
    """

    def __init__(self, config: dict, start_date: Optional[datetime] = None):
        """
        Args:
            config:     Full clawwork_config.json dict
            start_date: First day of ClawWork operations (for phase detection)
        """
        scoring_cfg       = config.get("task_scoring", {})
        self.weights      = {**DEFAULT_WEIGHTS, **scoring_cfg.get("weights", {})}
        self.min_accept   = scoring_cfg.get("min_accept_score", 0.65)
        self.auto_decline = scoring_cfg.get("auto_decline_below", 0.45)
        self.min_hourly   = scoring_cfg.get("min_effective_hourly", MINIMUM_EFFECTIVE_HOURLY)
        self.start_date   = start_date or datetime.utcnow()
        self._validate_weights()
        log.info("TaskScorer initialised | weights=%s | accept>=%.2f",
                 self.weights, self.min_accept)

    # ── Public API ──────────────────────────────────────────────────────────────────

    def evaluate(self, task: TaskCandidate) -> ScoredTask:
        """
        Score a single task and return an accept/decline decision.

        Returns:
            ScoredTask with .accept bool and .action str.
        """
        effective_hourly = self._effective_hourly(task)

        # Hard gate — below minimum hourly, auto-decline unless reputation phase
        if effective_hourly < self.min_hourly and not self._is_reputation_phase(task):
            return self._decline(task, "Below minimum hourly rate",
                                 effective_hourly=effective_hourly)

        pay_score        = self._score_pay_rate(effective_hourly)
        speed_score      = self._score_speed(task.estimated_minutes)
        skill_score      = self._score_skill(task.skill_match_score)
        rep_score        = self._score_reputation(task)
        client_score     = self._score_client(task)

        composite = (
            pay_score        * self.weights["pay_rate"]          +
            speed_score      * self.weights["completion_speed"]   +
            skill_score      * self.weights["skill_match"]        +
            rep_score        * self.weights["reputation_impact"]  +
            client_score     * self.weights["client_quality"]
        )

        # Randomisation: 10% chance to explore non-optimal sectors
        if random.random() < 0.10:
            composite = min(1.0, composite + 0.05)

        action = self._decide_action(composite)
        accept = action == "accept"

        result = ScoredTask(
            task             = task,
            composite_score  = round(composite, 4),
            pay_rate_score   = pay_score,
            speed_score      = speed_score,
            skill_score      = skill_score,
            reputation_score = rep_score,
            client_score     = client_score,
            effective_hourly = effective_hourly,
            accept           = accept,
            action           = action,
            notes            = self._generate_notes(task, effective_hourly, composite),
        )
        log.info("Scored task %s | composite=%.4f | action=%s",
                 task.task_id, composite, action)
        return result

    def rank_tasks(self, tasks: list) -> list:
        """
        Score and sort a list of TaskCandidate objects.

        Returns a list of ScoredTask sorted by composite_score descending,
        with only accepted or queued tasks included (declines filtered out).
        """
        scored = [self.evaluate(t) for t in tasks]
        # Keep accepts and queued; filter hard declines
        filtered = [s for s in scored if s.action in ("accept", "queue")]
        filtered.sort(key=lambda s: s.composite_score, reverse=True)
        log.info("Ranked %d/%d tasks", len(filtered), len(tasks))
        return filtered

    # ── Scoring sub-functions ───────────────────────────────────────────────────────────

    def _effective_hourly(self, task: TaskCandidate) -> float:
        """Calculate the effective $/hour rate for a task."""
        if task.estimated_minutes <= 0:
            return 0.0
        # Approximate platform fee (conservative 20% across all platforms)
        net_value = task.estimated_value_usd * 0.80
        hours     = task.estimated_minutes / 60.0
        return net_value / hours

    def _score_pay_rate(self, effective_hourly: float) -> float:
        """
        Normalise $/hour to [0, 1].

        $40/hr → 0.20 (floor)   $80/hr → 0.40   $120/hr → 0.60
        $160/hr → 0.80          $200/hr → 1.00
        """
        return min(1.0, max(0.0, effective_hourly / PAY_RATE_CAP))

    def _score_speed(self, minutes: int) -> float:
        """
        Shorter tasks score higher on speed.

        0 min → 1.0    30 min → 0.75    60 min → 0.50
        90 min → 0.25  120 min+ → 0.0
        """
        if minutes <= 0:
            return 1.0
        return max(0.0, 1.0 - (minutes / SPEED_CAP_MINUTES))

    def _score_skill(self, skill_match: int) -> float:
        """
        Convert 1–5 skill match score to [0, 1].

        1 → 0.0   2 → 0.25   3 → 0.50   4 → 0.75   5 → 1.0
        """
        return max(0.0, min(1.0, (skill_match - 1) / 4.0))

    def _score_reputation(self, task: TaskCandidate) -> float:
        """
        Score based on likelihood of receiving a positive review.

        Factors:
          - Client has left reviews before (+0.3)
          - Enterprise client who leaves detailed reviews (+0.2)
          - Sector has naturally high review rates (+0.1 for research, tech_writing)
        """
        score = 0.3   # baseline
        if task.has_review_history:
            score += 0.3
        if task.is_enterprise_client:
            score += 0.2
        if task.sector in ("research_reports", "technical_writing", "bookkeeping"):
            score += 0.1
        return min(1.0, score)

    def _score_client(self, task: TaskCandidate) -> float:
        """
        Score based on client quality.

        Repeat client: +0.4
        Enterprise:    +0.3
        On-time payer: +0.2 (from client_history)
        Review history:+0.1
        """
        score = 0.2  # baseline for unknown new client
        if task.is_repeat_client:
            score += 0.4
        if task.is_enterprise_client:
            score += 0.3
        if task.client_history.get("always_pays_on_time"):
            score += 0.2
        if task.has_review_history:
            score += 0.1
        return min(1.0, score)

    # ── Decision logic ─────────────────────────────────────────────────────────────────────

    def _decide_action(self, composite: float) -> str:
        """
        Map composite score to accept/queue/decline action.

        score >= min_accept  → 'accept'
        score >= auto_decline → 'queue'  (wait 5 min for better task)
        score < auto_decline  → 'decline'
        """
        if composite >= self.min_accept:
            return "accept"
        elif composite >= self.auto_decline:
            return "queue"
        else:
            return "decline"

    def _is_reputation_phase(self, task: TaskCandidate) -> bool:
        """
        Returns True if we are in the reputation-building phase (first 30 days)
        AND the task has reputation value (likely to produce a review).
        """
        days_active = (datetime.utcnow() - self.start_date).days
        is_early    = days_active < 30
        has_rep_value = task.has_review_history or task.client_history.get("leaves_reviews")
        return is_early and has_rep_value

    def _decline(self, task, reason, *, effective_hourly=0.0) -> ScoredTask:
        """Shortcut to produce a declined ScoredTask."""
        return ScoredTask(
            task             = task,
            composite_score  = 0.0,
            pay_rate_score   = 0.0,
            speed_score      = 0.0,
            skill_score      = self._score_skill(task.skill_match_score),
            reputation_score = 0.0,
            client_score     = 0.0,
            effective_hourly = effective_hourly,
            accept           = False,
            action           = "decline",
            decline_reason   = reason,
        )

    def _generate_notes(self, task, hourly, composite) -> list:
        """Human-readable notes for logging / dashboard display."""
        notes = []
        if hourly >= 120:
            notes.append(f"High-value task (${hourly:.0f}/hr effective)")
        if task.is_repeat_client:
            notes.append("Repeat client — priority bump applied")
        if task.sector in ("research_reports", "technical_writing"):
            notes.append("Tier 1 sector — Bob's domain advantage active")
        if composite >= 0.90:
            notes.append("Top-tier score — accept immediately")
        return notes

    # ── Utilities ────────────────────────────────────────────────────────────────────────────

    def _validate_weights(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.4f}: {self.weights}"
            )

    def to_dict(self) -> dict:
        """Serialise scorer configuration for logging."""
        return {
            "weights":       self.weights,
            "min_accept":    self.min_accept,
            "auto_decline":  self.auto_decline,
            "min_hourly":    self.min_hourly,
            "start_date":    self.start_date.isoformat(),
        }


# ── GDPVal integration helpers ───────────────────────────────────────────────────────

def fetch_gdpval_tasks(api_url: str, api_key: str) -> list:
    """
    Fetch available tasks from the GDPVal benchmark API.

    Returns a list of TaskCandidate objects.
    """
    try:
        resp = requests.get(
            f"{api_url}/tasks/available",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw_tasks = resp.json().get("tasks", [])
    except requests.RequestException as e:
        log.error("GDPVal fetch failed: %s", e)
        return []

    candidates = []
    for rt in raw_tasks:
        try:
            cand = TaskCandidate(
                task_id             = rt["task_id"],
                title               = rt.get("title", "Untitled"),
                platform            = "gdpval",
                sector              = rt.get("category", "general"),
                estimated_value_usd = float(rt["value_usd"]),
                estimated_minutes   = int(rt.get("estimated_minutes", 30)),
                skill_match_score   = _guess_skill_match(rt.get("category", "")),
                brief               = rt.get("description", ""),
            )
            candidates.append(cand)
        except (KeyError, ValueError) as e:
            log.warning("Skipping malformed GDPVal task %s: %s",
                        rt.get("task_id", "?"), e)

    log.info("Fetched %d GDPVal task candidates", len(candidates))
    return candidates


def _guess_skill_match(category: str) -> int:
    """
    Map GDPVal task category to Bob's 1–5 skill match score.
    """
    mapping = {
        "research":          5,
        "financial":         5,
        "accounting":        5,
        "real_estate":       5,
        "technical_writing": 5,
        "coding":            4,
        "code_review":       4,
        "content":           4,
        "writing":           4,
        "customer_support":  3,
        "data_entry":        3,
        "translation":       2,
        "creative_writing":  2,
        "legal":             1,
        "medical":           1,
    }
    for key, score in mapping.items():
        if key in category.lower():
            return score
    return 3  # default: moderate fit


# ── Symphony queue check ─────────────────────────────────────────────────────────────────

def symphony_queue_is_empty(endpoint: str, timeout: int = 5) -> bool:
    """
    Check whether the Symphony Smart Homes task queue is empty.

    Returns True (safe to continue ClawWork) or False (switch to Symphony).
    On network error, conservatively returns False (Symphony takes priority).
    """
    try:
        resp = requests.get(endpoint, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        queue_len = data.get("queue_length", 1)
        is_empty  = queue_len == 0
        if not is_empty:
            log.info("Symphony queue has %d tasks — suspending ClawWork", queue_len)
        return is_empty
    except requests.RequestException as e:
        log.warning("Symphony queue check failed (%s) — defaulting to Symphony", e)
        return False


# ── Demonstration / CLI ────────────────────────────────────────────────────────────────────

def main():
    """Demo: score a handful of representative tasks and print the ranked list."""
    config = {
        "task_scoring": {
            "min_accept_score":  0.65,
            "auto_decline_below": 0.45,
            "min_effective_hourly": 40.0,
        }
    }

    scorer = TaskScorer(config, start_date=datetime(2026, 2, 27))

    sample_tasks = [
        TaskCandidate(
            task_id="GDPVAL-001",
            title="Competitive analysis report — SaaS market",
            platform="gdpval",
            sector="research_reports",
            estimated_value_usd=320.0,
            estimated_minutes=90,
            skill_match_score=5,
            has_review_history=True,
            is_enterprise_client=True,
        ),
        TaskCandidate(
            task_id="UPW-042",
            title="Write 3 blog posts about smart home technology",
            platform="upwork",
            sector="content_writing",
            estimated_value_usd=75.0,
            estimated_minutes=60,
            skill_match_score=4,
            has_review_history=True,
        ),
        TaskCandidate(
            task_id="FVR-019",
            title="Data entry — 500 rows in CSV",
            platform="fiverr",
            sector="data_entry",
            estimated_value_usd=15.0,
            estimated_minutes=45,
            skill_match_score=3,
        ),
        TaskCandidate(
            task_id="GDPVAL-002",
            title="Reconcile accounts payable ledger for October",
            platform="gdpval",
            sector="bookkeeping",
            estimated_value_usd=180.0,
            estimated_minutes=60,
            skill_match_score=5,
            is_repeat_client=True,
            client_history={"always_pays_on_time": True, "leaves_reviews": True},
        ),
        TaskCandidate(
            task_id="UPW-043",
            title="Translate product manual from English to Spanish",
            platform="upwork",
            sector="translation",
            estimated_value_usd=40.0,
            estimated_minutes=120,
            skill_match_score=2,
        ),
    ]

    ranked = scorer.rank_tasks(sample_tasks)

    print("\n── ClawWork Task Ranking ──\n")
    print(f"{'Rank':<5} {'Score':<7} {'Action':<8} {'$/hr':<7} {'Title'}")
    print("-" * 70)
    for i, result in enumerate(ranked, 1):
        print(f"{i:<5} {result.composite_score:<7.4f} {result.action:<8} "
              f"${result.effective_hourly:<6.0f} {result.task.title[:44]}")
    print()

    declined = [r for r in [scorer.evaluate(t) for t in sample_tasks]
                if r.action == "decline"]
    if declined:
        print("── Declined ──")
        for result in declined:
            print(f"  {result.task.title[:44]} — {result.decline_reason}")


if __name__ == "__main__":
    main()
