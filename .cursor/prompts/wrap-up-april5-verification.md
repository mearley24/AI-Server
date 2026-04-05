# Wrap-Up — April 5 Verification & Cleanup Pass

**Priority:** Run NOW — this is the final sweep before moving to Wave 9.
**Purpose:** Fix the 4 remaining issues from `scripts/verify-readonly.sh`, resolve open manual items, update verification report.

**Read each file referenced below before editing. Do not re-implement anything that already works.**

---

## Context Files to Read First

- `cursor-prompts/VERIFICATION_REPORT.md` — current verification status
- `cursor-prompts/BACKLOG_CHECKLIST.md` — full backlog and risk ordering
- `scripts/verify-readonly.sh` — the test script (fix wrong class names here)
- `scripts/smoke-test-full.sh` — comprehensive smoke test (reference)
- `CONTEXT.md` — current system state
- `docker-compose.yml` — service definitions
- `.env.example` — env var documentation

---

## Part 1: Fix verify-readonly.sh Class Names (FAIL → PASS)

The verify script uses wrong class names for two strategy imports. Fix the script — NOT the strategies.

### 1a. PolymarketCopytrade → PolymarketCopyTrader

The actual class is `PolymarketCopyTrader` (capital T in Trader).

In `scripts/verify-readonly.sh`, find:
```bash
docker exec polymarket-bot python3 -c "from strategies.polymarket_copytrade import PolymarketCopytrade; print('OK')"
```
Replace with:
```bash
docker exec polymarket-bot python3 -c "from strategies.polymarket_copytrade import PolymarketCopyTrader; print('OK')"
```

And update the check label from `PolymarketCopytrade import` to `PolymarketCopyTrader import`.

### 1b. CheapBracketStrategy — Find the Real Class Name

Read `polymarket-bot/strategies/weather_trader.py` and find the actual class name. It is NOT `CheapBracketStrategy`. Look for `class ...Strategy` or `class ...Trader` definitions.

Update the verify script to use the correct class name.

### 1c. Also Fix wave-verification-unresolved.md

The same wrong class names appear in `.cursor/prompts/wave-verification-unresolved.md` Part 3 import block. Update those too so future verification passes don't chase ghosts.

---

## Part 2: Context Preprocessor Health (WARN → PASS)

The container is running but has no healthcheck and `/health` returned nothing.

### 2a. Check What's Actually Serving

Read `tools/context_preprocessor/app.py` (or `server.py` — check which exists). Find:
- What port it listens on inside the container
- Whether a `/health` route exists
- Whether the static UI (`templates/index.html`) is being served

### 2b. Add Healthcheck If Missing

If no `/health` endpoint exists, add one:
```python
@app.get("/health")
async def health():
    return {"status": "ok", "service": "context-preprocessor"}
```

### 2c. Add Docker Healthcheck

In `docker-compose.yml`, find the `context-preprocessor` service. If it has no `healthcheck` block, add:
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8028/health >/dev/null || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

Verify the internal port matches what the app actually listens on (8028 vs 8850 — check the Dockerfile and app code).

---

## Part 3: /api/llm-costs Endpoint (WARN → PASS)

`curl http://127.0.0.1:8099/api/llm-costs` returned non-200.

### 3a. Diagnose

Read `openclaw/main.py` and find the `/api/llm-costs` route. Check:
- Is it registered? (search for `llm-costs` or `llm_costs`)
- Does it require Redis? If Redis has no `llm:costs:*` keys yet, does it return an empty response or crash?
- Is there an auth requirement (token header)?

### 3b. Fix Graceful Empty State

The endpoint MUST return valid JSON even when no cost data exists yet:
```json
{
  "today": {"total": 0, "calls": 0},
  "week": {"total": 0, "calls": 0},
  "month": {"total": 0, "calls": 0},
  "cache_stats": {"hits": 0, "misses": 0, "hit_rate": 0},
  "by_service": {},
  "by_model": {},
  "projected_monthly": 0
}
```

If the route crashes when Redis has no keys, wrap the Redis reads in try/except and return the empty state.

---

## Part 4: Spread Arb Low-Balance Guard

Read `polymarket-bot/strategies/spread_arb.py` end to end.

### 4a. Add Minimum Profitable Trade Check

Find where trades are executed (look for `execute`, `place_order`, or `submit`). Before execution, add:

```python
# Minimum profitability guard — skip trades where fees eat the edge
min_profitable = (GAS_FEE * 2) + (SLIPPAGE * opp.cost_usd) + 0.01  # $0.01 min net profit
if opp.expected_profit_usd < min_profitable:
    logger.info("arb_skipped_unprofitable",
                market=opp.market_title,
                expected_profit=opp.expected_profit_usd,
                min_required=min_profitable,
                reason="fees exceed edge")
    continue
```

### 4b. Add Balance Check Before Execution

If there isn't already a balance check before placing orders:

```python
# Check available balance before attempting trade
available = await self._get_available_balance()
if available < opp.cost_usd:
    logger.info("arb_skipped_low_balance",
                market=opp.market_title,
                cost=opp.cost_usd,
                available=available)
    continue
```

### 4c. Add LOW_BALANCE_MODE Environment Variable

```python
LOW_BALANCE_MODE = os.environ.get("LOW_BALANCE_MODE", "false").lower() in ("true", "1", "yes")
```

When enabled:
- Double the minimum edge requirement (`MIN_COMPLEMENT_SPREAD *= 2`)
- Reduce scan frequency (5min → 15min)
- Skip contrarian bounce strategy entirely (too risky with small bankroll)
- Log: `logger.info("low_balance_mode_active", balance=available)`

Add `LOW_BALANCE_MODE=false` to `.env.example` with a comment.

---

## Part 5: D-Tools Graceful Degradation

### 5a. Check integrations/dtools/

Read `integrations/dtools/dtools_client.py` and `dtools_server.py`. Find where `DTOOLS_API_KEY` is read.

If the code crashes when the key is missing, wrap the initialization:

```python
DTOOLS_API_KEY = os.environ.get("DTOOLS_API_KEY", "")

if not DTOOLS_API_KEY or DTOOLS_API_KEY == "your-api-key-here":
    logger.warning("dtools_api_key_missing",
                   msg="D-Tools API key not configured — running in stub mode")
    # Set a flag so all API calls return graceful empty responses
    DTOOLS_STUB_MODE = True
```

### 5b. Check browser_agent Service

Read `agents/dtools_browser_agent.py`. Verify it checks for `DTOOLS_EMAIL` and `DTOOLS_PASSWORD` at startup and logs a clear warning (not crash) if missing.

### 5c. Verify .env.example

Confirm these placeholders exist in the root `.env.example`:
- `DTOOLS_API_KEY=your-api-key-here`
- `DTOOLS_EMAIL=your-dtools-email`
- `DTOOLS_PASSWORD=your-dtools-password`

If any are missing, add them under the `# 6. D-Tools Cloud` section.

---

## Part 6: Update VERIFICATION_REPORT.md

After completing Parts 1–5, rewrite `cursor-prompts/VERIFICATION_REPORT.md`:

```markdown
# Wave Verification Report

**Date:** 2026-04-05 (final pass)
**Repo:** `/Users/bob/AI-Server`
**Overall status:** ✓ VERIFIED

## verify-readonly.sh Results

| Check | Result | Notes |
|-------|--------|-------|
| Redis auth | PASS | PONG with auth, rejected without |
| Redis rejects unauthenticated | PASS | |
| Port security | PASS | All 127.0.0.1 (MC fixed) |
| All containers healthy | PASS | 17/17 running |
| OpenClaw /health | PASS | |
| OpenClaw /api/llm-costs | PASS/FAIL | (update after fix) |
| Email Monitor /health | PASS | |
| Context Preprocessor /health | PASS/FAIL | (update after fix) |
| Polymarket Bot /health | PASS | |
| PolymarketCopyTrader import | PASS | (class name fixed in script) |
| WeatherTrader import | PASS | (class name fixed in script) |
| SpreadArbScanner import | PASS | |
| StrategyManager import | PASS | |
| AvellanedaMarketMaker import | PASS | |
| BODY.PEEK in email-monitor | PASS | |
| Ollama reachable from host | PASS | 192.168.1.199:11434 |
| No leaked API keys | PASS | notes_analysis.json scrubbed |
| No Redis password in source | PASS | |
| Watchdog / watcher daemon | PASS/WARN | (document what com.symphony.watcher does) |
| py_compile all key files | PASS | 7/7 |

## Open Items (deferred to Wave 9+)

| Item | Status | Notes |
|------|--------|-------|
| API-4 Ensemble Weather | NOT STARTED | ecmwf_client.py and gfs_client.py don't exist yet |
| Testimonial collection | NOT STARTED | Prompt exists, code never generated |
| Multi-agent learning | PARTIAL | Supporting files exist, learning loop not wired |
| Voice receptionist v2 | BLOCKED | Needs Twilio account setup |
| Mobile API wiring | BLOCKED | Needs portfolio:snapshot in Redis |

## Security Actions Taken (April 5)

- Leaked OpenAI key scrubbed from knowledge/state/notes_analysis.json
- Key rotated in OpenAI dashboard
- New key deployed to .env on Bob
- All ports locked to 127.0.0.1
- Redis auth enforced, unauthenticated rejected
- Secrets scan: PASS (no keys in source)
```

Update the table with actual results after running each fix.

---

## Part 7: Commit & Push

```bash
git add -A
git commit -m "wrap-up: fix verify script class names, context-preprocessor healthcheck, llm-costs graceful empty, spread-arb low-balance guard, dtools graceful degrade, verification report final"
git push origin main
```

Then run the full verification to confirm:
```bash
bash scripts/verify-readonly.sh
bash scripts/smoke-test-full.sh
```

Both should return 0 FAIL.

---

## Rules (same as always)

- **Read before writing.** Every file listed in Context Files must be read before any edits.
- **Do not re-implement.** If something works, leave it alone. Fix only what's broken.
- **No secrets in code.** All credentials come from `.env` via `os.environ.get()`. Never hardcode.
- **Config change = rebuild.** Any file baked into a Docker image needs `docker compose up -d --build [service]`.
- **Test your changes.** Run the relevant import or curl check after each fix. Don't commit blind.
