---
description: Expand LLM Router adoption to all services — eliminate raw API calls
---

# LLM Router Expansion — Route All LLM Calls Through the Central Router

## Context

`openclaw/llm_router.py` is a smart LLM routing system that:
- Tries local Ollama first (free), falls back to cloud APIs
- Caches responses in Redis to avoid duplicate calls
- Tracks cost per provider per day
- Alerts when daily spend exceeds $5

**Current adoption** (only 3 services):
- `openclaw/auto_responder.py` — uses `from llm_router import completion`
- `email-monitor/analyzer.py` — uses `from openclaw.llm_router import completion`
- `polymarket-bot/strategies/llm_validator.py` — uses a duplicate `llm_completion.py` (Ollama-first but no caching or cost tracking)

**Services making raw API calls** (bypassing the router):
1. `polymarket-bot/strategies/presolution_scalp.py` — raw httpx to OpenAI
2. `polymarket-bot/src/debate_engine.py` — raw httpx to Anthropic + Ollama
3. `polymarket-bot/knowledge/ingest.py` — raw httpx to Anthropic
4. `polymarket-bot/knowledge/digest.py` — raw httpx to Anthropic
5. `polymarket-bot/heartbeat/parameter_tuner.py` — raw httpx to Anthropic
6. `knowledge-scanner/processor.py` — raw httpx to Anthropic
7. `scripts/imessage-server.py` — raw httpx to OpenAI
8. `openclaw/main.py` — raw httpx to both OpenAI and Anthropic (multiple places)

## Instructions

### Step 1: Make llm_router accessible everywhere

The openclaw directory is volume-mounted into polymarket-bot at `/app/openclaw`. Other containers also mount it. The router module needs to be importable.

Create a thin wrapper at `polymarket-bot/strategies/llm_completion.py` that delegates to the real router instead of duplicating logic. **Replace the entire file** with:

```python
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

    ollama_host = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434").rstrip("/")
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
                return {"text": data.get("response", ""), "model": model, "provider": "ollama", "cached": False}
    except Exception:
        pass

    # OpenAI fallback
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"text": "", "model": "none", "provider": "none", "cached": False, "error": "no LLM available"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": combined}], "max_tokens": max_tokens, "temperature": temperature},
        )
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"text": text, "model": "gpt-4o-mini", "provider": "openai", "cached": False}
```

### Step 2: Migrate presolution_scalp.py

In `polymarket-bot/strategies/presolution_scalp.py`, find the raw httpx call to `api.openai.com` (around line 266). Replace it with:

```python
from strategies.llm_completion import completion as llm_complete

result = await llm_complete(
    prompt=user_prompt,
    system_prompt=system_prompt,
    complexity="medium",
    max_tokens=512,
    temperature=0.2,
)
text = result.get("text", "")
```

Remove the raw httpx OpenAI call and the `OPENAI_API_KEY` lookup in that function. Keep the same prompt content, just change the transport.

### Step 3: Migrate debate_engine.py

In `polymarket-bot/src/debate_engine.py`, the `_llm_turn` method already does Ollama-first then Claude. Replace it to use the router:

1. Add at the top: `from strategies.llm_completion import completion as llm_complete`
2. Replace `_llm_turn` to use the router with `complexity="complex"` (debates need the best model)
3. Keep `_call_ollama` as a fallback if needed, but the primary path should go through the router

The key change: instead of manually calling Ollama then Anthropic, just call:
```python
result = await llm_complete(prompt=user_message, system_prompt=system_prompt, complexity="complex", max_tokens=1024)
```

### Step 4: Migrate knowledge/ingest.py and knowledge/digest.py

Both files in `polymarket-bot/knowledge/` make raw Anthropic calls. Replace with:

```python
from strategies.llm_completion import completion as llm_complete

result = await llm_complete(prompt=..., system_prompt=..., complexity="medium")
text = result.get("text", "")
```

### Step 5: Migrate heartbeat/parameter_tuner.py

Same pattern — find the raw Anthropic httpx call and replace with the router.

### Step 6: Migrate knowledge-scanner/processor.py

This runs in its own container. Check if openclaw is volume-mounted. If yes, use `from openclaw.llm_router import completion`. If not, add the volume mount in docker-compose.yml:

```yaml
volumes:
  - ./openclaw:/app/openclaw
```

Then replace the raw Anthropic call with:
```python
from openclaw.llm_router import completion
result = await completion(prompt=..., complexity="medium")
```

### Step 7: Migrate scripts/imessage-server.py

Find the raw OpenAI httpx call (around line 502). This script runs on the host, not in Docker. It can import via sys.path. Add near the top:

```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "openclaw"))
try:
    from llm_router import completion as llm_complete
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False
```

Then replace the raw call with the router when available.

### Step 8: DO NOT touch openclaw/main.py

`openclaw/main.py` is the central API server that **implements** the chat completions endpoint. Its raw API calls are intentional — they are the backend that the router delegates to. Leave these alone.

### Verification

After all changes:

1. `grep -rn "api.openai.com" --include="*.py" | grep -v __pycache__ | grep -v test | grep -v openclaw/main.py` — should only show the fallback in `llm_completion.py`
2. `grep -rn "api.anthropic.com" --include="*.py" | grep -v __pycache__ | grep -v test | grep -v openclaw/main.py` — should only show the fallback in `llm_completion.py` (if any)
3. `grep -rn "llm_complete\|llm_completion\|llm_router" --include="*.py" | grep -v __pycache__ | grep -v test | wc -l` — should be significantly more than 3

### What This Enables

- All LLM calls route through Ollama first (free) before hitting paid APIs
- Redis caching prevents duplicate calls (same prompt = cached response)
- Daily cost tracking with $5/day alert threshold
- Single place to change models, add providers, or adjust routing logic
- Cost savings could be 50-80% depending on cache hit rate

Commit message: `feat: expand LLM router to all services — eliminate raw API calls, enable caching + cost tracking`
