# AI-Server — Backlog, Verification & Risk Checklist

**Generated:** 2026-04-05 13:00 MDT  
**Repo:** `mearley24/AI-Server` (branch: `main`)  
**Host:** Bob (Mac Mini M4) at `/Users/bob/AI-Server`  
**Current state:** 16 services in Docker Compose, all ports locked to 127.0.0.1, Redis auth enforced, watchdog + launchd resilience in place.

---

## 1. Remaining Implementation Backlog

### 1.1 Auto-28 — Context Preprocessor FastAPI

| Field | Detail |
|-------|--------|
| **Status** | Container running on port 8028 (exists in docker-compose). Code in `tools/context_preprocessor/` — `app.py`, `preprocessor.py`, `templates/index.html`. Prompt spec calls for port 8850; actual port is 8028. |
| **Done means** | (a) Paste raw text at `http://bobs-mac-mini:8028` → get compressed output with token count. (b) Session manager generates <500-word context briefs from CONTEXT.md. (c) "Copy to Clipboard" works on LAN devices. (d) Dark-mode UI loads without JS errors. (e) `pbpaste \| python3 compress.py \| pbcopy` shortcut works on Bob. |
| **Files** | `tools/context_preprocessor/server.py` (or `app.py`), `preprocessor.py`, `session_manager.py`, `static/index.html`, `Dockerfile`, docker-compose snippet |
| **Dependencies** | None external. Runs standalone. Ollama optional for smart-paste type detection. |
| **Gap** | Verify UI is functional (not just a health endpoint). Session manager may be stub-only. |

### 1.2 Auto-25 — Apple Notes Indexer

| Field | Detail |
|-------|--------|
| **Status** | Code exists: `integrations/apple_notes/notes_parser.py`, `notes_indexer.py`, `__init__.py`. Runs on HOST (not Docker) — requires AppleScript access. launchd plist at `setup/launchd/com.symphony.notes-indexer.plist`. |
| **Done means** | (a) `python3 integrations/apple_notes/notes_parser.py` returns all notes as JSON without error. (b) `notes_indexer.py` categorizes notes and writes `data/notes_index.json`. (c) Access codes extracted to `knowledge/projects/[name]/access_codes.md` and `.gitignore`d. (d) Cleanup report sent via iMessage. (e) launchd plist installed and running. (f) Optional: `POST /api/notes/index` triggers re-index from OpenClaw. |
| **Files** | `integrations/apple_notes/notes_parser.py`, `notes_indexer.py`, `data/notes_index.json`, launchd plist |
| **Dependencies** | macOS host (not Docker). AppleScript permission grant in System Settings → Privacy & Security → Automation. Ollama at `192.168.1.199:11434` for LLM-based categorization (optional — keyword fallback exists). |
| **Gap** | AppleScript may fail on first run without permission grant. Verify `osascript` access is pre-authorized. |

### 1.3 API-3 — Neural Map / Knowledge Graph UI

| Field | Detail |
|-------|--------|
| **Status** | `knowledge/hardware/system_graph.py` and `tools/knowledge_graph.py` exist. CLI `--check` and `--recommend` specified. Visualization intended for Mission Control (`127.0.0.1:8098`). |
| **Done means** | (a) `python3 knowledge/hardware/system_graph.py --check "Samsung QN80F" "Sanus VLT7"` returns compatibility verdict. (b) `--recommend "100-inch TV" --budget 8000` returns options. (c) `GET /api/knowledge/graph` on OpenClaw returns JSON graph. (d) Mission Control has a visual graph page (D3.js or similar). |
| **Files** | `knowledge/hardware/system_graph.py`, `tools/knowledge_graph.py`, `openclaw/orchestrator.py` (endpoint registration), Mission Control frontend |
| **Dependencies** | Hardware JSON files (`tvs.json`, `mounts.json`, `networking.json`, `c4_tv_driver_reference.json`) must be populated with real product data. |
| **Gap** | CLI likely built. Visualization UI almost certainly not wired yet — check Mission Control source. |

### 1.4 API-4 — Ensemble Weather (ECMWF + GFS)

| Field | Detail |
|-------|--------|
| **Status** | **Not started.** No `ecmwf_client.py` or `gfs_client.py` exist in `polymarket-bot/src/`. Only `metar_client.py` and `noaa_client.py` are present. The prompt spec is in `cursor-prompts/DONE/API-4-ensemble-weather-models.md` but the code was never generated. |
| **Done means** | (a) `polymarket-bot/src/ecmwf_client.py` fetches from Open-Meteo ECMWF API. (b) `polymarket-bot/src/gfs_client.py` fetches from Open-Meteo GFS API. (c) `weather_trader.py` aggregates all 4 sources (METAR, NOAA, ECMWF, GFS) into confidence-weighted position sizing. (d) Redis cache keys `weather:ecmwf:*` and `weather:gfs:*` with 30-min TTL. (e) Log line in polymarket-bot: `ensemble_forecast_complete` with model agreement metric. |
| **Files** | `polymarket-bot/src/ecmwf_client.py` (new), `polymarket-bot/src/gfs_client.py` (new), `polymarket-bot/strategies/weather_trader.py` (modify) |
| **Dependencies** | Open-Meteo API (free, no key). Redis for caching. `httpx` or `aiohttp` (check `requirements.txt`). |
| **Gap** | Full implementation needed. Weather trader is currently the top performer — changes need careful testing. |

### 1.5 Auto-22 — Multi-Agent Learning

| Field | Detail |
|-------|--------|
| **Status** | Supporting files exist: `tools/cortex_curator.py`, `tools/knowledge_graph.py`, `openclaw/continuous_learning.py`, `cortex/seed_data.json`. Orchestrator directory has `orchestrator/core/bob_orchestrator.py` and `orchestrator/WORK_IN_PROGRESS.md`. Learning loop, question generator, task filler, overnight learner are spec'd but likely stubs. |
| **Done means** | (a) `cortex_curator.py` runs daily at 2 AM via heartbeat. (b) `knowledge/cortex/trusted/` and `knowledge/cortex/review/` directories populated. (c) Redis `learning:new_facts` channel active. (d) Weekly "What the team learned" iMessage report sent. (e) Overnight learner runs at 11 PM rotating through product categories. |
| **Files** | `orchestrator/learning_loop.py` (new or from `continuous_learning.py`), `tools/cortex_curator.py`, `tools/knowledge_graph.py`, `orchestrator/workers_question_generator.py`, `orchestrator/task_filler.py`, `tools/overnight_learner.py` |
| **Dependencies** | Ollama at `192.168.1.199:11434` for local LLM research. Redis for pub/sub. iMessage bridge for reports. Multiple agents (Bob, Betty, Beatrice) operational. |
| **Gap** | Heavyweight feature. Needs Ollama network confirmed working, and stable agent identities. Don't rush — this is Wave 7+ territory. |

### 1.6 Wave 8 / Auto-29 — Full Verification Pass

| Field | Detail |
|-------|--------|
| **Status** | `cursor-prompts/VERIFICATION_REPORT.md` exists with 2026-04-05 results. Part 1 (tonight's fixes) all PASS. Part 2 (open items) all marked **Manual**. `.cursor/prompts/wave-verification-unresolved.md` is the sweep prompt. |
| **Done means** | (a) Every import in `VERIFICATION_REPORT.md` runs without error on Bob. (b) DONE-1 through DONE-5 + API-1/2/3 verified. (c) `scripts/smoke-test-full.sh` returns 0 FAIL. (d) Manual items (testimonial, weather enrichment, spread arb sizing, D-Tools keys) either resolved or documented as deferred. |
| **Files** | `cursor-prompts/VERIFICATION_REPORT.md`, `scripts/smoke-test.sh`, `scripts/smoke-test-full.sh` |
| **Dependencies** | All services running. Redis healthy. |
| **Gap** | The 4 manual items from Part 2 remain open. See §2 below for exact verification commands. |

### 1.7 Wave 9 — New Services

| Item | Port | Key Files | External Dependencies | Done Means |
|------|------|-----------|----------------------|------------|
| **API-8 Voice Receptionist v2** | 8089 (spec) / 8093 (current v1) | `voice_receptionist/v2/server.py` (new), `call_routing.py`, `caller_memory.py`, `twilio_config.py`, `openai_realtime_config.json` | Twilio account (SID, auth token, phone number), OpenAI Realtime API key, public URL or ngrok for Twilio webhooks | Twilio webhook → call_routing → OpenAI Realtime WS bridge → caller gets Bob's voice. SMS follow-ups sent. Emergency calls forwarded to Matt's cell. |
| **API-9 Client AI Concierge** | per-client deployment | `client_ai/v2/concierge_server.py`, `knowledge_ingestion.py`, `client_onboarding.py`, `docker-compose.concierge.yml` | Ollama with `nomic-embed-text` for embeddings, ChromaDB, D-Tools project export | Client-specific Mac Mini answers "What speakers are in my living room?" using local Chroma vector store. |
| **API-10 Mobile API + WS** | 8420/8421 (launchd plists exist) | `api/mobile_api.py`, `api/trading_api.py`, `ios-app/SymphonyTrading/`, `ios-app/SymphonyOps/` | Redis keys `portfolio:snapshot`, `trades:live`, `trades:recent`. iOS dev environment (Xcode). | `GET /api/mobile/portfolio` returns live portfolio from Redis. iOS app connects and displays positions. |
| **Auto-12 ClawWork** | N/A (background) | `clawwork/` directory (full structure exists), `task_selector.py`, `earnings_tracker.py`, `v2/` | Upwork/Fiverr accounts (optional), direct outreach templates | Bob picks up freelance tasks when Symphony queue is empty. Earnings tracked. |
| **Auto-4 Bookmarks** | N/A (pipeline) | `integrations/x_intake/bookmark_scraper.py` | Browser access or API for bookmark export | Bookmarks auto-processed into knowledge base. |
| **Auto-27 X Autoposter** | N/A (cron/event-driven) | Needs new file or integration into x_intake | X/Twitter API write access (OAuth 2.0 with tweet.write scope) | Bob auto-posts project completions, market insights, industry content to @SymphonySH. |

### 1.8 Wave 10 — Long-Term

| Item | Key Files | Done Means |
|------|-----------|------------|
| **API-14 System Design Graph** | `tools/knowledge_graph.py`, `openclaw/design_validator.py` | Interactive graph showing every product's compatibility, cable requirements, VLAN placement. Powers automated design validation for proposals. |
| **API-15 Ops Dashboard** | Mission Control extension or new service | Web dashboard showing all Symphony projects, statuses, timelines, alerts. Replaces manual Linear checking. |
| **Auto-24 Portfolio Site** | New `symphonysh.com` section or standalone site | Public portfolio with project photos from Apple Notes, before/after, client testimonials (from §1.6 testimonial flow). |

---

## 2. Verification & Test Commands

> **Run all commands on Bob** (`ssh bob` or directly on the Mac Mini).  
> **Never paste real passwords into terminal output that gets shared.**  
> Use `$REDIS_PASS` variable pattern shown below.

### 2.1 OpenClaw — Health & LLM Costs

```bash
# Health check
curl -sf http://127.0.0.1:8099/health && echo " ✓ OpenClaw healthy"

# LLM costs endpoint (with Redis running)
curl -sf http://127.0.0.1:8099/api/llm-costs | python3 -m json.tool

# LLM costs endpoint (Redis down simulation — should return graceful error)
# Don't actually stop Redis; instead check the code handles ConnectionError
docker exec openclaw python3 -c "
from openclaw.llm_router import completion
print('llm_router imports OK')
"

# Briefing status
curl -sf http://127.0.0.1:8099/briefing/status | python3 -m json.tool
```

**Success signals:**
- `/health` → `200 OK` with JSON status
- `/api/llm-costs` → JSON with `today`, `week`, `month`, `cache_stats`, `by_service`, `by_model`
- If Redis is down: graceful error message, not a 500 traceback

### 2.2 Polymarket Bot — Strategy Imports & KRAKEN_DRY_RUN

```bash
# PYTHONPATH must include both polymarket-bot AND repo root
docker exec polymarket-bot python3 -c "
import sys; sys.path.insert(0, '/app')
from strategies.polymarket_copytrade import PolymarketCopytrade
from strategies.weather_trader import CheapBracketStrategy
from strategies.spread_arb import SpreadArbScanner
from strategies.strategy_manager import StrategyManager
from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker
from src.main import main
print('All strategy imports OK')
"

# Verify KRAKEN_DRY_RUN behavior
docker exec polymarket-bot python3 -c "
import os
dry = os.environ.get('KRAKEN_DRY_RUN', 'false')
print(f'KRAKEN_DRY_RUN = {dry}')
assert dry.lower() not in ('true', '1', 'yes'), 'WARNING: Kraken is in dry-run mode'
print('Kraken is LIVE (not dry-run)')
" 2>&1 || echo "⚠ Kraken dry-run check — review output above"

# Check no hardcoded redis:6379 fallbacks remain
docker exec polymarket-bot grep -rn "redis://redis:6379" /app/ 2>/dev/null \
  | grep -v ".pyc" | grep -v "__pycache__" | grep -v "example" | grep -v "README" | grep -v "health_check"
# Expected: empty output (no matches)
```

**Success signals:**
- All imports succeed without `ModuleNotFoundError`
- `KRAKEN_DRY_RUN=false` (or unset, defaulting to live)
- No hardcoded `redis://redis:6379` in Python files (excluding docs/examples)

### 2.3 Email Monitor — BODY.PEEK & Message-ID

```bash
# Check BODY.PEEK is used (not BODY[] which marks as read)
docker exec email-monitor grep -n "BODY\[" /app/*.py /app/**/*.py 2>/dev/null | grep -v "PEEK"
# Expected: empty (no non-PEEK BODY fetches)

docker exec email-monitor grep -n "BODY.PEEK" /app/*.py 2>/dev/null
# Expected: at least one match in monitor.py

# Check Message-ID based dedup
docker exec email-monitor grep -n "Message-ID\|message_id\|msg_id" /app/*.py 2>/dev/null | head -10
# Expected: stable message_id generation from Message-ID header

# Import check — note the package layout uses hyphen directory (email-monitor/)
# but Python imports need underscore. Check what actually works:
docker exec email-monitor python3 -c "
import sys; sys.path.insert(0, '/app')
# Try both patterns — one should work
try:
    from monitor import EmailMonitor
    print('OK: from monitor import EmailMonitor')
except ImportError as e:
    print(f'monitor.py direct import failed: {e}')
try:
    from main import app  # FastAPI app
    print('OK: from main import app')
except ImportError as e:
    print(f'main.py import failed: {e}')
"

# Routing config
docker exec email-monitor python3 -c "
import json
with open('/app/routing_config.json') as f:
    cfg = json.load(f)
routes = cfg.get('domain_routes', cfg.get('routes', {}))
print(f'Domain routes: {len(routes)}')
assert len(routes) >= 21, f'Expected 21+ routes, got {len(routes)}'
print('Routing config OK')
"
```

**Success signals:**
- No `BODY[]` without `PEEK` in monitor code
- `Message-ID` header used for dedup, not UID
- At least one import pattern works
- 21+ domain routes in routing config

### 2.4 Redis — Channels, Lists, Keys (No Passwords in Logs)

```bash
# Load password from .env (never echo it)
cd ~/AI-Server
REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env | cut -d= -f2- | tr -d '\r')

# Auth test
docker exec redis redis-cli -a "$REDIS_PASS" ping 2>/dev/null | grep -q PONG && echo "✓ Redis auth OK"

# Reject unauthenticated
docker exec redis redis-cli ping 2>/dev/null | grep -q PONG && echo "✗ DANGER: Redis accepts no-auth" || echo "✓ Redis rejects unauthenticated"

# Check channels (subscribe briefly then cancel)
timeout 3 docker exec redis redis-cli -a "$REDIS_PASS" SUBSCRIBE notification-hub 2>/dev/null | head -5
# Expected: shows subscription confirmation

# Check email drafts list
docker exec redis redis-cli -a "$REDIS_PASS" LLEN email:drafts 2>/dev/null
# Expected: integer (possibly 0 if no pending drafts)

# Check LLM cost keys
docker exec redis redis-cli -a "$REDIS_PASS" KEYS "llm:costs:*" 2>/dev/null | head -10
# Expected: keys like llm:costs:daily:2026-04-05, llm:costs:log

# Check LLM cache keys
docker exec redis redis-cli -a "$REDIS_PASS" KEYS "llm:cache:*" 2>/dev/null | head -5
# Expected: SHA256-based cache keys (or empty if cache cold)

# Port security
docker ps --format '{{.Ports}}' | grep "0.0.0.0" && echo "✗ EXPOSED PORTS FOUND" || echo "✓ All ports 127.0.0.1"
```

**Success signals:**
- PONG with auth, rejected without
- `notification-hub` subscription confirms
- `email:drafts` returns integer
- `llm:costs:*` keys present (if LLM calls have been made)
- No `0.0.0.0` port bindings

### 2.5 Ollama on LAN — Host vs Bridge Network

```bash
# From Bob host (should always work)
curl -sf http://192.168.1.199:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
models = [m['name'] for m in data.get('models', [])]
print(f'Ollama models ({len(models)}): {models[:5]}')
" 2>/dev/null || echo "✗ Ollama not reachable from host"

# From inside a Docker container (host network mode — e.g. polymarket-bot via VPN)
docker exec polymarket-bot curl -sf http://192.168.1.199:11434/api/tags 2>/dev/null \
  | python3 -c "import sys,json; print('✓ Ollama reachable from polymarket-bot')" 2>/dev/null \
  || echo "✗ Ollama NOT reachable from polymarket-bot container"

# From bridge-network container (e.g. openclaw)
docker exec openclaw curl -sf http://192.168.1.199:11434/api/tags 2>/dev/null \
  | python3 -c "import sys,json; print('✓ Ollama reachable from openclaw')" 2>/dev/null \
  || echo "✗ Ollama NOT reachable from openclaw (bridge network blocks LAN)"

# Check OLLAMA_HOST env in compose
grep -i "OLLAMA" ~/AI-Server/docker-compose.yml | head -5
grep -i "OLLAMA" ~/AI-Server/.env | head -5
```

**Success signals:**
- Host → `192.168.1.199:11434` returns model list (includes `llama3.1:8b`, `qwen3:8b`)
- VPN-networked containers can reach it (polymarket-bot uses `network_mode: service:vpn`)
- Bridge-network containers (openclaw, email-monitor) may need `extra_hosts` or `host.docker.internal` routing

**Key insight:** If bridge-network containers can't reach `192.168.1.199`, add to their compose config:
```yaml
extra_hosts:
  - "ollama:192.168.1.199"
```
Or use `OLLAMA_HOST=http://host.docker.internal:11434` and ensure Ollama binds to `0.0.0.0` on the iMac.

### 2.6 Testimonial Collection Flow

```bash
# Check if testimonial template exists
ls -la ~/AI-Server/proposals/email_templates/testimonial_request.md 2>/dev/null \
  && echo "✓ Template exists" || echo "✗ Template missing"

# Check if /review route exists in symphonysh.com source
grep -r "review\|testimonial\|Review" ~/AI-Server/symphonysh-web/src/ 2>/dev/null | head -5
# Or: check the live site
curl -sf https://www.symphonysh.com/review -o /dev/null -w "%{http_code}" 2>/dev/null
# Expected: 200 if deployed, 404 if not yet

# Check follow-up tracker for testimonial schedule type
grep -n "testimonial" ~/AI-Server/openclaw/follow_up_tracker.py 2>/dev/null | head -5
# Expected: testimonial_3day and testimonial_followup_7day in FOLLOWUP_TYPES

# Check orchestrator for job-complete → testimonial trigger
grep -n "testimonial\|complete\|paid_in_full" ~/AI-Server/openclaw/orchestrator.py 2>/dev/null | head -10
```

**Success signals:**
- Template file exists with `{project_address}`, `{client_first_name}`, `{testimonial_link}` placeholders
- `/review` route returns 200 with a form
- Follow-up tracker has testimonial schedule types
- Job lifecycle triggers testimonial request on completion

**Likely status:** Prompt exists at `.cursor/prompts/testimonial-collection-flow.md` but was **never executed**. This is a full implementation task.

### 2.7 Weather Trader Price Enrichment

```bash
# Check weather trader logs for enrichment activity
docker logs polymarket-bot --since 1h 2>&1 | grep -i "enrichm\|ensemble\|ecmwf\|gfs\|noaa_forecast\|weather_tick" | tail -10

# Check if ECMWF/GFS clients exist
docker exec polymarket-bot ls /app/src/ecmwf_client.py /app/src/gfs_client.py 2>/dev/null \
  && echo "✓ Ensemble clients exist" || echo "✗ ECMWF/GFS clients NOT built (API-4 not implemented)"

# Verify NOAA client works (existing baseline)
docker exec polymarket-bot python3 -c "
from src.noaa_client import NOAAClient
print('NOAAClient imports OK')
print(f'Stations configured: {list(getattr(NOAAClient, \"KALSHI_STATIONS\", {}).keys())[:5]}')
"

# Check weather candidates in recent logs
docker logs polymarket-bot --since 30m 2>&1 | grep "weather_tick_complete\|weather_candidates\|bracket" | tail -5
```

**Success signals:**
- `weather_tick_complete` log entries with `candidates` count
- Currently: only NOAA/METAR data flowing (enrichment = API-4, not yet built)
- Proof of enrichment would be log line: `ensemble_forecast_complete` with 4 sources — this does NOT exist yet

### 2.8 Spread Arb Low-Balance Mode

```bash
# Check env vars for arb sizing
docker exec polymarket-bot env | grep "^ARB_" | sort
# Key vars:
#   ARB_MAX_POSITION=50    (max $50 per arb trade)
#   ARB_MAX_PER_SIDE=25    (max $25 per side)
#   ARB_MAX_EXPOSURE=2000  (total exposure cap)

# Check for low-balance / minimum sizing logic
docker exec polymarket-bot grep -n "low.balance\|min_size\|MIN_ORDER\|insufficient\|balance_check\|wallet_balance" \
  /app/strategies/spread_arb.py 2>/dev/null | head -10

# Check recent arb activity
docker logs polymarket-bot --since 1h 2>&1 | grep "arb_\|spread_\|complement_\|negative_risk" | tail -10

# Check if arb gracefully handles low funds
docker logs polymarket-bot --since 6h 2>&1 | grep -i "insufficient\|balance\|low.*bal\|skip.*size\|order.*fail" | tail -10
```

**Success signals:**
- `ARB_MAX_POSITION=50` and `ARB_MAX_PER_SIDE=25` are set
- Arb scanner runs without crashing on ~$50 balance
- If balance < minimum trade size: log line like `arb_skipped_low_balance` (not an unhandled exception)
- Currently: spread arb has hardcoded `MIN_COMPLEMENT_SPREAD=0.015`, `MAX_POSITION_USD=50` — fits the ~$50 wallet. But minimum Polymarket order is 5 shares ($0.05 min), and gas is $0.05/trade. A $0.50 arb may not be profitable after fees.

**What to verify/fix:**
- Add a minimum profitable trade check: `expected_profit_usd > (GAS_FEE * 2 + SLIPPAGE * cost_usd)`
- Log `arb_skipped_unprofitable` instead of attempting unprofitable trades
- Consider a `LOW_BALANCE_MODE=true` env var that reduces scan frequency and raises minimum edge requirements

### 2.9 D-Tools — .env.example & Graceful Degradation

```bash
# Check .env.example exists with placeholders
cat ~/AI-Server/integrations/dtools/.env.example
# Expected: DTOOLS_API_KEY=your-api-key-here, DTOOLS_BRIDGE_PORT=5050

# Check main .env.example has D-Tools section
grep -A5 "D-Tools" ~/AI-Server/.env.example | head -10
# Expected: DTOOLS_API_KEY, DTOOLS_API_SECRET placeholders

# Check browser_agent env requirements
grep -n "DTOOLS_EMAIL\|DTOOLS_PASSWORD\|DTOOLS_API" ~/AI-Server/docker-compose.yml | head -5
# Expected: env vars referencing ${DTOOLS_EMAIL}, ${DTOOLS_PASSWORD}

# Check graceful behavior when keys missing
docker exec dtools-bridge python3 -c "
import os
key = os.environ.get('DTOOLS_API_KEY', '')
if not key or key == 'your-api-key-here':
    print('⚠ D-Tools API key not configured — bridge will run in read-only/stub mode')
else:
    print('✓ D-Tools API key present')
" 2>/dev/null || echo "dtools-bridge container not running (expected if no API key)"
```

**Success signals:**
- `.env.example` has clear placeholders for `DTOOLS_API_KEY`
- Services that depend on D-Tools API log a warning and continue (not crash) when key is missing
- `browser_agent` (port 9091) requires `DTOOLS_EMAIL` + `DTOOLS_PASSWORD` — check these are in `.env` on Bob

### 2.10 iOS / Swift — Sanity Checklist (No Full Rewrite)

Two Xcode projects exist:

| Project | Path | Purpose |
|---------|------|---------|
| **SymphonyTrading** | `ios-app/SymphonyTrading/` | Trading portfolio viewer |
| **SymphonyOps** | `ios-app/SymphonyOps/` | Business ops dashboard |
| **SymphonyMarkup** | `ios-app/SymphonyMarkup/` | iPad markup tool (WebView wrapper) |

**Sanity checks (run on a Mac with Xcode):**

```bash
# Check if projects open without error
cd ~/AI-Server/ios-app/SymphonyTrading
xcodebuild -list -project SymphonyTrading.xcodeproj 2>&1 | head -10

cd ~/AI-Server/ios-app/SymphonyOps
xcodebuild -list -project SymphonyOps.xcodeproj 2>&1 | head -10

# Check API client points to correct host
grep -n "baseURL\|127.0.0.1\|bobs-mac-mini\|localhost\|8420\|8421\|SYMPHONY_API" \
  ~/AI-Server/ios-app/SymphonyTrading/SymphonyTrading/APIClient.swift | head -10

grep -n "baseURL\|127.0.0.1\|bobs-mac-mini\|localhost\|SYMPHONY_API" \
  ~/AI-Server/ios-app/SymphonyOps/SymphonyOps/APIClient.swift | head -10

# Check for hardcoded secrets in Swift files
grep -rn "sk-\|Bearer \|password\|secret\|token.*=" ~/AI-Server/ios-app/ --include="*.swift" \
  | grep -v "SecretsVault\|placeholder\|example\|TODO" | head -10
# Expected: empty (all secrets should be in SecretsVault or Keychain)
```

**Don't do:**
- Full compilation/build (heavyweight, needs provisioning profile)
- UI testing (needs simulator + API running)

**Do verify:**
- `APIClient.swift` points to Tailscale or LAN URL (not hardcoded localhost)
- `SecretsVault.swift` reads from Keychain, not hardcoded
- `Info.plist` has `NSAppTransportSecurity` exceptions if using HTTP
- No API tokens committed in Swift source

---

## 3. Risk & Ordering

### 3.1 Priority Verification Order

Verify these **before** spending time on Wave 9–10 implementation:

| Priority | Task | Why First | Est. Time |
|----------|------|-----------|-----------|
| **P0** | Redis auth + channels | Everything depends on Redis. One bad password = cascading failures. | 5 min |
| **P0** | OpenClaw `/health` + `/api/llm-costs` | Core orchestrator. If this is broken, nothing autonomous works. | 5 min |
| **P0** | Port security scan | `0.0.0.0` bindings = LAN exposure. Verify the April 5 lockdown held. | 2 min |
| **P1** | Polymarket bot imports | Strategy imports break silently. One bad import = strategy doesn't run. | 5 min |
| **P1** | Email monitor BODY.PEEK + dedup | Broken = marking emails as read or sending duplicate notifications. | 5 min |
| **P1** | `smoke-test-full.sh` | Catches container health, API endpoints, Redis auth, watchdog, data integrity. | 3 min |
| **P2** | Ollama LAN reachability | Blocks: LLM router local mode, Apple Notes categorization, learning loop. | 5 min |
| **P2** | Spread arb profitability at ~$50 | Low priority if wallet is small, but bad trades waste gas fees. | 10 min |
| **P3** | D-Tools graceful degradation | Non-critical until D-Tools API key is generated. | 5 min |
| **P3** | iOS sanity | Non-critical until API-10 backend is wired. | 10 min |
| **Defer** | Testimonial collection | Full implementation task, not a verification. Requires symphonysh.com deploy. | — |
| **Defer** | Weather enrichment (API-4) | New code, not broken existing code. Top performer works fine with NOAA/METAR. | — |
| **Defer** | Multi-agent learning (Auto-22) | Depends on Ollama, stable agents, cortex infrastructure. Long build. | — |

### 3.2 Never Commit These

| Secret / File | Where It Lives | Why |
|---------------|---------------|-----|
| `.env` | Bob local only | All API keys, Redis password, Zoho creds, Twilio tokens |
| `redis/redis.conf` | Bob local only, `redis/` is gitignored | Contains `requirepass` |
| `polymarket-bot/vpn/wg0.conf` | Bob local only, `polymarket-bot/vpn/` is gitignored | WireGuard private key |
| Any `sk-...`, `sk-ant-...`, `pplx-...` | `.env` only | OpenAI / Anthropic / Perplexity API keys |
| `TWILIO_AUTH_TOKEN` | `.env` only | Twilio account credential |
| `DTOOLS_EMAIL` / `DTOOLS_PASSWORD` | `.env` only | D-Tools Cloud login |
| `REDIS_PASSWORD` value | `.env` only | Never in docker-compose.yml, never in Python defaults |
| `caller_memory.db` | Runtime only | Contains caller phone numbers and conversation history |
| `google-service-account.json` | Bob local only | Google Calendar service account key |

**Rule:** If `grep -rn "sk-\|password=\|REDIS_PASSWORD=d1" . --include="*.py" --include="*.yml"` returns anything outside `.env.example` or `# comment` lines, that's a leak.

### 3.3 Implementation Order for Wave 9–10

```
Wave 8 verification (Auto-29) ← DO THIS FIRST
    ↓
Auto-28 context preprocessor (verify existing container works)
    ↓
Auto-25 Apple Notes indexer (host-only, no Docker risk)
    ↓
API-4 ensemble weather (enhances top strategy, no breaking changes)
    ↓
API-8 voice receptionist v2 (needs Twilio — external dependency)
    ↓
API-10 mobile API wiring (needs Redis portfolio:snapshot from Auto-21)
    ↓
API-9 client concierge (needs Ollama + ChromaDB + a real client project)
    ↓
Auto-12 ClawWork (revenue generation, but needs stable platform first)
    ↓
Auto-22 multi-agent learning (last — depends on everything above)
    ↓
Wave 10 (API-14, API-15, Auto-24) — only after Wave 9 is stable
```

---

## 4. Copy-Paste Verification Script

Run this single block on Bob. It is **non-destructive** — read-only checks, no writes, no restarts, no rebuilds.

```bash
#!/usr/bin/env bash
# AI-Server Non-Destructive Verification — run on Bob
# Usage: bash verify-readonly.sh
set -uo pipefail

cd ~/AI-Server || { echo "FATAL: ~/AI-Server not found"; exit 1; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    local name="$1" result="$2"
    if [[ "$result" == "PASS" ]]; then
        echo -e "  ${GREEN}✓${NC} $name"; ((PASS++)) || true
    elif [[ "$result" == "WARN" ]]; then
        echo -e "  ${YELLOW}⚠${NC} $name"; ((WARN++)) || true
    else
        echo -e "  ${RED}✗${NC} $name"; ((FAIL++)) || true
    fi
}

echo "========================================="
echo "AI-Server Read-Only Verification"
echo "$(date)"
echo "========================================="

# ── 1. Redis ──────────────────────────────────────────────────────────────────
echo ""
echo "--- Redis ---"
REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env 2>/dev/null | cut -d= -f2- | tr -d '\r')
if [[ -z "$REDIS_PASS" ]]; then
    check "REDIS_PASSWORD in .env" "FAIL"
else
    if docker exec redis redis-cli -a "$REDIS_PASS" ping 2>/dev/null | grep -q PONG; then
        check "Redis auth (PONG)" "PASS"
    else
        check "Redis auth" "FAIL"
    fi
    if docker exec redis redis-cli ping 2>/dev/null | grep -q PONG; then
        check "Redis NO-auth (SHOULD FAIL)" "FAIL"
    else
        check "Redis rejects unauthenticated" "PASS"
    fi
    COST_KEYS=$(docker exec redis redis-cli -a "$REDIS_PASS" KEYS "llm:costs:*" 2>/dev/null | wc -l | tr -d ' ')
    check "llm:costs:* keys: $COST_KEYS" "PASS"
    DRAFT_LEN=$(docker exec redis redis-cli -a "$REDIS_PASS" LLEN email:drafts 2>/dev/null | tr -d ' ')
    check "email:drafts length: $DRAFT_LEN" "PASS"
fi

# ── 2. Port Security ─────────────────────────────────────────────────────────
echo ""
echo "--- Port Security ---"
EXPOSED=$(docker ps --format '{{.Ports}}' 2>/dev/null | grep "0.0.0.0" || true)
if [[ -z "$EXPOSED" ]]; then
    check "All ports 127.0.0.1" "PASS"
else
    check "EXPOSED PORTS: $EXPOSED" "FAIL"
fi

# ── 3. Container Health ──────────────────────────────────────────────────────
echo ""
echo "--- Container Health ---"
for c in redis openclaw email-monitor notification-hub mission-control polymarket-bot \
         context-preprocessor voice-receptionist openwebui remediator vpn \
         calendar-agent proposals dtools-bridge knowledge-scanner x-intake intel-feeds; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${c}$"; then
        health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "no-healthcheck")
        if [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then
            check "$c" "PASS"
        else
            check "$c ($health)" "WARN"
        fi
    else
        check "$c (NOT RUNNING)" "WARN"
    fi
done

# ── 4. API Endpoints ─────────────────────────────────────────────────────────
echo ""
echo "--- API Endpoints ---"
curl -sf http://127.0.0.1:8099/health >/dev/null 2>&1 && check "OpenClaw /health" "PASS" || check "OpenClaw /health" "FAIL"
curl -sf http://127.0.0.1:8099/api/llm-costs >/dev/null 2>&1 && check "OpenClaw /api/llm-costs" "PASS" || check "OpenClaw /api/llm-costs" "WARN"
curl -sf http://127.0.0.1:8092/health >/dev/null 2>&1 && check "Email Monitor /health" "PASS" || check "Email Monitor /health" "FAIL"
curl -sf http://127.0.0.1:8098/health >/dev/null 2>&1 && check "Mission Control /health" "PASS" || check "Mission Control /health" "WARN"
curl -sf http://127.0.0.1:8028/health >/dev/null 2>&1 && check "Context Preprocessor /health" "PASS" || check "Context Preprocessor /health" "WARN"
curl -sf http://127.0.0.1:8430/health >/dev/null 2>&1 && check "Polymarket Bot /health" "PASS" || check "Polymarket Bot /health" "FAIL"

# ── 5. Strategy Imports ──────────────────────────────────────────────────────
echo ""
echo "--- Strategy Imports ---"
docker exec polymarket-bot python3 -c "from strategies.polymarket_copytrade import PolymarketCopytrade; print('OK')" 2>/dev/null \
    && check "PolymarketCopytrade import" "PASS" || check "PolymarketCopytrade import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.weather_trader import CheapBracketStrategy; print('OK')" 2>/dev/null \
    && check "CheapBracketStrategy import" "PASS" || check "CheapBracketStrategy import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.spread_arb import SpreadArbScanner; print('OK')" 2>/dev/null \
    && check "SpreadArbScanner import" "PASS" || check "SpreadArbScanner import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.strategy_manager import StrategyManager; print('OK')" 2>/dev/null \
    && check "StrategyManager import" "PASS" || check "StrategyManager import" "FAIL"
docker exec polymarket-bot python3 -c "from strategies.crypto.avellaneda_market_maker import AvellanedaMarketMaker; print('OK')" 2>/dev/null \
    && check "AvellanedaMarketMaker import" "PASS" || check "AvellanedaMarketMaker import" "FAIL"

# ── 6. Email Monitor Checks ─────────────────────────────────────────────────
echo ""
echo "--- Email Monitor ---"
docker exec email-monitor grep -q "BODY.PEEK" /app/*.py 2>/dev/null \
    && check "BODY.PEEK in monitor" "PASS" || check "BODY.PEEK in monitor" "WARN"
BARE_BODY=$(docker exec email-monitor grep -c "BODY\[" /app/*.py 2>/dev/null | grep -v ":0$" | grep -v "PEEK" || true)
[[ -z "$BARE_BODY" ]] && check "No bare BODY[] fetch" "PASS" || check "Bare BODY[] found" "WARN"

# ── 7. Ollama LAN ───────────────────────────────────────────────────────────
echo ""
echo "--- Ollama LAN ---"
curl -sf http://192.168.1.199:11434/api/tags >/dev/null 2>&1 \
    && check "Ollama reachable from host" "PASS" || check "Ollama NOT reachable from host" "WARN"

# ── 8. Secrets Scan ──────────────────────────────────────────────────────────
echo ""
echo "--- Secrets Scan (should be empty) ---"
LEAKED=$(grep -rn "sk-ant-\|sk-proj-\|pplx-" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.json" \
    . 2>/dev/null | grep -v ".env.example" | grep -v "node_modules" | grep -v ".git/" | grep -v "# " | head -5)
[[ -z "$LEAKED" ]] && check "No leaked API keys in source" "PASS" || check "LEAKED KEYS: $LEAKED" "FAIL"

REDIS_LEAKED=$(grep -rn "d1fff1065992d132b000c01d6012fa52\|requirepass" --include="*.py" --include="*.yml" \
    . 2>/dev/null | grep -v ".git/" | grep -v "redis.conf" | grep -v ".env" | head -5)
[[ -z "$REDIS_LEAKED" ]] && check "No Redis password in source" "PASS" || check "REDIS PASSWORD IN SOURCE: $REDIS_LEAKED" "FAIL"

# ── 9. Watchdog & Bridge ────────────────────────────────────────────────────
echo ""
echo "--- Host Daemons ---"
launchctl list 2>/dev/null | grep -q "com.symphony.bob-watchdog" \
    && check "Watchdog daemon" "PASS" || check "Watchdog daemon" "WARN"
launchctl list 2>/dev/null | grep -q "com.symphony.imessage-bridge" \
    && check "iMessage bridge daemon" "PASS" || check "iMessage bridge daemon" "WARN"

# ── 10. py_compile Spot Checks ──────────────────────────────────────────────
echo ""
echo "--- Syntax Checks (py_compile) ---"
for f in openclaw/main.py openclaw/llm_router.py openclaw/llm_cache.py \
         openclaw/auto_responder.py integrations/x_intake/bridge.py \
         integrations/apple_notes/notes_indexer.py tools/cortex_curator.py; do
    if [[ -f "$f" ]]; then
        python3 -m py_compile "$f" 2>/dev/null \
            && check "py_compile $f" "PASS" || check "py_compile $f" "FAIL"
    else
        check "$f (file not found)" "WARN"
    fi
done

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "========================================="
echo -e "  ${GREEN}PASS: $PASS${NC}  ${YELLOW}WARN: $WARN${NC}  ${RED}FAIL: $FAIL${NC}"
echo "========================================="
```

Save this on Bob as `~/AI-Server/scripts/verify-readonly.sh` and run:
```bash
cd ~/AI-Server && bash scripts/verify-readonly.sh
```
