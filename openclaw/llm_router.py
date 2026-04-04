"""Central LLM routing, caching, and cost tracking (Auto-23)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

try:
    from llm_cache import LLMCache
except ImportError:  # package import path (e.g. from polymarket-bot cwd)
    from openclaw.llm_cache import LLMCache

logger = logging.getLogger(__name__)

OLLAMA_BASE_DEFAULT = "http://192.168.1.199:11434"
REDIS_URL_DEFAULT = "redis://172.18.0.100:6379"

MODEL_COSTS_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
    "llama3.1:8b": {"input": 0.0, "output": 0.0},
    "qwen3:8b": {"input": 0.0, "output": 0.0},
}

DAILY_COST_ALERT_USD = 5.0

_ollama_last_check: float = 0.0
_ollama_last_ok: bool = False
_OLLAMA_CHECK_TTL = 60.0

_cache_singleton: LLMCache | None = None
_redis_log: Any = None


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_HOST", OLLAMA_BASE_DEFAULT).rstrip("/")


def _router_mode() -> str:
    return os.environ.get("LLM_ROUTER_MODE", "local_first").strip().lower()


def _build_routing_table() -> dict[str, list[dict[str, Any]]]:
    base = _ollama_base()
    return {
        "simple": [
            {"provider": "ollama", "model": "llama3.1:8b", "base_url": base},
        ],
        "medium": [
            {"provider": "ollama", "model": "qwen3:8b", "base_url": base},
            {"provider": "openai", "model": "gpt-4o-mini", "fallback": True},
        ],
        "complex": [
            {"provider": "openai", "model": "gpt-4o"},
        ],
    }


def _cloud_only_routing() -> dict[str, list[dict[str, Any]]]:
    return {
        "simple": [{"provider": "openai", "model": "gpt-4o-mini"}],
        "medium": [
            {"provider": "openai", "model": "gpt-4o-mini"},
        ],
        "complex": [{"provider": "openai", "model": "gpt-4o"}],
    }


def _local_only_routing() -> dict[str, list[dict[str, Any]]]:
    base = _ollama_base()
    return {
        "simple": [{"provider": "ollama", "model": "llama3.1:8b", "base_url": base}],
        "medium": [{"provider": "ollama", "model": "qwen3:8b", "base_url": base}],
        "complex": [{"provider": "ollama", "model": "qwen3:8b", "base_url": base}],
    }


def _get_cache() -> LLMCache:
    global _cache_singleton
    if _cache_singleton is None:
        _cache_singleton = LLMCache(
            os.environ.get("REDIS_URL") or REDIS_URL_DEFAULT
        )
    return _cache_singleton


def _redis_cost_client() -> Any:
    global _redis_log
    if _redis_log is None:
        import redis

        url = os.environ.get("REDIS_URL") or REDIS_URL_DEFAULT
        _redis_log = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
    return _redis_log


def _estimate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COSTS_PER_1K_TOKENS.get(model, MODEL_COSTS_PER_1K_TOKENS["gpt-4o-mini"])
    return (input_tokens / 1000.0) * rates["input"] + (output_tokens / 1000.0) * rates["output"]


async def _ollama_available() -> bool:
    global _ollama_last_check, _ollama_last_ok
    now = time.time()
    if now - _ollama_last_check < _OLLAMA_CHECK_TTL:
        return _ollama_last_ok
    base = _ollama_base()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/api/tags")
            _ollama_last_ok = r.status_code == 200
    except (httpx.TimeoutException, httpx.ConnectError, OSError):
        _ollama_last_ok = False
    except Exception:
        _ollama_last_ok = False
    _ollama_last_check = now
    if not _ollama_last_ok:
        logger.warning("ollama_unavailable base=%s", base)
    return _ollama_last_ok


async def _call_ollama(
    model: str,
    prompt: str,
    base_url: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{base}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    return {
        "content": (data.get("response") or "").strip(),
        "input_tokens": int(data.get("prompt_eval_count") or 0),
        "output_tokens": int(data.get("eval_count") or 0),
    }


async def _call_openai_chat(
    model: str,
    user_prompt: str,
    system_prompt: str | None,
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
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    if inp == 0 and out == 0:
        est = max(1, len(user_prompt) // 4) + max(1, len(content) // 4)
        inp, out = est // 2, est - est // 2
    return {
        "content": content,
        "input_tokens": inp,
        "output_tokens": out,
    }


def _log_cost_sync(
    *,
    service: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    cached: bool,
    complexity: str,
    latency_ms: float,
) -> None:
    try:
        r = _redis_cost_client()
        payload = {
            "ts": time.time(),
            "service": service,
            "model": model,
            "provider": provider,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
            "cached": cached,
            "complexity": complexity,
            "latency_ms": round(latency_ms, 2),
        }
        r.lpush("llm:costs:log", json.dumps(payload, default=str))
        r.ltrim("llm:costs:log", 0, 9999)

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dk = f"llm:costs:daily:{day}"
        pipe = r.pipeline()
        pipe.hincrbyfloat(dk, "total_usd", cost_usd)
        pipe.hincrbyfloat(dk, f"{service}_usd", cost_usd)
        pipe.hincrbyfloat(dk, f"{model}_usd", cost_usd)
        if provider == "ollama":
            pipe.hincrby(dk, "ollama_calls", 1)
        else:
            pipe.hincrby(dk, "cloud_calls", 1)
        pipe.expire(dk, 86400 * 90)
        pipe.execute()

        total_today = float(r.hget(dk, "total_usd") or 0)
        if total_today >= DAILY_COST_ALERT_USD and cost_usd > 0:
            alert_key = f"llm:cost_alert_sent:{day}"
            if not r.get(alert_key):
                r.setex(alert_key, 86400, "1")
                body = json.dumps(
                    {
                        "day": day,
                        "total_usd": round(total_today, 2),
                        "service": service,
                        "last_model": model,
                    }
                )
                try:
                    r.publish(
                        "notifications:alerts",
                        json.dumps(
                            {
                                "title": "LLM cost alert",
                                "body": body,
                            }
                        ),
                    )
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("llm_cost_log_error: %s", exc)


async def _log_cost_async(**kwargs: Any) -> None:
    await asyncio.to_thread(_log_cost_sync, **kwargs)


def _incr_cache_hit_stat() -> None:
    try:
        _redis_cost_client().incr("llm:cache:hits")
    except Exception:
        pass


def _incr_cache_miss_stat() -> None:
    try:
        _redis_cost_client().incr("llm:cache:misses")
    except Exception:
        pass


def _combined_prompt(system_prompt: str | None, user_prompt: str) -> str:
    if system_prompt:
        return f"{system_prompt.strip()}\n\n{user_prompt.strip()}"
    return user_prompt.strip()


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
    """Route LLM request with cache and cost tracking.

    Returns:
        dict with keys: content, model, cached, cost_usd, provider (optional), error (optional)
    """
    complexity = (complexity or "medium").lower()
    if complexity not in ("simple", "medium", "complex"):
        complexity = "medium"

    mode = _router_mode()
    if mode == "cloud_only":
        routes = _cloud_only_routing().get(complexity, _cloud_only_routing()["medium"])
    elif mode == "local_only":
        routes = _local_only_routing().get(complexity, _local_only_routing()["medium"])
    else:
        routes = _build_routing_table().get(complexity, _build_routing_table()["medium"])

    ollama_up = await _ollama_available()
    if mode == "local_first" and not ollama_up:
        logger.warning("ollama_down_reroute_cloud complexity=%s", complexity)
        routes = _cloud_only_routing().get(
            complexity, _cloud_only_routing()["medium"]
        )

    cache = _get_cache()
    user_prompt = prompt
    sys_p = system_prompt or ""

    if cache_ttl > 0:
        for peek in routes:
            pm = peek.get("model", "")
            if not pm:
                continue
            hit = await asyncio.to_thread(
                lambda m=pm: cache.get(user_prompt, m, sys_p, record_stats=False)
            )
            if hit and hit.get("content") is not None:
                t0 = time.monotonic()
                lat = (time.monotonic() - t0) * 1000
                prov = hit.get("provider", peek.get("provider", "unknown"))
                await _log_cost_async(
                    service=service,
                    model=pm,
                    provider=prov,
                    input_tokens=int(hit.get("input_tokens") or 0),
                    output_tokens=int(hit.get("output_tokens") or 0),
                    cost_usd=0.0,
                    cached=True,
                    complexity=complexity,
                    latency_ms=lat,
                )
                await asyncio.to_thread(_incr_cache_hit_stat)
                return {
                    "content": hit["content"],
                    "model": pm,
                    "cached": True,
                    "cost_usd": 0.0,
                    "provider": prov,
                }
        await asyncio.to_thread(_incr_cache_miss_stat)

    for hop in routes:
        provider = hop.get("provider")
        model = hop.get("model", "")
        base_url = hop.get("base_url", _ollama_base())
        t0 = time.monotonic()

        try:
            if provider == "ollama":
                if mode == "local_first" and not ollama_up:
                    continue
                full = _combined_prompt(system_prompt, user_prompt)
                raw = await _call_ollama(model, full, base_url)
                content = raw["content"]
                inp, out = raw["input_tokens"], raw["output_tokens"]
                cost = 0.0
                prov = "ollama"
            elif provider == "openai":
                raw = await _call_openai_chat(
                    model,
                    user_prompt,
                    system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = raw["content"]
                inp, out = raw["input_tokens"], raw["output_tokens"]
                cost = _estimate_openai_cost(model, inp, out)
                prov = "openai"
            else:
                continue

            lat = (time.monotonic() - t0) * 1000
            payload = {
                "content": content,
                "model": model,
                "provider": prov,
                "input_tokens": inp,
                "output_tokens": out,
            }
            if cache_ttl > 0:
                await asyncio.to_thread(
                    cache.set, user_prompt, model, payload, cache_ttl, sys_p
                )

            await _log_cost_async(
                service=service,
                model=model,
                provider=prov,
                input_tokens=inp,
                output_tokens=out,
                cost_usd=cost,
                cached=False,
                complexity=complexity,
                latency_ms=lat,
            )
            await asyncio.to_thread(
                _incr_provider_counter, prov
            )
            return {
                "content": content,
                "model": model,
                "cached": False,
                "cost_usd": cost,
                "provider": prov,
            }
        except Exception as exc:
            logger.warning(
                "llm_route_hop_failed provider=%s model=%s error=%s",
                provider,
                model,
                str(exc)[:120],
            )
            continue

    if fallback == "error":
        raise RuntimeError("All LLM routes failed")
    if fallback == "skip":
        return {
            "content": "",
            "model": "",
            "cached": False,
            "cost_usd": 0.0,
            "error": "skipped",
        }
    return {
        "content": "",
        "model": "",
        "cached": False,
        "cost_usd": 0.0,
        "error": "all_routes_failed",
    }


def _incr_provider_counter(provider: str) -> None:
    try:
        r = _redis_cost_client()
        if provider == "ollama":
            r.incr("llm:stats:ollama_calls")
        else:
            r.incr("llm:stats:cloud_calls")
    except Exception:
        pass


def get_llm_cost_report() -> dict[str, Any]:
    """Build cost summary for GET /api/llm-costs (call via asyncio.to_thread from FastAPI)."""
    try:
        r = _redis_cost_client()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    hits = int(r.get("llm:cache:hits") or 0)
    misses = int(r.get("llm:cache:misses") or 0)
    total_hm = hits + misses
    hit_rate = round(100.0 * hits / total_hm, 2) if total_hm else 0.0

    ollama_calls = int(r.get("llm:stats:ollama_calls") or 0)
    cloud_calls = int(r.get("llm:stats:cloud_calls") or 0)
    oc_total = ollama_calls + cloud_calls
    local_pct = round(100.0 * ollama_calls / oc_total, 2) if oc_total else 0.0

    today_d = datetime.now(timezone.utc).date()

    def _sum_total_usd(days: int) -> float:
        total = 0.0
        for i in range(days):
            d = today_d - timedelta(days=i)
            key = f"llm:costs:daily:{d.isoformat()}"
            h = r.hgetall(key) or {}
            total += float(h.get("total_usd") or 0)
        return round(total, 4)

    today = _sum_total_usd(1)
    week = _sum_total_usd(7)
    month = _sum_total_usd(30)

    by_service: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for i in range(30):
        d = today_d - timedelta(days=i)
        key = f"llm:costs:daily:{d.isoformat()}"
        h = r.hgetall(key) or {}
        for field, val in h.items():
            if field in ("total_usd",) or field.endswith("_calls"):
                continue
            if not field.endswith("_usd"):
                continue
            name = field[:-4]
            amount = float(val)
            if name in MODEL_COSTS_PER_1K_TOKENS:
                by_model[name] = by_model.get(name, 0.0) + amount
            else:
                by_service[name] = by_service.get(name, 0.0) + amount

    week_avg = week / 7.0 if week else 0.0
    projected = round(week_avg * 30.0, 2)

    return {
        "ok": True,
        "today": {"total_usd": today},
        "this_week": {"total_usd": week},
        "this_month": {"total_usd": month},
        "cache_stats": {
            "hits": hits,
            "misses": misses,
            "hit_rate_pct": hit_rate,
        },
        "by_service": {k: round(v, 4) for k, v in sorted(by_service.items())},
        "by_model": {k: round(v, 4) for k, v in sorted(by_model.items())},
        "ollama_vs_cloud": {
            "ollama_calls": ollama_calls,
            "cloud_calls": cloud_calls,
            "local_pct": local_pct,
        },
        "projected_monthly_usd": projected,
    }
