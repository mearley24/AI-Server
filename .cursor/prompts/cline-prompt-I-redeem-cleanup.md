# Cline Prompt I: Redeem Unredeemed Wins + Position Cleanup

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push after completion.

## Context

As of April 11, the wallet (`0xa791e3090312981a1e18ed93238e480a03e7c0d2`) has:
- 48 resolved winning positions worth ~$187.52 sitting unredeemed
- 37 resolved losses with $66.93 in sunk token value (dust)
- 22 dust positions (tiny amounts not worth redeeming individually)

The `src/redeemer.py` module (672 lines) handles on-chain redemption by calling `redeemPositions` on the ConditionalTokens contract. The copytrade module also has `_check_and_redeem_positions` but it only logs `needs_manual_redemption` without actually redeeming.

## Step 1: Verify the redeemer is actually running

```bash
docker logs polymarket-bot 2>&1 | grep -i "redeem" | tail -20
```

Check for:
- `redeemer_enabled` at startup (means it initialized)
- `redeemer_check` or `redeemer_fetched_positions` (means it's scanning)
- `redeemer_redeemed` or `redeem_tx` (means it's actually redeeming)
- Any errors like `redeemer_error`, `redeem_failed`, `nonce_error`

## Step 2: Diagnose why positions are not being redeemed

Run this diagnostic inside the container:

```bash
docker exec polymarket-bot python -c "
import httpx, json

wallet = '0xa791e3090312981a1e18ed93238e480a03e7c0d2'
r = httpx.get('https://data-api.polymarket.com/positions', params={'user': wallet})
positions = r.json()

redeemable = 0
resolved_wins = 0
dust = 0
total_redeemable_value = 0

for p in positions:
    cur_price = float(p.get('curPrice', 0) or 0)
    current_value = float(p.get('currentValue', 0) or 0)
    redeemable_flag = p.get('redeemable', False)
    size = float(p.get('size', 0) or 0)
    
    if redeemable_flag and current_value > 0:
        redeemable += 1
        total_redeemable_value += current_value
        if redeemable <= 5:
            print(f'  REDEEMABLE: {p.get(\"title\", \"\")[:50]} value=\${current_value:.2f} price={cur_price}')
    elif cur_price == 1.0 and current_value > 0:
        resolved_wins += 1
    elif current_value < 0.50:
        dust += 1

print(f'')
print(f'Total positions: {len(positions)}')
print(f'Redeemable (API flag): {redeemable} (value: \${total_redeemable_value:.2f})')
print(f'Resolved wins (price=1.0): {resolved_wins}')
print(f'Dust (<\$0.50): {dust}')
"
```

## Step 3: Force a redemption cycle

If the redeemer is running but not redeeming, trigger it manually:

```bash
docker exec polymarket-bot python -c "
import asyncio
from src.redeemer import PolymarketRedeemer
import os

redeemer = PolymarketRedeemer(
    private_key=os.environ['POLY_PRIVATE_KEY'],
    check_interval=60,
    data_dir=os.environ.get('DATA_DIR', '/data'),
)

async def run():
    result = await redeemer.check_and_redeem()
    print(f'Redemption result: {result}')

asyncio.run(run())
"
```

If this errors, read the error carefully -- common issues:
- `nonce too low` -- another tx is pending, wait and retry
- `insufficient funds for gas` -- need POL for gas (check POL balance)
- `execution reverted` -- condition not actually resolved yet, or wrong index sets

## Step 4: Check POL balance for gas

Redemption tx needs POL (formerly MATIC) for gas:

```bash
docker exec polymarket-bot python -c "
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://polygon-bor-rpc.publicnode.com'))
wallet = '0xa791e3090312981a1e18ed93238e480a03e7c0d2'
bal = w3.eth.get_balance(Web3.to_checksum_address(wallet))
print(f'POL balance: {bal / 1e18:.4f} POL')
# Need at least 0.1 POL for redemption txs
if bal / 1e18 < 0.1:
    print('WARNING: Low POL balance -- may need to send POL for gas')
"
```

## Step 5: Fix the copytrade redemption checker

In `polymarket-bot/strategies/polymarket_copytrade.py`, find the `_check_and_redeem_positions` method (around line 3474). It currently only LOGS redeemable positions but does not redeem them. Since the standalone redeemer (`src/redeemer.py`) handles actual redemption, change this method to:

1. Keep the scanning logic (it's useful for logging)
2. Remove the misleading `needs_manual_redemption` action -- change it to `delegated_to_redeemer`
3. Add a count log at the end so we can track if the redeemer is falling behind

```python
                logger.info(
                    "copytrade_position_redeemable",
                    title=title[:50],
                    condition_id=condition_id[:20] + "...",
                    value=round(value, 2),
                    action="delegated_to_redeemer",
                )
```

## Step 6: Clean up the internal position tracker

The copytrade `_positions` dict may contain stale entries for positions that have already resolved. These bloat memory and cause the `max_positions` check to reject new trades prematurely.

Find the position cleanup section (look for `_cleanup_positions` or `_check_position_status` or the main loop section that checks for resolved markets). Ensure it:

1. Removes positions from `_positions` when `curPrice == 1.0` (resolved YES) or `curPrice == 0.0` (resolved NO)
2. Removes positions from `_active_condition_ids` and `_active_event_slugs` when cleaned up
3. Unregisters from `_exit_engine` when cleaned up

If no cleanup function exists, add one that runs every 10 minutes:

```python
    async def _cleanup_resolved_positions(self) -> None:
        """Remove resolved positions from tracking to free up position slots."""
        if not self._http or not self._client.wallet_address:
            return
        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/positions",
                params={"user": self._client.wallet_address},
            )
            resp.raise_for_status()
            api_positions = {p.get("conditionId", ""): p for p in resp.json()}

            cleaned = 0
            for pid, pos in list(self._positions.items()):
                api_pos = api_positions.get(pos.condition_id)
                if api_pos:
                    cur_price = float(api_pos.get("curPrice", 0.5))
                    if cur_price == 1.0 or cur_price == 0.0:
                        self._positions.pop(pid, None)
                        self._exit_engine.unregister_position(pid)
                        self._active_condition_ids.discard(pos.condition_id)
                        es = getattr(pos, "event_slug", "")
                        if es:
                            self._active_event_slugs.discard(es)
                        self._correlation_tracker.remove_position(pid)
                        cleaned += 1

            if cleaned:
                self._save_positions()
                logger.info("copytrade_cleanup_resolved", cleaned=cleaned, remaining=len(self._positions))
        except Exception as exc:
            logger.error("copytrade_cleanup_error", error=str(exc)[:200])
```

Wire this into the main loop to run every 10 minutes (600 seconds).

## Step 7: Verify and push

```bash
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py
python3 -m py_compile polymarket-bot/src/redeemer.py
cd /Users/bob/AI-Server && git add -A && git commit -m "fix: redemption pipeline -- cleanup resolved positions, improve redeemer logging" && git push origin main
docker compose up -d --build polymarket-bot
```
