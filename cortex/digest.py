"""DigestBuilder — builds daily and weekly summaries for Matt."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from cortex.config import DIGESTS_DIR
from cortex.goals import GoalTracker
from cortex.memory import MemoryStore

logger = structlog.get_logger(__name__)


class DigestBuilder:
    """Builds daily and weekly digests for Matt."""

    def __init__(self, memory: MemoryStore, goals: GoalTracker) -> None:
        self.memory = memory
        self.goals = goals

    async def build_daily_digest(self) -> dict[str, Any]:
        """Build a daily summary. Saved to /data/cortex/digests/YYYY-MM-DD.md"""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # 1. Memory stats
        stats = self.memory.get_stats()

        # 2. Goal progress
        goal_status = self.goals.check_goals()

        # 3. New learnings (memories added today)
        new_memories = self.memory.get_recent(hours=24, limit=20)

        # 4. Improvement actions (from improvement_log)
        improvement_rows = self._get_recent_improvements(hours=24)

        # 5. Opportunities (high-importance x_intel + edge memories from today)
        opps = self.memory.get_recent(hours=24, limit=10)
        opps = [m for m in opps if m.get("category") in ("x_intel", "edge", "market_pattern")]

        # 6. Strategy ideas pipeline
        ideas = self.memory.get_by_category("strategy_idea", limit=10)

        # 7. Trading rules summary
        top_rules = self.memory.get_rules(category="trading_rule", min_confidence=0.7)

        # Build markdown
        lines = [
            f"# Cortex Daily Digest — {date_str}",
            "",
            "## 📊 Memory Stats",
            f"- Total memories: **{stats['total']}**",
            f"- Active goals: **{stats['active_goals']}**",
            f"- Pending decisions: **{stats['pending_decisions']}**",
            "",
            "By category:",
        ]
        for cat, info in stats.get("by_category", {}).items():
            lines.append(f"  - {cat}: {info['count']} (avg confidence: {info['avg_confidence']:.2f})")

        lines += ["", "## 🎯 Goal Progress"]
        for g in goal_status:
            icon = "✅" if g["status"] == "achieved" else ("🟡" if g["status"] == "on_track" else "🔴")
            lines.append(
                f"- {icon} **{g['title']}**: {g['current_value']} → {g['target_value']} "
                f"({g['status']}, priority {g['priority']})"
            )
            if g.get("recommendation"):
                lines.append(f"  - 💡 {g['recommendation']}")

        lines += ["", "## 🧠 New Learnings (Last 24h)"]
        if new_memories:
            for m in new_memories[:8]:
                lines.append(f"- **[{m['category']}]** {m['title']} (importance={m['importance']})")
        else:
            lines.append("- No new memories in the last 24 hours.")

        lines += ["", "## ⚙️ Improvement Actions"]
        if improvement_rows:
            for row in improvement_rows[:5]:
                actions = json.loads(row.get("actions_taken", "[]"))
                lines.append(f"- **{row['loop_type']}** ({row['created_at'][:10]}): {row['findings'][:100]}")
                for a in actions[:3]:
                    lines.append(f"  - {a}")
        else:
            lines.append("- No improvement actions recorded today.")

        lines += ["", "## 🔍 Opportunities Found"]
        if opps:
            for o in opps[:5]:
                lines.append(f"- **{o['category']}**: {o['title']} (importance={o['importance']})")
        else:
            lines.append("- No new opportunities flagged today.")

        lines += ["", "## 💡 Ideas Pipeline"]
        active_ideas = [i for i in ideas if "implementing" in json.loads(i.get("tags", "[]"))]
        pending_ideas = [i for i in ideas if "pending" in json.loads(i.get("tags", "[]"))]
        lines.append(f"- **Implementing** ({len(active_ideas)}): {', '.join(i['title'] for i in active_ideas) or 'none'}")
        lines.append(f"- **Pending** ({len(pending_ideas)}): {', '.join(i['title'] for i in pending_ideas[:3]) or 'none'}")

        lines += ["", "## 📏 Top Trading Rules (confidence ≥ 0.7)"]
        for r in top_rules[:8]:
            lines.append(f"- [{r['confidence']:.0%}] **{r['title']}**")

        lines += ["", f"---", f"*Generated at {now.isoformat()}*"]

        content = "\n".join(lines)

        # Save to file
        digest_data = {
            "date": date_str,
            "stats": stats,
            "goal_status": goal_status,
            "new_memories_count": len(new_memories),
            "opportunities_count": len(opps),
            "markdown": content,
        }

        self._save_digest(f"{date_str}.md", content)
        logger.info("daily_digest_built", date=date_str)
        return digest_data

    async def build_weekly_digest(self) -> dict[str, Any]:
        """Weekly rollup. Saved to /data/cortex/digests/week-YYYY-WNN.md"""
        now = datetime.now(timezone.utc)
        week_str = f"week-{now.strftime('%Y-W%W')}"

        # Memory stats
        stats = self.memory.get_stats()

        # Goal trends
        goal_status = self.goals.check_goals()

        # Top learnings from this week (7 days)
        weekly_memories = self.memory.get_recent(hours=168, limit=50)
        top_weekly = sorted(weekly_memories, key=lambda m: m.get("importance", 0), reverse=True)[:10]

        # Strategy performance memories
        perf_memories = self.memory.get_by_category("strategy_performance", limit=10)

        # Strategy grading (based on performance memories)
        strategy_grades = self._grade_strategies(perf_memories)

        # Improvement loop summary
        improvement_rows = self._get_recent_improvements(hours=168)

        lines = [
            f"# Cortex Weekly Digest — {week_str}",
            "",
            "## 📊 Week Stats",
            f"- Total memories in brain: **{stats['total']}**",
            f"- New memories this week: **{len(weekly_memories)}**",
            f"- Active goals: **{stats['active_goals']}**",
            "",
            "## 🎯 Goal Trends",
        ]
        for g in goal_status:
            progress = f"{g.get('progress_pct', 0):.0f}%" if g.get("progress_pct") else "N/A"
            lines.append(
                f"- **{g['title']}**: progress {progress} — {g['status']}"
            )

        lines += ["", "## 📈 Strategy Report Card"]
        for name, grade in strategy_grades.items():
            lines.append(f"- **{name}**: {grade}")

        lines += ["", "## 🏆 Top Learnings This Week"]
        for m in top_weekly[:8]:
            lines.append(f"- **[{m['category']}]** {m['title']} (importance={m['importance']}, conf={m['confidence']:.2f})")

        lines += ["", "## ⚙️ Improvement Loop Summary"]
        lines.append(f"- Improvement cycles run: **{len(improvement_rows)}**")
        total_actions = sum(
            len(json.loads(r.get("actions_taken", "[]"))) for r in improvement_rows
        )
        lines.append(f"- Total auto-actions taken: **{total_actions}**")

        # Next week focus
        lines += ["", "## 🔭 Next Week Focus"]
        needs_attention = [g for g in goal_status if g["status"] == "needs_attention"]
        if needs_attention:
            for g in needs_attention[:3]:
                lines.append(f"- 🔴 Fix: {g['title']} (currently {g['current_value']}, target {g['target_value']})")
        else:
            lines.append("- All goals on track. Focus on discovering new edges.")

        lines += ["", f"---", f"*Generated at {now.isoformat()}*"]
        content = "\n".join(lines)

        self._save_digest(f"{week_str}.md", content)
        logger.info("weekly_digest_built", week=week_str)
        return {
            "week": week_str,
            "stats": stats,
            "goal_status": goal_status,
            "strategy_grades": strategy_grades,
            "markdown": content,
        }

    def _grade_strategies(self, perf_memories: list[dict]) -> dict[str, str]:
        """Simple letter grade for each strategy based on memory content."""
        grades: dict[str, str] = {}
        known_strategies = ["weather_trader", "copytrade", "cvd_arb", "presolution_scalp", "mean_reversion"]
        for strat in known_strategies:
            # Check if there's a performance memory mentioning this strategy
            related = [m for m in perf_memories if strat in m.get("content", "").lower()]
            if not related:
                grades[strat] = "? (no data)"
            else:
                # Use confidence as a proxy for grade
                avg_conf = sum(m.get("confidence", 0.5) for m in related) / len(related)
                if avg_conf >= 0.85:
                    grades[strat] = "A"
                elif avg_conf >= 0.70:
                    grades[strat] = "B"
                elif avg_conf >= 0.55:
                    grades[strat] = "C"
                else:
                    grades[strat] = "D"
        return grades

    def _get_recent_improvements(self, hours: int = 24) -> list[dict]:
        """Fetch recent improvement log rows."""
        try:
            from datetime import timedelta

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            rows = self.memory.conn.execute(
                "SELECT * FROM improvement_log WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_improvements_error", error=str(exc))
            return []

    def _save_digest(self, filename: str, content: str) -> None:
        """Save digest markdown to /data/cortex/digests/."""
        try:
            DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
            path = DIGESTS_DIR / filename
            path.write_text(content)
            logger.info("digest_saved", path=str(path))
        except Exception as exc:
            logger.error("digest_save_error", error=str(exc))
