# Final Opus Pass — April 5, 2026

## CRITICAL: Commit Rules

**YOU MUST commit and push when done.** Cursor worktrees get deleted — uncommitted work is lost forever.

Work ONLY in /Users/bob/AI-Server/. Do NOT create worktrees. All file paths must be absolute.

When complete:
```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "fix: weather trader prices, on-chain balance before sell, Redis password cleanup" && git push origin main
```

---

## FIX 1: Weather Trader — Empty Token Prices

### Problem
Weather trader scans 200 Polymarket weather markets but enters 0 positions. The diagnostic log shows `token_prices: []` for every event group. The Gamma API `/markets` endpoint returns markets but the `tokens` array either doesn't exist or has no `price` field.

### Root Cause
The Gamma API markets response does NOT include live prices in the `tokens[].price` field. It returns token metadata (token_id, outcome) but not current market prices. Prices must be fetched separately from the CLOB API.

### Fix in /Users/bob/AI-Server/polymarket-bot/strategies/weather_trader.py

**A.** After `_scan_polymarket_weather()` returns markets (around line 470 where `poly_markets` is assigned), add a price enrichment step. For each market, fetch the current price from the CLOB API:

```python
# Enrich markets with live prices from CLOB
async def _enrich_with_prices(self, markets: list[dict]) -> list[dict]:
    """Fetch live mid-prices from CLOB for each market's tokens."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as http:
        for mkt in markets:
            clob_ids = mkt.get("clobTokenIds", "[]")
            if isinstance(clob_ids, str):
                import json
                try:
                    clob_ids = json.loads(clob_ids)
                except:
                    clob_ids = []
            
            if not clob_ids:
                continue
            
            # Fetch midpoint price for the YES token (first token)
            try:
                resp = await http.get(
                    "https://clob.polymarket.com/midpoint",
                    params={"token_id": clob_ids[0]}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    mid = float(data.get("mid", 0))
                    # Store price in the tokens array for downstream use
                    if not mkt.get("tokens"):
                        mkt["tokens"] = []
                    if len(mkt["tokens"]) == 0:
                        mkt["tokens"].append({"token_id": clob_ids[0], "price": mid})
                    else:
                        mkt["tokens"][0]["price"] = mid
                    
                    # Also store the NO token price if available
                    if len(clob_ids) > 1:
                        no_mid = 1.0 - mid  # Binary market: NO = 1 - YES
                        if len(mkt["tokens"]) < 2:
                            mkt["tokens"].append({"token_id": clob_ids[1], "price": no_mid})
                        else:
                            mkt["tokens"][1]["price"] = no_mid
            except Exception:
                continue
    
    return markets
```

**B.** Call `_enrich_with_prices()` right after the Polymarket scan, BEFORE grouping by event:

Find the line (around 470) that does:
```python
event_groups = self._group_by_event(poly_markets)
```

Add BEFORE it:
```python
poly_markets = await self._enrich_with_prices(poly_markets)
```

**C.** To avoid hammering the CLOB API with 200 individual requests, batch the enrichment:
- Only fetch prices for markets that match a station we monitor (7 stations = ~50 markets max)
- Add a 50ms delay between requests to avoid rate limiting
- Cache prices for 60 seconds (they don't change that fast)

**D.** Also fix `_get_token_id()` (line 975) to use `clobTokenIds` when `tokens` is empty:
```python
def _get_token_id(self, mkt: dict, platform: str) -> str:
    if platform == "kalshi":
        return mkt.get("ticker", mkt.get("market_id", ""))
    tokens = mkt.get("tokens", [])
    if tokens and tokens[0].get("token_id"):
        return tokens[0]["token_id"]
    # Fallback to clobTokenIds
    clob_ids = mkt.get("clobTokenIds", "[]")
    if isinstance(clob_ids, str):
        import json
        try: clob_ids = json.loads(clob_ids)
        except: clob_ids = []
    return clob_ids[0] if clob_ids else mkt.get("condition_id", "")
```

---

## FIX 2: On-Chain Balance Check Before Every Sell

### Problem
Both the copytrade exit engine and the spread_arb repeatedly hit "not enough balance / allowance" errors because the internal position tracker records more shares than actually exist on-chain. The 7% haircut (0.93 multiplier) helps but doesn't fully solve it.

### Fix in /Users/bob/AI-Server/polymarket-bot/strategies/polymarket_copytrade.py

**A.** Add an on-chain balance query function. The redeemer already has this code — reuse the pattern from `/Users/bob/AI-Server/polymarket-bot/src/redeemer.py` lines 272-280:

```python
# Add near the top of the file, after imports
from web3 import Web3

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
ERC1155_ABI = [{"constant": True, "inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]

_w3 = None
_ctf_contract = None

def _get_onchain_balance(token_id: str, wallet: str) -> float | None:
    """Query ERC1155 balance for a CTF token. Returns shares or None on error."""
    global _w3, _ctf_contract
    try:
        if _w3 is None:
            _w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            _ctf_contract = _w3.eth.contract(
                address=Web3.to_checksum_address(CTF_ADDRESS),
                abi=ERC1155_ABI,
            )
        balance = _ctf_contract.functions.balanceOf(
            Web3.to_checksum_address(wallet),
            int(token_id),
        ).call()
        return balance / 1e6  # CTF tokens have 6 decimals
    except Exception:
        return None
```

**B.** In the sell execution (around line 3132 where `sell_shares` is calculated), BEFORE placing the sell order:

Replace:
```python
sell_shares = round(pos.size_shares * signal.sell_fraction * 0.93, 2)  # 7% haircut
```

With:
```python
# Query actual on-chain balance instead of relying on internal tracker
wallet = self._settings.poly_proxy_address or (self._clob_client._api_key if self._clob_client else "")
onchain_balance = _get_onchain_balance(pos.token_id, wallet) if pos.token_id else None

if onchain_balance is not None and onchain_balance > 0:
    # Use on-chain balance as the truth, apply small haircut for in-flight txns
    sell_shares = round(min(onchain_balance, pos.size_shares) * signal.sell_fraction * 0.995, 2)
    if abs(onchain_balance - pos.size_shares) > 1.0:
        logger.info("balance_drift_detected", position_id=position_id, 
                     internal=pos.size_shares, onchain=onchain_balance)
elif onchain_balance == 0:
    # No tokens on-chain — remove from tracking silently
    logger.info("zero_balance_cleanup", position_id=position_id, market=pos.market_question[:50])
    del self._positions[position_id]
    return
else:
    # RPC failed — fall back to internal tracker with large haircut
    sell_shares = round(pos.size_shares * signal.sell_fraction * 0.90, 2)
```

**C.** The wallet address should be read from env. Find it from:
```python
wallet = os.environ.get("POLY_PROXY_ADDRESS", os.environ.get("POLY_SAFE_ADDRESS", ""))
```

Make sure this is set at module level or passed to `_get_onchain_balance`.

### Also fix in /Users/bob/AI-Server/polymarket-bot/strategies/spread_arb.py

**D.** Before each arb order in the execution section, check wallet USDC balance:

```python
# At the start of the execution loop (before iterating opportunities)
import httpx
try:
    # Check current USDC.e balance
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
        abi=[{"constant":True,"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
    )
    wallet = os.environ.get("POLY_PROXY_ADDRESS", os.environ.get("POLY_SAFE_ADDRESS", ""))
    usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    logger.info("arb_wallet_balance", usdc=round(usdc_balance, 2))
except Exception:
    usdc_balance = 999999  # Don't block on RPC failure

# Then inside the loop, before placing orders:
estimated_cost = sum(opp.tokens[i]["price"] * shares for i in range(2))  # rough estimate
if estimated_cost > usdc_balance * 0.9:  # Leave 10% buffer
    logger.info("arb_skip_insufficient_balance", market=opp.condition_id[:20], 
                 cost=estimated_cost, balance=usdc_balance)
    skipped += 1
    continue
```

---

## FIX 3: Redis Password Cleanup

### Problem
Several files still have hardcoded Redis URLs without auth or with stale passwords.

### Fix

In these files, replace all hardcoded Redis URLs with env var reads:

**A.** /Users/bob/AI-Server/polymarket-bot/scripts/test_imessage.py line 58:
```python
# OLD: url = "redis://localhost:6379"
url = os.environ.get("REDIS_URL", "redis://localhost:6379")
```

**B.** /Users/bob/AI-Server/polymarket-bot/sidecar/bridge.py line 29:
```python
# OLD: REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
# This one already reads from env — just verify it's correct. 
# The default fallback is fine since this runs inside Docker where REDIS_URL is set.
# No change needed IF the env var is set in docker-compose.yml
```

**C.** Do a final sweep — search ALL .py files in the entire repo for any remaining hardcoded Redis URLs that don't read from env:
```bash
grep -rn "redis://redis:6379\|redis://172.18.0.100:6379\|redis://localhost:6379" --include="*.py" | grep -v "os.environ\|env\|ENV\|.pyc\|__pycache__\|test_\|example\|README"
```

For any found: wrap in `os.environ.get("REDIS_URL", "<existing_default>")` unless already wrapped.

Also check the `cvd_publish_error` that still appears occasionally:
```bash
grep -rn "cvd_publish" polymarket-bot/ --include="*.py" | grep -v ".pyc"
```
Find where it connects to Redis and ensure it uses the REDIS_URL env var.

---

## Verify

```bash
python3 -m py_compile /Users/bob/AI-Server/polymarket-bot/strategies/weather_trader.py
python3 -m py_compile /Users/bob/AI-Server/polymarket-bot/strategies/polymarket_copytrade.py
python3 -m py_compile /Users/bob/AI-Server/polymarket-bot/strategies/spread_arb.py
```

Then commit and push:
```bash
cd /Users/bob/AI-Server && git add -A && git commit -m "fix: weather trader prices, on-chain balance before sell, Redis password cleanup" && git push origin main
```
