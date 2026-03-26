"""LLM Trade Validation — Pre-trade screening using OpenAI.

Before executing a copy trade, queries gpt-4o-mini to assess whether
buying at the current price represents positive expected value.

Configurable via LLM_VALIDATION_ENABLED env var (default: false).
5-second timeout ensures trading is never delayed significantly.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of LLM trade validation."""

    approved: bool
    llm_probability: float  # LLM's estimated probability (0-1)
    market_price: float
    expected_value: float  # llm_prob - market_price
    reasoning: str
    model: str
    latency_ms: float
    error: str = ""


class LLMValidator:
    """Pre-trade screening using OpenAI GPT-4o-mini."""

    def __init__(
        self,
        enabled: bool | None = None,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 5.0,
        min_ev_threshold: float = 0.0,  # reject if LLM says negative EV
    ) -> None:
        # Check environment for enable flag
        if enabled is None:
            enabled = os.environ.get("LLM_VALIDATION_ENABLED", "false").lower() in ("true", "1", "yes")

        self._enabled = enabled
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._timeout = timeout_seconds
        self._min_ev = min_ev_threshold

        if self._enabled and not self._api_key:
            logger.warning("llm_validator_no_api_key", msg="LLM validation enabled but OPENAI_API_KEY not set")
            self._enabled = False

        if self._enabled:
            logger.info("llm_validator_initialized", model=self._model, timeout=self._timeout)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def validate_trade(
        self,
        market_question: str,
        current_price: float,
        trade_direction: str,  # "BUY" or "SELL"
        wallet_win_rate: float,
    ) -> ValidationResult:
        """Validate a trade using LLM probability assessment.

        Returns ValidationResult. If disabled or on error, returns approved=True
        (fail-open to avoid blocking trades on LLM failures).
        """
        if not self._enabled:
            return ValidationResult(
                approved=True,
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning="LLM validation disabled",
                model=self._model,
                latency_ms=0.0,
            )

        start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._call_openai(market_question, current_price, trade_direction, wallet_win_rate),
                timeout=self._timeout,
            )
            result.latency_ms = (time.monotonic() - start) * 1000
            return result

        except asyncio.TimeoutError:
            logger.warning("llm_validation_timeout", timeout=self._timeout)
            return ValidationResult(
                approved=True,  # fail-open
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning="Timeout — approved by default",
                model=self._model,
                latency_ms=(time.monotonic() - start) * 1000,
                error="timeout",
            )

        except Exception as exc:
            logger.warning("llm_validation_error", error=str(exc))
            return ValidationResult(
                approved=True,  # fail-open
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning=f"Error: {str(exc)[:100]}",
                model=self._model,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
            )

    async def _call_openai(
        self,
        market_question: str,
        current_price: float,
        trade_direction: str,
        wallet_win_rate: float,
    ) -> ValidationResult:
        """Make the actual OpenAI API call."""
        prompt = f"""You are a prediction market analyst. Evaluate this trade:

Market question: {market_question}
Current market price: ${current_price:.2f} (implies {current_price*100:.0f}% probability)
Proposed action: {trade_direction} at ${current_price:.2f}
Source wallet win rate: {wallet_win_rate*100:.1f}%

Task:
1. Estimate the true probability of this outcome (0.00 to 1.00)
2. Is buying at ${current_price:.2f} positive expected value?

Respond in this exact JSON format:
{{"probability": 0.XX, "positive_ev": true/false, "reasoning": "brief 1-2 sentence explanation"}}"""

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]

        # Parse JSON response
        try:
            # Handle markdown code blocks
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            parsed = json.loads(content.strip())
            llm_prob = float(parsed.get("probability", 0.5))
            positive_ev = parsed.get("positive_ev", True)
            reasoning = parsed.get("reasoning", "")
        except (json.JSONDecodeError, KeyError, ValueError):
            # Fall back to approved if we can't parse
            return ValidationResult(
                approved=True,
                llm_probability=0.5,
                market_price=current_price,
                expected_value=0.0,
                reasoning=f"Parse error. Raw: {content[:100]}",
                model=self._model,
                latency_ms=0.0,
                error="parse_error",
            )

        # Calculate expected value
        ev = llm_prob - current_price

        # Decision: approve if positive EV or if we can't determine
        approved = ev >= self._min_ev and positive_ev

        logger.info(
            "llm_validation_result",
            market=market_question[:50],
            price=current_price,
            llm_prob=round(llm_prob, 3),
            ev=round(ev, 3),
            approved=approved,
            reasoning=reasoning[:80],
        )

        return ValidationResult(
            approved=approved,
            llm_probability=llm_prob,
            market_price=current_price,
            expected_value=ev,
            reasoning=reasoning,
            model=self._model,
            latency_ms=0.0,
        )
