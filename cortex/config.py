"""Cortex configuration — reads from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("CORTEX_DATA_DIR", "/data/cortex"))
DB_PATH = DATA_DIR / "brain.db"
DIGESTS_DIR = DATA_DIR / "digests"

# Source files (mounted read-only in Docker)
AGENT_LEARNINGS_PATH = Path(os.environ.get("AGENT_LEARNINGS_PATH", "/app/AGENT_LEARNINGS.md"))
IDEAS_PATH = Path(os.environ.get("IDEAS_PATH", "/app/ideas.txt"))
KNOWLEDGE_DIR = Path(os.environ.get("KNOWLEDGE_DIR", "/app/knowledge"))

# ── Redis ─────────────────────────────────────────────────────────────────────

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

# ── Ollama ────────────────────────────────────────────────────────────────────

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.189:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

# ── API ───────────────────────────────────────────────────────────────────────

CORTEX_PORT = int(os.environ.get("CORTEX_PORT", "8102"))
CORTEX_LOG_LEVEL = os.environ.get("CORTEX_LOG_LEVEL", "INFO")

# ── Behaviour ─────────────────────────────────────────────────────────────────

# Minimum confidence below which memories are candidates for pruning
PRUNE_CONFIDENCE_THRESHOLD = float(os.environ.get("PRUNE_CONFIDENCE_THRESHOLD", "0.3"))
# Days since last access before a low-confidence memory is pruned
PRUNE_STALE_DAYS = int(os.environ.get("PRUNE_STALE_DAYS", "14"))

# ── Embeddings ────────────────────────────────────────────────────────────────

# Master switch — default OFF in this PR. Flip to "1" on Bob after dedup backfill.
CORTEX_EMBEDDINGS_ENABLED = os.environ.get("CORTEX_EMBEDDINGS_ENABLED", "0") == "1"

# Allow falling back to OpenAI text-embedding-3-small when Ollama is unreachable.
# Requires OPENAI_API_KEY to also be set. Default: local-only.
CORTEX_EMBED_OPENAI_OK = os.environ.get("CORTEX_EMBED_OPENAI_OK", "0") == "1"

# Ollama embedding model name.
CORTEX_EMBED_OLLAMA_MODEL = os.environ.get("CORTEX_EMBED_OLLAMA_MODEL", "nomic-embed-text")

# Ollama host for embeddings (may differ from analysis model host).
CORTEX_EMBED_OLLAMA_HOST = os.environ.get("CORTEX_EMBED_OLLAMA_HOST", OLLAMA_HOST)
