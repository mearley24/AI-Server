# Auto-23: LLM Cost Optimization — $50/Month Target

## The Problem

Bob runs 15+ Docker services that all make OpenAI API calls independently. Every trade validation in `llm_validator.py`, every email classification in `email-monitor/analyzer.py`, every debate in `debate_engine.py` hits the OpenAI API directly. There's no caching, no routing to cheaper models, no awareness of what has already been asked. At scale, this could run $200-500/month. The target is $50/month.

Ollama is already running on Betty/Maestro (iMac, 64GB RAM) at `http://192.168.1.199:11434` with `llama3.1:8b` and `qwen3:8b` available — completely free inference that is currently unused by any service.

## Context Files to Read First

- `openclaw/auto_responder.py` — direct OpenAI calls; primary migration target for medium-complexity tasks
- `email-monitor/analyzer.py` — OpenAI calls for email classification; prime candidate for local routing
- `polymarket-bot/strategies/llm_validator.py` — OpenAI calls per trade; needs caching + routing
- `openclaw/main.py` — FastAPI app structure; where to add the `/api/llm-costs` endpoint

## Prompt

Build a central LLM routing and cost tracking layer. Two new files: `openclaw/llm_router.py` and `openclaw/llm_cache.py`. All services that currently call OpenAI directly should migrate to use `from openclaw.llm_router import completion` instead.

### 1. LLM Router (`openclaw/llm_router.py`)

The single interface every service uses for LLM calls:

```python
from openclaw.llm_router import completion

response = await completion(
    prompt="Classify this email as spam or not",
    complexity="simple",          # simple | medium | complex
    cache_ttl=3600,               # seconds; 0 = no cache
    service="email-monitor",      # for cost attribution
    fallback="cloud",             # "cloud" | "skip" | "error"
)
# Returns: {"content": "...", "model": "llama3.1:8b", "cached": False, "cost_usd": 0.0}
```

#### Routing Logic

```python
COMPLEXITY_ROUTING = {
    "simple": [
        {"provider": "ollama", "model": "llama3.1:8b", "base_url": "http://192.168.1.199:11434"},
    ],
    "medium": [
        {"provider": "ollama", "model": "qwen3:8b",    "base_url": "http://192.168.1.199:11434"},
        {"provider": "openai", "model": "gpt-4o-mini", "fallback": True},
    ],
    "complex": [
        {"provider": "openai", "model": "gpt-4o"},
    ],
}
```

- `simple` — classification, yes/no questions, entity extraction, short categorization: always try Ollama first
- `medium` — summarization, trade validation, email drafting, short generation: try Ollama `qwen3:8b`, fall back to `gpt-4o-mini`
- `complex` — proposal generation, long reasoning chains, code generation, multi-step analysis: always use OpenAI `gpt-4o`

#### Ollama Availability Check

Before routing to Ollama, test connectivity with a 3-second timeout:

```python
async def _ollama_available() -> bool:
    """Ping Ollama health endpoint. Cache result for 60 seconds."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://192.168.1.199:11434/api/tags")
            return r.status_code == 200
    except (httpx.TimeoutException, httpx.ConnectError):
        return False
```

Cache the availability result for 60 seconds — don't ping on every request. If Ollama is down, automatically route `simple` and `medium` calls to `gpt-4o-mini` as fallback. Log a warning but don't fail.

#### Environment Variable: `LLM_ROUTER_MODE`

```
LLM_ROUTER_MODE=local_first   (default) — route simple/medium to Ollama
LLM_ROUTER_MODE=cloud_only    — all calls go to OpenAI regardless of complexity
LLM_ROUTER_MODE=local_only    — all calls go to Ollama; fail if unavailable
```

This allows quick override without code changes — useful for debugging or if Ollama is down for maintenance.

### 2. Redis Cache (`openclaw/llm_cache.py`)

Prompt cache layer backed by Redis. Check cache before any API call:

```python
class LLMCache:
    def __init__(self, redis_url: str = "redis://172.18.0.100:6379"):
        self.redis = redis.from_url(redis_url, decode_responses=True)
    
    def _cache_key(self, prompt: str, model: str) -> str:
        """SHA256 of (model + normalized prompt)."""
        content = f"{model}:{prompt.strip().lower()}"
        return f"llm:cache:{hashlib.sha256(content.encode()).hexdigest()}"
    
    async def get(self, prompt: str, model: str) -> dict | None:
        """Return cached response or None."""
        key = self._cache_key(prompt, model)
        value = self.redis.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set(self, prompt: str, model: str, response: dict, ttl: int) -> None:
        """Store response with TTL."""
        key = self._cache_key(prompt, model)
        self.redis.setex(key, ttl, json.dumps(response))
```

Default TTLs (callers can override):
- `simple` classification (emails, categories): 3600 seconds (1 hour)
- `medium` trade validation: 300 seconds (5 minutes — prices change)
- `medium` market categorization: 86400 seconds (24 hours — categories don't change)
- `complex` proposal content: 0 seconds (no cache — every proposal is unique)

Cache hit rate target: 40%+. Log cache hits/misses to Redis counter `llm:cache:hits` and `llm:cache:misses` for monitoring.

### 3. Cost Tracking

Log every API call — whether cached or live — to Redis:

```python
# Per-call cost log (append to list, LTRIM to 10000)
redis.lpush("llm:costs:log", json.dumps({
    "ts": time.time(),
    "service": service,         # "email-monitor", "llm_validator", etc.
    "model": model_used,
    "provider": "ollama" | "openai",
    "input_tokens": n,
    "output_tokens": n,
    "cost_usd": computed_cost,
    "cached": True | False,
    "complexity": "simple" | "medium" | "complex",
    "latency_ms": elapsed,
}))

# Daily aggregate (hash per day)
date_key = f"llm:costs:daily:{datetime.utcnow().strftime('%Y-%m-%d')}"
redis.hincrbyfloat(date_key, "total_usd", cost)
redis.hincrbyfloat(date_key, f"{service}_usd", cost)
redis.hincrbyfloat(date_key, f"{model}_usd", cost)
redis.expire(date_key, 86400 * 90)  # keep 90 days of history
```

Model pricing constants (update when OpenAI changes rates):
```python
MODEL_COSTS_PER_1K_TOKENS = {
    "gpt-4o":        {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini":   {"input": 0.000150, "output": 0.000600},
    "llama3.1:8b":   {"input": 0.0, "output": 0.0},   # Ollama = free
    "qwen3:8b":      {"input": 0.0, "output": 0.0},
}
```

Alert rule: if daily cost exceeds `$5.00`, publish to Redis channel `notifications:alerts` with title "LLM cost alert" and body showing service breakdown.

### 4. Cost Reporting API Endpoint

Add to `openclaw/main.py`:

```python
@app.get("/api/llm-costs")
async def get_llm_costs():
    """Return LLM cost breakdown by service, model, and time period."""
    return {
        "today": _aggregate_costs(days=1),
        "this_week": _aggregate_costs(days=7),
        "this_month": _aggregate_costs(days=30),
        "cache_stats": {
            "hits": redis.get("llm:cache:hits") or 0,
            "misses": redis.get("llm:cache:misses") or 0,
            "hit_rate_pct": ...,
        },
        "by_service": _costs_by_service(days=30),
        "by_model": _costs_by_model(days=30),
        "ollama_vs_cloud": {
            "ollama_calls": ...,
            "cloud_calls": ...,
            "local_pct": ...,
        },
        "projected_monthly_usd": ...,
    }
```

### 5. Service Migration — What Changes

For each service listed below, replace the direct OpenAI call with `completion()` from the router. The existing logic for parsing the response stays the same — only the API call changes.

**`polymarket-bot/strategies/llm_validator.py`:**
```python
# BEFORE:
response = openai_client.chat.completions.create(model="gpt-4o-mini", ...)

# AFTER:
from openclaw.llm_router import completion
result = await completion(
    prompt=validation_prompt,
    complexity="medium",
    cache_ttl=300,   # 5-minute cache on trade validation
    service="llm_validator",
)
response_text = result["content"]
```

**`email-monitor/analyzer.py`:**
```python
# Classification calls → "simple" complexity (route to Ollama)
result = await completion(
    prompt=classification_prompt,
    complexity="simple",
    cache_ttl=3600,
    service="email-monitor",
)
```

**`openclaw/auto_responder.py`:**
```python
# Email drafting → "medium" complexity
result = await completion(
    prompt=drafting_prompt,
    complexity="medium",
    cache_ttl=0,     # no cache — each response is personalized
    service="auto_responder",
)
```

### 6. Ollama API Format

Ollama uses a different API shape than OpenAI. The router must handle both:

```python
async def _call_ollama(model: str, prompt: str, timeout: float = 30.0) -> dict:
    """Call Ollama generate API and return normalized response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "http://192.168.1.199:11434/api/generate",
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "content": data["response"].strip(),
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
        }
```

### 7. Docker Networking Note

`openclaw/llm_router.py` runs inside Docker. To reach Ollama on the host iMac at `192.168.1.199`:
- Use `192.168.1.199:11434` directly (LAN IP, accessible from any container on the host network)
- This is the Maestro/Betty iMac — always on, 64GB RAM, never sleeps
- The Docker service must be on the `host` network OR have the LAN accessible (check `docker-compose.yml`)

### 8. Testing

Create `tests/test_llm_router.py` with:
- Test `simple` prompt routes to Ollama when available
- Test `complex` prompt routes to OpenAI regardless
- Test fallback to `gpt-4o-mini` when Ollama is unreachable (mock the ping to return False)
- Test cache hit returns cached value without calling any API
- Test cost is logged to Redis on every call
- Test daily aggregate key is updated correctly

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.
