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

        # Only analyze strategies that have resolved trades (not just open positions)
        active = [s for s in strategy_reviews if s.get("trades", 0) > 0 or s.get("open_positions", 0) > 0]
        if not active:
            return []

        # Check if there's enough resolved data to make proposals
        total_resolved = sum(s.get("won_count", 0) + s.get("lost_count", 0) for s in active)
        if total_resolved < 3:
            logger.info(
                "parameter_tuner_skipped",
                reason="insufficient_resolved_data",
                resolved=total_resolved,
                open_positions=sum(s.get("open_positions", 0) for s in active),
            )
            return []

        review_text = ""
        for s in active:
            resolved = s.get("won_count", 0) + s.get("lost_count", 0)
            review_text += (
                f"- {s['name']} ({s['platform']}): "
                f"RESOLVED: {resolved} trades ({s.get('won_count', 0)}W/{s.get('lost_count', 0)}L), "
                f"realized P&L: ${s.get('realized_pnl', s.get('pnl', 0)):.2f} | "
                f"OPEN: {s.get('open_positions', 0)} positions worth ${s.get('open_value', 0):.2f} (not yet resolved), "
                f"status={s['status']}\n"
            )

        prompt = f"""You are a quantitative trading analyst reviewing strategy performance.

IMPORTANT: Only evaluate performance based on RESOLVED (settled) trades. Open positions have NOT been
settled yet — they are neither wins nor losses until the market resolves. Do NOT count open positions
as losses or use them to calculate win rate. A low resolved trade count simply means markets haven't
settled yet, not that the strategy is failing.

Current strategy performance (last 24h):
{review_text}

Rules:
- Only propose halting if REALIZED losses exceed $50 (not open position value)
- If few trades have resolved, say "insufficient data" rather than making dramatic recommendations
- Open positions are normal and expected — they should not trigger concern
- Win rate can only be calculated from resolved trades

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

Only propose changes backed by resolved data. If too few trades have resolved, return an empty array []."""

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
