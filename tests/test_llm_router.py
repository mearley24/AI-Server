"""Tests for openclaw LLM router (Auto-23)."""

from __future__ import annotations

import importlib
import os
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "openclaw"))

llm_router = importlib.import_module("llm_router")


def _reset_router_globals() -> None:
    llm_router._cache_singleton = None
    llm_router._redis_log = None
    llm_router._ollama_last_check = 0.0
    llm_router._ollama_last_ok = False


class LLMRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _reset_router_globals()

    async def test_complex_routes_openai(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_ROUTER_MODE": "cloud_only", "OPENAI_API_KEY": "sk-test"},
            clear=False,
        ):
            with patch.object(
                llm_router, "_call_openai_chat", new_callable=AsyncMock
            ) as m_openai:
                m_openai.return_value = {
                    "content": '{"ok": true}',
                    "input_tokens": 100,
                    "output_tokens": 50,
                }
                with patch.object(llm_router, "_log_cost_async", new_callable=AsyncMock):
                    with patch.object(llm_router, "_incr_provider_counter"):
                        r = await llm_router.completion(
                            prompt="reason deeply",
                            complexity="complex",
                            cache_ttl=0,
                            service="test",
                        )
        self.assertEqual(r["model"], "gpt-4o")
        self.assertFalse(r["cached"])
        m_openai.assert_awaited()

    async def test_simple_ollama_when_up(self) -> None:
        with patch.dict(os.environ, {"LLM_ROUTER_MODE": "local_first"}, clear=False):
            with patch.object(
                llm_router, "_ollama_available", new_callable=AsyncMock, return_value=True
            ):
                with patch.object(
                    llm_router, "_call_ollama", new_callable=AsyncMock
                ) as m_ol:
                    m_ol.return_value = {
                        "content": "yes",
                        "input_tokens": 5,
                        "output_tokens": 2,
                    }
                    with patch.object(llm_router, "_log_cost_async", new_callable=AsyncMock):
                        with patch.object(llm_router, "_incr_provider_counter"):
                            r = await llm_router.completion(
                                prompt="classify: spam?",
                                complexity="simple",
                                cache_ttl=0,
                                service="test",
                            )
        self.assertEqual(r["model"], "llama3.1:8b")
        self.assertEqual(r["provider"], "ollama")
        m_ol.assert_awaited()

    async def test_ollama_down_falls_back_openai(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_ROUTER_MODE": "local_first", "OPENAI_API_KEY": "sk-x"},
            clear=False,
        ):
            with patch.object(
                llm_router, "_ollama_available", new_callable=AsyncMock, return_value=False
            ):
                with patch.object(
                    llm_router, "_call_openai_chat", new_callable=AsyncMock
                ) as m_openai:
                    m_openai.return_value = {
                        "content": "fallback",
                        "input_tokens": 10,
                        "output_tokens": 10,
                    }
                    with patch.object(llm_router, "_log_cost_async", new_callable=AsyncMock):
                        with patch.object(llm_router, "_incr_provider_counter"):
                            r = await llm_router.completion(
                                prompt="hello",
                                complexity="simple",
                                cache_ttl=0,
                                service="test",
                            )
        self.assertIn(r["model"], ("gpt-4o-mini", "gpt-4o"))
        m_openai.assert_awaited()

    async def test_cache_hit_skips_api(self) -> None:
        fake_cache = MagicMock()
        fake_cache.get.return_value = {
            "content": "from cache",
            "provider": "ollama",
            "input_tokens": 1,
            "output_tokens": 1,
        }
        fake_cache.set = MagicMock()
        with patch.object(llm_router, "_get_cache", return_value=fake_cache):
            with patch.object(llm_router, "_ollama_available", new_callable=AsyncMock, return_value=True):
                with patch.object(llm_router, "_call_ollama", new_callable=AsyncMock) as m_ol:
                    with patch.object(llm_router, "_call_openai_chat", new_callable=AsyncMock) as m_openai:
                        with patch.object(llm_router, "_log_cost_async", new_callable=AsyncMock):
                            with patch.object(llm_router, "_incr_cache_hit_stat"):
                                with patch.object(llm_router, "_incr_cache_miss_stat"):
                                    r = await llm_router.completion(
                                        prompt="same prompt",
                                        complexity="medium",
                                        cache_ttl=300,
                                        service="test",
                                    )
        self.assertTrue(r["cached"])
        self.assertEqual(r["content"], "from cache")
        m_ol.assert_not_called()
        m_openai.assert_not_called()

    def test_cost_log_updates_daily_hash(self) -> None:
        r = MagicMock()
        r.lpush = MagicMock()
        r.ltrim = MagicMock()
        r.hget = MagicMock(return_value="0")
        r.get = MagicMock(return_value=None)
        pipe = MagicMock()
        r.pipeline = MagicMock(return_value=pipe)
        pipe.hincrbyfloat = MagicMock(return_value=pipe)
        pipe.hincrby = MagicMock(return_value=pipe)
        pipe.expire = MagicMock(return_value=pipe)
        pipe.execute = MagicMock()
        with patch.object(llm_router, "_redis_cost_client", return_value=r):
            llm_router._log_cost_sync(
                service="unit",
                model="gpt-4o-mini",
                provider="openai",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=0.01,
                cached=False,
                complexity="medium",
                latency_ms=50.0,
            )
        pipe.hincrbyfloat.assert_called()
        r.lpush.assert_called()
        self.assertIn("llm:costs:log", r.lpush.call_args[0][0])


class CostReportTests(unittest.TestCase):
    def test_get_llm_cost_report_structure(self) -> None:
        r = MagicMock()
        r.get.side_effect = lambda k, default=None: {
            "llm:cache:hits": "10",
            "llm:cache:misses": "10",
            "llm:stats:ollama_calls": "4",
            "llm:stats:cloud_calls": "6",
        }.get(k, default)
        r.hgetall.return_value = {"total_usd": "1.5", "gpt-4o-mini_usd": "1.5"}
        _reset_router_globals()
        with patch.object(llm_router, "_redis_cost_client", return_value=r):
            out = llm_router.get_llm_cost_report()
        self.assertTrue(out.get("ok"))
        self.assertIn("cache_stats", out)
        self.assertEqual(out["cache_stats"]["hit_rate_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
