"""LLM Trade Validation — Pre-trade screening with research and anti-pattern detection.

Before executing a copy trade, performs lightweight research on WHY the source
wallet is making the trade, detects known losing anti-patterns, and queries
gpt-4o-mini to assess expected value and generate a thesis.

Configurable via LLM_VALIDATION_ENABLED env var (default: false).
8-second timeout ensures trading is never delayed significantly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Known esports keywords for detection
ESPORTS_KEYWORDS = ["counter-strike", "cs2", "cs:go", "valorant", "dota", "lol ", "league of legends"]


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
    thesis: str = ""  # Research thesis — WHY this trade makes sense (or doesn't)
    anti_patterns: list[str] = field(default_factory=list)
    error: str = ""


def detect_anti_patterns(
    market_question: str,
    current_price: float,
    category: str,
    source_wallet: str = "",
    bot_positions: list[dict] | None = None,
) -> list[str]:
    """Detect known losing anti-patterns before even calling the LLM.

    Returns a list of anti-pattern names detected. Empty = clean.
    """
    patterns: list[str] = []
    title_lower = (market_question or "").lower()

    # 1. Penny plays at extreme odds on short-window crypto markets
    if current_price <= 0.04 and ("up or down" in title_lower or "updown" in title_lower):
        patterns.append("penny_crypto_lottery")

    # 2. Stale esports — thin books, high spread, unknown teams
    if any(kw in title_lower for kw in ESPORTS_KEYWORDS):
        patterns.append("esports_thin_market")

    # 3. Contradictory positions — bot already has opposite side on same market
    if bot_positions:
        for pos in bot_positions:
            pos_market = (pos.get("market_question", "") or "").lower()
            pos_condition = pos.get("condition_id", "")
            # Check if same market (by condition_id or title similarity)
            if pos_condition and pos_condition == category:
                # Already have a position in this exact market
                patterns.append("contradictory_position")
                break

    return patterns


def detect_both_sides_buying(
    market_question: str,
    source_wallet: str,
    recent_wallet_trades: list[dict] | None = None,
) -> bool:
    """Detect if source wallet is buying BOTH sides of a binary market.

    This is a market-making strategy that only works for the maker (earns spread).
    Copying it means paying spread TWICE — guaranteed loss.
    """
    if not recent_wallet_trades:
        return False

    title_lower = (market_question or "").lower()

    # For crypto up/down markets, check if wallet bought both Up and Down
    if "up or down" in title_lower or "updown" in title_lower:
        # Extract the base market (e.g., "Will BTC go up or down in the next 5 minutes")
        # Look for both BUY trades on different tokens in the same condition
        condition_ids = set()
        for t in recent_wallet_trades:
            if t.get("side", "").upper() == "BUY":
                cid = t.get("conditionId", t.get("market", ""))
                if cid:
                    condition_ids.add(cid)

        # If the wallet has many BUY trades across crypto up/down, it's likely both-sides
        crypto_buys = sum(
            1 for t in recent_wallet_trades
            if t.get("side", "").upper() == "BUY"
            and ("up or down" in (t.get("title", "") or "").lower()
                 or "updown" in (t.get("title", "") or "").lower())
        )
        if crypto_buys >= 4:  # 4+ crypto up/down buys = pattern detected
            return True

    return False


class LLMValidator:
    """Pre-trade screening with research, anti-pattern detection, and LLM assessment."""

    def __init__(
        self,
        enabled: bool | None = None,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 8.0,
        min_ev_threshold: float = 0.0,
    ) -> None:
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
        trade_direction: str,
        wallet_win_rate: float,
        category: str = "",
        category_pnl: float = 0.0,
        source_wallet: str = "",
        recent_wallet_trades: list[dict] | None = None,
        bot_positions: list[dict] | None = None,
    ) -> ValidationResult:
        """Validate a trade with research, anti-pattern detection, and LLM assessment.

        Returns ValidationResult with thesis. If disabled or on error, returns approved=True
        (fail-open to avoid blocking trades on LLM failures).
        """
        # ── Phase 1: Anti-pattern detection (always runs, even if LLM disabled) ──
        anti_patterns = detect_anti_patterns(
            market_question=market_question,
            current_price=current_price,
            category=category,
            source_wallet=source_wallet,
            bot_positions=bot_positions,
        )

        # Check for both-sides buying
        if detect_both_sides_buying(market_question, source_wallet, recent_wallet_trades):
            anti_patterns.append("both_sides_crypto")

        # Hard-reject on critical anti-patterns
        critical_patterns = {"both_sides_crypto", "penny_crypto_lottery", "contradictory_position"}
        critical_found = [p for p in anti_patterns if p in critical_patterns]
        if critical_found:
            thesis = f"REJECTED: Anti-pattern detected — {', '.join(critical_found)}"
            logger.info(
                "copytrade_anti_pattern_rejected",
                market=market_question[:50],
                price=current_price,
                anti_patterns=critical_found,
            )
            return ValidationResult(
                approved=False,
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning=thesis,
                thesis=thesis,
                anti_patterns=anti_patterns,
                model="anti_pattern_filter",
                latency_ms=0.0,
            )

        # ── Phase 2: LLM research and validation ──
        if not self._enabled:
            # Generate a basic thesis even without LLM
            thesis = self._generate_basic_thesis(
                market_question, current_price, wallet_win_rate, category, category_pnl, anti_patterns,
            )
            return ValidationResult(
                approved=True,
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning="LLM disabled — anti-pattern check passed",
                thesis=thesis,
                anti_patterns=anti_patterns,
                model=self._model,
                latency_ms=0.0,
            )

        start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._call_openai_with_research(
                    market_question, current_price, trade_direction, wallet_win_rate,
                    category, category_pnl, anti_patterns,
                ),
                timeout=self._timeout,
            )
            result.latency_ms = (time.monotonic() - start) * 1000
            result.anti_patterns = anti_patterns

            logger.info(
                "copytrade_research_complete",
                market=market_question[:50],
                thesis=result.thesis[:80],
                confidence=round(result.llm_probability, 3),
                anti_patterns=anti_patterns,
                wallet_context=f"{wallet_win_rate*100:.0f}% WR",
            )
            return result

        except asyncio.TimeoutError:
            logger.warning("llm_validation_timeout", timeout=self._timeout)
            thesis = self._generate_basic_thesis(
                market_question, current_price, wallet_win_rate, category, category_pnl, anti_patterns,
            )
            return ValidationResult(
                approved=True,
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning="Timeout — approved by default",
                thesis=thesis,
                anti_patterns=anti_patterns,
                model=self._model,
                latency_ms=(time.monotonic() - start) * 1000,
                error="timeout",
            )

        except Exception as exc:
            logger.warning("llm_validation_error", error=str(exc))
            thesis = self._generate_basic_thesis(
                market_question, current_price, wallet_win_rate, category, category_pnl, anti_patterns,
            )
            return ValidationResult(
                approved=True,
                llm_probability=0.0,
                market_price=current_price,
                expected_value=0.0,
                reasoning=f"Error: {str(exc)[:100]}",
                thesis=thesis,
                anti_patterns=anti_patterns,
                model=self._model,
                latency_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
            )

    def _generate_basic_thesis(
        self,
        market_question: str,
        price: float,
        wallet_win_rate: float,
        category: str,
        category_pnl: float,
        anti_patterns: list[str],
    ) -> str:
        """Generate a basic thesis without LLM (for when LLM is disabled or errors)."""
        parts = []
        parts.append(f"Copying {wallet_win_rate*100:.0f}% WR wallet")
        parts.append(f"at {price:.2f} ({category})")
        if category_pnl != 0:
            parts.append(f"cat P/L: ${category_pnl:+.2f}")
        if anti_patterns:
            parts.append(f"warnings: {', '.join(anti_patterns)}")
        return " | ".join(parts)

    async def _call_openai_with_research(
        self,
        market_question: str,
        current_price: float,
        trade_direction: str,
        wallet_win_rate: float,
        category: str,
        category_pnl: float,
        anti_patterns: list[str],
    ) -> ValidationResult:
        """Make the OpenAI API call with enhanced research context."""
        warnings_text = ""
        if anti_patterns:
            warnings_text = f"\nWarnings detected: {', '.join(anti_patterns)}"

        prompt = f"""You are a prediction market copy-trade analyst. Research this trade and provide a thesis:

Market question: {market_question}
Current price: ${current_price:.2f} (implies {current_price*100:.0f}% probability)
Proposed action: {trade_direction} at ${current_price:.2f}
Source wallet win rate: {wallet_win_rate*100:.1f}%
Market category: {category}
Category historical P/L: ${category_pnl:+.2f}{warnings_text}

Tasks:
1. What is this market about? What would make this outcome happen?
2. Is the source wallet likely making a smart bet, or is this a mechanical/spread trade?
3. Estimate the true probability (0.00 to 1.00)
4. Write a 1-sentence thesis: WHY does copying this trade make sense (or not)?

Respond in this exact JSON format:
{{"probability": 0.XX, "positive_ev": true/false, "thesis": "1-sentence explanation of WHY this trade", "reasoning": "brief analysis"}}"""

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
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]

        try:
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            parsed = json.loads(content.strip())
            llm_prob = float(parsed.get("probability", 0.5))
            positive_ev = parsed.get("positive_ev", True)
            reasoning = parsed.get("reasoning", "")
            thesis = parsed.get("thesis", reasoning[:100])
        except (json.JSONDecodeError, KeyError, ValueError):
            return ValidationResult(
                approved=True,
                llm_probability=0.5,
                market_price=current_price,
                expected_value=0.0,
                reasoning=f"Parse error. Raw: {content[:100]}",
                thesis=f"LLM parse error — copying {wallet_win_rate*100:.0f}% WR wallet at {current_price:.2f}",
                model=self._model,
                latency_ms=0.0,
                error="parse_error",
            )

        ev = llm_prob - current_price
        approved = ev >= self._min_ev and positive_ev

        logger.info(
            "llm_validation_result",
            market=market_question[:50],
            price=current_price,
            llm_prob=round(llm_prob, 3),
            ev=round(ev, 3),
            approved=approved,
            thesis=thesis[:80],
        )

        return ValidationResult(
            approved=approved,
            llm_probability=llm_prob,
            market_price=current_price,
            expected_value=ev,
            reasoning=reasoning,
            thesis=thesis,
            model=self._model,
            latency_ms=0.0,
        )
