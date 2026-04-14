# Security Cleanup + Service Consolidation + Port Registry

## Overview
Five tasks in one prompt:
1. Merge knowledge-scanner's scan topics into cortex-autobuilder (then remove knowledge-scanner service)
2. Wire context-preprocessor as a utility library into openclaw (then remove the standalone service)
3. Remove remediator service entirely
4. Fix all hardcoded secrets (Redis password in 24 locations, Zoho client secret)
5. Create PORTS.md port registry at repo root

Execute in this exact order. Commit and push when all five are done.

---

## Task 1 — Merge Knowledge Scanner into Cortex Autobuilder

The knowledge-scanner runs Perplexity queries on a fixed topic list every 6 hours, processes results through Ollama, and stores scored insights in SQLite. The cortex-autobuilder already has Betty (researcher.py) doing LLM-powered research. Merge the scanning capability into the autobuilder so one service handles both.

### Steps

1. Open `integrations/cortex_autobuilder/daemon.py`

2. Add a new background task `_topic_scanner_loop()` that runs every 6 hours (configurable via env `SCAN_INTERVAL_HOURS`, default `6`). This loop should:
   - Query Perplexity via OpenRouter for each topic (reuse the existing researcher.py HTTP client pattern)
   - Process results through Ollama using the existing `_call_ollama()` or the llm_router
   - Store insights into cortex via the existing `_store_to_cortex()` function (POST to `{CORTEX_URL}/remember`)
   - Publish high-relevance findings (score >= 7) to Redis channel `notifications:knowledge`

3. Create `integrations/cortex_autobuilder/scan_topics.py` containing the topic list migrated from `knowledge-scanner/scanner.py`:
```python
SCAN_TOPICS = [
    {
        "query": "latest Polymarket prediction market trading strategies edges techniques Reddit",
        "category": "trading",
    },
    {
        "query": "latest crypto market making strategies DeFi automated trading bots Reddit",
        "category": "trading",
    },
    {
        "query": "latest smart home automation Control4 Savant Crestron trends innovations 2026",
        "category": "smart_home",
    },
    {
        "query": "latest RFID NFC IoT tracking innovations real-time location systems",
        "category": "iot",
    },
    {
        "query": "latest AI agent orchestration frameworks tools multi-agent systems",
        "category": "ai_tools",
    },
]
```

4. The processing system prompt for extracting insights (from `knowledge-scanner/processor.py`) should be included in `scan_topics.py`:
```python
SCAN_PROCESS_PROMPT = """You are a knowledge extraction assistant. Given raw search results, extract actionable insights.

For each distinct insight, return a JSON object with:
- "topic": short topic title (max 80 chars)
- "category": one of: trading, smart_home, iot, ai_tools, business, general
- "insight": the actionable insight (2-3 sentences)
- "source_summary": brief summary of where this info came from
- "relevance_score": 1-10 rating of relevance to a tech entrepreneur running a smart home integration business who also trades crypto and prediction markets

Return a JSON array of objects. Return ONLY valid JSON, no markdown."""
```

5. In `daemon.py`, start `_topic_scanner_loop()` as an additional asyncio task alongside the existing question generation and research loops in the lifespan handler.

6. Add a `/scan` endpoint to the FastAPI app for manual trigger (for testing).

7. Add a `/scan/topics` GET endpoint that returns the current topic list.

8. Update the autobuilder's health endpoint to include `"scanning_enabled": True` and `"scan_interval_hours"` in its response.

### What NOT to do
- Do NOT create a separate SQLite database. All insights go into cortex via the existing HTTP API.
- Do NOT add new pip dependencies beyond what cortex-autobuilder already uses (httpx is already there).
- Do NOT change the existing question_generator.py or researcher.py logic.

---

## Task 2 — Wire Context Preprocessor as an OpenClaw Utility

The context-preprocessor has a solid text-cleaning pipeline (ANSI stripping, whitespace normalization, smart truncation, Docker log deduplication). Instead of running as a standalone web service, extract it into a utility module that openclaw can import.

### Steps

1. Copy `context-preprocessor/preprocessor.py` to `openclaw/context_cleaner.py`

2. In the new `openclaw/context_cleaner.py`:
   - Keep the `process()` function and all its pipeline steps (strip_ansi, normalize_whitespace, smart_truncate, detect_format, etc.)
   - Add a simpler convenience function:
```python
def clean_context(text: str, max_lines: int = 100) -> str:
    """Clean raw text for LLM consumption. Returns cleaned string."""
    result = process(text)
    return result.output
```

3. In `openclaw/llm_router.py`, add an optional `clean_input` parameter to the `completion()` function:
   - When `clean_input=True`, run the input prompt through `clean_context()` before sending to the LLM
   - Default to `False` so existing callers are unaffected
   - Import: `from openclaw.context_cleaner import clean_context`

4. In `integrations/cortex_autobuilder/researcher.py`, import and use `clean_context` to clean Perplexity/Ollama responses before storing them in cortex. Add at the response processing step:
```python
from openclaw.context_cleaner import clean_context
# After getting raw LLM response:
cleaned = clean_context(raw_response)
```

### What NOT to do
- Do NOT remove the context-preprocessor directory yet (that happens in Task 3 cleanup)
- Do NOT change the preprocessor logic itself, just relocate it
- Do NOT make clean_context a required dependency — always guard imports with try/except in files that might run standalone

---

## Task 3 — Remove Dead Services from Docker Compose

### Remove these three services from `docker-compose.yml`:

**remediator** (port 8090):
- Remove the entire `remediator:` service block from docker-compose.yml
- Docker's `restart: unless-stopped` already handles container restarts

**knowledge-scanner** (port 8100):
- Remove the entire `knowledge-scanner:` service block from docker-compose.yml
- Its functionality is now in cortex-autobuilder (Task 1)

**context-preprocessor** (port 8028):
- Remove the entire `context-preprocessor:` service block from docker-compose.yml
- Its functionality is now an openclaw utility (Task 2)

### Update references:

1. `cortex/dashboard.py` — Remove these entries from the services health-check list:
   - `{"name": "Context Preprocessor", "host": "context-preprocessor", "port": 8028 ...}`
   - `{"name": "Remediator", "host": "remediator", "port": 8090 ...}`
   - `{"name": "Knowledge Scanner", "host": "knowledge-scanner", "port": 8100 ...}`

2. `scripts/imessage-server.py` — In the `get_system_status()` function (around line 1370), remove `"Knowledge": 8100` from the services dict. Add these new entries to the health check:
   - `"Cortex": 8102`
   - `"Intel Feeds": 8765`
   - `"X-Intake": 8101`
   - `"Autobuilder": 8115`

3. Do NOT delete the source directories (`remediator/`, `knowledge-scanner/`, `context-preprocessor/`). Just remove them from compose so they stop running as containers.

---

## Task 4 — Fix Hardcoded Secrets

### 4A — Redis Password

The password `d19c9b0faebeee9927555eb8d6b28ec9` is hardcoded in 24 locations. Fix ALL of them.

**docker-compose.yml (11 occurrences):**
Every service that currently has:
```yaml
- REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
```
Replace with:
```yaml
- REDIS_URL=${REDIS_URL}
```

The `.env` file on the host already has `REDIS_URL` defined (per `.env.example`). This makes compose pull it from the environment.

**Python files with hardcoded fallback defaults (13 occurrences):**

For each of these files, replace the hardcoded Redis URL with a safe default that has no password:

| File | Current Pattern | Replace With |
|------|----------------|--------------|
| `scripts/imessage-server.py` line 103 | `"redis://:d19c9b0faebeee9927555eb8d6b28ec9@127.0.0.1:6379"` | `os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")` |
| `polymarket-bot/strategies/polymarket_copytrade.py` line 193 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/strategies/wallet_rolling_redis.py` line 23 | `REDIS_URL_DEFAULT = "redis://...password..."` | `REDIS_URL_DEFAULT = os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/strategies/liquidity_provider.py` line 60 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/strategies/cvd_detector.py` line 30 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/src/config.py` line 118 | `Field(default="redis://...password...")` | `Field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://redis:6379"))` |
| `polymarket-bot/src/whale_scanner/scanner_engine.py` line 255 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/paper_runner.py` line 41 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `polymarket-bot/notifications/imessage.py` line 13 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `openclaw/intel_briefing.py` line 35 | hardcoded URL | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `openclaw/approval_drain.py` line 42 | hardcoded URL | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `integrations/x_alpha_collector/collector.py` line 37 | hardcoded default | `os.environ.get("REDIS_URL", "redis://redis:6379")` |
| `cortex/dashboard.py` line 277 | hardcoded URL | `os.environ.get("REDIS_URL", "redis://redis:6379")` |

**Important:** Add `import os` at the top of any file that doesn't already import it.

**Verification:** After all replacements, run:
```
grep -rn "d19c9b0faebeee9927555eb8d6b28ec9" --include="*.py" --include="*.yml" --include="*.js" --include="*.yaml"
```
This MUST return zero results.

### 4B — Zoho Client Secret

In `docker-compose.yml` around line 215, change:
```yaml
- ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET:-1be316a2f0448b2a62bc9659f5a4e01fc800936810}
```
To:
```yaml
- ZOHO_CLIENT_SECRET=${ZOHO_CLIENT_SECRET}
```

Also change the Zoho Client ID default on the line above it:
```yaml
- ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID:-1000.MO1TLB2AXFHH2YABDD2TSSIJ68SK5J}
```
To:
```yaml
- ZOHO_CLIENT_ID=${ZOHO_CLIENT_ID}
```

These values must come from `.env` only, never from compose defaults.

---

## Task 5 — Create PORTS.md Port Registry

Create `PORTS.md` at the repo root with this content:

```markdown
# Symphony AI-Server Port Registry

Quick reference for all active services. Update this file when adding or removing services.

Last updated: 2026-04-14

## Active Services

| Port | Service | Container | Purpose | Category |
|------|---------|-----------|---------|----------|
| 6379 | Redis | redis | Central data store, pub/sub, caching | Infrastructure |
| 8091 | Proposals | proposals | Symphony proposal generation engine | Business |
| 8092 | Email Monitor | email-monitor | Zoho email pipeline monitoring | Communication |
| 8093 | Voice Receptionist | voice-receptionist | Twilio voice call handling | Communication |
| 8094 | Calendar Agent | calendar-agent | Zoho calendar integration | Business |
| 8095 | Notification Hub | notification-hub | Alert routing and delivery | Infrastructure |
| 8096 | D-Tools Bridge | dtools-bridge | D-Tools project/inventory sync | Business |
| 8097 | ClawWork | clawwork | Side-hustle task engine | Business |
| 8099 | OpenClaw | openclaw | Central LLM orchestration + routing | Core AI |
| 8101 | X-Intake | x-intake | X/Twitter link analysis + bookmarks | Intelligence |
| 8102 | Cortex | cortex | Brain, memory, dashboard (1582+ memories) | Core AI |
| 8115 | Cortex Autobuilder | cortex-autobuilder | Bob/Betty research loop + topic scanning | Core AI |
| 8430 | Polymarket Bot | polymarket-bot | Prediction market trading (via VPN) | Trading |
| 8765 | Intel Feeds | intel-feeds | News, Reddit, Polymarket monitors | Intelligence |

## Removed Services

| Port | Service | Reason | Date |
|------|---------|--------|------|
| 8028 | Context Preprocessor | Merged into openclaw as context_cleaner.py utility | 2026-04-14 |
| 8090 | Remediator | Docker restart policies handle this natively | 2026-04-14 |
| 8100 | Knowledge Scanner | Merged into cortex-autobuilder topic scanner | 2026-04-14 |

## Notes

- All ports bind to `127.0.0.1` only (no external exposure)
- Redis password and all secrets live in `.env` (never hardcode in source files)
- To check service health: `curl http://127.0.0.1:<port>/health`
- Host service (imessage-server.py) runs outside Docker on the Mac Mini
```

---

## Final Verification Checklist

Before committing, verify:

1. `grep -rn "d19c9b0faebeee9927555eb8d6b28ec9" --include="*.py" --include="*.yml" --include="*.js"` returns NOTHING
2. `grep -n "1be316a2f0448b2a62bc9659f5a4e01fc800936810" docker-compose.yml` returns NOTHING
3. `grep -c "context-preprocessor:" docker-compose.yml` returns 0 (service removed)
4. `grep -c "remediator:" docker-compose.yml` returns 0 (service removed)
5. `grep -c "knowledge-scanner:" docker-compose.yml` returns 0 (service removed)
6. `PORTS.md` exists at repo root
7. `openclaw/context_cleaner.py` exists and has `clean_context()` function
8. `integrations/cortex_autobuilder/scan_topics.py` exists with 5 topics
9. `cortex-autobuilder/daemon.py` has `_topic_scanner_loop` function and `/scan` endpoint

## Git Commit

```
git add -A
git commit -m "security cleanup: remove hardcoded secrets, consolidate 3 orphaned services, add port registry

- Merge knowledge-scanner topic scanning into cortex-autobuilder
- Extract context-preprocessor as openclaw/context_cleaner.py utility
- Remove remediator, knowledge-scanner, context-preprocessor from compose
- Replace 24 hardcoded Redis passwords with env var references
- Remove Zoho client secret/ID defaults from compose
- Add PORTS.md port registry
- Update imessage-server health checks for current service list"
git push origin main
```
