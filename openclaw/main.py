"""
OpenClaw — Multi-Agent Orchestration Service
Symphony Smart Homes | Bob the Conductor | Mac Mini M4

Exposes an OpenAI-compatible POST /api/chat/completions endpoint.
Loads agent YAML configs from agents/ and routes requests by model name.
"""

import os
import logging
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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

        payload = {
            "model": agent.model_id,
            "max_tokens": kwargs.get("max_tokens", agent.max_output_tokens),
            "temperature": kwargs.get("temperature", agent.temperature),
            "system": system_text,
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


@app.on_event("startup")
async def startup():
    global registry, llm
    logger.info("OpenClaw starting up...")
    registry = AgentRegistry(AGENTS_DIR)
    llm = LLMRouter()

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "conversations").mkdir(exist_ok=True)
    (DATA_DIR / "logs").mkdir(exist_ok=True)

    logger.info("OpenClaw ready on port %d — %d agents loaded", PORT, len(registry.agents))


@app.on_event("shutdown")
async def shutdown():
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


@app.get("/")
async def root():
    return {
        "service": "OpenClaw",
        "organization": "Symphony Smart Homes",
        "conductor": "Bob",
        "docs": "/docs",
        "health": "/health",
        "models": "/api/models",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
