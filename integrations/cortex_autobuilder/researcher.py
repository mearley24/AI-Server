"""Betty researches questions using Ollama (free local LLM) via LLM Router."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from typing import Any

import httpx
import redis

sys.path.insert(0, "/app")

logger = logging.getLogger(__name__)

BETTY_SYSTEM_PROMPT = (
    "You are Betty, Bob's research assistant. You provide thorough, accurate answers "
    "focused on prediction markets, trading, smart home technology, and AI infrastructure."
)

RESEARCH_PROMPT_TEMPLATE = """You are Betty, an expert research assistant. Answer the following question thoroughly.
Provide specific, actionable information with concrete examples where possible.
If you are uncertain about something, say so explicitly.

Category: {category}
Context: {context}

Question: {question}

Provide your answer in this structure:
- SUMMARY: 2-3 sentence answer
- DETAILS: Detailed explanation with specifics
- ACTIONABLE: Concrete steps or recommendations
- CONFIDENCE: How confident are you (low/medium/high)?
- RELATED: What follow-up questions would deepen this knowledge?"""

CONFIDENCE_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}


def _parse_structured_response(content: str) -> dict[str, Any]:
    """Parse the structured LLM response into sections."""
    sections: dict[str, str] = {}
    current_key = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        stripped = line.strip()
        # Handle plain "- SUMMARY:", markdown bold "**SUMMARY:**", and heading "### SUMMARY:"
        match = re.match(r"^[#\-*\s]*\*{0,2}(SUMMARY|DETAILS|ACTIONABLE|CONFIDENCE|RELATED)\*{0,2}\s*:\s*(.*)", stripped, re.IGNORECASE)
        if match:
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = match.group(1).upper()
            rest = match.group(2).strip()
            current_lines = [rest] if rest else []
        elif current_key:
            current_lines.append(stripped)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _validate_answer(content: str, sections: dict[str, str]) -> bool:
    """Validate answer quality — reject empty, too-short, or clearly bad answers."""
    if not content or len(content.strip()) < 50:
        return False
    if not sections.get("SUMMARY"):
        return False
    summary = sections.get("SUMMARY", "")
    if len(summary) < 20:
        return False
    refusal_phrases = [
        "i cannot", "i don't know", "i'm not sure", "no information",
        "i cannot answer", "unable to answer", "i don't have",
    ]
    if any(phrase in summary.lower() for phrase in refusal_phrases) and len(summary) < 80:
        return False
    return True


def _format_answer(question: dict, sections: dict[str, str]) -> str:
    """Format the parsed sections into a clean Cortex memory entry."""
    lines = [
        f"Question: {question['question']}",
        f"Category: {question['category']}",
        f"Source context: {question.get('context', '')}",
        "",
    ]
    if sections.get("SUMMARY"):
        lines.append(f"Summary: {sections['SUMMARY']}")
        lines.append("")
    if sections.get("DETAILS"):
        lines.append(f"Details:\n{sections['DETAILS']}")
        lines.append("")
    if sections.get("ACTIONABLE"):
        lines.append(f"Action steps:\n{sections['ACTIONABLE']}")
        lines.append("")
    if sections.get("CONFIDENCE"):
        lines.append(f"Confidence: {sections['CONFIDENCE']}")
    return "\n".join(lines).strip()


def _extract_followup_questions(sections: dict[str, str], base_category: str) -> list[dict]:
    """Extract follow-up questions from the RELATED section, capped at 2, priority max 4."""
    related_text = sections.get("RELATED", "")
    if not related_text:
        return []

    followups = []
    for line in related_text.split("\n"):
        line = line.strip().lstrip("-*123456789. ")
        if len(line) > 20 and "?" in line:
            followups.append({
                "question": line,
                "category": base_category,
                "context": "Follow-up generated from previous research answer",
                "priority": 4,
                "source": "followup",
            })
        if len(followups) >= 2:
            break
    return followups


class BettyResearcher:
    """Betty — researches questions from Redis queue using Ollama via LLM Router."""

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
                socket_timeout=30,
            )
        return self._redis

    def _incr_stat(self, field: str, amount: int = 1) -> None:
        """Increment a counter in Redis stats hash."""
        try:
            self._get_redis().hincrby("cortex:autobuilder:stats", field, amount)
        except Exception:
            pass

    def pop_question_sync(self, timeout: int = 30) -> dict | None:
        """Synchronously pop a question from Redis queue (safe to call via asyncio.to_thread)."""
        try:
            r = self._get_redis()
            result = r.brpop("cortex:research_queue", timeout=timeout)
            if result:
                _, raw = result
                return json.loads(raw)
        except Exception as exc:
            logger.warning("pop_question_failed error=%s", str(exc)[:100])
        return None

    async def pop_question(self, timeout: int = 30) -> dict | None:
        """Async wrapper around pop_question_sync."""
        return await asyncio.to_thread(self.pop_question_sync, timeout)

    async def research_question(self, question: dict) -> dict:
        """Main research method — LLM call + Cortex storage."""
        from openclaw.llm_router import completion

        q_text = question.get("question", "")
        category = question.get("category", "general")
        context = question.get("context", "")
        priority = question.get("priority", 5)

        logger.info("researching question=%s", q_text[:80])
        self._incr_stat("questions_asked")

        prompt = RESEARCH_PROMPT_TEMPLATE.format(
            category=category,
            context=context,
            question=q_text,
        )

        try:
            result = await completion(
                prompt=prompt,
                complexity="medium",
                cache_ttl=86400,
                service="cortex_autobuilder",
                system_prompt=BETTY_SYSTEM_PROMPT,
                max_tokens=800,
                temperature=0.3,
            )
            self._incr_stat("ollama_calls")
        except Exception as exc:
            logger.error("llm_call_failed error=%s", str(exc)[:200])
            self._incr_stat("errors")
            return {"error": str(exc), "question": question}

        raw_response = (result.get("content") or "").strip()
        # Strip ANSI only — do NOT run full clean_context pipeline (that wraps in
        # prompt template which destroys SUMMARY/DETAILS/ACTIONABLE structure).
        try:
            from openclaw.context_cleaner import strip_ansi, normalize_whitespace
            content = normalize_whitespace(strip_ansi(raw_response))
        except Exception:
            content = raw_response

        if not content:
            logger.warning("empty_llm_response question=%s", q_text[:60])
            self._incr_stat("errors")
            return {"error": "empty_response", "question": question}

        sections = _parse_structured_response(content)

        if not _validate_answer(content, sections):
            logger.warning("answer_failed_validation question=%s", q_text[:60])
            self._incr_stat("errors")
            return {"error": "validation_failed", "question": question}

        confidence_str = sections.get("CONFIDENCE", "medium").lower().split()[0]
        confidence_score = CONFIDENCE_MAP.get(confidence_str, 0.6)

        formatted = _format_answer(question, sections)

        cortex_payload = {
            "category": category,
            "title": f"Research: {q_text[:80]}",
            "content": formatted,
            "source": "cortex_autobuilder",
            "importance": priority,
            "tags": ["auto_research", category, question.get("source", "unknown")],
            "confidence": confidence_score,
        }

        stored = await self._store_in_cortex(cortex_payload)
        if stored:
            self._incr_stat("knowledge_stored")
            self._incr_stat("questions_answered")

        followups = _extract_followup_questions(sections, category)
        if followups:
            await self._push_followups(followups)

        return {
            "ok": True,
            "question": q_text,
            "category": category,
            "confidence": confidence_score,
            "stored": stored,
            "followups_generated": len(followups),
            "model": result.get("model", ""),
            "provider": result.get("provider", ""),
            "cost_usd": result.get("cost_usd", 0.0),
        }

    async def _store_in_cortex(self, payload: dict) -> bool:
        """POST the researched answer to Cortex /remember."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"{self.cortex_url}/remember", json=payload)
                if r.status_code in (200, 201):
                    logger.info("cortex_stored title=%s", payload["title"][:60])
                    return True
                logger.warning("cortex_store_failed status=%d body=%s", r.status_code, r.text[:100])
        except Exception as exc:
            logger.error("cortex_store_error error=%s", str(exc)[:200])
        self._incr_stat("errors")
        return False

    async def _push_followups(self, followups: list[dict]) -> None:
        """Push follow-up questions to Redis queue (priority capped at 4)."""
        try:
            r = self._get_redis()
            for fq in followups:
                fq["priority"] = min(fq.get("priority", 4), 4)
                r.lpush("cortex:research_queue", json.dumps(fq))
            logger.info("followups_queued count=%d", len(followups))
        except Exception as exc:
            logger.warning("followup_push_failed error=%s", str(exc)[:100])
