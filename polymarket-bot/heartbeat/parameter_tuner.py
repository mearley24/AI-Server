"""Analyze strategy performance and propose parameter adjustments (Ollama first, Claude fallback)."""

from __future__ import annotations

import json
import os
import re

import structlog

logger = structlog.get_logger(__name__)


class ParameterTuner:
    """Uses Ollama (local) or Claude to analyze strategy performance data and propose specific
    parameter adjustments for underperforming or strong strategies."""

    async def analyze(self, strategy_reviews: list[dict]) -> list[dict]:
        """Send performance data to Ollama first, then Claude. Returns parameter adjustment proposals."""
        active = [s for s in strategy_reviews if s.get("trades", 0) > 0 or s.get("open_positions", 0) > 0]
        if not active:
            return []

        total_resolved = sum(s.get("won_count", 0) + s.get("lost_count", 0) for s in active)
        min_resolved = int(os.environ.get("PARAMETER_TUNER_MIN_RESOLVED", "3"))
        if total_resolved < min_resolved:
            logger.info(
                "parameter_tuner_skipped",
                reason="insufficient_resolved_data",
                resolved=total_resolved,
                min_resolved=min_resolved,
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

        proposals = await self._analyze_ollama(prompt)
        if proposals is not None:
            return proposals

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info("parameter_tuner_skipped", reason="no Ollama result and no ANTHROPIC_API_KEY")
            return []

        logger.warning("parameter_tuner_using_claude — Ollama was unavailable")
        return await self._analyze_claude(prompt, api_key)

    async def _analyze_ollama(self, prompt: str) -> list[dict] | None:
        """Try parameter analysis via Ollama. Returns None on failure; [] is valid success."""
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if not ollama_host:
            return None
        try:
            import httpx
        except ImportError:
            return None
        model = os.environ.get("OLLAMA_DEBATE_MODEL", "qwen3:32b")
        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                resp = await http.post(
                    f"{ollama_host.rstrip('/')}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.3, "num_predict": 1000},
                    },
                )
            if resp.status_code != 200:
                return None
            content = resp.json().get("message", {}).get("content", "")
            if not content.strip():
                return None
            proposals = self._parse_proposals_json(content)
            logger.info("parameter_tuner_ollama_success", suggestions=len(proposals))
            return proposals
        except Exception as e:
            logger.info("parameter_tuner_ollama_failed", error=str(e)[:100])
            return None

    def _parse_proposals_json(self, content: str) -> list[dict]:
        """Parse JSON array from model output; handle markdown fences."""
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("suggestions", []) if "suggestions" in data else []
        except (json.JSONDecodeError, TypeError):
            pass
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return []
        return []

    async def _analyze_claude(self, prompt: str, api_key: str) -> list[dict]:
        """Fallback: parameter analysis via Claude (paid)."""
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


def evaluate_pause_rules(strategy_reviews: list[dict]) -> list[str]:
    """Auto-20: simple rules — win rate <45% or 7d negative streak."""
    recs: list[str] = []
    for s in strategy_reviews:
        name = s.get("name", "unknown")
        wr = float(s.get("win_rate", 0) or 0)
        if wr and wr < 0.45:
            recs.append(f"pause_candidate:{name}: win_rate {wr:.2f} < 0.45")
        streak = int(s.get("negative_day_streak", 0) or 0)
        if streak >= 7:
            recs.append(f"auto_pause:{name}: negative P/L 7 consecutive days")
    return recs
