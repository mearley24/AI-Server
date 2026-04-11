"""GoalTracker — tracks Bob's objectives and progress."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from cortex.config import OLLAMA_HOST, OLLAMA_MODEL
from cortex.memory import MemoryStore

logger = structlog.get_logger(__name__)

SEED_GOALS: list[dict[str, Any]] = [
    {
        "title": "Maximize daily trading profit",
        "description": (
            "Increase net daily P/L across all strategies. "
            "Current: ~$2-5/day target. Stretch: $20/day."
        ),
        "goal_type": "financial",
        "priority": 10,
        "target_metric": "daily_net_pnl",
        "current_value": "2.00",
        "target_value": "20.00",
    },
    {
        "title": "Maintain 60%+ win rate across all strategies",
        "description": (
            "Track resolved trade win rate. Currently variable. "
            "Target sustained 60%+."
        ),
        "goal_type": "performance",
        "priority": 9,
        "target_metric": "overall_win_rate",
        "current_value": "0.50",
        "target_value": "0.60",
    },
    {
        "title": "Discover and validate one new edge per week",
        "description": (
            "From X intel, research, whale watching, or pattern mining. "
            "Must be backtestable."
        ),
        "goal_type": "growth",
        "priority": 8,
        "target_metric": "new_edges_per_week",
        "current_value": "0",
        "target_value": "1",
    },
    {
        "title": "Zero downtime on trading operations",
        "description": (
            "Bot should trade 24/7. No missed trades due to crashes, "
            "network issues, or stale containers."
        ),
        "goal_type": "reliability",
        "priority": 10,
        "target_metric": "uptime_percent",
        "current_value": "0.90",
        "target_value": "0.99",
    },
    {
        "title": "Reduce Matt's required intervention to zero",
        "description": (
            "Bob should self-heal, self-tune, and self-improve "
            "without Matt needing to check in."
        ),
        "goal_type": "autonomy",
        "priority": 9,
        "target_metric": "manual_interventions_per_week",
        "current_value": "10",
        "target_value": "0",
    },
]


class GoalTracker:
    """Tracks Bob's objectives and progress against them."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store
        self._seed_goals()

    def _seed_goals(self) -> None:
        """Ensure all seed goals exist in the DB."""
        for goal in SEED_GOALS:
            self.memory.upsert_goal(goal)
        logger.info("goals_seeded", count=len(SEED_GOALS))

    def update_progress(
        self,
        goal_id: str,
        new_value: str,
        note: str = "",
    ) -> None:
        """Update a goal's current value and append to progress_log."""
        self.memory.update_goal_value(goal_id, new_value, note)
        logger.info("goal_progress_updated", goal_id=goal_id, value=new_value)

    def check_goals(self) -> list[dict[str, Any]]:
        """Review all active goals. Returns list of status dicts."""
        goals = self.memory.get_goals(status="active")
        results = []
        for g in goals:
            try:
                current = float(g["current_value"])
                target = float(g["target_value"])
                gap = target - current
                if target != 0:
                    progress_pct = min(100.0, (current / target) * 100)
                else:
                    progress_pct = 100.0

                if gap <= 0:
                    status = "achieved"
                elif progress_pct >= 80:
                    status = "close"
                elif progress_pct >= 50:
                    status = "on_track"
                else:
                    status = "needs_attention"

                recommendation = self._recommend(g, gap, status)

            except (ValueError, TypeError):
                # Non-numeric goals
                status = "active"
                gap = None
                progress_pct = None
                recommendation = "Check status manually."

            results.append({
                "goal_id": g["id"],
                "title": g["title"],
                "goal_type": g["goal_type"],
                "priority": g["priority"],
                "current_value": g["current_value"],
                "target_value": g["target_value"],
                "status": status,
                "gap": gap,
                "progress_pct": progress_pct,
                "recommendation": recommendation,
            })

        return results

    def _recommend(
        self,
        goal: dict[str, Any],
        gap: float | None,
        status: str,
    ) -> str:
        """Generate a simple recommendation based on gap and goal type."""
        if status == "achieved":
            return "Goal achieved! Consider raising the target."
        if gap is None:
            return "Monitor manually."

        metric = goal.get("target_metric", "")
        if metric == "daily_net_pnl":
            if gap > 10:
                return "Focus on high-conviction trades and reduce category spread."
            return "Keep current approach; incremental gains add up."
        if metric == "overall_win_rate":
            if gap > 0.1:
                return "Tighten entry filters — avoid <40¢ entries and US sports."
            return "Fine-tune position sizing to protect win rate."
        if metric == "new_edges_per_week":
            return "Run opportunity scanner daily; prioritize X intel signals."
        if metric == "uptime_percent":
            return "Review Docker restart policies and health-check intervals."
        if metric == "manual_interventions_per_week":
            return "Automate the top recurring manual task this week."
        return f"Gap is {gap:.2f} — focus effort here."

    async def suggest_subgoals(self, goal_id: str) -> list[str]:
        """Use Ollama to suggest concrete sub-goals for a parent goal."""
        goals = self.memory.get_goals()
        goal = next((g for g in goals if g["id"] == goal_id), None)
        if not goal:
            return []

        prompt = (
            f"You are Bob's goal advisor. The main goal is:\n"
            f"Title: {goal['title']}\n"
            f"Description: {goal['description']}\n"
            f"Current: {goal['current_value']} → Target: {goal['target_value']}\n\n"
            f"Suggest 3-5 concrete, measurable sub-goals that would help achieve this. "
            f"Reply with one sub-goal per line, no bullets or numbering."
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
                text = resp.json().get("response", "")
                subgoals = [s.strip() for s in text.strip().split("\n") if s.strip()]
                return subgoals[:5]
        except Exception as exc:
            logger.error("suggest_subgoals_error", goal_id=goal_id, error=str(exc))
            return []
