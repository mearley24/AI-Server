"""
OpenClaw — Multi-Agent Orchestration Service
Symphony Smart Homes | Bob the Conductor | Mac Mini M4

Exposes an OpenAI-compatible POST /api/chat/completions endpoint.
Loads agent YAML configs from agents/ and routes requests by model name.
"""

import asyncio
import os
import logging
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from memory import MemoryPlugin
from agent_bus import AgentBus

# ---------------------------------------------------------------------------
# Environment & logging
# ---------------------------------------------------------------------------
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("openclaw")

PORT = int(os.getenv("PORT", "3000"))
AGENTS_DIR = Path(os.getenv("AGENTS_DIR", "/app/agents"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))

# Provider API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "")
CONDUCTOR_MODEL = os.getenv("CONDUCTOR_MODEL", "claude-sonnet-4-5")

# Redis (optional — graceful fallback if unavailable)
REDIS_URL = os.getenv("REDIS_URL", "")

# ---------------------------------------------------------------------------
# Daily token budget tracking
# ---------------------------------------------------------------------------
DAILY_TOKEN_BUDGET = int(os.getenv("DAILY_TOKEN_BUDGET", "500000"))  # default 500k


class TokenTracker:
    """Simple daily token counter. Resets at midnight. Logs warning on budget exceed."""

    def __init__(self, budget: int = DAILY_TOKEN_BUDGET):
        self.budget = budget
        self.tokens_used = 0
        self._current_date = datetime.now().strftime("%Y-%m-%d")

    def _maybe_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            logger.info("token_tracker_reset previous_day=%s tokens=%d", self._current_date, self.tokens_used)
            self.tokens_used = 0
            self._current_date = today

    def record(self, usage: dict):
        """Record token usage from an API response's 'usage' block."""
        self._maybe_reset()
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        self.tokens_used += input_t + output_t
        if self.tokens_used > self.budget:
            logger.warning(
                "DAILY TOKEN BUDGET EXCEEDED: %d / %d",
                self.tokens_used,
                self.budget,
            )

    def summary(self) -> dict:
        self._maybe_reset()
        return {
            "date": self._current_date,
            "tokens_used": self.tokens_used,
            "budget": self.budget,
            "remaining": max(0, self.budget - self.tokens_used),
        }


token_tracker = TokenTracker()


# ---------------------------------------------------------------------------
# Agent config model
# ---------------------------------------------------------------------------
class AgentConfig:
    """Parsed agent from a YAML config file."""

    def __init__(self, data: dict, source_file: str):
        self.agent_id: str = data.get("agent_id", "unknown")
        self.display_name: str = data.get("display_name", self.agent_id)
        self.enabled: bool = data.get("enabled", True)
        self.version: str = data.get("version", "0.0.0")

        model_block = data.get("model", {})
        self.provider: str = model_block.get("provider", "anthropic")
        self.model_id: str = model_block.get("model_id", "claude-sonnet-4-5")
        self.max_output_tokens: int = model_block.get("max_output_tokens", 4096)
        self.temperature: float = model_block.get("temperature", 0.3)
        self.top_p: float = model_block.get("top_p", 0.9)
        self.stream: bool = model_block.get("stream", False)

        self.system_prompt: str = data.get("system_prompt", "")
        self.tools: list = data.get("tools", [])
        self.restrictions: dict = data.get("restrictions", {})
        self.source_file: str = source_file

    def __repr__(self):
        return f"<Agent {self.agent_id} ({self.provider}/{self.model_id})>"


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------
class AgentRegistry:
    """Loads all agent YAML configs and provides lookup by agent_id or model alias."""

    def __init__(self, agents_dir: Path):
        self.agents: dict[str, AgentConfig] = {}
        self.default_agent_id: str = "bob_conductor"
        self._load_agents(agents_dir)

    def _load_agents(self, agents_dir: Path):
        if not agents_dir.exists():
            logger.warning("Agents directory not found: %s", agents_dir)
            return

        for yml_path in sorted(agents_dir.glob("*.yml")):
            try:
                with open(yml_path) as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
                # Skip the registry file itself
                if "registry_version" in data:
                    logger.info("Skipping registry file: %s", yml_path.name)
                    continue
                agent = AgentConfig(data, str(yml_path))
                if agent.enabled:
                    self.agents[agent.agent_id] = agent
                    logger.info("Loaded agent: %s (%s/%s)", agent.agent_id, agent.provider, agent.model_id)
                else:
                    logger.info("Skipped disabled agent: %s", agent.agent_id)
            except Exception as e:
                logger.error("Failed to load agent config %s: %s", yml_path, e)

        logger.info("Registry ready: %d agents loaded", len(self.agents))

    def get(self, agent_id: str) -> Optional[AgentConfig]:
        """Look up by agent_id directly."""
        return self.agents.get(agent_id)

    def resolve(self, model_name: str) -> AgentConfig:
        """
        Resolve an OpenAI-compatible 'model' field to an agent.

        Accepts:
          - Direct agent_id: "bob_conductor"
          - Shorthand: "bob", "proposals", "dtools"
          - Fallback: returns default agent
        """
        # Direct match
        if model_name in self.agents:
            return self.agents[model_name]

        # Shorthand match (prefix search)
        for aid, agent in self.agents.items():
            if aid.startswith(model_name) or model_name in aid:
                return agent

        # Fallback to default
        default = self.agents.get(self.default_agent_id)
        if default:
            logger.info("Model '%s' not found, routing to default: %s", model_name, self.default_agent_id)
            return default

        # Last resort: first enabled agent
        if self.agents:
            first = next(iter(self.agents.values()))
            logger.warning("No default agent, using first available: %s", first.agent_id)
            return first

        raise ValueError("No agents available")

    def list_agents(self) -> list[dict]:
        """Return agent info for /models endpoint."""
        return [
            {
                "id": a.agent_id,
                "object": "model",
                "created": 1709049600,
                "owned_by": "symphony",
                "display_name": a.display_name,
                "provider": a.provider,
                "model_id": a.model_id,
            }
            for a in self.agents.values()
        ]


# ---------------------------------------------------------------------------
# LLM provider calls
# ---------------------------------------------------------------------------
class LLMRouter:
    """Routes completion requests to the right LLM provider."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=120.0)

    async def complete(self, agent: AgentConfig, messages: list[dict], **kwargs) -> str:
        """Send messages to the agent's configured LLM provider, return response text."""
        provider = agent.provider.lower()
        if provider == "anthropic":
            return await self._call_anthropic(agent, messages, **kwargs)
        elif provider == "openai":
            return await self._call_openai(agent, messages, **kwargs)
        elif provider == "ollama":
            return await self._call_ollama(agent, messages, **kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def _call_anthropic(self, agent: AgentConfig, messages: list[dict], **kwargs) -> str:
        """Call Anthropic Messages API."""
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Separate system message from conversation
        system_parts = []
        conv_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_parts.append(m["content"])
            else:
                conv_messages.append({"role": m["role"], "content": m["content"]})

        # Prepend agent system prompt if not already in messages
        if agent.system_prompt and agent.system_prompt not in " ".join(system_parts):
            system_parts.insert(0, agent.system_prompt)

        system_text = "\n\n".join(system_parts)

        # Ensure conversation starts with user message (Anthropic requirement)
        if not conv_messages or conv_messages[0]["role"] != "user":
            conv_messages.insert(0, {"role": "user", "content": "Hello"})

        # Merge consecutive same-role messages (Anthropic requires alternating)
        merged = []
        for msg in conv_messages:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(dict(msg))
        conv_messages = merged

        # Use structured system block with cache_control for prompt caching.
        # This saves ~90% on input tokens for repeated calls with the same agent system prompt.
        payload = {
            "model": agent.model_id,
            "max_tokens": kwargs.get("max_tokens", agent.max_output_tokens),
            "temperature": kwargs.get("temperature", agent.temperature),
            "system": [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": conv_messages,
        }

        resp = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )

        if resp.status_code != 200:
            logger.error("Anthropic error %d: %s", resp.status_code, resp.text[:500])
            raise HTTPException(status_code=502, detail=f"Anthropic API error: {resp.status_code}")

        data = resp.json()
        # Track token usage for daily budget
        usage = data.get("usage", {})
        if usage:
            token_tracker.record(usage)
        # Extract text from content blocks
        content_blocks = data.get("content", [])
        text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return "\n".join(text_parts).strip()

    async def _call_openai(self, agent: AgentConfig, messages: list[dict], **kwargs) -> str:
        """Call OpenAI Chat Completions API."""
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")

        # Inject agent system prompt
        final_messages = list(messages)
        if agent.system_prompt:
            has_system = any(m.get("role") == "system" for m in final_messages)
            if not has_system:
                final_messages.insert(0, {"role": "system", "content": agent.system_prompt})

        payload = {
            "model": agent.model_id,
            "max_tokens": kwargs.get("max_tokens", agent.max_output_tokens),
            "temperature": kwargs.get("temperature", agent.temperature),
            "messages": final_messages,
        }

        resp = await self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if resp.status_code != 200:
            logger.error("OpenAI error %d: %s", resp.status_code, resp.text[:500])
            raise HTTPException(status_code=502, detail=f"OpenAI API error: {resp.status_code}")

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def _call_ollama(self, agent: AgentConfig, messages: list[dict], **kwargs) -> str:
        """Call Ollama via its OpenAI-compatible endpoint."""
        if not OLLAMA_HOST:
            raise ValueError("OLLAMA_HOST not set")

        base = OLLAMA_HOST.rstrip("/")

        # Inject agent system prompt
        final_messages = list(messages)
        if agent.system_prompt:
            has_system = any(m.get("role") == "system" for m in final_messages)
            if not has_system:
                final_messages.insert(0, {"role": "system", "content": agent.system_prompt})

        payload = {
            "model": agent.model_id,
            "messages": final_messages,
            "stream": False,
        }

        resp = await self._http.post(
            f"{base}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload,
        )

        if resp.status_code != 200:
            logger.error("Ollama error %d: %s", resp.status_code, resp.text[:500])
            raise HTTPException(status_code=502, detail=f"Ollama API error: {resp.status_code}")

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def close(self):
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Request / response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "bob_conductor"
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None


def make_completion_response(agent_id: str, content: str, model_id: str) -> dict:
    """Build an OpenAI-compatible chat completion response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": agent_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "system_fingerprint": f"openclaw-{agent_id}",
    }


# ---------------------------------------------------------------------------
# Link analysis models & helpers
# ---------------------------------------------------------------------------
LINK_ANALYSIS_DIR = DATA_DIR / "link-analysis"

LINK_ANALYSIS_SYSTEM_PROMPT = (
    "You are a business intelligence analyst for Symphony Smart Homes, "
    "a company that runs AI trading bots and smart home service automation. "
    "Analyze the provided content and return ONLY valid JSON with these fields:\n"
    '  "tool_or_topic": what tool, technique, or product is discussed,\n'
    '  "relevance": integer 1-10 how actionable for a smart home business running AI trading bots and service automation,\n'
    '  "action": specific action if relevant (e.g. "integrate into trading bot", "add to knowledge graph", "bookmark for later"),\n'
    '  "category": one of trading/smart_home/iot/ai_tools/general,\n'
    '  "summary": one-line summary\n'
    "Return ONLY the JSON object, no markdown fences or extra text."
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

MAX_URLS_PER_REQUEST = 20
LLM_DELAY_SECONDS = 2
MAX_CONTENT_LENGTH = 15000  # Truncate fetched content to keep LLM costs low


class LinkAnalysisRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=MAX_URLS_PER_REQUEST)
    context: Optional[str] = None  # hint: trading, smart_home, iot, ai_tools, general


class LinkAnalysisResult(BaseModel):
    url: str
    summary: str = ""
    relevance: int = 0
    action: str = ""
    category: str = "general"
    tool_or_topic: str = ""
    status: str = "ok"  # ok | fetch_failed | analysis_skipped
    raw_text: str = ""


async def fetch_url_content(url: str) -> tuple[str, str]:
    """
    Fetch page content. Returns (text_content, status).
    For GitHub URLs, tries to fetch README. For Twitter/X, falls back to
    Perplexity search when direct fetch returns empty/login-wall content.
    """
    headers = {"User-Agent": BROWSER_USER_AGENT}

    # GitHub repo → fetch README
    if "github.com" in url:
        parts = url.rstrip("/").split("/")
        # https://github.com/org/repo → need at least 5 parts
        if len(parts) >= 5:
            owner, repo = parts[3], parts[4]
            readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                    resp = await client.get(readme_url, headers=headers)
                    if resp.status_code == 200:
                        return resp.text[:MAX_CONTENT_LENGTH], "ok"
            except Exception:
                pass  # Fall through to normal fetch

    content = ""
    status = "ok"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content = resp.text[:MAX_CONTENT_LENGTH]
    except Exception as e:
        logger.warning("fetch_failed url=%s error=%s", url, e)
        status = "fetch_failed"

    # Fallback: Twitter/X links often return empty/login-wall content.
    # Use Perplexity to retrieve tweet content instead.
    if len(content) < 100 and ("x.com" in url or "twitter.com" in url):
        perplexity_key = os.getenv("PERPLEXITY_API_KEY", "")
        if perplexity_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://api.perplexity.ai/chat/completions",
                        headers={"Authorization": f"Bearer {perplexity_key}"},
                        json={
                            "model": "sonar",
                            "messages": [
                                {
                                    "role": "user",
                                    "content": (
                                        "What does this tweet say? Summarize the "
                                        "content, tools, and links shared: " + url
                                    ),
                                }
                            ],
                        },
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        status = "ok_via_perplexity"
                        logger.info("twitter_perplexity_fallback url=%s len=%d", url, len(content))
            except Exception as e:
                logger.warning("perplexity_fallback_failed url=%s error=%s", url, e)

    if not content:
        return "", status if status != "ok" else "fetch_failed"
    return content, status


def _parse_llm_json(text: str) -> dict:
    """Parse JSON from an LLM response, handling markdown fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```" in text:
            json_part = text.split("```")[1]
            if json_part.startswith("json"):
                json_part = json_part[4:]
            return json.loads(json_part.strip())
        logger.warning("Failed to parse LLM JSON: %s", text[:200])
        return {}


async def _analyze_with_ollama(url: str, content: str, context_hint: str) -> dict:
    """Try Ollama (free) for link analysis. Returns {} on failure."""
    if not OLLAMA_HOST:
        return {}

    user_prompt = f"Analyze this content from {url}:\n\n{content[:10000]}"
    if context_hint:
        user_prompt += f"\n\nContext hint: focus on relevance to {context_hint}."

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_HOST.rstrip('/')}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "qwen3:8b",
                    "messages": [
                        {"role": "system", "content": LINK_ANALYSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "stream": False,
                },
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                result = _parse_llm_json(text)
                if result:
                    logger.info("link_analysis_ollama url=%s", url)
                    return result
    except Exception as e:
        logger.warning("ollama_link_analysis_failed url=%s error=%s", url, e)

    return {}


async def _analyze_with_haiku(url: str, content: str, context_hint: str) -> dict:
    """Fallback to Claude Haiku (paid) for link analysis."""
    user_prompt = f"Content from {url}:\n\n{content}"
    if context_hint:
        user_prompt += f"\n\nContext hint: focus on relevance to {context_hint}."

    payload = {
        "model": "claude-haiku-4-5-20241022",
        "max_tokens": 512,
        "temperature": 0.2,
        "system": [
            {
                "type": "text",
                "text": LINK_ANALYSIS_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_prompt}],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )

    if resp.status_code != 200:
        logger.error("Haiku analysis error %d: %s", resp.status_code, resp.text[:300])
        return {}

    data = resp.json()
    usage = data.get("usage", {})
    if usage:
        token_tracker.record(usage)

    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()

    return _parse_llm_json(text)


async def analyze_with_llm(url: str, content: str, context_hint: str) -> dict:
    """Analyze link content. Tries Ollama first (free), falls back to Claude Haiku."""
    # Try Ollama first (free — runs on Maestro)
    result = await _analyze_with_ollama(url, content, context_hint)
    if result:
        return result

    # Fallback to Claude Haiku (paid)
    return await _analyze_with_haiku(url, content, context_hint)


def save_analysis_results(results: list[dict]) -> str:
    """Save analysis results to a timestamped JSON file. Returns filename."""
    LINK_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"analysis_{ts}.json"
    filepath = LINK_ANALYSIS_DIR / filename
    with open(filepath, "w") as f:
        json.dump({"timestamp": ts, "results": results}, f, indent=2)
    return filename


async def publish_high_relevance(results: list[dict]):
    """Publish items with relevance >= 7 to Redis notifications:links channel."""
    if not REDIS_URL:
        return
    high = [r for r in results if r.get("relevance", 0) >= 7]
    if not high:
        return
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        for item in high:
            await r.publish("notifications:links", json.dumps(item))
        await r.aclose()
        logger.info("Published %d high-relevance links to Redis", len(high))
    except Exception as e:
        logger.warning("Redis publish failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# Delegation detection
# ---------------------------------------------------------------------------
def detect_delegation(text: str, registry: AgentRegistry) -> Optional[tuple[str, str]]:
    """
    Check if agent output contains a @delegation command.
    Returns (target_agent_id, stripped_message) or None.
    """
    if not text:
        return None
    lines = text.strip().split("\n")
    first_line = lines[0].strip()
    if first_line.startswith("@"):
        parts = first_line.split(None, 1)
        prefix = parts[0][1:]  # Strip @
        rest = parts[1] if len(parts) > 1 else ""
        # Check remaining lines too
        if not rest and len(lines) > 1:
            rest = "\n".join(lines[1:]).strip()
        # Try to resolve the prefix to an agent
        for aid in registry.agents:
            short = aid.replace("_agent", "")
            if prefix.lower() in (aid.lower(), short.lower()):
                return aid, rest
    return None


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="OpenClaw",
    description="Multi-agent orchestration — OpenAI-compatible API",
    version="1.0.0",
)

registry: AgentRegistry = None  # type: ignore
llm: LLMRouter = None  # type: ignore
orchestrator = None  # type: ignore
memory: MemoryPlugin = None  # type: ignore
agent_bus: AgentBus = None  # type: ignore


@app.on_event("startup")
async def startup():
    global registry, llm, orchestrator, memory, agent_bus
    logger.info("OpenClaw starting up...")
    registry = AgentRegistry(AGENTS_DIR)
    llm = LLMRouter()

    # Ensure data directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "conversations").mkdir(exist_ok=True)
    (DATA_DIR / "logs").mkdir(exist_ok=True)
    LINK_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize persistent memory
    memory = MemoryPlugin(str(DATA_DIR / "openclaw_memory.db"))
    logger.info("Persistent memory initialized")

    # Initialize agent bus
    agent_bus = AgentBus(redis_url=REDIS_URL)
    await agent_bus.start()
    logger.info("Agent bus initialized")

    # Start autonomous orchestration loop (pass memory for context)
    from orchestrator import Orchestrator
    orchestrator = Orchestrator(memory=memory)
    asyncio.create_task(orchestrator.run_loop())
    logger.info("Autonomous orchestrator started")

    logger.info("OpenClaw ready on port %d — %d agents loaded", PORT, len(registry.agents))


@app.on_event("shutdown")
async def shutdown():
    if orchestrator:
        await orchestrator.close()
    if agent_bus:
        await agent_bus.stop()
    if memory:
        memory.close()
    if llm:
        await llm.close()
    logger.info("OpenClaw shut down.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    agent_count = len(registry.agents) if registry else 0
    agent_list = list(registry.agents.keys()) if registry else []
    return {
        "status": "ok",
        "service": "openclaw",
        "version": "1.0.0",
        "agents_loaded": agent_count,
        "agents": agent_list,
        "uptime": "running",
    }


@app.get("/api/models")
@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing."""
    return {
        "object": "list",
        "data": registry.list_agents() if registry else [],
    }


@app.post("/api/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """
    OpenAI-compatible chat completions endpoint.

    The 'model' field is used to select which agent handles the request.
    Agents are resolved by agent_id (e.g., 'bob_conductor', 'proposals_agent')
    or shorthand (e.g., 'bob', 'proposals', 'dtools').
    """
    if not registry or not registry.agents:
        raise HTTPException(status_code=503, detail="No agents loaded")

    # Resolve agent from model name
    try:
        agent = registry.resolve(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        "Request → agent=%s provider=%s model=%s msgs=%d",
        agent.agent_id, agent.provider, agent.model_id, len(req.messages),
    )

    # Build messages list
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # Inject memory context as a system block
    if memory:
        try:
            agent_memories = memory.get_context_for_agent(agent.agent_id)
            if agent_memories:
                mem_lines = [f"- {m['key']}: {m['value']}" for m in agent_memories[:20]]
                mem_block = "## Relevant Memories\n" + "\n".join(mem_lines)
                messages.insert(0, {"role": "system", "content": mem_block})
        except Exception as e:
            logger.warning("memory_inject_failed: %s", e)

    # Optional overrides
    kwargs = {}
    if req.max_tokens is not None:
        kwargs["max_tokens"] = req.max_tokens
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature

    try:
        response_text = await llm.complete(agent, messages, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("LLM call failed for agent %s: %s", agent.agent_id, e)
        raise HTTPException(status_code=502, detail=f"LLM provider error: {e}")

    # Check for delegation in the response
    delegation = detect_delegation(response_text, registry)
    if delegation:
        target_id, delegated_msg = delegation
        target_agent = registry.get(target_id)
        if target_agent:
            # Verify delegation is allowed
            allowed = agent.restrictions.get("can_delegate", True)
            if allowed:
                logger.info(
                    "Delegation: %s → %s (%d chars)",
                    agent.agent_id, target_id, len(delegated_msg),
                )
                try:
                    delegation_messages = [{"role": "user", "content": delegated_msg}]
                    sub_response = await llm.complete(target_agent, delegation_messages)
                    # Combine: note the delegation happened + sub-agent response
                    response_text = (
                        f"[Delegated to {target_agent.display_name}]\n\n{sub_response}"
                    )
                except Exception as e:
                    logger.error("Delegation to %s failed: %s", target_id, e)
                    response_text += f"\n\n[Delegation to {target_agent.display_name} failed: {e}]"

    return JSONResponse(
        content=make_completion_response(agent.agent_id, response_text, agent.model_id)
    )


@app.get("/api/agents")
async def list_agents_detail():
    """Detailed agent listing (non-OpenAI, internal use)."""
    if not registry:
        return {"agents": []}
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "display_name": a.display_name,
                "provider": a.provider,
                "model_id": a.model_id,
                "enabled": a.enabled,
                "version": a.version,
                "has_system_prompt": bool(a.system_prompt),
                "tool_count": len(a.tools),
            }
            for a in registry.agents.values()
        ]
    }


@app.get("/api/token-usage")
async def token_usage():
    """Current daily token usage stats."""
    return token_tracker.summary()


@app.post("/api/analyze-links")
async def analyze_links(req: LinkAnalysisRequest):
    """
    Analyze a list of URLs using Ollama (free) with Claude Haiku fallback.
    Fetches each URL, classifies content, stores results, and notifies on high-relevance items.
    """
    context_hint = req.context or ""
    results = []

    for i, url in enumerate(req.urls):
        # Fetch content
        content, status = await fetch_url_content(url)

        if status == "fetch_failed":
            results.append({
                "url": url,
                "summary": "",
                "relevance": 0,
                "action": "",
                "category": "general",
                "tool_or_topic": "",
                "status": "fetch_failed",
            })
            continue

        # If no LLM backend available, return raw text without analysis
        if not ANTHROPIC_API_KEY and not OLLAMA_HOST:
            results.append({
                "url": url,
                "summary": content[:200],
                "relevance": 0,
                "action": "",
                "category": "general",
                "tool_or_topic": "",
                "status": "analysis_skipped",
                "raw_text": content[:500],
            })
            continue

        # Call Claude Haiku for analysis
        try:
            analysis = await analyze_with_llm(url, content, context_hint)
        except Exception as e:
            logger.error("LLM analysis failed for %s: %s", url, e)
            analysis = {}

        results.append({
            "url": url,
            "summary": analysis.get("summary", ""),
            "relevance": analysis.get("relevance", 0),
            "action": analysis.get("action", ""),
            "category": analysis.get("category", "general"),
            "tool_or_topic": analysis.get("tool_or_topic", ""),
            "status": "ok",
        })

        # Rate limit: 2s delay between LLM calls (skip after last URL)
        if i < len(req.urls) - 1:
            await asyncio.sleep(LLM_DELAY_SECONDS)

    # Save results to JSON file
    save_analysis_results(results)

    # Publish high-relevance items to Redis
    await publish_high_relevance(results)

    logger.info("link_analysis completed=%d urls", len(results))

    return JSONResponse(content={
        "analyzed": len(results),
        "results": results,
    })


@app.get("/api/analyzed-links")
async def get_analyzed_links(limit: int = Query(default=50, ge=1, le=500)):
    """Return recent link analyses from stored JSON files, sorted by timestamp descending."""
    if not LINK_ANALYSIS_DIR.exists():
        return {"analyses": []}

    # List all analysis JSON files, sorted newest first
    files = sorted(LINK_ANALYSIS_DIR.glob("analysis_*.json"), reverse=True)
    analyses = []
    for fp in files[:limit]:
        try:
            with open(fp) as f:
                data = json.load(f)
            analyses.append(data)
        except Exception as e:
            logger.warning("Failed to read analysis file %s: %s", fp.name, e)

    return {"analyses": analyses}


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------
class MemoryRequest(BaseModel):
    key: str
    value: str
    category: str = "project_context"
    source_agent: str = "openclaw"


@app.post("/memory/remember")
async def memory_remember(req: MemoryRequest):
    """Store a memory."""
    if not memory:
        raise HTTPException(status_code=503, detail="Memory plugin not initialized")
    memory.remember(req.key, req.value, req.category, req.source_agent)
    return {"status": "stored", "key": req.key}


@app.get("/memory/recall")
async def memory_recall(
    query: str = Query(..., min_length=1),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
):
    """Search memories by key or value."""
    if not memory:
        raise HTTPException(status_code=503, detail="Memory plugin not initialized")
    results = memory.recall(query, category=category, limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/memory/export")
async def memory_export():
    """Export all memories as markdown."""
    if not memory:
        raise HTTPException(status_code=503, detail="Memory plugin not initialized")
    return JSONResponse(content={"markdown": memory.export_to_markdown()})


@app.get("/memory/stats")
async def memory_stats():
    """Memory statistics: count by category, total, oldest/newest."""
    if not memory:
        raise HTTPException(status_code=503, detail="Memory plugin not initialized")
    return memory.stats()


# ---------------------------------------------------------------------------
# Agent bus endpoints
# ---------------------------------------------------------------------------
class AgentMessageRequest(BaseModel):
    from_agent: str
    to_agent: str = "broadcast"
    type: str = "request"
    payload: dict = {}


@app.post("/agents/message")
async def send_agent_message(req: AgentMessageRequest):
    """Send an inter-agent message."""
    if not agent_bus:
        raise HTTPException(status_code=503, detail="Agent bus not initialized")
    await agent_bus.publish(req.from_agent, req.to_agent, req.type, req.payload)
    return {"status": "sent", "from": req.from_agent, "to": req.to_agent}


@app.get("/agents/messages")
async def get_agent_messages(
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get recent messages for an agent."""
    if not agent_bus:
        raise HTTPException(status_code=503, detail="Agent bus not initialized")
    messages = agent_bus.get_messages(agent_id=agent_id, limit=limit)
    return {"messages": messages, "count": len(messages)}


@app.get("/")
async def root():
    return {
        "service": "OpenClaw",
        "organization": "Symphony Smart Homes",
        "conductor": "Bob",
        "docs": "/docs",
        "health": "/health",
        "models": "/api/models",
        "memory": "/memory/stats",
        "agent_bus": "/agents/messages",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
