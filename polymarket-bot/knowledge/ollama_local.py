"""Ollama-first helpers for polymarket-bot knowledge paths (Phase 3 local-first)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.199:11434").strip()
OLLAMA_MODEL = os.getenv(
    "OLLAMA_KNOWLEDGE_MODEL",
    os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen3:8b"),
)


async def ollama_chat(
    user_prompt: str,
    *,
    system: str | None = None,
    format_json: bool = False,
    timeout: float = 90.0,
) -> str | None:
    """POST /api/chat to Ollama. Returns assistant message content or None."""
    if not OLLAMA_HOST:
        return None
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    if format_json:
        payload["format"] = "json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        if r.status_code != 200:
            logger.warning("ollama_chat_http_%s body=%s", r.status_code, (r.text or "")[:200])
            return None
        data = r.json()
        text = (data.get("message") or {}).get("content") or ""
        out = text.strip()
        if out:
            logger.info("ollama_chat_ok model=%s chars=%d", OLLAMA_MODEL, len(out))
        return out or None
    except Exception as e:
        logger.info("ollama_chat_failed: %s", str(e)[:120])
        return None


def parse_json_loose(text: str) -> dict[str, Any] | None:
    """Parse JSON object from model output; tolerate fences."""
    s = (text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    if s.startswith("```"):
        lines = s.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
