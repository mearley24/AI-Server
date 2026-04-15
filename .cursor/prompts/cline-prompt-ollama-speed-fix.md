## Ollama Speed Fix -- Faster Model + Configurable Timeout

You are working on ~/AI-Server on Bob.

### Problem

Maestro (2019 iMac, quad-core i3, 64GB RAM, CPU-only) runs Ollama but `qwen3:8b` takes 170-340 seconds per response, causing timeouts. All autobuilder questions fall back to OpenAI gpt-4o-mini ($).

### Solution

1. Pull a fast 3B model on Maestro
2. Make the model and timeout configurable via env vars
3. Bump default timeout to 120s
4. Disable qwen3 thinking mode (adds overhead)

### Step 1 -- Pull a fast model on Maestro

```zsh
curl -s http://192.168.1.199:11434/api/pull -d '{"name": "llama3.2:3b"}' | tail -1
```

Wait for it to complete. Verify:

```zsh
curl -s http://192.168.1.199:11434/api/tags | python3 -c "import sys,json; [print(f\"  {m['name']} ({m['details']['parameter_size']})\" ) for m in json.load(sys.stdin)['models']]"
```

### Step 2 -- Make autobuilder model and timeout configurable

Edit `integrations/cortex_autobuilder/daemon.py`:

At the top where env vars are read, add:

```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
```

In the `_call_ollama_local` function, replace:
- The hardcoded `"model": "qwen3:8b"` with `"model": OLLAMA_MODEL`
- The hardcoded `timeout=60.0` with `timeout=float(OLLAMA_TIMEOUT)`
- Add `"think": false` to the options dict to disable thinking mode (qwen3 feature that adds overhead)

The function should look like:

```python
async def _call_ollama_local(prompt: str) -> str:
    """Process text through local Ollama -- free, always preferred.
    Falls back to OpenAI if Ollama is unreachable."""
    try:
        async with _httpx.AsyncClient(timeout=float(OLLAMA_TIMEOUT)) as client:
            r = await client.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 512},
                    "think": False,
                },
            )
            r.raise_for_status()
            return (r.json().get("response") or "").strip()
    except Exception as exc:
        logger.warning("scanner_ollama_error model=%s error=%s -- trying OpenAI fallback", OLLAMA_MODEL, str(exc)[:100])
        return await _call_openai_fallback(prompt)
```

Key changes:
- `num_predict` reduced from 1024 to 512 (JSON extraction doesn't need 1024 tokens, this halves generation time)
- `think: false` added (prevents qwen3 from using chain-of-thought mode)
- Timeout now reads from env var (default 120s)
- Model now reads from env var (default llama3.2:3b)

### Step 3 -- Update docker-compose.yml

Add the new env vars to cortex-autobuilder service:

```yaml
      - OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:3b}
      - OLLAMA_TIMEOUT=${OLLAMA_TIMEOUT:-120}
```

Also add to the cortex service if it has similar Ollama calls.

### Step 4 -- Also fix notes_indexer.py

In `integrations/apple_notes/notes_indexer.py`, the `OLLAMA_MODEL` is set to `llama3.1:8b` which is also too slow. Change the default:

```python
OLLAMA_MODEL = os.environ.get("NOTES_INDEXER_OLLAMA_MODEL", "llama3.2:3b")
```

### Step 5 -- Rebuild and test

```zsh
docker compose build cortex-autobuilder
docker compose up -d --no-deps cortex-autobuilder
sleep 30
docker logs cortex-autobuilder --tail 30 --since 1m
```

Check for:
- `scanner_querying` lines (Perplexity is fetching)
- `scanner_ollama_error` lines -- if still timing out even with llama3.2:3b and 120s, the fallback to gpt-4o-mini will handle it
- No `scanner_ollama_error` lines = Ollama is fast enough now

### Step 6 -- Benchmark the model (quick sanity check)

```zsh
time curl -s http://192.168.1.199:11434/api/generate -d '{
  "model": "llama3.2:3b",
  "prompt": "Extract insights as JSON array: AI startup funding reached $100B in 2025",
  "stream": false,
  "options": {"num_predict": 256, "temperature": 0.1}
}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Tokens: {d.get('eval_count',0)}, Time: {d.get('eval_duration',0)/1e9:.1f}s, Speed: {d.get('eval_count',0)/(d.get('eval_duration',1)/1e9):.1f} tok/s\")"
```

Report the speed. If under 5 tok/s, we may need an even smaller model or just accept the OpenAI fallback.

### Output

Report:
- Models available on Maestro after pull
- Benchmark speed for llama3.2:3b on Maestro
- Whether autobuilder successfully uses Ollama now or still falls back
- Any errors

Commit and push:

```zsh
git add -A && git commit -m "fix: configurable Ollama model/timeout, default llama3.2:3b, disable thinking mode" && git push
```
