# Local-First X Intake — Route All LLM/Transcription Through Ollama + Local Whisper

**Priority:** High — every X video link currently burns OpenAI credits for transcription + analysis when we have a local Ollama server and can run Whisper locally on the M4.

**Principle:** All analysis happens locally first. Only fall back to cloud APIs if local services are down or the task genuinely requires a cloud model (vision on images). The LLM router (`openclaw/llm_router.py`) already implements `local_first` mode — use it.

---

## Read First

- `integrations/x_intake/video_transcriber.py` — current code calls OpenAI Whisper + GPT-4o-mini directly
- `openclaw/llm_router.py` — existing local-first router (Ollama at 192.168.1.199:11434, llama3.1:8b and qwen3:8b)
- `scripts/imessage-server.py` — `research_link()` function calls GPT-4o-mini directly
- `integrations/x_intake/analyzer.py` — keyword-based, no LLM (leave alone)

---

## Part 1: Local Whisper Transcription

### Current Problem

`transcribe_audio()` in `video_transcriber.py` sends audio to OpenAI's Whisper API:
```python
client = OpenAI(api_key=api_key)
transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
```

### Fix: Use Local Whisper via CLI

Bob is a Mac Mini M4 — Whisper runs fast locally. The priority order:

1. **`whisper.cpp` CLI** (fastest on Apple Silicon via Metal) — check if `whisper-cpp` or `whisper` CLI is installed
2. **`mlx-whisper`** (MLX framework, also fast on M4) — `pip install mlx-whisper`
3. **Python `openai-whisper`** (slower but works) — `pip install openai-whisper`
4. **Ollama** — doesn't support audio transcription natively, skip
5. **OpenAI API** — last resort fallback only

Replace `transcribe_audio()` with:

```python
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")  # base, small, medium, large
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434")


def transcribe_audio(audio_path: str, openai_api_key: str = "") -> Optional[str]:
    """Transcribe audio locally first, cloud fallback only if local unavailable.
    
    Priority: whisper CLI → mlx-whisper → openai-whisper → OpenAI API (last resort)
    """
    # 1. Try whisper.cpp CLI (fastest on Apple Silicon)
    transcript = _transcribe_whisper_cli(audio_path)
    if transcript:
        return transcript

    # 2. Try mlx-whisper
    transcript = _transcribe_mlx_whisper(audio_path)
    if transcript:
        return transcript

    # 3. Try Python openai-whisper package (local)
    transcript = _transcribe_local_whisper(audio_path)
    if transcript:
        return transcript

    # 4. Last resort: OpenAI API
    logger.warning("all_local_whisper_failed — falling back to OpenAI API")
    return _transcribe_openai_api(audio_path, openai_api_key)


def _transcribe_whisper_cli(audio_path: str) -> Optional[str]:
    """Use whisper.cpp CLI if available."""
    import shutil
    whisper_bin = shutil.which("whisper-cpp") or shutil.which("whisper") or shutil.which("main")
    if not whisper_bin:
        # Check common install locations on macOS
        for path in ["/usr/local/bin/whisper", "/opt/homebrew/bin/whisper",
                     os.path.expanduser("~/whisper.cpp/main")]:
            if os.path.isfile(path):
                whisper_bin = path
                break
    if not whisper_bin:
        logger.info("whisper_cli_not_found — skipping")
        return None

    try:
        output_path = audio_path + ".txt"
        rc, output = _run_command_with_progress(
            [whisper_bin, "-m", f"models/ggml-{WHISPER_MODEL}.bin",
             "-f", audio_path, "--output-txt", "--output-file", audio_path],
            timeout=300,
            stage="whisper_cli",
        )
        if rc == 0 and os.path.exists(output_path):
            with open(output_path, "r") as f:
                transcript = f.read().strip()
            if transcript:
                logger.info("whisper_cli_success: %d chars", len(transcript))
                return transcript
    except Exception as e:
        logger.info("whisper_cli_error: %s", str(e)[:100])
    return None


def _transcribe_mlx_whisper(audio_path: str) -> Optional[str]:
    """Use mlx-whisper (Apple Silicon optimized) if available."""
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=f"mlx-community/whisper-{WHISPER_MODEL}-mlx",
        )
        transcript = result.get("text", "").strip()
        if transcript:
            logger.info("mlx_whisper_success: %d chars", len(transcript))
            return transcript
    except ImportError:
        logger.info("mlx_whisper_not_installed — skipping")
    except Exception as e:
        logger.info("mlx_whisper_error: %s", str(e)[:100])
    return None


def _transcribe_local_whisper(audio_path: str) -> Optional[str]:
    """Use the Python openai-whisper package (local model, no API call)."""
    try:
        import whisper
        model = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(audio_path)
        transcript = result.get("text", "").strip()
        if transcript:
            logger.info("local_whisper_success: %d chars", len(transcript))
            return transcript
    except ImportError:
        logger.info("openai_whisper_not_installed — skipping")
    except Exception as e:
        logger.info("local_whisper_error: %s", str(e)[:100])
    return None


def _transcribe_openai_api(audio_path: str, openai_api_key: str = "") -> Optional[str]:
    """Last resort: OpenAI Whisper API."""
    api_key = openai_api_key or OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.error("no_transcription_available — no local whisper and no OPENAI_API_KEY")
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        logger.warning("using_openai_whisper_api — install local whisper to avoid cloud costs")
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, response_format="text",
            )
        logger.info("openai_whisper_success: %d chars", len(transcript))
        return transcript
    except Exception as e:
        logger.error("openai_whisper_error: %s", str(e)[:200])
        return None
```

### Install Local Whisper on Bob

Run on Bob (one-time setup):
```bash
# Option A: mlx-whisper (recommended for M4)
pip3 install mlx-whisper

# Option B: openai-whisper (universal fallback)
pip3 install openai-whisper

# Option C: whisper.cpp (fastest, compile from source)
cd /tmp && git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && make -j
cp main /usr/local/bin/whisper-cpp
bash models/download-ggml-model.sh base
```

Add to `.env.example`:
```
# Whisper transcription (local-first, no cloud API needed)
WHISPER_MODEL=base  # base, small, medium, large (larger = more accurate, slower)
```

---

## Part 2: Route Analysis Through Ollama (Not OpenAI)

### Current Problem

`analyze_transcript()` calls GPT-4o-mini directly:
```python
client = OpenAI(api_key=api_key)
response = client.chat.completions.create(model="gpt-4o-mini", ...)
```

### Fix: Use Ollama for Analysis

Replace `analyze_transcript()` to use Ollama first:

```python
def _ollama_chat(prompt: str, model: str = "qwen3:8b") -> Optional[str]:
    """Call Ollama chat completion. Returns response text or None."""
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.3},
        }).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        content = data.get("message", {}).get("content", "")
        if content:
            logger.info("ollama_chat_success: model=%s chars=%d", model, len(content))
        return content or None
    except Exception as e:
        logger.info("ollama_chat_failed: %s", str(e)[:100])
        return None


def analyze_transcript(transcript: str, author: str = "", post_text: str = "", openai_api_key: str = "") -> dict:
    """Analyze transcript with local LLM first, cloud fallback."""
    prompt = _build_analysis_prompt(transcript, author, post_text)

    # 1. Try Ollama (local)
    response = _ollama_chat(prompt, model="qwen3:8b")
    if response:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning("ollama_json_parse_failed — trying cloud fallback")

    # 2. Fallback to OpenAI
    api_key = openai_api_key or OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"error": "Analysis unavailable — Ollama down and no OPENAI_API_KEY"}
    logger.warning("using_openai_for_analysis — Ollama was unavailable")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}


def _build_analysis_prompt(transcript: str, author: str, post_text: str) -> str:
    """Build the analysis prompt (shared between local and cloud)."""
    return f"""Analyze this video transcript from @{author} about trading/prediction markets.

Post text: {post_text[:500]}

Transcript:
{transcript[:15000]}

Respond in this exact JSON format:
{{
    "summary": "2-3 sentence overview of the key message",
    "flags": [
        {{"type": "🔨", "text": "specific actionable item"}},
        {{"type": "💡", "text": "trading edge or alpha insight"}},
        {{"type": "📊", "text": "specific number, threshold, or backtested result"}},
        {{"type": "🔧", "text": "tool, library, or resource mentioned"}},
        {{"type": "⚠️", "text": "warning or pitfall to avoid"}}
    ],
    "strategies": [
        {{
            "name": "strategy name",
            "description": "how it works",
            "parameters": "key thresholds or settings",
            "backtested_return": "if mentioned",
            "implementable": true,
            "priority": "high"
        }}
    ],
    "key_quotes": ["most important direct quotes from the transcript"]
}}

Only include flags genuinely present in the transcript. Include actual numbers and parameters."""
```

### Also fix: analyze_images() — keep as cloud-only with warning

Image analysis (GPT-4o vision) has no local equivalent on Ollama yet. Keep it as-is but add a log warning:
```python
logger.warning("using_openai_vision — no local alternative available for image analysis")
```

---

## Part 3: Route imessage-server.py research_link Through Ollama

### Current Problem

`research_link()` in `scripts/imessage-server.py` calls GPT-4o-mini directly for every link shared via iMessage:
```python
data = json.dumps({
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": prompt}],
}).encode()
req = Request("https://api.openai.com/v1/chat/completions", ...)
```

### Fix

Replace the OpenAI call in `research_link()` with an Ollama-first approach:

```python
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434")

def _ollama_completion(prompt: str, model: str = "qwen3:8b") -> Optional[str]:
    """Local LLM completion via Ollama."""
    try:
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 400},
        }).encode()
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data.get("message", {}).get("content", "")
    except Exception as e:
        log.info("[ollama] Failed: %s", str(e)[:100])
        return None
```

Then in `research_link()`, replace the OpenAI section with:
```python
        # Try local Ollama first
        result = _ollama_completion(prompt)
        if result:
            return result

        # Fallback to OpenAI if Ollama is down
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            if text:
                return "Link: %s\n\n%s" % (url, text[:500])
            return "Link: %s\nCan't analyze — Ollama is down and no OpenAI API key." % url

        log.warning("[research] Ollama unavailable — falling back to OpenAI")
        # ... existing OpenAI code as fallback ...
```

---

## Part 4: Install Dependencies on Bob

Run on Bob after code changes:

```bash
# Install mlx-whisper for local transcription (M4 optimized)
pip3 install mlx-whisper

# Pre-download the whisper model so first transcription isn't slow
python3 -c "import mlx_whisper; mlx_whisper.transcribe('/dev/null', path_or_hf_repo='mlx-community/whisper-base-mlx')" 2>/dev/null || true

# Verify Ollama has the models
curl -s http://192.168.1.199:11434/api/tags | python3 -c "
import sys, json
models = [m['name'] for m in json.load(sys.stdin).get('models', [])]
print('Models:', models)
assert 'qwen3:8b' in models or any('qwen' in m for m in models), 'qwen3:8b not found!'
print('OK — Ollama ready for analysis')
"
```

---

## Part 5: .env.example Updates

Add these:
```
# Local LLM (Ollama on iMac)
OLLAMA_HOST=http://192.168.1.199:11434
LLM_ROUTER_MODE=local_first  # local_first, cloud_only, local_only

# Local Whisper transcription
WHISPER_MODEL=base  # base, small, medium, large-v3
```

---

## Verification

```bash
# Test Ollama connectivity
curl -sf http://192.168.1.199:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"

# Test local whisper
python3 -c "import mlx_whisper; print('mlx-whisper available')" 2>/dev/null || echo "mlx-whisper not installed"

# Test x-intake with a real URL (after rebuild)
curl -s -X POST http://127.0.0.1:8101/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/test/status/1"}' | python3 -m json.tool
# Should NOT see "openai" in the logs — check:
docker logs x-intake --tail 20 2>&1 | grep -i "openai\|ollama"
```

---

## Rules

- **Local first, always.** Cloud APIs are the last resort, not the default.
- **Log when cloud is used.** Every cloud API call should log a WARNING so we can track cost leaks.
- **Don't break fallbacks.** If Ollama is down or whisper isn't installed, gracefully fall back to cloud.
- **Config change = rebuild.** `docker compose up -d --build x-intake` after changes.
- **Test the iMessage bridge separately** — it runs on the host, not Docker: `pkill -f imessage-server.py; sleep 2; nohup python3 ~/AI-Server/scripts/imessage-server.py &`
