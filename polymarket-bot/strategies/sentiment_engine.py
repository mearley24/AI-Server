"""Perplexity (or Ollama) sentiment pass before larger copy-trade entries."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "").rstrip("/")
SENTIMENT_MIN_USD = float(os.environ.get("SENTIMENT_MIN_USD", "5"))


async def analyze_sentiment(
    market_title: str,
    outcome_hint: str = "YES",
    size_usd: float = 0.0,
) -> dict[str, Any]:
    """
    Returns dict with:
      skip: bool — if True, skip the trade
      size_mult: float — multiply position size (e.g. 0.5 if bearish conflict)
      label: bullish | bearish | neutral
      confidence: 0-100
      reason: str
    """
    key = os.environ.get("PERPLEXITY_API_KEY", "")
    # Gap: >= SENTIMENT_MIN_USD → Perplexity when available; smaller → Ollama
    if size_usd >= SENTIMENT_MIN_USD and key:
        return await _perplexity_sentiment(market_title, outcome_hint, key)

    if OLLAMA_HOST:
        return await _ollama_sentiment(market_title, outcome_hint)

    if size_usd >= SENTIMENT_MIN_USD and not key:
        return {"skip": False, "size_mult": 1.0, "label": "unavailable", "confidence": 0, "reason": "no_perplexity_key"}

    return {"skip": False, "size_mult": 1.0, "label": "neutral", "confidence": 0, "reason": "below_min_no_ollama"}


async def _perplexity_sentiment(market_title: str, outcome_hint: str, api_key: str) -> dict[str, Any]:
    prompt = (
        f'For this prediction market: "{market_title}"\n'
        f'We consider buying outcome: {outcome_hint}.\n'
        "Reply with a single JSON object only: "
        '{"label":"bullish|bearish|neutral","confidence":0-100,"conflicts_copy_buy":true|false,"one_line_reason":""}'
    )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                PERPLEXITY_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "sonar",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        logger.warning("sentiment_perplexity_error", error=str(e)[:200])
        return {"skip": False, "size_mult": 1.0, "label": "error", "confidence": 0, "reason": str(e)[:120]}

    parsed = _parse_json_loose(text)
    label = str(parsed.get("label", "neutral")).lower()
    confidence = float(parsed.get("confidence", 50))
    conflicts = bool(parsed.get("conflicts_copy_buy", False))
    reason = str(parsed.get("one_line_reason", ""))[:300]

    size_mult = 1.0
    skip = False
    if conflicts and label == "bearish":
        size_mult = 0.5
        if confidence >= 70:
            skip = True

    logger.info(
        "sentiment_result",
        label=label,
        confidence=confidence,
        conflicts=conflicts,
        skip=skip,
        size_mult=size_mult,
    )
    return {
        "skip": skip,
        "size_mult": size_mult,
        "label": label,
        "confidence": confidence,
        "reason": reason,
    }


async def _ollama_sentiment(market_title: str, outcome_hint: str) -> dict[str, Any]:
    prompt = f'Market: {market_title}\nOutcome: {outcome_hint}\nJSON only: {{"label":"bullish|bearish|neutral","confidence":0-100}}'
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                json={"model": os.environ.get("OLLAMA_SENTIMENT_MODEL", "llama3.1:8b"), "messages": [{"role": "user", "content": prompt}], "stream": False},
            )
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("sentiment_ollama_error", error=str(e)[:200])
        return {"skip": False, "size_mult": 1.0, "label": "error", "confidence": 0, "reason": str(e)[:120]}

    parsed = _parse_json_loose(text)
    label = str(parsed.get("label", "neutral")).lower()
    return {"skip": False, "size_mult": 1.0, "label": label, "confidence": float(parsed.get("confidence", 40)), "reason": "ollama"}


def _parse_json_loose(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _result_to_gap_score(res: dict[str, Any], source: str) -> dict[str, Any]:
    """Map analyze_sentiment-style dict to next-level-gaps {score, reasoning, source}."""
    label = str(res.get("label", "neutral")).lower()
    conf = float(res.get("confidence", 50) or 50)
    reason = str(res.get("reason", ""))[:400]
    if label == "skipped":
        return {
            "score": 50,
            "reasoning": reason or "below sentiment min USD — skipped",
            "source": source,
            "size_mult": 1.0,
            "skip_trade": False,
        }
    if label == "error" or label == "unavailable":
        return {
            "score": 50,
            "reasoning": reason or "Sentiment check unavailable",
            "source": "none",
            "size_mult": 1.0,
            "skip_trade": False,
        }
    if label == "bullish":
        score = min(100, 55 + conf * 0.45)
    elif label == "bearish":
        score = max(0, 45 - conf * 0.35)
    else:
        score = 48 + min(4, conf * 0.04)
    skip_trade = bool(res.get("skip", False))
    return {
        "score": round(score, 1),
        "reasoning": reason or label,
        "source": source,
        "size_mult": float(res.get("size_mult", 1.0)),
        "skip_trade": skip_trade,
    }


class SentimentEngine:
    """Cached sentiment pass before copy-trade entries (30-minute TTL per market)."""

    CACHE_TTL_SEC = float(os.environ.get("SENTIMENT_CACHE_TTL_SEC", "1800"))

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _cache_key(self, market_title: str, outcome: str) -> str:
        return f"{market_title.strip()[:500]}|{outcome.strip()[:80]}"

    async def check_sentiment(
        self,
        market_title: str,
        outcome: str,
        position_usd: float,
    ) -> dict[str, Any]:
        """Returns score 0–100, reasoning, source, optional size_mult / skip_trade."""
        key = self._cache_key(market_title, outcome)
        now = __import__("time").time()
        ent = self._cache.get(key)
        if ent and (now - ent[0]) < self.CACHE_TTL_SEC:
            return dict(ent[1])

        raw = await analyze_sentiment(market_title, outcome_hint=outcome, size_usd=position_usd)
        src = "perplexity" if os.environ.get("PERPLEXITY_API_KEY") else (
            "ollama" if OLLAMA_HOST else "none"
        )
        out = _result_to_gap_score(raw, src)
        self._cache[key] = (now, out)
        return dict(out)
