"""ImprovementLoop — Bob's autonomous self-improvement engine."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from cortex.config import OLLAMA_HOST, OLLAMA_MODEL, REDIS_URL
from cortex.goals import GoalTracker
from cortex.memory import MemoryStore
from cortex.opportunity import OpportunityScanner

logger = structlog.get_logger(__name__)


class ImprovementLoop:
    """Bob's autonomous self-improvement engine."""

    def __init__(
        self,
        memory: MemoryStore,
        goals: GoalTracker,
        opportunity_scanner: OpportunityScanner,
    ) -> None:
        self.memory = memory
        self.goals = goals
        self.scanner = opportunity_scanner

    async def run_daily_improvement(self) -> dict[str, Any]:
        """Full daily improvement cycle. Runs at 5:30 AM MT (before heartbeat at 6 AM)."""
        logger.info("improvement_daily_started")
        findings: dict[str, Any] = {}

        # 1. REVIEW: What happened in the last 24 hours?
        findings["trade_review"] = await self._review_trade_outcomes()

        # 2. LEARN: Extract lessons from outcomes
        findings["lessons"] = await self._extract_lessons(findings["trade_review"])

        # 3. EVALUATE: How are current strategies performing vs goals?
        findings["goal_progress"] = self.goals.check_goals()

        # 4. PRUNE: Deprecate bad rules/ideas with low confidence
        findings["pruned"] = self._prune_low_confidence()

        # 5. SCAN: Look for new opportunities
        findings["opportunities"] = await self.scanner.scan()

        # 6. PROPOSE: Generate improvement proposals
        findings["proposals"] = await self._generate_proposals(findings)

        # 7. ACT: Auto-execute safe proposals, queue risky ones for review
        findings["actions"] = await self._execute_safe_proposals(findings["proposals"])

        # 8. RECORD: Log this improvement cycle
        self._log_cycle(findings)

        # 9. NOTIFY: Alert Matt only if something significant
        await self._notify_if_significant(findings)

        logger.info(
            "improvement_daily_complete",
            lessons=len(findings.get("lessons", [])),
            proposals=len(findings.get("proposals", [])),
            opportunities=len(findings.get("opportunities", [])),
        )
        return findings

    async def run_hourly_pulse(self) -> dict[str, Any]:
        """Quick hourly check — is anything on fire? Any quick wins?"""
        findings: dict[str, Any] = {"type": "hourly_pulse"}

        try:
            # Check Redis for recent X intel signals
            import redis.asyncio as aioredis

            r = aioredis.from_url(REDIS_URL)
            signal_count = await r.llen("polymarket:intel_signals:log")
            await r.aclose()
            findings["x_intel_queued"] = signal_count
        except Exception as exc:
            logger.debug("hourly_pulse_redis_error", error=str(exc))
            findings["x_intel_queued"] = 0

        # Check for presolution opportunities in memory
        presolution = self.memory.recall(
            "presolution",
            category="strategy_idea",
            min_importance=7,
            limit=3,
        )
        findings["presolution_ideas"] = len(presolution)

        logger.info("hourly_pulse_complete", findings=findings)
        return findings

    async def _review_trade_outcomes(self) -> dict[str, Any]:
        """Pull recent resolved trades from memory and recent performance data."""
        review: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "recent_rules": [],
            "recent_performance": [],
        }
        try:
            # Get recent trading rule memories (last 24h)
            recent_rules = self.memory.get_recent(hours=24, limit=20)
            trade_outcomes = [
                m for m in recent_rules
                if m.get("category") in ("trading_rule", "strategy_performance")
            ]
            review["recent_rules"] = trade_outcomes

            # Get strategy performance memories for summary
            perf = self.memory.get_by_category("strategy_performance", limit=10)
            review["recent_performance"] = perf[:5]

        except Exception as exc:
            logger.error("trade_review_error", error=str(exc))

        return review

    async def _extract_lessons(self, trade_review: dict[str, Any]) -> list[dict[str, Any]]:
        """Use Ollama to extract actionable lessons from trade outcomes."""
        lessons: list[dict[str, Any]] = []
        try:
            recent = trade_review.get("recent_rules", [])
            perf = trade_review.get("recent_performance", [])
            if not recent and not perf:
                return lessons

            # Build a compact summary for the prompt
            summary_lines = []
            for m in (recent + perf)[:10]:
                summary_lines.append(f"- {m.get('title', '')}: {m.get('content', '')[:150]}")
            summary = "\n".join(summary_lines)

            prompt = (
                "You are Bob's trading performance analyst. "
                "Based on the following recent trading data and memories, "
                "extract 2-3 specific, actionable lessons. "
                "Each lesson must reference data (win rates, P/L amounts, categories). "
                "Reply in JSON array format: "
                '[{"title": "...", "content": "...", "confidence": 0.7, "tags": ["..."]}]\n\n'
                f"Data:\n{summary}"
            )

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
                raw = resp.json().get("response", "[]")

            # Try to parse JSON from response
            try:
                # Extract JSON array from response (handle markdown code blocks)
                import re

                match = re.search(r"\[.*\]", raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                    for lesson in parsed[:3]:
                        if isinstance(lesson, dict) and lesson.get("title"):
                            mem_id = self.memory.remember(
                                category="trading_rule",
                                title=lesson["title"][:100],
                                content=lesson.get("content", "")[:500],
                                source="improvement_loop",
                                confidence=lesson.get("confidence", 0.5),
                                importance=6,
                                tags=lesson.get("tags", ["auto_learned"]),
                            )
                            lessons.append({**lesson, "memory_id": mem_id})
            except (json.JSONDecodeError, Exception) as parse_exc:
                logger.debug("lesson_parse_error", error=str(parse_exc))

        except Exception as exc:
            logger.error("extract_lessons_error", error=str(exc))

        return lessons

    def _prune_low_confidence(self) -> dict[str, list[str]]:
        """Deprecate memories with low confidence and TTL-expired memories."""
        expired = self.memory.prune_expired()
        low_conf = self.memory.prune_low_confidence()
        return {"expired": expired, "low_confidence": low_conf}

    async def _generate_proposals(self, findings: dict[str, Any]) -> list[dict[str, Any]]:
        """Use Ollama to generate concrete improvement proposals."""
        proposals: list[dict[str, Any]] = []

        # Build a compact findings summary
        goal_summary = []
        for g in findings.get("goal_progress", [])[:5]:
            goal_summary.append(
                f"- {g['title']}: {g['current_value']} → {g['target_value']} ({g['status']})"
            )

        opp_summary = []
        for o in findings.get("opportunities", [])[:5]:
            opp_summary.append(f"- {o['type']}: {o['title']} — {o.get('action', '')}")

        rules = self.memory.get_rules(category="trading_rule", min_confidence=0.7)
        rule_summary = [f"- {r['title']} (conf={r['confidence']:.2f})" for r in rules[:5]]

        prompt = (
            "You are Bob's self-improvement engine. Based on the following findings, "
            "propose 2-4 specific, actionable improvements. "
            "Each proposal must include: what to change, why (data-backed), "
            "expected impact, risk level (safe/moderate/risky), "
            "and whether it's auto-executable (true only if risk=safe and no code changes needed). "
            "Reply in JSON array format:\n"
            '[{"title": "...", "what": "...", "why": "...", "impact": "...", '
            '"risk": "safe|moderate|risky", "auto_executable": true|false}]\n\n'
            f"Goals:\n{chr(10).join(goal_summary)}\n\n"
            f"Opportunities:\n{chr(10).join(opp_summary)}\n\n"
            f"Top rules:\n{chr(10).join(rule_summary)}"
        )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
                raw = resp.json().get("response", "[]")

            import re

            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                proposals = [p for p in parsed if isinstance(p, dict) and p.get("title")][:4]
        except Exception as exc:
            logger.error("generate_proposals_error", error=str(exc))

        return proposals

    async def _execute_safe_proposals(
        self, proposals: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Auto-execute proposals marked as safe. Queue the rest."""
        executed: list[dict[str, Any]] = []
        queued: list[dict[str, Any]] = []

        for p in proposals:
            if p.get("risk") == "safe" and p.get("auto_executable"):
                try:
                    await self._execute_proposal(p)
                    executed.append(p)
                    logger.info("proposal_auto_executed", title=p.get("title", ""))
                except Exception as exc:
                    logger.error("proposal_execute_error", error=str(exc))
                    queued.append(p)
            else:
                # Store in improvement_log as "proposed"
                self.memory.log_improvement(
                    loop_type="proposal",
                    findings=json.dumps(p),
                    status="proposed",
                )
                queued.append(p)
                # Publish non-safe proposals to ops channel for Linear issue creation
                if p.get("risk") in ("moderate", "risky"):
                    try:
                        import redis as _redis_sync
                        _r = _redis_sync.Redis.from_url(REDIS_URL, decode_responses=True)
                        _r.publish("ops:cortex_proposal", json.dumps({
                            "title": p.get("title", "")[:80],
                            "proposal": p.get("what", p.get("proposal", "")),
                            "impact": p.get("impact", ""),
                            "risk": p.get("risk", ""),
                            "priority": 3 if p.get("risk") == "moderate" else 4,
                        }))
                        _r.close()
                    except Exception as _exc:
                        logger.debug("ops_proposal_publish_error", error=str(_exc))

        return {"executed": executed, "queued": queued}

    async def _execute_proposal(self, proposal: dict[str, Any]) -> None:
        """Execute a safe proposal. Currently stores learnings to memory."""
        # Safe proposals store their content as a high-confidence memory
        self.memory.remember(
            category="trading_rule",
            title=f"Auto-applied: {proposal.get('title', '')[:80]}",
            content=(
                f"What: {proposal.get('what', '')}\n"
                f"Why: {proposal.get('why', '')}\n"
                f"Expected impact: {proposal.get('impact', '')}"
            ),
            source="improvement_loop_auto",
            confidence=0.6,
            importance=7,
            tags=["auto_applied", "safe"],
        )

    def _log_cycle(self, findings: dict[str, Any]) -> None:
        """Log this improvement cycle to the improvement_log table."""
        summary = {
            "lessons_extracted": len(findings.get("lessons", [])),
            "opportunities_found": len(findings.get("opportunities", [])),
            "proposals_generated": len(findings.get("proposals", [])),
            "auto_executed": len(findings.get("actions", {}).get("executed", [])),
            "queued_for_review": len(findings.get("actions", {}).get("queued", [])),
            "pruned_expired": len(findings.get("pruned", {}).get("expired", [])),
            "pruned_low_conf": len(findings.get("pruned", {}).get("low_confidence", [])),
        }
        self.memory.log_improvement(
            loop_type="daily_improvement",
            findings=json.dumps(summary),
            actions=findings.get("actions", {}).get("executed", []),
            status="complete",
        )

    async def _notify_if_significant(self, findings: dict[str, Any]) -> None:
        """Only notify Matt if something is actually important."""
        alerts: list[str] = []

        # New edges found
        for opp in findings.get("opportunities", []):
            if opp.get("importance", 0) >= 8:
                alerts.append(f"🔍 New edge: {opp['title']}")

        # Goals regressing
        for g in findings.get("goal_progress", []):
            if g.get("status") == "needs_attention" and g.get("priority", 0) >= 9:
                alerts.append(f"⚠️ Goal needs attention: {g['title']} ({g['current_value']} → {g['target_value']})")

        if not alerts:
            return

        message = "🧠 Cortex Daily Report\n" + "\n".join(alerts)
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(REDIS_URL)
            await r.publish(
                "notifications:cortex",
                json.dumps({
                    "type": "cortex_daily",
                    "message": message,
                    "priority": "medium",
                }),
            )
            await r.aclose()
            logger.info("cortex_notification_sent", alerts=len(alerts))
        except Exception as exc:
            logger.error("cortex_notify_error", error=str(exc))
