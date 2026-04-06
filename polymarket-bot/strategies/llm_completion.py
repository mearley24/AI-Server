"""LLM completion for polymarket-bot Docker image (no openclaw package).

Mirrors ``openclaw.llm_router.completion`` return shape: Ollama first when
``LLM_ROUTER_MODE=local_first``, then OpenAI. Cache/cost Redis omitted.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434").rstrip("/")


def _router_mode() -> str:
    return os.environ.get("LLM_ROUTER_MODE", "local_first").strip().lower()


def _combined_prompt(system_prompt: str | None, user_prompt: str) -> str:
    if system_prompt:
        return f"{system_prompt.strip()}\n\n{user_prompt.strip()}"
    return user_prompt.strip()


async def _ollama_generate(
    model: str,
    prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.3,
    timeout: float = 45.0,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max(64, min(max_tokens, 4096)),
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    return {
        "content": (data.get("response") or "").strip(),
        "input_tokens": int(data.get("prompt_eval_count") or 0),
        "output_tokens": int(data.get("eval_count") or 0),
    }


async def _openai_chat(
    model: str,
    user_prompt: str,
    system_prompt: str | None,
    *,
    max_tokens: int = 512,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        r.raise_for_status()
        data = r.json()
    choice = data["choices"][0]["message"]
    content = (choice.get("content") or "").strip()
    usage = data.get("usage") or {}
    inp = int(usage.get("prompt_tokens") or 0)
    out = int(usage.get("completion_tokens") or 0)
    return {
        "content": content,
        "input_tokens": inp,
        "output_tokens": out,
    }


async def _ollama_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def completion(
    prompt: str,
    complexity: str = "medium",
    cache_ttl: int = 0,
    service: str = "unknown",
    fallback: str = "cloud",
    system_prompt: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """Route LLM: Ollama first in ``local_first``, then OpenAI.

    ``cache_ttl`` / ``complexity`` / ``service`` accepted for API parity; unused.
    """
    del cache_ttl, complexity, service
    mode = _router_mode()
    full = _combined_prompt(system_prompt, prompt)
    ollama_model = os.environ.get("OLLAMA_KNOWLEDGE_MODEL", "qwen3:8b")
    openai_model = os.environ.get("LLM_VALIDATOR_OPENAI_MODEL", "gpt-4o-mini")
    t0 = time.monotonic()

    if mode in ("local_first", "local_only") and OLLAMA_BASE:
        up = await _ollama_up()
        if not up:
            if mode == "local_only":
                return {
                    "content": "",
                    "model": "",
                    "cached": False,
                    "cost_usd": 0.0,
                    "error": "ollama_unavailable",
                }
            logger.warning("ollama_down_reroute_cloud_shim")
        else:
            try:
                raw = await _ollama_generate(
                    ollama_model,
                    full,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=45.0,
                )
                lat = (time.monotonic() - t0) * 1000
                logger.info(
                    "llm_shim_ollama_ok model=%s ms=%.0f",
                    ollama_model,
                    lat,
                )
                return {
                    "content": raw["content"],
                    "model": ollama_model,
                    "cached": False,
                    "cost_usd": 0.0,
                    "provider": "ollama",
                }
            except Exception as exc:
                logger.warning("llm_shim_ollama_failed: %s", str(exc)[:120])
                if mode == "local_only":
                    return {
                        "content": "",
                        "model": "",
                        "cached": False,
                        "cost_usd": 0.0,
                        "error": "ollama_failed",
                    }

    try:
        raw = await _openai_chat(
            openai_model,
            prompt,
            system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning("llm_shim_openai_failed: %s", str(exc)[:120])
        if fallback == "error":
            raise
        return {
            "content": "",
            "model": "",
            "cached": False,
            "cost_usd": 0.0,
            "error": str(exc),
        }

    if mode == "local_first":
        logger.info("llm_shim_openai_fallback model=%s", openai_model)
    _ = (time.monotonic() - t0) * 1000
    return {
        "content": raw["content"],
        "model": openai_model,
        "cached": False,
        "cost_usd": 0.0,
        "provider": "openai",
    }
