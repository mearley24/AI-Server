"""Generate a daily briefing summarizing Bob's state."""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


class BriefingGenerator:
    """Generates human-readable daily briefings from heartbeat review data.

    Uses Claude for AI-powered briefings, with a basic fallback when
    ANTHROPIC_API_KEY is not available.
    """

    async def generate(self, report: dict) -> str:
        """Generate a human-readable daily briefing from the full review report.

        Falls back to _generate_basic() if Claude is unavailable.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return self._generate_basic(report)

        health = report.get("health", {})
        strategies = report.get("strategies", [])
        proposals = report.get("proposals", [])

        prompt = f"""Generate a brief daily trading briefing for Bob (Mac Mini M4 running trading bots).

Platform health:
{health}

Strategy performance (last 24h):
{strategies}

Parameter adjustment proposals:
{proposals}

Write a 3-5 paragraph briefing covering:
1. Overall system health (1 sentence)
2. Top performing and underperforming strategies
3. Key numbers (total P&L, best trade, worst trade)
4. Recommended actions for today
5. Any risks or alerts

Keep it concise and actionable. This is for the human operator."""

        try:
            import httpx
        except ImportError:
            logger.error("httpx_not_available")
            return self._generate_basic(report)

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
                return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.error("briefing_generation_error", error=str(e))
            return self._generate_basic(report)

    def _generate_basic(self, report: dict) -> str:
        """Fallback briefing without AI — simple stats summary."""
        strategies = report.get("strategies", [])
        total_pnl = sum(s.get("pnl", 0) for s in strategies)
        total_trades = sum(s.get("trades", 0) for s in strategies)
        active = sum(1 for s in strategies if s.get("status") != "idle")

        platforms = report.get("health", {}).get("platforms", {})
        connected = sum(1 for p in platforms.values() if p.get("status") == "connected")
        total_platforms = len(platforms)

        strong = [s["name"] for s in strategies if s.get("status") == "strong"]
        underperforming = [s["name"] for s in strategies if s.get("status") == "underperforming"]

        lines = [
            f"**System Status**: {connected}/{total_platforms} platforms connected.\n",
            f"**Trading Summary**: {total_trades} trades across {active} active strategies. "
            f"Total P&L: ${total_pnl:.2f}\n",
        ]

        if strong:
            lines.append(f"**Strong performers**: {', '.join(strong)}\n")
        if underperforming:
            lines.append(f"**Underperforming**: {', '.join(underperforming)} — review parameters.\n")

        proposal_count = len(report.get("proposals", []))
        if proposal_count:
            lines.append(f"**Proposals**: {proposal_count} parameter adjustments suggested.\n")

        return "\n".join(lines)
