# Symphony Full Stack Fix — Single Cline Prompt (7 Parts, Run Sequentially)

Read `.clinerules` for project context first. Work ONLY in `/Users/bob/AI-Server/`. Do NOT create worktrees. Execute each Part in order — commit after each Part before moving to the next.

---

## PART 1: REDEEMER — RECOVER STUCK MONEY (PRIORITY)

**Why:** ~$700 in resolved positions stuck on-chain. 6 bugs in `polymarket-bot/src/redeemer.py` preventing redemption.

### Bug 1: neg-risk field name mismatch
The Polymarket Data API returns `neg_risk` (underscore) but the redeemer reads `negativeRisk` (camelCase). Multi-outcome neg-risk markets silently go through the wrong (standard CTF) redemption path and revert.

In `redeem_all_winning()` around line 456, find:
```python
is_neg_risk = pos.get("negativeRisk", False)
```
Change to:
```python
is_neg_risk = pos.get("neg_risk", pos.get("negativeRisk", False))
```

Also do the same at any other place `negativeRisk` is read from position data. Search the entire file for `negativeRisk` and add the `neg_risk` fallback everywhere.

### Bug 2: outcomeIndex defaults to -1
Around line 366:
```python
outcome_index = pos.get("outcomeIndex", -1)
```
Python interprets `-1` as the last array element. For a 2-outcome market with payout_numerators `[1, 0]`, index `-1` returns `0` (the losing payout), so the redeemer thinks you lost even though you won.

Change BOTH occurrences (line ~366 and line ~457) to:
```python
outcome_index = int(pos.get("outcomeIndex", 0))
```

And add a guard before the payout lookup (around line 399):
```python
if outcome_index < 0 or outcome_index >= len(payout_nums):
    logger.warning("redeemer_invalid_outcome_index", condition_id=condition_id[:20], outcome_index=outcome_index, payout_count=len(payout_nums))
    continue
```

### Bug 3: Gas ceiling at 300 Gwei too aggressive
Line 134:
```python
MAX_GAS_PRICE_GWEI = 300
```
Polygon regularly spikes to 300+ Gwei during normal congestion. This skips entire redemption cycles.

Change to:
```python
MAX_GAS_PRICE_GWEI = 800  # Polygon can spike; 800 Gwei is still < $0.05 per tx
```

### Bug 4: No gas token check
The redeemer never checks if the wallet has enough POL/MATIC for gas. If POL is zero, every redemption tx fails with an unhelpful error.

Add at the top of `redeem_all_winning()`, right after the gas price check (after line ~332):
```python
# Check gas token balance
matic_balance = self._get_matic_balance()
if matic_balance < 0.05:
    logger.warning("redeemer_low_gas", matic_balance=round(matic_balance, 4))
    return {"error": "insufficient_gas_token", "matic_balance": round(matic_balance, 4)}
```

### Bug 5: Silent field skips
When `conditionId` or `asset` is missing from a position, the redeemer silently `continue`s with no log. Positions vanish from processing without any trace.

Around line 368, change:
```python
if not condition_id or not asset:
    continue
```
To:
```python
if not condition_id or not asset:
    logger.debug("redeemer_skip_missing_fields", title=pos.get("title", "?")[:40], has_cid=bool(condition_id), has_asset=bool(asset))
    continue
```

### Bug 6: Add nonce delay between sequential redemptions
The 2-second sleep (line ~478) is sometimes not enough. Increase and add nonce retry:

Replace the redemption loop block (around lines 450-485) with:
```python
for pos in unique:
    condition_id = pos["conditionId"]
    title = pos.get("title", "")[:50]
    value = pos.get("_expected_usdc", 0)

    for attempt in range(3):
        try:
            is_neg_risk = pos.get("neg_risk", pos.get("negativeRisk", False))
            outcome_index = int(pos.get("outcomeIndex", 0))
            token_balance_raw = int(pos.get("_token_balance", 0) * 1e6)
            tx_hash = await self._redeem_single(
                condition_id,
                neg_risk=is_neg_risk,
                outcome_index=outcome_index,
                token_balance=token_balance_raw,
            )
            if tx_hash:
                self._redeemed_conditions.add(condition_id)
                self._save_redeemed()
                redeemed_count += 1
                logger.info(
                    "redeemer_redeemed",
                    title=title,
                    value=round(value, 2),
                    tx_hash=tx_hash,
                )
            break  # Success, move to next position
        except Exception as exc:
            err_msg = str(exc)
            if "nonce" in err_msg.lower() and attempt < 2:
                logger.warning("redeemer_nonce_retry", attempt=attempt + 1, error=err_msg[:80])
                self._next_nonce = None  # Force nonce refresh
                await asyncio.sleep(5)
                continue
            self._next_nonce = None
            errors.append({"condition_id": condition_id[:20], "error": err_msg[:80]})
            logger.error("redeemer_redeem_error", title=title, error=err_msg[:120])
            break

    await asyncio.sleep(4)  # 4s between redemptions for nonce propagation
```

### Add force-redeem API endpoint
In `polymarket-bot/src/api.py` (or wherever the FastAPI routes are defined), add:
```python
@app.post("/redeem/force")
async def force_redeem():
    """Trigger immediate redemption cycle."""
    if not hasattr(app.state, "redeemer") or not app.state.redeemer:
        return {"error": "redeemer not initialized"}
    result = await app.state.redeemer.redeem_all_winning()
    return result
```

Find where the redeemer instance is created during startup and store it on `app.state.redeemer`. If there's already a reference, just wire the endpoint. Search for `PolymarketRedeemer` instantiation.

### Verification — Part 1
```bash
python3 -m py_compile polymarket-bot/src/redeemer.py && echo "PART 1 COMPILE OK"
grep 'neg_risk.*negativeRisk' polymarket-bot/src/redeemer.py && echo "neg_risk fallback present"
grep 'outcomeIndex.*0)' polymarket-bot/src/redeemer.py && echo "outcomeIndex default fixed"
grep 'MAX_GAS_PRICE_GWEI = 800' polymarket-bot/src/redeemer.py && echo "gas ceiling raised"
grep 'matic_balance < 0.05' polymarket-bot/src/redeemer.py && echo "gas check added"
git add -A && git commit -m "fix: redeemer — 6 bugs fixed, nonce retry, force-redeem endpoint"
```

---

## PART 2: PROFITABILITY TIGHTENING

**Why:** Bot is -25.3% ROI ($-1,322 over 12 days). Only 5-35c entries are profitable. Sports -37.7%, politics -77.1%.

All changes in `polymarket-bot/strategies/polymarket_copytrade.py` and `polymarket-bot/strategies/exit_engine.py` and `polymarket-bot/src/config.py`.

### 2a. Weather max entry: 25c → 15c
Find `CATEGORY_MAX_ENTRY` dict. Change `"weather": 0.25` to `"weather": 0.15`. The most profitable bracket is 5-15c.

### 2b. Kill LLM override on blacklisted categories
Search for where blacklisted categories can be overridden by high LLM score or high-conviction wallets. There's likely a section where `CATEGORY_TIERS["blacklist"]` is checked but then bypassed if `llm_score > threshold` or wallet is in priority list. Remove or disable that bypass:
```python
# If category is blacklisted, NEVER allow — no LLM or wallet override
if category_tier == "blacklist":
    logger.info("copytrade_skip", reason="category_blacklisted", category=category)
    return False
```
Make sure this check happens BEFORE the LLM and priority wallet checks.

### 2c. Halve position sizes
Find `copytrade_size_usd` default. It should currently be around $3-5. Set it to $2.0:
In `src/config.py`:
```python
copytrade_size_usd: float = Field(default=2.0, description="Base USD size per copied trade")
```

### 2d. Daily loss halt: $25 → $15
In `src/config.py`:
```python
copytrade_daily_loss_limit: float = Field(default=15.0, description="Max net daily loss before halting trades")
```
Also update the matching default in `polymarket_copytrade.py` if there's a separate default there.

### 2e. Fix category P&L seeds
Search for hardcoded P&L values (likely a dict with specific dollar amounts for each category, dated around March 28). These fake seeds reset real performance tracking on every restart. Replace with:
```python
# Start from zero — let real data accumulate
self._category_pnl = defaultdict(float)
```
Or if there's a persistence mechanism, make sure it loads from Redis/disk instead of hardcoded values.

### 2f. Fix fabricated priority wallet stats
Search for where priority wallets (like @tradecraft, @coldmath, etc.) get injected with fake win rates or stats. Remove the injection — let real trade data determine wallet quality.

### 2g. Fix neg_risk in copy orders
Search `polymarket_copytrade.py` for where orders are placed (the actual CLOB order creation). Check if `neg_risk` is being set correctly. If it's hardcoded to `False` or missing the underscore variant, fix it:
```python
neg_risk = market_data.get("neg_risk", market_data.get("negativeRisk", False))
```

### 2h. Extend quiet hours
Find the quiet hours / time restriction section. If it currently blocks trading during certain hours, extend it to also block 12am-6am UTC (high-spread, low-liquidity period).

### 2i. Max trades per hour: 20 → 8, min trade gap: 10s → 30s
```python
self._max_trades_per_hour: int = int(os.environ.get("MAX_TRADES_PER_HOUR", "8"))
self._min_trade_gap: float = 30.0
```

### 2j. Max positions: 100 → 30
```python
self._max_positions: int = getattr(settings, "copytrade_max_positions", 30)
```
And in `src/config.py`:
```python
copytrade_max_positions: int = Field(default=30, description="Max concurrent copied positions")
```

### 2k. Exit engine — let cheap brackets ride, tighter trailing
In `strategies/exit_engine.py`, add before the stop-loss check in `evaluate()`:
```python
# HOLD RULE: cheap entries (< 25c) get 6 hours before any stop-loss
cheap_entry = entry < 0.25
if cheap_entry and hold_hours < 6.0 and pnl_pct > -0.80:
    return None  # Hold unless down 80%+
```

Update near-resolution take-profit threshold:
```python
near_resolution_price = 0.85  # was 0.92 — lock gains earlier
```

### Verification — Part 2
```bash
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py && python3 -m py_compile polymarket-bot/strategies/exit_engine.py && python3 -m py_compile polymarket-bot/src/config.py && echo "PART 2 COMPILE OK"
grep '"weather": 0.15' polymarket-bot/strategies/polymarket_copytrade.py && echo "weather cap at 15c"
grep 'category_blacklisted' polymarket-bot/strategies/polymarket_copytrade.py && echo "blacklist enforcement present"
grep 'daily_loss_limit.*15' polymarket-bot/src/config.py && echo "daily loss at 15"
grep 'cheap_entry' polymarket-bot/strategies/exit_engine.py && echo "cheap bracket hold rule present"
git add -A && git commit -m "fix: profitability — tighten caps, kill blacklist bypass, halve sizes, fix exits"
```

---

## PART 3: SPREAD_ARB EXPOSURE LEAK

**Why:** `polymarket-bot/strategies/spread_arb.py` — the positions dict never clears. Exposure grows monotonically until it hits limits and the strategy dies.

Find the positions tracking dict (likely `self._positions` or `self._active_positions`). Add cleanup logic:
1. Remove positions when they're closed/exited
2. Add a periodic cleanup that removes positions older than 24 hours
3. Clear the dict on strategy restart

```python
# In the main loop or after each trade cycle:
now = time.time()
stale_keys = [k for k, v in self._positions.items() if now - v.get("entered_at", 0) > 86400]
for k in stale_keys:
    del self._positions[k]
    logger.info("spread_arb_cleared_stale", position_id=k)
```

Also ensure that when a position is exited (sold), it's removed from the dict immediately.

### Verification — Part 3
```bash
python3 -m py_compile polymarket-bot/strategies/spread_arb.py && echo "PART 3 COMPILE OK"
grep 'stale_keys\|cleared_stale\|del self._positions' polymarket-bot/strategies/spread_arb.py && echo "cleanup present"
git add -A && git commit -m "fix: spread_arb — clear stale positions, prevent exposure leak"
```

---

## PART 4: PRESOLUTION_SCALP LLM FALLBACK

**Why:** `polymarket-bot/strategies/presolution_scalp.py` — when the LLM is unavailable, the fallback approves ALL trades instead of rejecting them.

Find the LLM call and its exception handler. The fallback on LLM failure should REJECT, not approve:

```python
except Exception as e:
    logger.warning("presolution_llm_unavailable", error=str(e)[:80])
    return False  # REJECT when LLM is down — don't approve blind trades
```

Search for any `return True` in exception handlers related to LLM/AI scoring. All should be `return False`.

### Verification — Part 4
```bash
python3 -m py_compile polymarket-bot/strategies/presolution_scalp.py && echo "PART 4 COMPILE OK"
git add -A && git commit -m "fix: presolution_scalp — reject trades when LLM unavailable"
```

---

## PART 5: ARCHITECTURAL CLEANUP

### 5a. Remove hardcoded Redis password
Search the entire codebase for hardcoded Redis passwords:
```bash
grep -rn "redis.*password\|REDIS_PASSWORD" --include="*.py" polymarket-bot/
```
Any hardcoded passwords should be replaced with `os.environ.get("REDIS_PASSWORD", "")` or read from the `.env` file. The Redis URL should come from `REDIS_URL` env var.

### 5b. Wire ExecutionSandbox
Find `ExecutionSandbox` class — it exists but isn't enforced. All trade execution should route through it. Check if trades are bypassing it by going directly to CLOB clients. If so, wire them through the sandbox.

### 5c. Fix bankroll refresh timing
The bankroll refreshes at inconsistent times, sometimes mid-trade. Find the bankroll refresh logic and ensure it only refreshes:
1. At the start of each tick (before any trade decisions)
2. After all trades in a tick complete
3. Never during trade execution

### Verification — Part 5
```bash
grep -rn "redis.*hardcoded\|password.*=.*\"[a-zA-Z]" --include="*.py" polymarket-bot/ | grep -v "environ\|getenv\|\.env" | head -5
echo "If no output above, hardcoded passwords are gone"
git add -A && git commit -m "fix: architectural cleanup — Redis creds, sandbox enforcement, bankroll timing"
```

---

## PART 6: ACTIVATE OPERATIONS — JOBS DB + BRIEFING

**Why:** The jobs DB is empty. D-Tools sync sees 100 opportunities but creates zero jobs. Follow-up tracker, payment tracker, and proposal checker are all dead because they depend on jobs existing. Daily briefing also broken.

### 6a. Auto-create jobs from D-Tools Won opportunities
Edit `openclaw/dtools_sync.py`. At the block around line 150 where it logs "no active job", add:
```python
if opp.get("status") == "Won" and self._job_mgr:
    # Check for duplicate first
    existing = self._job_mgr.find_by_source_id(str(opp.get("id", ""))) if hasattr(self._job_mgr, 'find_by_source_id') else None
    if not existing:
        job_data = {
            "title": f"{client_name} — {project_name}",
            "client_name": client_name,
            "source": "dtools",
            "source_id": str(opp.get("id", "")),
            "status": "active",
            "value": opp.get("amount", 0),
            "address": project_name,
        }
        try:
            job_id = self._job_mgr.create_job(job_data)
            logger.info("Auto-created job %s from D-Tools Won opp: %s ($%.0f)", job_id, client_name, opp.get("amount", 0))
        except Exception as e:
            logger.warning("Failed to auto-create job: %s", e)
```

Check the actual `JobLifecycleManager` class for correct method names and required fields. Adapt accordingly.

### 6b. Fix daily briefing DB path
Edit `openclaw/daily_briefing.py`:
```python
def find_email_db():
    paths = [
        os.environ.get("EMAIL_DB_PATH", ""),
        "/Users/bob/AI-Server/data/email-monitor/emails.db",
        "/app/data/email-monitor/emails.db",
        "/data/emails.db",
    ]
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None
```

### 6c. Print the fixed crontab command (don't edit crontab directly)
Print this for the user:
```
UPDATED CRONTAB LINE:
0 12 * * * cd /Users/bob/AI-Server && set -a && source .env && set +a && /opt/homebrew/bin/python3 openclaw/daily_briefing.py >> /tmp/briefing.log 2>&1
```

### Verification — Part 6
```bash
python3 -m py_compile openclaw/dtools_sync.py && python3 -m py_compile openclaw/daily_briefing.py && echo "PART 6 COMPILE OK"
grep 'Auto-created job' openclaw/dtools_sync.py && echo "job creation present"
grep 'find_email_db' openclaw/daily_briefing.py && echo "DB path fallback present"
git add -A && git commit -m "fix: activate operations — auto-create jobs from D-Tools, fix briefing DB path"
```

---

## PART 7: MISSION CONTROL — TRADING-FIRST REDESIGN

**Why:** Mission Control currently shows ops noise (email queue, calendar, AI employee cards) as the primary view. It should be a trading dashboard.

Edit `mission_control/static/index.html`.

### Layout: 3-column trading-first
- **Left column (250px):** Portfolio summary — wallet balance (USDC.e + USDC), total position value, daily P&L, 7-day P&L
- **Center column (flex):** Positions table (sortable by value, P&L%, category) + Chart.js line chart showing P&L over time
- **Right column (300px):** Live activity feed (WebSocket) showing recent trades, redemptions, strategy decisions

### New backend endpoints needed
Add to `mission_control/app.py` (or the main Flask/FastAPI file):

1. `GET /api/wallet` — reads from Redis `portfolio:snapshot` or calls the polymarket-bot API
2. `GET /api/pnl-series` — reads P&L time-series from Redis or aggregates from trade history
3. `GET /api/positions` — returns current positions with live prices
4. `GET /api/activity` — returns recent activity log entries

Each endpoint should gracefully return empty data if the polymarket-bot is down.

### Frontend
- Use vanilla JS (no frameworks) — keep it consistent with existing code
- Chart.js for the P&L line chart (CDN include)
- Auto-refresh every 30 seconds
- WebSocket connection for live activity feed (connect to existing WS if available, or poll `/api/activity`)
- Dark theme: true black `#000`, cards `#1c1c1e`, accent teal `#2dd4bf`
- Font: `-apple-system, 'SF Pro Display', 'Inter', system-ui, sans-serif`

### Move ops to /ops route
All existing ops content (email queue, calendar, system stats, AI employee cards, service health) should be accessible at `/ops` but NOT on the main `/` route. Create a simple tab or link to switch between Trading and Ops views.

### Delete redundant files
Check for `trading.html`, `dashboard.html`, or other duplicate dashboard files in `mission_control/static/`. Delete any that are no longer the primary view.

### Verification — Part 7
```bash
python3 -m py_compile mission_control/app.py 2>/dev/null; echo "MC compile check done"
grep 'wallet\|pnl-series\|positions\|activity' mission_control/app.py | head -5
git add -A && git commit -m "feat: mission control — trading-first redesign with 3-column layout"
```

---

## FINAL: REBUILD AND DEPLOY ALL

After all 7 parts are committed:

```bash
cd /Users/bob/AI-Server
bash scripts/pull.sh
docker compose build --no-cache polymarket-bot mission-control openclaw
docker compose up -d polymarket-bot mission-control openclaw
sleep 30
echo "=== REDEEMER STATUS ==="
docker logs polymarket-bot 2>&1 | grep -i "redeem" | tail -10
echo "=== JOBS ==="
docker logs openclaw 2>&1 | grep -i "auto-created\|job" | tail -10
echo "=== MISSION CONTROL ==="
curl -s http://localhost:8098/api/wallet 2>/dev/null | head -3 || echo "MC wallet endpoint not responding yet"
echo "=== POLYMARKET BOT HEALTH ==="
docker logs polymarket-bot 2>&1 | tail -5
echo ""
echo "DEPLOY COMPLETE. Check Mission Control at http://192.168.1.189:8098"
```

Push everything:
```bash
git push origin main
```
