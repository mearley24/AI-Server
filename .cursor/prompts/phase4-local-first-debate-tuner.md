# Phase 4 — Local-First Debate Engine + Parameter Tuner

**Priority:** Run after Phase 2+3 verified.
**Purpose:** Move debate engine and parameter tuner to Ollama (qwen3:32b on Betty). These are the last cloud-dependent LLM calls besides the OpenClaw conductor and Perplexity web search.

**Depends on:** Betty has `qwen3:32b` pulled. `.env` has `OLLAMA_HOST=http://192.168.1.199:11434`.

---

## Read First

- `polymarket-bot/src/debate_engine.py` — Bull/Bear/Judge debate via Anthropic Claude Sonnet. Uses `_call_claude()` with prompt caching.
- `polymarket-bot/heartbeat/parameter_tuner.py` — Strategy parameter tuning via Claude Sonnet 4.
- `polymarket-bot/knowledge/ollama_local.py` — shared Ollama helper created in Phase 3 (reuse this).
- `polymarket-bot/strategies/llm_completion.py` — shared LLM completion helper created in Phase 3 (reuse this if applicable).

---

## 4a. Debate Engine — Ollama First, Claude Fallback

**File:** `polymarket-bot/src/debate_engine.py`

### What to change

The debate engine calls `_call_claude()` three times per debate: bull, bear, judge. Each call sends a system prompt + trade context to Claude Sonnet and gets a ~300 token response.

**Add an `_call_ollama()` method** that mirrors `_call_claude()` but uses Betty's Ollama:

```python
    async def _call_ollama(self, system_prompt: str, user_message: str) -> str | None:
        """Try Ollama (local, free). Returns None on failure."""
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if not ollama_host:
            return None
        model = os.environ.get("OLLAMA_DEBATE_MODEL", "qwen3:32b")
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 400},
            }
            resp = await self._http.post(
                f"{ollama_host.rstrip('/')}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120,  # 32B model may be slower
            )
            if resp.status_code != 200:
                logger.info("debate_ollama_error", status=resp.status_code)
                return None
            content = resp.json().get("message", {}).get("content", "")
            if content:
                logger.info("debate_ollama_success", model=model, chars=len(content))
                return content
        except Exception as e:
            logger.info("debate_ollama_failed", error=str(e)[:100])
        return None
```

**Modify `_call_claude()`** to try Ollama first:

Rename the existing `_call_claude` to `_call_claude_direct`, then create a new `_call_claude` that wraps both:

```python
    async def _call_claude(self, system_prompt: str, user_message: str) -> str:
        """LLM call: Ollama first, Claude fallback."""
        # Try local first
        result = await self._call_ollama(system_prompt, user_message)
        if result:
            return result

        # Fallback to Claude
        if not self._api_key:
            logger.warning("debate_no_llm_available — Ollama down and no ANTHROPIC_API_KEY")
            return ""
        logger.warning("debate_using_claude — Ollama was unavailable")
        return await self._call_claude_direct(system_prompt, user_message)

    async def _call_claude_direct(self, system_prompt: str, user_message: str) -> str:
        """Direct Claude API call (paid fallback)."""
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": 300,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_message}],
        }
        resp = await self._http.post(ANTHROPIC_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]
        return ""
```

**Also update `enabled` property** — the debate engine currently requires `self._api_key` to be set. With Ollama, it should work even without an Anthropic key:

```python
    @property
    def enabled(self) -> bool:
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        return self._enabled and (bool(self._api_key) or bool(ollama_host))
```

**Do NOT change:** The prompts (BULL_SYSTEM_PROMPT, BEAR_SYSTEM_PROMPT, JUDGE_SYSTEM_PROMPT), the debate flow, `_build_context()`, `_parse_judge_response()`, `should_execute()`, or any scoring logic.

---

## 4b. Parameter Tuner — Ollama First, Claude Fallback

**File:** `polymarket-bot/heartbeat/parameter_tuner.py`

### What to change

The `analyze()` method builds a prompt from strategy reviews and calls Claude Sonnet 4. Replace the API call with Ollama-first:

```python
    async def analyze(self, strategy_reviews: list[dict]) -> list[dict]:
        """Analyze strategy performance and suggest parameter adjustments.

        Uses Ollama (local, free) first, falls back to Claude Sonnet.
        """
        if not strategy_reviews:
            return []

        # ... existing prompt building code stays the same ...

        # Try Ollama first
        suggestions = await self._analyze_ollama(prompt)
        if suggestions is not None:
            return suggestions

        # Fallback to Claude
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info("parameter_tuner_skipped", reason="no Ollama and no ANTHROPIC_API_KEY")
            return []

        logger.warning("parameter_tuner_using_claude — Ollama was unavailable")
        return await self._analyze_claude(prompt, api_key)

    async def _analyze_ollama(self, prompt: str) -> list[dict] | None:
        """Try parameter analysis via Ollama. Returns None on failure."""
        ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
        if not ollama_host:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=120) as http:
                resp = await http.post(
                    f"{ollama_host.rstrip('/')}/api/chat",
                    json={
                        "model": os.environ.get("OLLAMA_DEBATE_MODEL", "qwen3:32b"),
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.3, "num_predict": 1000},
                    },
                )
                if resp.status_code != 200:
                    return None
                content = resp.json().get("message", {}).get("content", "")
                if not content:
                    return None

                # Parse JSON (handle markdown fences)
                if content.startswith("```"):
                    lines = content.split("\n")
                    lines = [l for l in lines if not l.startswith("```")]
                    content = "\n".join(lines).strip()

                data = json.loads(content)
                suggestions = data if isinstance(data, list) else data.get("suggestions", [])
                logger.info("parameter_tuner_ollama_success", suggestions=len(suggestions))
                return suggestions
        except Exception as e:
            logger.info("parameter_tuner_ollama_failed", error=str(e)[:100])
            return None

    async def _analyze_claude(self, prompt: str, api_key: str) -> list[dict]:
        """Fallback: parameter analysis via Claude (paid)."""
        # Move the existing Claude API call code here unchanged
        ...
```

Move the existing Claude API call block (the `async with httpx.AsyncClient` section currently in `analyze()`) into `_analyze_claude()`. Keep the prompt building and response parsing identical.

---

## 4c. Environment Variables

**Add to `.env.example`:**
```bash
# Debate engine / parameter tuner model (larger model for reasoning tasks)
# OLLAMA_DEBATE_MODEL=qwen3:32b  # defaults to qwen3:32b, needs ~20GB RAM on Betty
```

**Add `OLLAMA_HOST` to polymarket-bot in `docker-compose.yml`** if not already there:
```yaml
polymarket-bot:
  environment:
    - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
```

This should already be set from Phase 3 changes — verify.

---

## After All Changes

```bash
# Rebuild
docker compose up -d --build polymarket-bot

# Verify env
docker exec polymarket-bot printenv OLLAMA_HOST
# Expected: http://192.168.1.199:11434

# Syntax checks
python3 -m py_compile polymarket-bot/src/debate_engine.py
python3 -m py_compile polymarket-bot/heartbeat/parameter_tuner.py

# Check that Ollama has qwen3:32b
curl -s http://192.168.1.199:11434/api/tags | python3 -c "
import sys, json
models = [m['name'] for m in json.load(sys.stdin)['models']]
print('Models:', [m for m in models if '32b' in m or 'qwen' in m])
assert any('32b' in m for m in models), 'qwen3:32b not found on Betty!'
print('32B model available')
"

# Monitor first debate (may take a few minutes for a trade to trigger)
docker logs polymarket-bot --since 5m 2>&1 | grep -i "debate_ollama\|debate_using_claude\|parameter_tuner_ollama"
```

---

## Phase 4 Gate

**DONE when:**
- `py_compile` passes on debate_engine.py and parameter_tuner.py
- Betty has qwen3:32b available
- First debate runs via Ollama (log: `debate_ollama_success`)
- Parameter tuner runs via Ollama (log: `parameter_tuner_ollama_success`)
- No degradation in debate quality (monitor for 24 hours — if verdicts seem wrong, check judge responses)
- `bash scripts/verify-readonly.sh` still all PASS

---

## Rollback Plan

If debate quality degrades with qwen3:32b:
1. Set `OLLAMA_DEBATE_MODEL=qwen3:8b` — faster but lower quality
2. Or set `OLLAMA_HOST=` (empty) in .env to force Claude fallback
3. Or revert just the debate_engine.py changes

The fallback chain means nothing breaks — worst case you're back on Claude temporarily.

---

## Rules

- **Read before writing.** Every file must be read before editing.
- **Config change = rebuild.** `docker compose up -d --build polymarket-bot`.
- **No secrets in code.** Anthropic API key from env only.
- **Local first, cloud fallback.** Every Claude call must try Ollama first with WARNING on fallback.
- **Don't touch prompts or scoring.** Only change the LLM transport layer. Bull/Bear/Judge prompts, `_parse_judge_response()`, and all scoring logic stay exactly as-is.
- **Timeout: 120s for 32B model.** Betty's Intel i3 runs 32B at ~5 tok/s. A 400-token response takes ~80 seconds.
