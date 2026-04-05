# Local-First Migration — Phased Plan

**Goal:** Move all LLM calls that don't require cloud-grade reasoning to Ollama on Betty (192.168.1.199:11434, 64GB iMac). Reduce cloud API spend, remove rate limits, keep data on-LAN, and unlock continuous learning for the neural map.

**Architecture:** Bob (Mac Mini M4) runs Docker services. Betty (iMac 64GB) runs Ollama with qwen3:8b and llama3.1:8b. All services call Ollama over LAN. Cloud APIs become fallback-only.

**Rule for every phase:** Local first, cloud fallback. Never break the fallback chain. If Ollama is down, everything must still work via cloud APIs — just with a WARNING log.

---

## Phase 1 — Foundation: LLM Router + X Intake + iMessage Bridge

**Why first:** The LLM router is already built with local_first mode. X intake and iMessage bridge are the simplest standalone services — no downstream dependencies. This phase proves the Ollama integration pattern that all later phases copy.

### 1a. Verify Ollama connectivity from all networks

**Files:** None — this is infrastructure verification only.

**Steps:**
1. From Bob host: `curl -sf http://192.168.1.199:11434/api/tags`
2. From bridge-network containers (openclaw, email-monitor): `docker exec openclaw curl -sf http://192.168.1.199:11434/api/tags`
3. From VPN-network containers (polymarket-bot): `docker exec polymarket-bot curl -sf http://192.168.1.199:11434/api/tags`

If bridge-network containers can't reach Betty, add to docker-compose.yml for each service that needs Ollama:
```yaml
extra_hosts:
  - "betty:192.168.1.199"
```
And use `http://betty:11434` as `OLLAMA_HOST`.

**Gate:** All three network paths return model list. Do not proceed until this works.

### 1b. Install mlx-whisper on Bob

**Steps:**
```bash
cd ~/AI-Server
source .venv/bin/activate
pip install mlx-whisper
python3 -c "import mlx_whisper; print('OK')"
deactivate
```

**Gate:** `import mlx_whisper` succeeds in the venv.

### 1c. Migrate X Intake video_transcriber.py

**Files:** `integrations/x_intake/video_transcriber.py`

**Exact changes (already implemented by Cursor — verify these are present):**

1. **Environment variables at top of file:**
   - `WHISPER_MODEL` from env (default `base`)
   - `OLLAMA_HOST` from env (default `http://192.168.1.199:11434`)
   - `OLLAMA_ANALYSIS_MODEL` from env (default `qwen3:8b`) — matches llm_router defaults

2. **`transcribe_audio()` — local-first chain:**
   - whisper.cpp CLI → mlx-whisper → Python openai-whisper → OpenAI Whisper API
   - Each step tries and falls through silently on ImportError/missing binary
   - OpenAI API step logs `logger.warning("using_openai_whisper_api — install local whisper to avoid cloud costs")`

3. **`analyze_transcript()` — Ollama first:**
   - `_ollama_chat()` helper using urllib `POST {OLLAMA_HOST}/api/chat`
   - `_parse_json_maybe()` to handle fenced JSON blocks (```json ... ```) from Ollama responses
   - `_build_analysis_prompt()` shared between Ollama and OpenAI paths
   - Falls back to GPT-4o-mini with `logger.warning("using_openai_for_analysis — Ollama was unavailable")`

4. **`analyze_images()` — stays cloud but warns:**
   - `logger.warning("using_openai_vision — no local alternative available for image analysis")` before the GPT-4o vision call

5. **Module docstring** updated to describe local-first behavior

**Docker compose changes for x-intake service:**
Add to `docker-compose.yml` under x-intake environment:
```yaml
- OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
- OLLAMA_ANALYSIS_MODEL=${OLLAMA_ANALYSIS_MODEL:-qwen3:8b}
- WHISPER_MODEL=${WHISPER_MODEL:-base}
```
This lets the Docker container reach Ollama on Betty for video analysis.

**Gate test:**
```bash
# Rebuild
docker compose up -d --build x-intake

# Syntax check
python3 -m py_compile integrations/x_intake/video_transcriber.py

# Test analyze endpoint — check logs for "ollama" not "openai"
curl -s -X POST http://127.0.0.1:8101/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/test/status/1"}'
docker logs x-intake --tail 10 2>&1 | grep -i "ollama\|openai\|whisper"
```

**Success:** Logs show `ollama_chat_success` or `mlx_whisper_success`, NOT `using_openai_for_analysis`.

### 1d. Migrate iMessage bridge research_link()

**Files:** `scripts/imessage-server.py`

**Exact changes (already implemented by Cursor — verify these are present):**

1. **Shebang** changed to: `#!/Users/bob/AI-Server/.venv/bin/python3`
2. **`from typing import Optional`** added to imports
3. **`OLLAMA_HOST`** read from env (default `http://192.168.1.199:11434`)
4. **`_ollama_completion(prompt, model="qwen3:8b")`** helper — POST to `{OLLAMA_HOST}/api/chat`
5. **`research_link()`** tries Ollama first, then OpenAI. No-key error message updated to:
   `"Can't analyze — Ollama is down and no OpenAI API key."`

**Gate test:**
```bash
# Syntax check
python3 -m py_compile scripts/imessage-server.py

# Restart bridge with venv Python
pkill -f imessage-server.py; sleep 2
nohup /Users/bob/AI-Server/.venv/bin/python3 ~/AI-Server/scripts/imessage-server.py &

# Send yourself an X link via iMessage — should get analysis without OpenAI calls
```

**Success:** Link analysis returns via Ollama. OpenAI not called.

### 1e. Update .env.example

Add/verify these entries:
```bash
# LLM Routing (local-first via Ollama on Betty/Maestro)
LLM_ROUTER_MODE=local_first
OLLAMA_HOST=http://192.168.1.199:11434
# OLLAMA_ANALYSIS_MODEL=qwen3:8b  # optional override, defaults to qwen3:8b

# Local Whisper transcription (no cloud API needed)
WHISPER_MODEL=base  # base, small, medium, large-v3
```

### 1f. Host setup on Bob

```bash
# Install local whisper into venv (PEP 668 safe)
cd ~/AI-Server
source .venv/bin/activate
pip install mlx-whisper
# Optional broader fallback:
pip install openai-whisper
deactivate

# Rebuild x-intake container
docker compose up -d --build x-intake

# Restart iMessage bridge (picks up new shebang + Ollama path)
pkill -f imessage-server.py; sleep 2
nohup /Users/bob/AI-Server/.venv/bin/python3 ~/AI-Server/scripts/imessage-server.py &
```

### Phase 1 hardening

After 1a–1f all pass:
```bash
# Full verify
bash scripts/verify-readonly.sh

# Syntax checks
python3 -m py_compile integrations/x_intake/video_transcriber.py
python3 -m py_compile scripts/imessage-server.py

# Monitor for 1 hour — watch for fallback warnings
docker logs x-intake --since 1h 2>&1 | grep -c "openai\|fallback"
# Expected: 0 (all local)
```

**Phase 1 DONE when:** verify-readonly.sh passes, py_compile succeeds on both files, x-intake uses Ollama, iMessage bridge uses Ollama, no cloud API calls in logs for 1 hour of normal operation.

---

## Phase 2 — Knowledge Pipeline: Scanner + Client Tracker + Calendar

**Why second:** These services process business data (client emails, documents, calendar events). Moving them local means client data never leaves the LAN. This is also a prerequisite for the neural map — the knowledge scanner feeds the cortex.

**Depends on:** Phase 1 (Ollama connectivity proven, helper pattern established).

### 2a. Migrate knowledge-scanner/processor.py

**Files:** `knowledge-scanner/processor.py`

**Currently:** Anthropic Claude Haiku for document classification and summarization.

**Change to:** Ollama qwen3:8b first → Claude Haiku fallback.

Replace the direct Anthropic API call with:
1. Try `POST http://{OLLAMA_HOST}/api/chat` with qwen3:8b
2. If Ollama fails, fall back to existing Claude Haiku code
3. Log WARNING on every cloud fallback

**Gate test:**
```bash
docker compose up -d --build knowledge-scanner
# Trigger a scan
curl -s http://127.0.0.1:8096/scan  # or whatever the scanner endpoint is
docker logs knowledge-scanner --tail 20 2>&1 | grep -i "ollama\|anthropic"
```

**Success:** Logs show Ollama processing, not Anthropic.

### 2b. Migrate openclaw/client_tracker.py

**Files:** `openclaw/client_tracker.py`

**Currently:** OpenAI GPT-4o for extracting client preferences from emails.

**Change to:** Ollama qwen3:8b first → OpenAI fallback. This is JSON extraction from email text — well within 8B model capability.

**Gate test:**
```bash
docker compose up -d --force-recreate openclaw
# Wait for an email cycle, check logs
docker logs openclaw --since 5m 2>&1 | grep -i "client_tracker\|preference\|ollama"
```

### 2c. Migrate calendar-agent/api.py

**Files:** `calendar-agent/api.py`

**Currently:** OpenAI AsyncOpenAI for scheduling intelligence.

**Change to:** Ollama first → OpenAI fallback. Calendar logic is straightforward — "find free slots", "check conflicts" — 8B handles it fine.

**Gate test:**
```bash
docker compose up -d --build calendar-agent
curl -sf http://127.0.0.1:8094/health
```

### Phase 2 hardening

```bash
bash scripts/verify-readonly.sh
# Monitor all three services for 2 hours
for svc in knowledge-scanner openclaw calendar-agent; do
  echo "--- $svc ---"
  docker logs $svc --since 2h 2>&1 | grep -c "openai\|anthropic\|fallback"
done
# Expected: all 0
```

**Phase 2 DONE when:** All three services process on Ollama, no cloud calls in 2 hours of operation, client data stays on LAN.

---

## Phase 3 — Trading Intelligence: Polymarket Lightweight Tasks

**Why third:** Trading bot has the most API calls and the highest stakes. Start with low-risk tasks (digest, ingest, scalp analysis) before touching the debate engine.

**Depends on:** Phase 2 (Ollama proven stable under sustained load from Phase 2 services).

### 3a. Migrate polymarket-bot/knowledge/digest.py

**Currently:** Claude Sonnet for daily trading digest.

**Change to:** Ollama qwen3:8b → Claude Sonnet fallback. Daily digest is a summary task — perfect for local.

### 3b. Migrate polymarket-bot/knowledge/ingest.py

**Currently:** Claude Sonnet for parsing research documents into knowledge base.

**Change to:** Ollama qwen3:8b → Claude Sonnet fallback. Document chunking and classification.

### 3c. Migrate polymarket-bot/strategies/presolution_scalp.py

**Currently:** OpenAI GPT-4o-mini for quick market analysis.

**Change to:** Ollama qwen3:8b → OpenAI fallback. Short analysis, low-stakes (presolution markets are small).

### Phase 3 hardening

```bash
# Run the bot for a full trading session (4+ hours)
docker logs polymarket-bot --since 4h 2>&1 | grep -i "ollama\|openai\|anthropic\|fallback" | sort | uniq -c
# Expected: mostly ollama, minimal/zero cloud calls for digest/ingest/scalp
```

**Phase 3 DONE when:** Daily digest generates via Ollama, knowledge ingest processes locally, presolution scalp runs without cloud, bot P&L is not degraded.

---

## Phase 4 — Trading Core: Debate Engine + Parameter Tuner (NEEDS 70B MODEL)

**Why last:** These are the highest-stakes LLM calls in the system. The debate engine needs strong adversarial reasoning — 8B models tend to agree with themselves. The parameter tuner adjusts real trading parameters.

**Depends on:** Phase 3 (trading bot proven stable with local models for lighter tasks).

**BLOCKER:** This phase requires a larger model on Betty. Options:

| Model | VRAM/RAM needed | Quality | Speed on Betty (64GB, Intel i3) |
|-------|----------------|---------|------|
| qwen3:8b | ~5GB | Good for simple tasks | Fast |
| llama3.1:70b | ~40GB | Near-Claude quality | Slow (CPU-only, ~2-5 tok/s on Intel) |
| qwen3:32b | ~20GB | Very good reasoning | Moderate (~5-10 tok/s) |
| deepseek-r1:32b | ~20GB | Strong reasoning | Moderate |

**Recommendation:** Pull `qwen3:32b` on Betty first. Test debate quality offline. Only migrate debate engine + parameter tuner once the local model produces comparable bull/bear/judge verdicts.

```bash
# On Betty
ollama pull qwen3:32b
```

### 4a. Migrate debate_engine.py

**Currently:** Claude Sonnet for bull/bear/judge pattern.

**Change to:** Ollama qwen3:32b → Claude Sonnet fallback.

**Critical quality gate:** Run 10 past debates through both local and cloud models. Compare verdicts. If local model agrees with cloud >80% of the time, it's safe to migrate.

### 4b. Migrate parameter_tuner.py

**Currently:** Claude Sonnet for strategy parameter tuning.

**Change to:** Ollama qwen3:32b → Claude Sonnet fallback.

**Critical quality gate:** Run tuner on historical data. Compare suggested parameters. If local suggestions are within 10% of cloud suggestions, migrate.

### Phase 4 hardening

Run the bot for a full week with local debate engine. Compare P&L to previous week. If P&L drops >15%, revert to cloud.

**Phase 4 DONE when:** Debate engine and parameter tuner run locally with comparable quality, trading P&L maintained.

---

## What stays cloud permanently

| Service | Why |
|---------|-----|
| **OpenClaw conductor** (Claude Sonnet 4.5) | Core business brain. Client-facing email drafts, bid triage, job orchestration. Revisit when 70B+ runs fast on Apple Silicon. |
| **Perplexity Sonar** (research_agent, market_intel, sentiment) | Web search + synthesis. No local equivalent — Ollama can't search the internet. |
| **Image vision** (GPT-4o) | No competitive local vision model yet. |

---

## Neural Map Benefits Unlocked Per Phase

| Phase | What it enables for the neural map |
|-------|-----------------------------------|
| **Phase 1** | Continuous X/Twitter analysis → trading signal nodes + edges to markets |
| **Phase 2** | Every document, email, client preference → knowledge nodes. Scanner runs unlimited. Client preference extraction builds relationship edges. |
| **Phase 3** | Trading decisions + outcomes → strategy performance nodes. Daily digest becomes training data. Knowledge ingest builds market understanding. |
| **Phase 4** | Debate transcripts become reasoning chains. Parameter changes become experiment nodes. The graph learns which reasoning patterns lead to profit. |

After Phase 2, the cortex curator (Auto-22) can run continuously instead of in a nightly batch — Betty handles the load. After Phase 3, the overnight learner has unlimited compute to process the day's trading activity. After Phase 4, the neural map has a complete picture: products ↔ compatibility ↔ clients ↔ preferences ↔ markets ↔ strategies ↔ outcomes.

---

## Implementation Notes

**Shared Ollama helper pattern** — every service should use the same pattern:

```python
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434")

def _ollama_chat(prompt: str, model: str = "qwen3:8b", format: str = "") -> Optional[str]:
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        if format:
            payload["format"] = format
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read()).get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("ollama_unavailable: %s — will fall back to cloud", str(e)[:100])
        return None
```

**Consider extracting this into a shared module** (e.g. `lib/local_llm.py`) after Phase 1 so every service imports from one place.

**Docker compose:** Add `OLLAMA_HOST=http://192.168.1.199:11434` to the environment block of every service that needs it, or add it to `.env` and reference `${OLLAMA_HOST}`.

**Bob uses venv Python** for host-side scripts. Docker containers have their own Python. Never `pip3 install` outside the venv on Bob.
