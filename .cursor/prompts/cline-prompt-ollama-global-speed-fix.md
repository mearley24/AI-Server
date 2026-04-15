## Ollama Global Speed Fix — Switch ALL Services to llama3.2:3b + 120s Timeout

You are working on ~/AI-Server on Bob (Mac Mini M4).

### Problem

Maestro (2019 iMac, CPU-only i3) runs Ollama. Every service defaults to `qwen3:8b` or `qwen3:32b`, which take 170-340 seconds on Maestro's CPU — always timing out. This causes:
- Every Ollama call falls back to OpenAI gpt-4o-mini (costs money)
- `qwen3:32b` (debate engine) is completely unusable on Maestro
- `llama3.1:8b` also too slow (~100s+ per response)
- We're bleeding OpenAI credits 24/7 for tasks that should be free

### Solution

1. Pull `llama3.2:3b` on Maestro (if not already there)
2. Switch ALL model defaults from `qwen3:8b` / `qwen3:32b` / `llama3.1:8b` to `llama3.2:3b`
3. Bump all Ollama timeouts to 120s
4. Disable thinking mode where applicable
5. Reduce `num_predict` to 512 where it's 1024+ (JSON extraction doesn't need long outputs)
6. Rebuild affected containers

Bob only has `llama3.2:3b` locally. Maestro has `qwen3:32b`, `qwen3:8b`, `llama3.1:8b` — all too slow. We need `llama3.2:3b` on Maestro too.

---

### Step 1 — Pull llama3.2:3b on Maestro

```zsh
curl -s http://192.168.1.199:11434/api/pull -d '{"name": "llama3.2:3b"}' | tail -1
```

Wait for completion. Verify all models:

```zsh
curl -s http://192.168.1.199:11434/api/tags | python3 -c "import sys,json; [print(f'  {m[\"name\"]} ({m[\"details\"][\"parameter_size\"]})') for m in json.load(sys.stdin)['models']]"
```

Benchmark it:

```zsh
time curl -s http://192.168.1.199:11434/api/generate -d '{
  "model": "llama3.2:3b",
  "prompt": "Extract insights as JSON array: AI startup funding reached $100B in 2025",
  "stream": false,
  "options": {"num_predict": 256, "temperature": 0.1}
}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Tokens: {d.get('eval_count',0)}, Time: {d.get('eval_duration',0)/1e9:.1f}s, Speed: {d.get('eval_count',0)/(d.get('eval_duration',1)/1e9):.1f} tok/s\")"
```

Record the speed in your commit message.

---

### Step 2 — Fix docker-compose.yml defaults

Change ALL `qwen3:8b` and `qwen3:32b` defaults to `llama3.2:3b`:

**Line 89** (polymarket-bot): `OLLAMA_KNOWLEDGE_MODEL=${OLLAMA_KNOWLEDGE_MODEL:-qwen3:8b}` → `OLLAMA_KNOWLEDGE_MODEL=${OLLAMA_KNOWLEDGE_MODEL:-llama3.2:3b}`

**Line 90** (polymarket-bot): `OLLAMA_VALIDATE_MODEL=${OLLAMA_VALIDATE_MODEL:-qwen3:8b}` → `OLLAMA_VALIDATE_MODEL=${OLLAMA_VALIDATE_MODEL:-llama3.2:3b}`

**Line 91** (polymarket-bot): `OLLAMA_DEBATE_MODEL=${OLLAMA_DEBATE_MODEL:-qwen3:32b}` → `OLLAMA_DEBATE_MODEL=${OLLAMA_DEBATE_MODEL:-llama3.2:3b}`

**Line 262** (calendar-agent): `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}` → `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-llama3.2:3b}`

**Line 389** (openclaw): `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}` → `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-llama3.2:3b}`

**Line 511** (x-intake): `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}` → `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-llama3.2:3b}`

**Line 666** (x-intake-lab): `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}` → `OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-llama3.2:3b}`

Also **add** these two new env vars to the `cortex-autobuilder` service (after the existing `OLLAMA_HOST` line around line 628):

```yaml
      - OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:3b}
      - OLLAMA_TIMEOUT=${OLLAMA_TIMEOUT:-120}
```

And add `OLLAMA_MODEL` to the `cortex` service (after `OLLAMA_HOST` around line 448):

```yaml
      - OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.2:3b}
```

---

### Step 3 — Fix integrations/cortex_autobuilder/daemon.py

This is the autobuilder scanner. It hardcodes `qwen3:8b` with a 60s timeout.

**Near the top** (around line 20-30, where other env vars are read), add:

```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
```

**In the `_call_ollama_local` function** (around line 215-235), replace the entire function body:

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

Key changes: model from env var, timeout from env var, `num_predict` 1024→512, `think: False` added.

---

### Step 4 — Fix cortex/config.py

**Line 26**: Change `"qwen3:8b"` to `"llama3.2:3b"`:

```python
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
```

---

### Step 5 — Fix openclaw/llm_router.py

**Line 28-29** — Update cost map:
```python
    "llama3.2:3b": {"input": 0.0, "output": 0.0},
```
(Remove or keep `llama3.1:8b` and `qwen3:8b` entries — they're still free, just add `llama3.2:3b`.)

**Line 54**: Change `"llama3.1:8b"` to `"llama3.2:3b"`
**Line 57**: Change `"qwen3:8b"` to `"llama3.2:3b"`
**Lines 79-81** (local_first routes): Change all three to `"llama3.2:3b"`:
```python
        "simple": [{"provider": "ollama", "model": "llama3.2:3b", "base_url": base}],
        "medium": [{"provider": "ollama", "model": "llama3.2:3b", "base_url": base}],
        "complex": [{"provider": "ollama", "model": "llama3.2:3b", "base_url": base}],
```

---

### Step 6 — Fix openclaw/main.py

**Line 581**: Change `"model": "qwen3:8b"` to `"model": os.getenv("OLLAMA_ANALYSIS_MODEL", "llama3.2:3b")`

Also on the same Ollama call, find the timeout and bump it to 120 if it's lower.

---

### Step 7 — Fix openclaw/client_tracker.py

**Line 38**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`:
```python
"model": os.getenv("OLLAMA_ANALYSIS_MODEL", "llama3.2:3b"),
```

---

### Step 8 — Fix integrations/x_intake/ (3 files)

**integrations/x_intake/main.py**:
- **Line 210**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`
- **Line 495**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`
- **Lines 231 and 511**: Bump Ollama timeouts from `timeout=60` to `timeout=120`

**integrations/x_intake/transcript_analyst.py**:
- **Line 41**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`

**integrations/x_intake/video_transcriber.py**:
- **Line 40**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`

---

### Step 9 — Fix knowledge-scanner/processor.py

**Line 65**: Change `"model": "qwen3:8b"` to `"model": os.getenv("OLLAMA_ANALYSIS_MODEL", "llama3.2:3b")`

Also check the timeout on that call (line 60, `timeout=60`) — bump to `timeout=120`.

---

### Step 10 — Fix calendar-agent/api.py

**Line 28**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`

Also check timeout — bump to 120 if it's 60.

---

### Step 11 — Fix polymarket-bot files (5 files)

**polymarket-bot/knowledge/ollama_local.py**:
- **Line 17**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`

**polymarket-bot/strategies/llm_completion.py**:
- **Line 47**: Change `model = "qwen3:8b"` to `model = os.getenv("OLLAMA_KNOWLEDGE_MODEL", "llama3.2:3b")`
- (add `import os` at top if not already there)

**polymarket-bot/strategies/presolution_scalp.py**:
- **Line 24**: Change fallback from `"qwen3:8b"` to `"llama3.2:3b"`

**polymarket-bot/strategies/sentiment_engine.py**:
- **Line 107**: Change default from `"llama3.1:8b"` to `"llama3.2:3b"`

**polymarket-bot/src/debate_engine.py**:
- **Line 184**: Change default from `"qwen3:32b"` to `"llama3.2:3b"`
- **Line 249**: Change default from `"qwen3:32b"` to `"llama3.2:3b"`

**polymarket-bot/heartbeat/parameter_tuner.py**:
- **Line 95**: Change default from `"qwen3:32b"` to `"llama3.2:3b"`

---

### Step 12 — Fix scripts/imessage-server.py

**Line 83**: Change default from `"qwen3:8b"` to `"llama3.2:3b"`:
```python
def _ollama_completion(prompt: str, model: str = "llama3.2:3b") -> Optional[str]:
```

Also bump the timeout on line 94 from `timeout=60` to `timeout=120`.

---

### Step 13 — Fix integrations/apple_notes/notes_indexer.py

**Line 49**: Change default from `"llama3.1:8b"` to `"llama3.2:3b"`:
```python
OLLAMA_MODEL = os.environ.get("NOTES_INDEXER_OLLAMA_MODEL", "llama3.2:3b")
```

---

### Step 14 — Rebuild and restart ALL affected containers

```zsh
docker compose build polymarket-bot calendar-agent openclaw cortex cortex-autobuilder x-intake knowledge-scanner
docker compose up -d --no-deps polymarket-bot calendar-agent openclaw cortex cortex-autobuilder x-intake knowledge-scanner
```

Wait 60 seconds, then check health:

```zsh
sleep 60
docker ps --format "table {{.Names}}\t{{.Status}}" | sort
```

All containers should show `Up` and `(healthy)` where applicable.

---

### Step 15 — Verify Ollama is being used (not just OpenAI fallback)

Check autobuilder logs for Ollama success:

```zsh
docker logs cortex-autobuilder --tail 50 --since 5m 2>&1 | grep -E "ollama|scanner_"
```

Check x-intake:

```zsh
docker logs x-intake --tail 50 --since 5m 2>&1 | grep -i "ollama"
```

Check polymarket-bot:

```zsh
docker logs polymarket-bot --tail 50 --since 5m 2>&1 | grep -i "ollama\|debate\|sentiment"
```

If you see `scanner_ollama_error` lines, note the error — if it's a timeout even at 120s, that's expected for Maestro (the fallback handles it). But ideally with `llama3.2:3b` and 120s, most calls should succeed.

---

### Step 16 — Update tests/test_llm_router.py

**Line 77**: Change expected model from `"llama3.1:8b"` to `"llama3.2:3b"`.

Run the test to make sure it passes:

```zsh
cd ~/AI-Server && python3 -m pytest tests/test_llm_router.py -v 2>&1 | tail -20
```

---

### Output

Commit and push:

```zsh
cd ~/AI-Server
bash scripts/pull.sh
git add -A
git commit -m "fix: global Ollama speed fix — all services default to llama3.2:3b, 120s timeout, disable thinking

- Switched 20+ hardcoded qwen3:8b/qwen3:32b/llama3.1:8b defaults to llama3.2:3b
- Bumped Ollama timeouts from 60s to 120s across all services
- Added OLLAMA_MODEL and OLLAMA_TIMEOUT env vars to cortex-autobuilder
- Reduced num_predict to 512 in autobuilder (JSON extraction)
- Disabled thinking mode (think: false) in autobuilder
- Rebuilt: polymarket-bot, calendar-agent, openclaw, cortex, cortex-autobuilder, x-intake, knowledge-scanner
- Maestro benchmark: [FILL IN tok/s for llama3.2:3b]"
git push
```

Report:
1. Maestro benchmark speed for llama3.2:3b
2. Which containers rebuilt successfully
3. Whether Ollama calls are succeeding now (or still falling back)
4. Any errors encountered
