"""Multi-agent bull/bear debate engine for trade validation.

Before executing trades above a configurable threshold, runs a structured
debate between Bull, Bear, and Judge agents (Ollama first, Claude fallback). The judge
evaluates both arguments and returns a confidence score and recommendation.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.config import Settings
from src.market_intel import MarketIntel

logger = structlog.get_logger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

BULL_SYSTEM_PROMPT = """You are a seasoned bull-case analyst for prediction market trading.
Your job is to make the strongest possible case FOR executing this trade.
Consider: market mispricing signals, favorable momentum, information edge,
risk/reward ratio, historical precedents, and market microstructure advantages.
Be specific and quantitative. Cite the data provided. Keep your argument
to 150 words or fewer."""

BEAR_SYSTEM_PROMPT = """You are a seasoned bear-case analyst for prediction market trading.
Your job is to make the strongest possible case AGAINST executing this trade.
Consider: adverse selection risk, execution slippage, model errors, market
efficiency, liquidity concerns, potential information we're missing, and
worst-case scenarios. Be specific and quantitative. Cite the data provided.
Keep your argument to 150 words or fewer."""

JUDGE_SYSTEM_PROMPT = """You are a senior risk manager evaluating a proposed prediction market trade.
You have received arguments from a Bull (for) and Bear (against) analyst.
Evaluate both arguments objectively. Consider:
1. Strength of evidence on each side
2. Magnitude of potential gain vs loss
3. Confidence in the pricing edge
4. Risk of adverse selection or model error

Respond with EXACTLY this JSON format (no markdown, no extra text):
{"confidence": 0.XX, "recommendation": "EXECUTE" or "REJECT", "reasoning": "One sentence explanation"}

The confidence score should be between 0.0 and 1.0, where:
- 0.0-0.3 = Strong reject (bear case dominates)
- 0.3-0.5 = Lean reject (uncertain, too risky)
- 0.5-0.65 = Marginal (could go either way)
- 0.65-0.85 = Lean execute (edge likely real)
- 0.85-1.0 = Strong execute (compelling edge)"""


@dataclass
class DebateResult:
    """Result of a bull/bear debate."""

    confidence: float
    recommendation: str  # "EXECUTE" or "REJECT"
    reasoning: str
    bull_argument: str
    bear_argument: str
    debate_time_seconds: float
    model_used: str


class DebateEngine:
    """Runs bull/bear/judge debates on trade proposals (Ollama first, Claude fallback)."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.debate_enabled
        self._model = settings.debate_model
        self._min_position = settings.debate_min_position_for_debate
        self._confidence_threshold = settings.debate_confidence_threshold
        self._max_time = settings.debate_max_debate_time_seconds
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=self._max_time + 5)
        self._market_intel = MarketIntel()

        # Fall back to CONDUCTOR_MODEL if debate model not explicitly set
        if not self._model or self._model == "claude-3-5-sonnet-20241022":
            conductor = os.environ.get("CONDUCTOR_MODEL", "")
            if conductor:
                self._model = conductor

    @property
    def enabled(self) -> bool:
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        return self._enabled and (bool(self._api_key) or bool(ollama_host))

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    async def should_execute(
        self,
        strategy_name: str,
        market: str,
        side: str,
        price: float,
        size: float,
        context: dict[str, Any] | None = None,
    ) -> DebateResult | None:
        """Run a debate if the position size warrants it.

        Returns None if debate is disabled or position is below threshold
        (meaning: proceed without debate). Returns a DebateResult otherwise.
        """
        if not self.enabled:
            return None

        if size < self._min_position:
            return None

        return await self.debate(
            strategy_name=strategy_name,
            market=market,
            side=side,
            price=price,
            size=size,
            context=context or {},
        )

    async def debate(
        self,
        strategy_name: str,
        market: str,
        side: str,
        price: float,
        size: float,
        context: dict[str, Any],
    ) -> DebateResult:
        """Run the full bull/bear/judge debate cycle."""
        start = time.time()

        # Gather live market intelligence before debate
        try:
            market_ctx = await asyncio.wait_for(
                self._market_intel.gather(market, context),
                timeout=5.0,
            )
            market_block = market_ctx.format()
        except Exception as exc:
            logger.debug("market_intel_skipped", error=str(exc))
            market_block = ""

        trade_context = self._build_context(strategy_name, market, side, price, size, context)
        if market_block:
            trade_context = f"{market_block}\n\n{trade_context}"

        try:
            # Run bull and bear in parallel (Ollama first, Claude fallback per call)
            bull_task = asyncio.create_task(
                self._llm_turn(BULL_SYSTEM_PROMPT, trade_context)
            )
            bear_task = asyncio.create_task(
                self._llm_turn(BEAR_SYSTEM_PROMPT, trade_context)
            )

            (bull_arg, src_bull), (bear_arg, src_bear) = await asyncio.wait_for(
                asyncio.gather(bull_task, bear_task),
                timeout=self._max_time * 0.6,
            )

            # Run judge with both arguments
            judge_input = (
                f"TRADE PROPOSAL:\n{trade_context}\n\n"
                f"BULL CASE:\n{bull_arg}\n\n"
                f"BEAR CASE:\n{bear_arg}"
            )

            judge_response, src_judge = await asyncio.wait_for(
                self._llm_turn(JUDGE_SYSTEM_PROMPT, judge_input),
                timeout=self._max_time * 0.4,
            )

            sources = (src_bull, src_bear, src_judge)
            ollama_model = os.environ.get("OLLAMA_DEBATE_MODEL", "qwen3:32b")
            if all(s == "ollama" for s in sources):
                model_used = f"ollama:{ollama_model}"
            elif any(s == "claude" for s in sources):
                model_used = self._model
            else:
                model_used = "none"

            # Parse judge response
            result = self._parse_judge_response(judge_response)

            debate_time = time.time() - start
            debate_result = DebateResult(
                confidence=result["confidence"],
                recommendation=result["recommendation"],
                reasoning=result["reasoning"],
                bull_argument=bull_arg,
                bear_argument=bear_arg,
                debate_time_seconds=round(debate_time, 2),
                model_used=model_used,
            )

            logger.info(
                "debate_complete",
                strategy=strategy_name,
                market=market,
                confidence=debate_result.confidence,
                recommendation=debate_result.recommendation,
                reasoning=debate_result.reasoning,
                debate_time=debate_result.debate_time_seconds,
            )

            return debate_result

        except asyncio.TimeoutError:
            logger.warning("debate_timeout", strategy=strategy_name, market=market)
            # On timeout, return a neutral result that defers to strategy
            return DebateResult(
                confidence=0.5,
                recommendation="EXECUTE",
                reasoning="Debate timed out — defaulting to strategy decision",
                bull_argument="(timeout)",
                bear_argument="(timeout)",
                debate_time_seconds=time.time() - start,
                model_used=self._model,
            )

        except Exception as exc:
            logger.error("debate_error", error=str(exc), strategy=strategy_name)
            # On error, allow trade to proceed
            return DebateResult(
                confidence=0.5,
                recommendation="EXECUTE",
                reasoning=f"Debate failed: {exc}",
                bull_argument="(error)",
                bear_argument="(error)",
                debate_time_seconds=time.time() - start,
                model_used=self._model,
            )

    async def _call_ollama(self, system_prompt: str, user_message: str) -> str | None:
        """Try Ollama /api/chat (local). Returns None on failure."""
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if not ollama_host:
            return None
        model = os.environ.get("OLLAMA_DEBATE_MODEL", "qwen3:32b")
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 400},
            }
            resp = await self._http.post(
                f"{ollama_host.rstrip('/')}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120.0,
            )
            if resp.status_code != 200:
                logger.info("debate_ollama_error", status=resp.status_code)
                return None
            content = resp.json().get("message", {}).get("content", "")
            if content and content.strip():
                logger.info("debate_ollama_success", model=model, chars=len(content))
                return content.strip()
        except Exception as e:
            logger.info("debate_ollama_failed", error=str(e)[:100])
        return None

    async def _llm_turn(self, system_prompt: str, user_message: str) -> tuple[str, str]:
        """One debate turn: Ollama first, then Claude. Returns (text, 'ollama'|'claude'|'none')."""
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if ollama_host:
            o = await self._call_ollama(system_prompt, user_message)
            if o:
                return o, "ollama"
        if not self._api_key:
            logger.warning("debate_no_llm_available — Ollama down and no ANTHROPIC_API_KEY")
            return "", "none"
        if ollama_host:
            logger.warning("debate_using_claude — Ollama was unavailable")
        text = await self._call_claude_direct(system_prompt, user_message)
        return text, "claude"

    async def _call_claude_direct(self, system_prompt: str, user_message: str) -> str:
        """Direct Claude API call (paid fallback)."""
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Use structured system block with cache_control for prompt caching.
        # Bull/Bear/Judge system prompts are reused constantly — saves ~90% on input tokens.
        payload = {
            "model": self._model,
            "max_tokens": 300,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_message}],
        }

        resp = await self._http.post(ANTHROPIC_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]
        return ""

    def _build_context(
        self,
        strategy_name: str,
        market: str,
        side: str,
        price: float,
        size: float,
        context: dict[str, Any],
    ) -> str:
        """Build the trade context string for the debate agents."""
        lines = [
            f"Strategy: {strategy_name}",
            f"Market: {market}",
            f"Side: {side}",
            f"Price: {price}",
            f"Position Size: ${size} USDC",
        ]

        for key, value in context.items():
            lines.append(f"{key}: {value}")

        return "\n".join(lines)

    def _parse_judge_response(self, response: str) -> dict[str, Any]:
        """Parse the judge's JSON response."""
        import json

        # Try to extract JSON from the response
        response = response.strip()

        # Handle cases where the model wraps in markdown code blocks
        if response.startswith("```"):
            lines = response.split("\n")
            json_lines = [l for l in lines if not l.startswith("```")]
            response = "\n".join(json_lines).strip()

        try:
            data = json.loads(response)
            return {
                "confidence": float(data.get("confidence", 0.5)),
                "recommendation": str(data.get("recommendation", "EXECUTE")).upper(),
                "reasoning": str(data.get("reasoning", "No reasoning provided")),
            }
        except (json.JSONDecodeError, ValueError):
            logger.warning("judge_parse_error", response=response[:200])
            # Default to cautious approval if we can't parse
            return {
                "confidence": 0.5,
                "recommendation": "EXECUTE",
                "reasoning": "Could not parse judge response — defaulting to strategy",
            }

    async def close(self) -> None:
        """Close the HTTP client and market intel."""
        await self._market_intel.close()
        await self._http.aclose()
