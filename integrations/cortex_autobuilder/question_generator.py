"""Generate research questions by analyzing Cortex gaps and current context."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import redis

logger = logging.getLogger(__name__)

SCHEDULED_TOPICS: dict[int, dict[str, Any]] = {
    0: {  # Monday
        "theme": "trading strategies",
        "category": "trading_strategy",
        "questions": [
            "What is the optimal Kelly criterion sizing for prediction markets with binary outcomes?",
            "What are the most reliable leading indicators for political prediction markets on Polymarket?",
            "How can machine learning improve entry timing on Polymarket binary markets?",
        ],
    },
    1: {  # Tuesday
        "theme": "market mechanics and arbitrage",
        "category": "market_mechanics",
        "questions": [
            "How does Polymarket's CLOB order book handle negative risk positions?",
            "What arbitrage opportunities exist between Kalshi and Polymarket for the same events?",
            "How does order book depth on Polymarket affect slippage for large positions?",
        ],
    },
    2: {  # Wednesday
        "theme": "risk management and treasury",
        "category": "risk_management",
        "questions": [
            "What are the best practices for hedging correlated prediction market positions?",
            "How should a prediction market portfolio be sized to limit drawdown below 20%?",
            "What position limits are appropriate for illiquid Polymarket events with thin order books?",
        ],
    },
    3: {  # Thursday
        "theme": "AI infrastructure and automation",
        "category": "tech_infrastructure",
        "questions": [
            "What are the performance characteristics of Ollama vs vLLM for local inference on Apple Silicon?",
            "What are the best patterns for building reliable multi-agent autonomous systems with Python asyncio?",
            "How can Redis pub/sub be used as a backbone for real-time agent-to-agent communication?",
        ],
    },
    4: {  # Friday
        "theme": "smart home technical knowledge",
        "category": "smart_home",
        "questions": [
            "What is the correct wire gauge for low-voltage Control4 keypads over 100ft runs?",
            "How do you configure VLAN segmentation for Lutron RadioRA3 devices on Araknis switches?",
            "What are the best practices for integrating Sonos audio across multiple VLANs with mDNS reflectors?",
        ],
    },
    5: {  # Saturday
        "theme": "business development and client services",
        "category": "business",
        "questions": [
            "What are the most effective client acquisition channels for smart home integrators in mountain resort markets?",
            "How can AI-powered proposal generation reduce the sales cycle for AV integration companies?",
            "What recurring revenue models work best for smart home integration firms?",
        ],
    },
    6: {  # Sunday
        "theme": "cross-domain synthesis",
        "category": "trading_strategy",
        "questions": [
            "How can smart home monitoring data generate predictive signals for local real estate markets?",
            "What lessons from algorithmic trading can improve autonomous workflow automation?",
            "How can AI agents collaborate on research tasks without exceeding API rate limits?",
        ],
    },
}

CATEGORY_GAP_QUESTIONS: dict[str, list[str]] = {
    "trading_strategy": [
        "What position sizing rules prevent ruin in prediction markets with 60% win rate?",
        "How does time-to-resolution affect optimal bet sizing on Polymarket?",
    ],
    "market_mechanics": [
        "How do market makers price uncertainty on long-duration prediction markets?",
        "What causes sudden liquidity withdrawals on Polymarket CLOB?",
    ],
    "risk_management": [
        "What stop-loss strategies work best for prediction markets that resolve unexpectedly?",
        "How should correlation between related Polymarket events affect portfolio weighting?",
    ],
    "tech_infrastructure": [
        "What monitoring strategies detect Ollama model drift over time?",
        "How can Docker healthchecks be made more reliable for Python async services?",
    ],
    "smart_home": [
        "What are the Control4 driver best practices for Lutron RA3 integration in 2025?",
        "How do you troubleshoot Sonos groups breaking after a network switch reboot?",
    ],
    "business": [
        "How do top smart home integrators price annual service plans?",
        "What CRM workflows best capture referral opportunities from completed projects?",
    ],
    "x_intel": [
        "What Polymarket trading patterns are most commonly shared by successful traders on X?",
        "How do X influencers in the AI space signal new tool releases ahead of mainstream adoption?",
    ],
}


class QuestionGenerator:
    """Generate research questions by analyzing Cortex gaps, goals, and X intel."""

    def __init__(self, cortex_url: str, redis_url: str) -> None:
        self.cortex_url = cortex_url.rstrip("/")
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None

    def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
            )
        return self._redis

    async def _fetch_memories(self, category: str, limit: int = 50) -> list[dict]:
        """Fetch memories from Cortex for a given category."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{self.cortex_url}/memories",
                    params={"category": category, "limit": limit},
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    return data.get("memories", data.get("items", []))
        except Exception as exc:
            logger.warning("fetch_memories_failed category=%s error=%s", category, str(exc)[:100])
        return []

    async def _fetch_goals(self) -> list[dict]:
        """Fetch active goals from Cortex."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.cortex_url}/goals")
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    return data.get("goals", [])
        except Exception as exc:
            logger.warning("fetch_goals_failed error=%s", str(exc)[:100])
        return []

    def _get_scheduled_topic(self) -> dict[str, Any]:
        """Get today's scheduled research topic based on day of week."""
        weekday = datetime.now(timezone.utc).weekday()
        return SCHEDULED_TOPICS.get(weekday, SCHEDULED_TOPICS[0])

    def _build_gap_questions(self, memories: list[dict], category: str) -> list[dict]:
        """Build questions targeting knowledge gaps based on existing memories."""
        existing_titles = {
            m.get("title", "").lower()
            for m in memories
            if isinstance(m, dict)
        }

        questions = []
        gap_qs = CATEGORY_GAP_QUESTIONS.get(category, [])
        for q_text in gap_qs:
            already_covered = any(
                kw in existing_titles
                for kw in q_text.lower().split()
                if len(kw) > 5
            )
            if not already_covered:
                questions.append({
                    "question": q_text,
                    "category": category,
                    "context": f"Gap detected: no existing memories closely matching this topic",
                    "priority": 6,
                    "source": "gap_analysis",
                })
        return questions[:2]

    def _build_goal_questions(self, goals: list[dict]) -> list[dict]:
        """Generate questions driven by active Cortex goals."""
        questions = []
        goal_question_map = {
            "trading": ("What strategies most reliably improve prediction market win rate above 60%?", "trading_strategy"),
            "copytrade": ("How can on-chain wallet tracking improve Polymarket copytrade detection accuracy?", "trading_strategy"),
            "polymarket": ("What are the highest-ROI Polymarket market categories for small bankrolls?", "market_mechanics"),
            "risk": ("What drawdown limits should trigger a full portfolio pause on Polymarket?", "risk_management"),
            "smart home": ("What are the top 3 Control4 programming patterns that save the most commissioning time?", "smart_home"),
            "ai": ("What autonomous agent frameworks have the best Python ecosystem support in 2025?", "tech_infrastructure"),
            "automation": ("How can Claude Code and OpenAI Assistants be combined for 24/7 autonomous research workflows?", "tech_infrastructure"),
            "revenue": ("What are the highest-margin add-on services for residential AV integration companies?", "business"),
        }

        for goal in goals[:5]:
            if not isinstance(goal, dict):
                continue
            title = (goal.get("title") or goal.get("name") or "").lower()
            desc = (goal.get("description") or goal.get("content") or "").lower()
            combined = f"{title} {desc}"
            for keyword, (question, category) in goal_question_map.items():
                if keyword in combined:
                    questions.append({
                        "question": question,
                        "category": category,
                        "context": f"Related to active goal: {goal.get('title', 'unknown')}",
                        "priority": 8,
                        "source": "goal_driven",
                    })
                    break

        return questions[:3]

    def _build_x_intel_questions(self, intel_memories: list[dict]) -> list[dict]:
        """Generate follow-up questions from recent X intel."""
        questions = []
        for mem in intel_memories[:5]:
            if not isinstance(mem, dict):
                continue
            content = (mem.get("content") or mem.get("title") or "")[:300]
            if not content:
                continue

            if any(kw in content.lower() for kw in ["polymarket", "prediction market", "kalshi"]):
                questions.append({
                    "question": f"Based on recent X intel about prediction markets, what specific strategy adjustment would improve trading performance?",
                    "category": "trading_strategy",
                    "context": f"Follow-up on X intel: {content[:100]}",
                    "priority": 7,
                    "source": "x_intel_followup",
                })
            elif any(kw in content.lower() for kw in ["agent", "llm", "mcp", "claude", "openai"]):
                questions.append({
                    "question": f"How can this AI development be integrated into the Symphony AI Server stack?",
                    "category": "tech_infrastructure",
                    "context": f"Follow-up on X intel: {content[:100]}",
                    "priority": 6,
                    "source": "x_intel_followup",
                })

        return questions[:2]

    async def generate_questions(self) -> list[dict]:
        """Main method — generate research questions and push to Redis queue."""
        questions: list[dict] = []

        trading_memories = await self._fetch_memories("trading_rule", 50)
        x_intel_memories = await self._fetch_memories("x_intel", 20)
        goals = await self._fetch_goals()

        scheduled = self._get_scheduled_topic()
        for i, q_text in enumerate(scheduled["questions"]):
            questions.append({
                "question": q_text,
                "category": scheduled["category"],
                "context": f"Scheduled topic: {scheduled['theme']}",
                "priority": 7 - i,
                "source": "scheduled_topic",
            })

        questions.extend(self._build_gap_questions(trading_memories, "trading_strategy"))
        questions.extend(self._build_goal_questions(goals))
        questions.extend(self._build_x_intel_questions(x_intel_memories))

        pushed = 0
        try:
            r = self._get_redis()
            for q in questions:
                r.lpush("cortex:research_queue", json.dumps(q))
                pushed += 1
            logger.info("questions_generated count=%d pushed=%d", len(questions), pushed)
        except Exception as exc:
            logger.error("redis_push_failed error=%s", str(exc)[:200])

        return questions
