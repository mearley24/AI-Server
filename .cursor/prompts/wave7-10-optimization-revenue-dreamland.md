# Wave 7-10: Optimization + Revenue + Dreamland

**Priority:** MEDIUM — these build on a stable, verified core. Don't rush.
**Dependencies:** Waves 0-6 complete and verified. API-11 (Brain) operational.

---

## Context Files to Read First

- `openclaw/auto_responder.py` — direct OpenAI calls, primary migration target
- `email-monitor/analyzer.py` — OpenAI calls for email classification
- `polymarket-bot/strategies/llm_validator.py` — OpenAI per trade
- `openclaw/main.py` — FastAPI app, where to add endpoints
- `CONTEXT.md` — current system state
- `AGENTS.md` — architecture overview
- All specs: read `cursor-prompts/DONE/Auto-23-cost-optimization.md`, `Auto-28-context-preprocessor.md`, `Auto-25-apple-notes-indexer.md`, `API-3-neural-map.md`, `API-4-ensemble-weather-models.md`, `Auto-22-multi-agent-learning.md`, `Auto-29-verify-all-implementations.md`, `API-8-voice-receptionist-v2.md`, `API-9-client-ai-concierge-deploy.md`, `API-10-trading-mobile-app.md`, `Auto-12-clawwork-activation.md`, `Auto-4-bookmark-processor.md`, `Auto-27-x-twitter-autoposter.md`, `API-14-system-design-graph.md`, `API-15-symphony-ops-web-dashboard.md`, `Auto-24-portfolio-website.md`

---

## WAVE 7 — Cost Optimization & Context Efficiency

### Part 1: Auto-23 — LLM Cost Optimization ($50/Month Target)

Read `cursor-prompts/DONE/Auto-23-cost-optimization.md` for the complete spec (~10KB).

**Two new files: `openclaw/llm_router.py` and `openclaw/llm_cache.py`**

#### LLM Router (`openclaw/llm_router.py`)

Single interface for ALL LLM calls across ALL services:

```python
from openclaw.llm_router import completion

response = await completion(
    prompt="Classify this email",
    complexity="simple",     # simple | medium | complex
    cache_ttl=3600,
    service="email-monitor",
    fallback="cloud",
)
```

**Routing logic:**
- `simple` (classification, yes/no, extraction) → Ollama `llama3.1:8b` at `http://192.168.1.199:11434`
- `medium` (summarization, validation, drafting) → Ollama `qwen3:8b`, fallback `gpt-4o-mini`
- `complex` (proposals, long reasoning, code gen) → OpenAI `gpt-4o`

Ollama health check: 3-second ping, cache result 60 seconds. Env var `LLM_ROUTER_MODE`: `local_first` (default), `cloud_only`, `local_only`.

#### Redis Cache (`openclaw/llm_cache.py`)

SHA256 of (model + normalized prompt) as key. Default TTLs: simple 1hr, medium 5min, complex none. Target 40%+ cache hit rate. Track hits/misses in Redis counters.

#### Cost Tracking

Log every call to Redis `llm:costs:log` (LTRIM 10000). Daily aggregates per service and model in `llm:costs:daily:{YYYY-MM-DD}`. Alert if daily >$5.

Model costs: gpt-4o ($0.0025/$0.01 per 1K), gpt-4o-mini ($0.00015/$0.0006), Ollama ($0/$0).

#### API: `GET /api/llm-costs` — today, week, month, cache stats, by-service, by-model, projected monthly.

#### Service Migration

Replace direct OpenAI calls with `completion()` in:
- `llm_validator.py` → complexity="medium", cache_ttl=300
- `email-monitor/analyzer.py` → complexity="simple", cache_ttl=3600
- `openclaw/auto_responder.py` → complexity="medium", cache_ttl=0

#### Ollama API format

Use `/api/generate` endpoint with `{"model": "...", "prompt": "...", "stream": false}`. Parse `response`, `prompt_eval_count`, `eval_count`.

#### Docker networking note: `192.168.1.199:11434` is Maestro/Betty iMac LAN IP. Accessible from containers on host network.

---

### Part 2: Auto-28 — Context Preprocessor

Read `cursor-prompts/DONE/Auto-28-context-preprocessor.md` for full spec (~7KB).

**FastAPI service on port 8850** (`tools/context_preprocessor/server.py`):

1. **Preprocessor**: Paste raw text → strip ANSI, dedup logs, compress JSON, summarize patterns → output compressed markdown with token estimate.

2. **Web UI** (`tools/context_preprocessor/static/index.html`): Dark-mode page with paste area, process button, copy-to-clipboard, stats bar showing compression ratio.

3. **Session Manager** (`session_manager.py`):
   - Context summary generator: CONTEXT.md + recent session → <500 word session brief
   - Task splitter: multi-task request → recommended thread breakdown with pre-written first messages
   - Auto-update CONTEXT.md after each session

4. **Clipboard integration** (macOS): `pbpaste | python3 compress.py | pbcopy`. Create Alfred/Raycast shortcut.

5. **Smart paste rules**: Detect content type (Docker logs, terminal, email, JSON, git diff, traceback, config, code) → apply type-specific compression.

6. **Credit calculator**: Estimate cost in current thread vs fresh thread. Alert if >20K credits.

7. Docker service: `context-preprocessor`, port 8850.

---

### Part 3: Auto-25 — Apple Notes Indexer

Read `cursor-prompts/DONE/Auto-25-apple-notes-indexer.md` for complete spec (~14KB). Runs on HOST (not Docker).

1. **Notes Parser** (`integrations/apple_notes/notes_parser.py`): Access via AppleScript. Functions: `get_all_notes()`, `get_folders()`, `get_note_by_id()`, `get_attachments()`. Returns `NoteRecord` dataclasses.

2. **Notes Indexer** (`integrations/apple_notes/notes_indexer.py`):
   - Categorize: access_codes, project_reference, photo_log, meeting_notes, learning, idea, stale_draft
   - Keyword matching first, Ollama LLM second for ambiguous
   - Value scoring 0-100 (attachments +20, access_codes +30, project match +25, recently modified +15, content +10, duplicate -50)
   - Project matching via client_tracker data
   - Output: `data/notes_index.json`
   - Duplicate detection: same title or >80% Jaccard similarity

3. **Knowledge extraction**: Extract WiFi/alarm/gate codes from access_code notes → save to `knowledge/projects/[name]/access_codes.md`. Add to `.gitignore`.

4. **Cleanup report**: iMessage to Matt with keep/archive/delete/review counts.

5. **Scheduled**: launchd daily at midnight. Also expose via `POST /api/notes/index`.

6. **CLI**: `--index`, `--report`, `--extract-codes`, `--folders`, `--search`, `--dry-run`

---

### Part 4: API-3 — Neural Map (Knowledge Graph)

Read `cursor-prompts/DONE/API-3-neural-map.md` for full spec.

Knowledge graph visualization showing how all of Bob's services, data sources, and knowledge connect. D3.js force-directed graph accessible via Mission Control.

---

### Part 5: API-4 — Ensemble Weather Models

Read `cursor-prompts/DONE/API-4-ensemble-weather-models.md` for full spec.

ECMWF + GFS ensemble for tighter weather brackets. Feeds the weather_trader strategy with better probability estimates.

---

### Part 6: Auto-22 — Multi-Agent Learning

Read `cursor-prompts/DONE/Auto-22-multi-agent-learning.md` for full spec.

1. Employee chit-chat: services communicate observations and coordinate
2. Cortex curator: clean and organize the knowledge graph
3. Overnight learning: batch process yesterday's events and improve decision making

---

## WAVE 8 — Verification Pass

### Auto-29 — Verify All Implementations

Read `cursor-prompts/DONE/Auto-29-verify-all-implementations.md` for complete spec.

Run after system is substantially complete. For EVERY completed prompt:

1. Verify DONE-1 through DONE-5 (Polymarket fixes, RBI, Bob autonomy, iCloud watcher, X transcription)
2. Verify API-1, API-2, API-3 (trading bot, business operator, neural map)
3. For each: check code exists, imports resolve, basic instantiation works
4. Integration test: start bot, check all strategy imports, check all openclaw imports
5. Fix anything broken
6. Report: `cursor-prompts/VERIFICATION_REPORT.md` — PASS/FAIL per check, fixes applied, known issues
7. Commit and push

---

## WAVE 9 — Revenue & Product Layer

### Part 7: API-8 — Voice Receptionist V2

Read `cursor-prompts/DONE/API-8-voice-receptionist-v2.md` for complete spec (~9KB).

V2 module files exist. Wire them into a working server:

1. **Server** (`voice_receptionist/v2/server.py` — new): FastAPI server tying all v2 modules. Routes: `POST /voice/incoming`, `/voice/status`, `/voice/voicemail`, `/sms/incoming`. WebSocket `/ws/realtime` bridging Twilio ↔ OpenAI Realtime.

2. **OpenAI Realtime**: Bridge Twilio G.711 μ-law audio to OpenAI. Inject caller context from memory into system prompt. Handle 10 function calls from `call_scripts.py`.

3. **Caller Memory**: Redis-backed. `caller:{e164_number}` hash. Pre-seed from `data/clients.json`.

4. **Emergency Handler**: Real-time transcript scanning. P1 → immediate transfer + SMS. P2 → SMS + notify. 5-min cooldown.

5. **SMS Follow-Up**: Post-call SMS by intent. Only if call >30 seconds.

6. **Voice Analytics**: Redis logging. Daily summary at 6 PM via iMessage.

7. **Docker**: port 8089. Separate from existing voice webhook on 8088.

---

### Part 8: API-9 — Client AI Concierge

Read `cursor-prompts/DONE/API-9-client-ai-concierge-deploy.md` for complete spec (~8KB).

Deployable product — local Mac Mini running private AI for each Symphony client:

1. **Knowledge Ingestion**: D-Tools export + device manuals → ChromaDB vector store. `nomic-embed-text` embeddings via Ollama.

2. **Client Onboarding**: Single CLI command provisions new client. Validates D-Tools export, creates registry entry, builds KB, generates system prompt, self-tests.

3. **Concierge Server**: FastAPI with REST chat and WebSocket streaming. RAG: embed query → ChromaDB top 5 → augmented prompt → Ollama llama3.1:8b → stream response.

4. **Docker Stack**: Self-contained `docker-compose.yml` (Ollama, ChromaDB, concierge, nginx). Single `docker compose up -d` from cold.

5. **Test with Topletz data** as first client.

---

### Part 9: API-10 — Trading Mobile App

Read `cursor-prompts/DONE/API-10-trading-mobile-app.md` for complete spec (~7KB).

1. **Wire Mobile API** (`api/mobile_api.py`): Portfolio, positions, recent trades, alert settings — all from live Redis `portfolio:snapshot`.

2. **Trading API routes** (`api/trading_api.py`): Full trade history, strategies, markets, daily P/L, strategy pause/resume.

3. **Auth**: Simple API key header (`X-API-Key`). No OAuth.

4. **WebSocket** `/ws/trades`: Real-time trade feed from Redis pub/sub `trades:live`.

5. **CORS**: localhost + 100.x.x.x (Tailscale).

6. **Docker**: port 8421 on polymarket-bot.

7. **iOS verification**: Check Swift project structure, flag obvious issues. Don't rewrite.

---

### Part 10: Auto-12 — ClawWork Activation

Read `cursor-prompts/DONE/Auto-12-clawwork-activation.md` for full spec.

Bob's idle-time freelance revenue engine. Wire existing framework:
- Task scoring by fit/pay/risk
- Quality control (self-review, score 0-100)
- Earnings dashboard + daily iMessage summary
- Auto-pause when Symphony queue has work

---

### Part 11: Auto-4 — Bookmark Processor

Read `cursor-prompts/DONE/Auto-4-bookmark-processor.md` for full spec.

Process Matt's X bookmarks: categorize, extract insights, file into knowledge base.

---

### Part 12: Auto-27 — X/Twitter Autoposter

Read `cursor-prompts/DONE/Auto-27-x-twitter-autoposter.md` for full spec.

Bob posts to @symphonysmart with approval queue. Content generation from project milestones and industry insights.

---

## WAVE 10 — Dreamland (Endgame)

### Part 13: API-14 — System Design Graph

Read `cursor-prompts/DONE/API-14-system-design-graph.md` for full spec (~9KB).

Compatibility intelligence, design validation, wiring diagrams for Symphony installations.

---

### Part 14: API-15 — Symphony Ops Web Dashboard

Read `cursor-prompts/DONE/API-15-symphony-ops-web-dashboard.md` for full spec (~8KB).

Business ops GUI: product catalog, SOW builder, project tracker.

---

### Part 15: Auto-24 — Portfolio Website

Read `cursor-prompts/DONE/Auto-24-portfolio-website.md` for full spec.

Auto-generated portfolio from project photos. Showcases Symphony's work.

---

## Execution Notes

- **Build order**: Wave 7 (Auto-23 → Auto-28 → Auto-25 → API-3 → API-4 → Auto-22) → Wave 8 (Auto-29) → Wave 9 (API-8 → API-9 → API-10 → Auto-12 → Auto-4 → Auto-27) → Wave 10 (API-14 → API-15 → Auto-24)
- Wave 8 (Auto-29) MUST run after Waves 3-7 are complete — it verifies everything
- Wave 10 items are non-blocking — build whenever capacity allows
- **Commit each part separately**: `feat: add LLM cost optimization router (Auto-23)`
- Use standard logging throughout (NO structlog)
- Redis at `redis://172.18.0.100:6379` inside Docker
- Push to origin main when done
