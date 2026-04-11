# Cline Prompt G: Fix Spread Arb Execution

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push after completion.

## Context

The spread_arb scanner finds 13+ arbitrage opportunities per tick (guaranteed profit trades) but execution is crippled by:
- `GAS_FEE = 0.05` is 10x too high (real Polygon gas is $0.003-0.005)
- Size calculation goes negative and silently skips opportunities
- Complement arb adds too much slippage, pushing YES+NO above $1.00
- Conservative limits block easy money

## Changes

File: `polymarket-bot/strategies/spread_arb.py`

### 1. Fix GAS_FEE

Find `GAS_FEE = 0.05` near the top of the file. Change to:

```python
GAS_FEE = 0.005  # Polygon gas is ~$0.003-0.005 per tx
```

### 2. Tune execute_opportunities constants

Find the `execute_opportunities` method. At the top of it there are local constants. Change them to:

```python
        MIN_PROFIT_PCT = 0.5   # arb is risk-free, even small edges compound
        MAX_PER_TICK = 5       # execute up to 5 arbs per scan
        MAX_PER_SIDE = 15.0    # up to $15 per side
```

### 3. Fix size calculation

In `execute_opportunities`, find the size calculation line that contains `self._bankroll * 0.25 - total_exposure`. That whole expression can go negative and kill valid arbs. Replace the size assignment and the `if size < 1.0` block below it with:

```python
            size = min(MAX_PER_SIDE, opp.cost_usd / 2.0)
            if size < 1.0:
                skipped += 1
                continue
```

### 4. Add complement arb cost guard

In the complement execution block (where `opp.opp_type == "complement"`), right BEFORE the existing `order_results = []` line, insert:

```python
                    total_cost_check = sum(
                        round(min(0.99, max(0.01, opp.tokens[i]["price"] + 0.005)), 2)
                        for i in range(2)
                    )
                    if total_cost_check >= 1.0:
                        logger.info("arb_complement_skip_no_edge", market=opp.market_title[:60], total_cost=total_cost_check)
                        skipped += 1
                        continue
```

### 5. Fix complement order pricing

In the complement order loop (same block), wherever you see `opp.tokens[i]["price"] + SLIPPAGE`, change it to `opp.tokens[i]["price"] + 0.005` so complement arbs use a tighter buffer.

### 6. Add native USDC balance check

In `execute_opportunities`, find the `usdc_balance` block that checks USDC.e. Right after that try/except block ends, add:

```python
            try:
                _usdc_native = _w3.eth.contract(
                    address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
                    abi=[{"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}],
                )
                usdc_native = _usdc_native.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
                usdc_balance += usdc_native
            except Exception:
                pass
```

## Verify and deploy

```zsh
python3 -m py_compile polymarket-bot/strategies/spread_arb.py
git add -A
git commit -m "fix: spread_arb -- GAS_FEE 10x too high, sizing, complement pricing"
git push origin main
docker compose up -d --build polymarket-bot
```

Then confirm arbs are executing:

```zsh
sleep 30
docker logs polymarket-bot --tail 50 2>&1 | grep "arb_"
```

Confirm `arb_trade_executed` logs appear and fewer `arb_skipped_unprofitable` than before.
