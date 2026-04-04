"""Redis-backed LLM response cache (Auto-23)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

REDIS_URL_DEFAULT = "redis://172.18.0.100:6379"


class LLMCache:
    """Prompt cache; sync Redis client (caller may use asyncio.to_thread)."""

    def __init__(self, redis_url: str | None = None) -> None:
        url = (redis_url or os.environ.get("REDIS_URL") or REDIS_URL_DEFAULT).strip()
        self._redis_url = url
        self._redis: Any = None

    def _client(self) -> Any:
        if self._redis is None:
            import redis

            self._redis = redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=5,
            )
        return self._redis

    def _cache_key(self, prompt: str, model: str, system: str = "") -> str:
        content = f"{model}:{system.strip().lower()}:{prompt.strip().lower()}"
        digest = hashlib.sha256(content.encode()).hexdigest()
        return f"llm:cache:{digest}"

    def get(self, prompt: str, model: str, system: str = "", *, record_stats: bool = True) -> dict[str, Any] | None:
        try:
            key = self._cache_key(prompt, model, system)
            raw = self._client().get(key)
            if raw:
                if record_stats:
                    self._client().incr("llm:cache:hits")
                return json.loads(raw)
            return None
        except Exception as exc:
            logger.warning("llm_cache_get_error: %s", exc)
            return None

    def set(
        self,
        prompt: str,
        model: str,
        response: dict[str, Any],
        ttl: int,
        system: str = "",
    ) -> None:
        if ttl <= 0:
            return
        try:
            key = self._cache_key(prompt, model, system)
            self._client().setex(key, ttl, json.dumps(response, default=str))
        except Exception as exc:
            logger.warning("llm_cache_set_error: %s", exc)
