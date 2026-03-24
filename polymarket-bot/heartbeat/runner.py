"""Heartbeat runner — Bob's self-review system.

Runs on a schedule (cron or internal timer) to:
1. Check platform health
2. Review strategy performance
3. Update knowledge with learnings
4. Propose parameter adjustments
5. Generate briefing
6. Update HEARTBEAT.md
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from .briefing import BriefingGenerator
from .health_check import HealthChecker
from .knowledge_updater import KnowledgeUpdater
from .parameter_tuner import ParameterTuner
from .strategy_review import StrategyReviewer

logger = structlog.get_logger(__name__)

HEARTBEAT_DIR = Path(__file__).parent.parent
HEARTBEAT_MD = HEARTBEAT_DIR / "HEARTBEAT.md"
REPORTS_DIR = HEARTBEAT_DIR / "heartbeat_reports"


class HeartbeatRunner:
    """Orchestrates Bob's self-review cycle."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.health_checker = HealthChecker()
        self.strategy_reviewer = StrategyReviewer()
        self.knowledge_updater = KnowledgeUpdater()
        self.parameter_tuner = ParameterTuner()
        self.briefing_generator = BriefingGenerator()

    async def run_full_review(self) -> dict:
        """Run a complete self-review cycle.

        Steps: health check -> strategy review -> knowledge update ->
        parameter tuning -> briefing generation -> update HEARTBEAT.md -> save report.
        """
        logger.info("heartbeat_full_review_started")

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "full_review",
        }

        # 1. Health check — are all platforms connected?
        report["health"] = await self.health_checker.check_all()

        # 2. Strategy review — how is each strategy performing?
        report["strategies"] = await self.strategy_reviewer.review_all()

        # 3. Knowledge update — feed learnings back into knowledge graph
        try:
            await self.knowledge_updater.update_from_review(report["strategies"])
        except Exception as e:
            logger.error("heartbeat_knowledge_update_error", error=str(e))

        # 4. Parameter tuning — propose adjustments
        report["proposals"] = await self.parameter_tuner.analyze(report["strategies"])

        # 5. Generate briefing
        report["briefing"] = await self.briefing_generator.generate(report)

        # 6. Send notifications
        try:
            from notifications.manager import NotificationManager
            nm = NotificationManager()
            await nm.on_heartbeat_complete(report)
            if report.get("proposals"):
                await nm.on_proposal(report["proposals"])
        except Exception as e:
            logger.error("heartbeat_notification_error", error=str(e))

        # 7. Update HEARTBEAT.md
        self._update_heartbeat_md(report)

        # 8. Save full report
        self._save_report(report)

        logger.info(
            "heartbeat_full_review_complete",
            strategies_reviewed=len(report["strategies"]),
            proposals=len(report["proposals"]),
        )

        return report

    async def run_quick_pulse(self) -> dict:
        """Quick health check — platforms up, any critical alerts."""
        logger.info("heartbeat_quick_pulse_started")

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "quick_pulse",
        }
        report["health"] = await self.health_checker.check_all()
        self._update_heartbeat_md(report)

        logger.info("heartbeat_quick_pulse_complete")
        return report

    def _update_heartbeat_md(self, report: dict) -> None:
        """Rewrite HEARTBEAT.md with latest status."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        status = "healthy"

        # Determine overall status
        health = report.get("health", {})
        platforms = health.get("platforms", {})
        if any(p.get("status") == "error" for p in platforms.values()):
            status = "degraded"
        if platforms and all(p.get("status") == "error" for p in platforms.values()):
            status = "critical"

        # Build platform table
        platform_rows = ""
        for name, info in platforms.items():
            platform_rows += (
                f"| {name} | {info.get('status', 'unknown')} | "
                f"{info.get('last_check', 'never')} | "
                f"{info.get('notes', '')} |\n"
            )
        if not platform_rows:
            platform_rows = "| — | No platforms checked | — | — |\n"

        # Build strategy table
        strategy_rows = ""
        for s in report.get("strategies", []):
            strategy_rows += (
                f"| {s['name']} | {s['platform']} | {s['signals']} | "
                f"{s['trades']} | {s['win_rate']} | ${s['pnl']:.2f} | "
                f"{s['status']} |\n"
            )
        if not strategy_rows:
            strategy_rows = "| — | — | — | — | — | — | Quick pulse only |\n"

        # Build proposals
        proposals_text = ""
        for p in report.get("proposals", []):
            proposals_text += (
                f"- **{p['strategy']}**: {p['proposal']} "
                f"(expected impact: {p['expected_impact']})\n"
            )
        if not proposals_text:
            proposals_text = "No proposals at this time.\n"

        # Build briefing
        briefing = report.get("briefing", "No briefing generated.")

        md = f"""# HEARTBEAT — Bob's Self-Review System

> Last heartbeat: {now}
> Status: {status}
> Review type: {report.get('type', 'unknown')}

## Schedule
- **Full review**: Every 24 hours at 6:00 AM MT (13:00 UTC)
- **Quick pulse**: Every 4 hours
- **On-demand**: POST /heartbeat/run

## Current Health

### Platforms
| Platform | Status | Last Check | Notes |
|----------|--------|-----------|-------|
{platform_rows}
### Strategies (Last 24h)
| Strategy | Platform | Signals | Trades | Win Rate | P&L | Status |
|----------|----------|---------|--------|----------|-----|--------|
{strategy_rows}
## Active Proposals
{proposals_text}
## Today's Briefing
{briefing}
"""
        try:
            HEARTBEAT_MD.write_text(md)
            logger.info("heartbeat_md_updated", path=str(HEARTBEAT_MD))
        except Exception as e:
            logger.error("heartbeat_md_write_error", error=str(e))

    def _save_report(self, report: dict) -> None:
        """Save full report to heartbeat_reports/."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_file = REPORTS_DIR / f"review_{ts}.json"
        try:
            report_file.write_text(json.dumps(report, indent=2, default=str))
            logger.info("heartbeat_report_saved", path=str(report_file))
        except Exception as e:
            logger.error("heartbeat_report_save_error", error=str(e))
