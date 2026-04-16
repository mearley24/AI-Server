"""LLM completion for polymarket-bot — delegates to openclaw.llm_router.

This wrapper ensures all polymarket-bot LLM calls go through the central
router for caching, cost tracking, and smart Ollama-first routing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from openclaw.llm_router import completion as _router_completion
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False
    logger.warning("openclaw.llm_router not available, falling back to direct calls")


async def completion(
    prompt: str,
    *,
    system_prompt: str | None = None,
    complexity: str = "medium",
    max_tokens: int = 512,
    temperature: float = 0.3,
    **kwargs: Any,
) -> dict[str, Any]:
    """Route through central LLM router if available, else minimal fallback."""
    if _HAS_ROUTER:
        return await _router_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            complexity=complexity,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    # Minimal fallback — direct Ollama then OpenAI (no caching/cost tracking)
    import os
    import httpx

    ollama_host = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434").rstrip("/")
    model = "qwen3:8b"
    combined = f"{system_prompt.strip()}\n\n{prompt.strip()}" if system_prompt else prompt

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={"model": model, "prompt": combined, "stream": False, "options": {"num_predict": max_tokens, "temperature": temperature}},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"text": data.get("response", ""), "content": data.get("response", ""), "model": model, "provider": "ollama", "cached": False}
    except Exception:
        pass

    # OpenAI fallback
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"text": "", "content": "", "model": "none", "provider": "none", "cached": False, "error": "no LLM available"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": combined}], "max_tokens": max_tokens, "temperature": temperature},
        )
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"text": text, "content": text, "model": "gpt-4o-mini", "provider": "openai", "cached": False}
