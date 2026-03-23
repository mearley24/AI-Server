"""Analyze strategy performance and propose parameter adjustments via Claude."""

from __future__ import annotations

import json
import os
import re

import structlog

logger = structlog.get_logger(__name__)


class ParameterTuner:
    """Uses Claude to analyze strategy performance data and propose specific
    parameter adjustments for underperforming or strong strategies."""

    async def analyze(self, strategy_reviews: list[dict]) -> list[dict]:
        """Send performance data to Claude and return parameter adjustment proposals.

        Returns a list of proposal dicts with: strategy, proposal, expected_impact,
        parameter, current_value, proposed_value.

        Falls back gracefully to an empty list if ANTHROPIC_API_KEY is not set.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info("parameter_tuner_skipped", reason="no ANTHROPIC_API_KEY")
            return []

        # Only analyze strategies with enough data
        active = [s for s in strategy_reviews if s["trades"] > 0]
        if not active:
            return []

        review_text = ""
        for s in active:
            review_text += (
                f"- {s['name']} ({s['platform']}): "
                f"{s['trades']} trades, {s['win_rate']} win rate, "
                f"${s['pnl']:.2f} P&L, status={s['status']}\n"
            )

        prompt = f"""You are a quantitative trading analyst reviewing strategy performance.

Current strategy performance (last 24h):
{review_text}

For any underperforming or idle strategies, propose specific parameter adjustments.
For strong strategies, propose ways to capture more value.

Return a JSON array of proposals:
[
  {{
    "strategy": "strategy_name",
    "proposal": "specific adjustment description",
    "expected_impact": "high|medium|low",
    "parameter": "parameter_name",
    "current_value": "current",
    "proposed_value": "proposed"
  }}
]

Only propose changes backed by the data. If everything looks fine, return an empty array []."""

        try:
            import httpx
        except ImportError:
            logger.error("httpx_not_available", msg="Cannot call Claude API")
            return []

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "content-type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
                content = resp.json()["content"][0]["text"]
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    proposals = json.loads(match.group())
                    logger.info("parameter_proposals_generated", count=len(proposals))
                    return proposals
        except Exception as e:
            logger.error("parameter_tuner_error", error=str(e))

        return []
