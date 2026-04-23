"""
cortex/embeddings.py — Pluggable embedding providers for Cortex memories.

Providers
---------
OllamaProvider  : nomic-embed-text via local Ollama (default).
OpenAIProvider  : text-embedding-3-small — opt-in only (CORTEX_EMBED_OPENAI_OK=1).
NullProvider    : Deterministic hash-based vector — unit tests, no network.

Usage
-----
    provider = get_provider()
    vec = await provider.embed("some text")

Writer task (spawned by engine on startup when CORTEX_EMBEDDINGS_ENABLED=1):
    await embed_worker(queue, store)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

_PACK_FMT_PREFIX = "<"   # little-endian floats


# ── Vector serialisation ──────────────────────────────────────────────────────

def pack_vector(vec: List[float]) -> bytes:
    """Serialize a float list to a little-endian BLOB."""
    return struct.pack(_PACK_FMT_PREFIX + "f" * len(vec), *vec)


def unpack_vector(blob: bytes) -> List[float]:
    """Deserialize a BLOB produced by pack_vector."""
    n = len(blob) // 4
    return list(struct.unpack(_PACK_FMT_PREFIX + "f" * n, blob))


# ── Provider protocol ─────────────────────────────────────────────────────────

class EmbeddingProvider(Protocol):
    model_name: str

    async def embed(self, text: str) -> List[float]:
        ...


# ── Ollama provider ───────────────────────────────────────────────────────────

class OllamaProvider:
    def __init__(self, host: str, model: str) -> None:
        self.host = host.rstrip("/")
        self.model_name = model

    async def embed(self, text: str) -> List[float]:
        import httpx
        url = f"{self.host}/api/embeddings"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"model": self.model_name, "prompt": text[:4096]})
        resp.raise_for_status()
        return resp.json()["embedding"]


# ── OpenAI provider ───────────────────────────────────────────────────────────

class OpenAIProvider:
    model_name = "text-embedding-3-small"

    async def embed(self, text: str) -> List[float]:
        import httpx
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        url = "https://api.openai.com/v1/embeddings"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self.model_name, "input": text[:8191]},
            )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


# ── Null provider (deterministic, no network) ─────────────────────────────────

_NULL_DIM = 64


class NullProvider:
    """Hash-based deterministic 64-dim unit vector — for tests only."""
    model_name = "null-v1"

    async def embed(self, text: str) -> List[float]:
        raw = hashlib.sha256(text.encode()).digest() * (_NULL_DIM // 32 + 1)
        floats = [b / 255.0 for b in raw[:_NULL_DIM]]
        norm = sum(f * f for f in floats) ** 0.5
        return [f / norm if norm else 0.0 for f in floats]


# ── Factory ───────────────────────────────────────────────────────────────────

def get_provider() -> EmbeddingProvider:
    """Return the configured provider based on env/config."""
    from cortex.config import (
        CORTEX_EMBED_OLLAMA_HOST,
        CORTEX_EMBED_OLLAMA_MODEL,
        CORTEX_EMBED_OPENAI_OK,
    )
    return OllamaProvider(host=CORTEX_EMBED_OLLAMA_HOST, model=CORTEX_EMBED_OLLAMA_MODEL)


# ── Async writer task ─────────────────────────────────────────────────────────

async def embed_worker(
    queue: asyncio.Queue,
    store: Any,   # MemoryStore — avoid circular import
    provider: Optional[EmbeddingProvider] = None,
) -> None:
    """Long-lived task: drain the embedding queue and write rows.

    Each item on the queue is (memory_id, content).
    Runs until the task is cancelled.
    """
    if provider is None:
        provider = get_provider()

    retry_set: set = set()   # track IDs already failed this run — no second retry

    while True:
        try:
            memory_id, content = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            return

        if memory_id in retry_set:
            queue.task_done()
            continue

        try:
            vec = await asyncio.wait_for(provider.embed(content[:4096]), timeout=10.0)
            blob = pack_vector(vec)
            digest = hashlib.sha256(content[:4096].encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            store.conn.execute(
                """INSERT OR REPLACE INTO memory_embeddings
                   (memory_id, embedding, dim, model, content_digest, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (memory_id, blob, len(vec), provider.model_name, digest, now, now),
            )
            store.conn.commit()
            logger.debug("embedding_written memory_id=%s model=%s", memory_id, provider.model_name)
        except asyncio.TimeoutError:
            logger.warning("embedding_timeout memory_id=%s", memory_id)
            retry_set.add(memory_id)
        except Exception as exc:
            logger.warning("embedding_error memory_id=%s error=%s", memory_id, str(exc)[:100])
            retry_set.add(memory_id)
        finally:
            queue.task_done()
