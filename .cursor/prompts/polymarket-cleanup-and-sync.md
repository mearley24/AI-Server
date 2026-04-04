# Polymarket — Full Position Cleanup, Redemption Fix, and Portfolio Sync

## Current State (Broken)
- **100 on-chain positions** worth $621 total
- **Only 28 internally tracked** — the bot only knows about 28 of its 100 positions
- **71 orphan positions** detected but never adopted back into tracking
- **122 orphans in orphan_positions.json** growing every tick
- **$506 drift** between internal bankroll ($122) and on-chain value ($629)
- **Redeemer found 2 redeemable** but failed 1 due to nonce collision (sequential tx sent too fast)
- **4 positions show as "redeemable"** on Polymarket API but 3 are worth $0 (already redeemed or lost)
- **36 positions at 95¢+ or 5¢-** are effectively resolved but can't be redeemed until Polymarket officially closes them

## Root Causes

### 1. Orphans are detected but never adopted
The reconciliation at line ~2476 in `strategies/polymarket_copytrade.py` detects orphan positions (on-chain but not tracked) and saves them to `orphan_positions.json`, but **never creates internal CopytradePosition objects for them**. The orphan list just grows forever.

**Fix:** When an orphan is detected, create an internal position entry so the exit engine and redeemer can manage it:
```python
# After detecting orphan, adopt it into self._positions
if orphan_pos and orphan_value > 0.5:  # Skip dust
    adopted_pos = CopytradePosition(
        position_id=f"adopted-{orphan_cid[:12]}",
        condition_id=orphan_cid,
        token_id=str(orphan_token),
        market_slug=orphan_pos.get("slug", ""),
        question=orphan_pos.get("title", "Unknown"),
        outcome="Yes" if orphan_pos.get("outcomeIndex", 0) == 0 else "No",
        buy_price=float(orphan_pos.get("avgPrice", 0) or 0),
        size_shares=float(orphan_pos.get("size", 0) or 0),
        size_usd=orphan_value,
        source_wallet="adopted",
        entered_at=time.time(),
    )
    self._positions[adopted_pos.position_id] = adopted_pos
    logger.info("orphan_adopted", position_id=adopted_pos.position_id, 
                title=adopted_pos.question[:50], value=orphan_value)
    stats["adopted"] = stats.get("adopted", 0) + 1
```

Check the actual `CopytradePosition` dataclass fields and match them. The key fields are condition_id, token_id, and size_shares.

### 2. Redeemer nonce collisions
The redeemer sends redemption transactions sequentially but doesn't wait for the previous nonce to confirm before sending the next. When two txs fire back-to-back, the second gets "nonce too low".

**Fix in `src/redeemer.py`:** After each successful redemption, add a short delay and refresh the nonce:
```python
# In the redemption loop (around line 410-440), after each successful redeem:
await asyncio.sleep(3)  # Wait for nonce to propagate
```

Also, wrap each redemption in a retry with nonce refresh:
```python
for attempt in range(3):
    try:
        tx_hash = await self._redeem_position(condition_id, ...)
        break
    except Exception as e:
        if "nonce too low" in str(e).lower():
            await asyncio.sleep(5)  # Wait for chain to catch up
            continue
        raise
```

### 3. Zero-value "redeemable" positions clogging the queue
The redeemer fetches positions flagged as redeemable but some have $0 value (already claimed or lost). These waste gas and cause nonce issues.

**Fix:** In `redeem_all_winning()`, add a minimum value filter:
```python
# When checking on-chain token balance, skip if balance is 0
if token_balance_raw == 0:
    self._redeemed_conditions.add(condition_id)  # Mark as done so we stop checking
    continue
```

Also add the Data API `currentValue` check before even doing on-chain verification:
```python
current_value = float(pos.get("currentValue", 0) or 0)
if current_value < 0.01:
    self._redeemed_conditions.add(condition_id)
    continue
```

### 4. Bankroll is $122 when on-chain value is $629
The internal bankroll tracks only USDC.e cash, not position value. But when it reconciles, it oscillates between cash-only and cash+positions.

**Fix in the reconciliation:** The bankroll should ONLY be USDC.e cash (for position sizing). But the bot needs a separate `portfolio_value` that includes positions:
```python
# In _reconcile_pnl, after computing on_chain_value:
self._portfolio_value = round(on_chain_value + onchain_usdc, 2)
# Log portfolio value separately from bankroll
logger.info("portfolio_value_updated", 
    cash=round(onchain_usdc, 2),
    positions=round(on_chain_value, 2), 
    total=self._portfolio_value)
```

Make sure `get_status()` returns both:
```python
"bankroll": self._bankroll,  # USDC.e cash for sizing
"portfolio_value": getattr(self, '_portfolio_value', self._bankroll),  # Total value
"open_positions": len(self._positions),
```

### 5. Position syncer not persisting to Redis
Check `src/position_syncer.py` — it writes to `portfolio:snapshot` in Redis. Verify it's actually being called in the main loop. Search for where `sync_positions` or `persist_snapshot_redis` is called. If it's not in the main bot loop, add it:

In `strategies/polymarket_copytrade.py`, in the main tick (around line 575 where it says "Main loop"):
```python
# After reconciliation, sync to Redis for Mission Control
try:
    from src.position_syncer import sync_positions, persist_snapshot_redis
    snap = await sync_positions(self._clob_client)
    persist_snapshot_redis(snap)
except Exception as e:
    logger.debug("position_sync_redis_error", error=str(e)[:80])
```

### 6. Clean up stale orphan_positions.json
After adopting orphans into tracking, remove them from the orphan file:
```python
# After adoption loop, remove adopted orphans from file
remaining_orphans = [o for o in orphan_records if o["condition_id"] not in adopted_cids]
_save_orphans(remaining_orphans)
```

Also add a periodic cleanup — remove orphans that:
- Have `estimated_value` of 0 (worthless)
- Were detected more than 7 days ago (stale)
- Have been resolved and redeemed

## Task Summary

### File: `polymarket-bot/strategies/polymarket_copytrade.py`
1. **Adopt orphans** into internal tracking (not just log them)
2. **Clean orphan file** after adoption, remove stale/zero-value entries
3. **Add portfolio_value** tracking separate from bankroll
4. **Call position syncer** to persist snapshot to Redis after reconciliation
5. **Update get_status()** to return portfolio_value and position count accurately

### File: `polymarket-bot/src/redeemer.py`
1. **Add nonce delay** — 3s sleep between sequential redemption transactions
2. **Add nonce retry** — retry up to 3x on "nonce too low" errors
3. **Skip zero-value positions** — mark them as redeemed so they stop appearing
4. **Skip low-value positions** — don't waste gas on < $0.50 redemptions
5. **Persist redeemed_conditions** to disk so they survive restarts

### File: `polymarket-bot/src/position_syncer.py`
1. **Verify Redis connection** — the URL might be wrong (needs container IP, not localhost)
2. **Verify sync_positions** is called — if not in the main loop, add it
3. **Include orphan/adopted position data** in the snapshot

## Verification

After changes, rebuild and test:
```bash
docker compose build --no-cache polymarket-bot && docker compose up -d polymarket-bot
sleep 60
echo "=== RECONCILIATION ==="
docker logs polymarket-bot 2>&1 | grep -i "reconcil\|orphan\|adopted\|portfolio_value\|drift" | tail -15
echo "=== REDEEMER ==="
docker logs polymarket-bot 2>&1 | grep -i "redeem" | tail -10
echo "=== POSITIONS ==="
docker logs polymarket-bot 2>&1 | grep -i "internal_positions\|on_chain\|portfolio" | tail -5
echo "=== REDIS ==="
docker exec redis redis-cli GET portfolio:snapshot | python3 -m json.tool | head -10
```

Expected after fix:
- `internal_positions` should match or be close to `on_chain_positions` (not 28 vs 99)
- `drift` should be < $10 (not $506)
- Orphan file should shrink as positions get adopted
- Redeemer should successfully redeem multiple positions without nonce errors
- Redis `portfolio:snapshot` should have current data
