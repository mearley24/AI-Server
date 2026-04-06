# Phase 2 — Local-First Knowledge Pipeline

**Priority:** Run after Phase 1 is verified (x-intake + iMessage bridge using Ollama).
**Purpose:** Move knowledge scanner, client tracker, and calendar agent to Ollama. Client data stays on LAN.

**Depends on:** `.env` has `OLLAMA_HOST=http://192.168.1.199:11434` (set in Phase 1).

---

## Read First

- `knowledge-scanner/processor.py` — already has `_process_with_ollama()` + Haiku fallback. Just needs OLLAMA_HOST set.
- `openclaw/client_tracker.py` — lines 239-275, uses OpenAI GPT-4o-mini for client preference extraction.
- `calendar-agent/api.py` — lines 117-160, uses OpenAI GPT-4o-mini for meeting prep notes.
- `openclaw/llm_router.py` — existing local-first router pattern (reference).

---

## 2a. Knowledge Scanner — Already Done, Just Verify

The scanner's `processor.py` already has Ollama-first with Claude Haiku fallback. It reads `OLLAMA_HOST` from env. The compose file has `OLLAMA_HOST=${OLLAMA_HOST:-}` and `.env` now has the correct value.

**Just restart:**
```bash
docker compose up -d --force-recreate knowledge-scanner
```

**Gate test:**
```bash
docker exec knowledge-scanner printenv OLLAMA_HOST
# Expected: http://192.168.1.199:11434

# Trigger a scan and check logs
docker logs knowledge-scanner --tail 20 --since 2m 2>&1 | grep -i "ollama\|anthropic\|haiku"
# Expected: "processing_complete_ollama" — NOT "anthropic" or "haiku"
```

---

## 2b. Client Tracker — Migrate Preference Extraction to Ollama

**File:** `openclaw/client_tracker.py`

**Current code (lines ~239-275):** Uses `from openai import OpenAI` and calls `gpt-4o-mini` for extracting client preferences from emails.

**Change:** Add Ollama-first with OpenAI fallback. The task is simple JSON extraction from email text — well within qwen3:8b capability.

### What to change

Find the `extract_preferences_from_email` method (or similar name). Replace the OpenAI section with Ollama-first:

```python
    def _ollama_extract(self, prompt: str) -> Optional[str]:
        """Extract via Ollama (local, free). Returns raw content or None."""
        ollama_host = os.environ.get("OLLAMA_HOST", "")
        if not ollama_host:
            return None
        try:
            import urllib.request
            url = f"{ollama_host.rstrip('/')}/api/chat"
            payload = json.dumps({
                "model": os.environ.get("OLLAMA_ANALYSIS_MODEL", "qwen3:8b"),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 200},
            }).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            content = data.get("message", {}).get("content", "")
            if content:
                logger.debug("ollama_preference_extraction_success")
                return content
        except Exception as e:
            logger.info("ollama_preference_extraction_failed: %s", str(e)[:100])
        return None
```

Then in the main extraction method, replace the OpenAI call block:

```python
        # Try Ollama first (local, free)
        content = self._ollama_extract(prompt)

        if not content:
            # Fallback to OpenAI
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                logger.debug("No Ollama and no OpenAI — skipping preference extraction")
                return []
            try:
                logger.warning("using_openai_for_preferences — Ollama was unavailable")
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                    temperature=0.2,
                )
                content = response.choices[0].message.content.strip()
            except Exception as e:
                logger.debug("Client preference extraction failed: %s", e)
                return []

        # Parse response (shared between Ollama and OpenAI)
        try:
            # Strip markdown fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            prefs = json.loads(content)
            if not isinstance(prefs, list):
                return []

            results = []
            for pref in prefs[:3]:
                ptype = pref.get("type", "preference")
                pcontent = pref.get("content", "")
                if ptype and pcontent:
                    self.add_preference(client_name, ptype, pcontent, source=f"email:{subject[:50]}")
                    results.append({"type": ptype, "content": pcontent})

            return results
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.debug("Preference parse failed: %s", e)
            return []
```

**Do NOT change:** The `add_preference`, `get_preferences`, or any other method. Only the extraction/LLM call path.

---

## 2c. Calendar Agent — Migrate Meeting Prep to Ollama

**File:** `calendar-agent/api.py`

**Current code (lines ~117-160):** Uses `AsyncOpenAI` and calls `gpt-4o-mini` for meeting prep notes.

**Change:** Add Ollama-first with OpenAI fallback.

### What to change

Replace the `/meeting-prep/{event_id}` endpoint body with:

```python
@router.post("/meeting-prep/{event_id}")
async def meeting_prep(event_id: str):
    """Generate AI meeting prep notes. Ollama first, OpenAI fallback."""
    client = get_client()
    _require_configured(client)

    # Fetch the event
    now = datetime.now()
    events = await client.list_events(
        (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00+00:00"),
        (now + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59+00:00"),
    )
    event = next((e for e in events if e.get("uid") == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    title = event.get("title", "Meeting")
    attendees = event.get("attendees", [])
    description = event.get("description", "")

    prompt = f"""Prepare brief meeting prep notes for: {title}
Attendees: {attendees}
Description: {description}
Include: key talking points, questions to ask, and any prep needed."""

    # 1. Try Ollama (local, free)
    prep_notes = await _ollama_meeting_prep(prompt)

    # 2. Fallback to OpenAI
    if not prep_notes:
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            raise HTTPException(status_code=503, detail="Ollama unavailable and no OpenAI API key")
        logger.warning("using_openai_for_meeting_prep — Ollama was unavailable")
        from openai import AsyncOpenAI
        ai = AsyncOpenAI(api_key=openai_key)
        resp = await ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        prep_notes = resp.choices[0].message.content

    return {
        "event_id": event_id,
        "title": title,
        "prep_notes": prep_notes,
    }


async def _ollama_meeting_prep(prompt: str) -> Optional[str]:
    """Generate meeting prep via Ollama. Returns None on failure."""
    ollama_host = os.getenv("OLLAMA_HOST", "")
    if not ollama_host:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                f"{ollama_host.rstrip('/')}/api/chat",
                json={
                    "model": os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen3:8b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.5},
                },
            )
            if resp.status_code != 200:
                return None
            content = resp.json().get("message", {}).get("content", "")
            if content:
                logger.info("meeting_prep_ollama_success")
                return content
    except Exception as e:
        logger.info("ollama_meeting_prep_failed: %s", str(e)[:100])
    return None
```

Add `from typing import Optional` at the top if not already present. Add `import structlog` and `logger = structlog.get_logger(__name__)` if no logger exists (check what logging the file already uses).

### Docker compose

Add `OLLAMA_HOST` to the calendar-agent environment if not already present:
```yaml
calendar-agent:
  environment:
    - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
```

Also add to openclaw's environment if not already there (for client_tracker):
```yaml
openclaw:
  environment:
    - OLLAMA_HOST=${OLLAMA_HOST:-http://192.168.1.199:11434}
```

---

## After All Changes

```bash
# Rebuild services with code changes
docker compose up -d --build knowledge-scanner calendar-agent
docker compose up -d --force-recreate openclaw

# Verify OLLAMA_HOST is set in all three
docker exec knowledge-scanner printenv OLLAMA_HOST
docker exec calendar-agent printenv OLLAMA_HOST
docker exec openclaw printenv OLLAMA_HOST
# All should return: http://192.168.1.199:11434

# Syntax checks
python3 -m py_compile openclaw/client_tracker.py
python3 -m py_compile calendar-agent/api.py
python3 -m py_compile knowledge-scanner/processor.py

# Monitor for cloud fallbacks (should be zero)
sleep 60
for svc in knowledge-scanner calendar-agent openclaw; do
  echo "--- $svc ---"
  docker logs $svc --since 2m 2>&1 | grep -i "openai\|anthropic\|fallback\|using_openai" | head -3
done
# Expected: empty output (all local)
```

---

## Phase 2 Gate

**DONE when:**
- All three services have `OLLAMA_HOST=http://192.168.1.199:11434`
- `py_compile` passes on all modified files
- Knowledge scanner logs show `processing_complete_ollama` (not `anthropic`)
- No `using_openai` warnings in logs for 30 minutes of operation
- Client preference extraction works (check next email cycle)
- `bash scripts/verify-readonly.sh` still 47 PASS, 0 FAIL

---

## Rules

- **Read before writing.** Every file must be read before editing.
- **Config change = rebuild.** `docker compose up -d --build [service]`.
- **No secrets in code.** All credentials from `.env` via `os.environ.get()`.
- **Local first, cloud fallback.** Every cloud call must have an Ollama attempt first and a WARNING log when falling back.
- **Don't touch what works.** Only change the LLM call paths. Leave all other logic alone.
