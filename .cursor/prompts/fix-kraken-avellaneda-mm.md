# Fix: Kraken Avellaneda Market Maker — Silent After Init

The Kraken Avellaneda MM starts but goes silent — no tick logs after init. Two bugs:

## Bug A: CryptoClient created in dry_run mode (`polymarket-bot/src/main.py`)

Line ~339: `CryptoClient()` is instantiated without passing `dry_run=False`. The constructor defaults to `dry_run=True`:
```python
class CryptoClient(PlatformClient):
    def __init__(self, ..., dry_run: bool = True, ...):
```

This means:
- API keys are never configured on the CCXT exchange (`connect()` checks `if self._api_key and not self._dry_run`)
- `is_dry_run` returns True, so `_tick()` uses fake $10k balance instead of real exchange data
- All orders go to the paper trader, nothing hits Kraken

**Fix**: In `polymarket-bot/src/main.py` around line 339, change:
```python
kraken_crypto = CryptoClient(
    exchange_id="kraken",
    api_key=os.environ["KRAKEN_API_KEY"],
    api_secret=os.environ.get("KRAKEN_SECRET", ""),
)
```
to:
```python
kraken_crypto = CryptoClient(
    exchange_id="kraken",
    api_key=os.environ["KRAKEN_API_KEY"],
    api_secret=os.environ.get("KRAKEN_SECRET", ""),
    dry_run=False,
)
```

## Bug B: CryptoClient.connect() is never called

After creating `kraken_crypto`, `connect()` is never called. This method creates the CCXT exchange instance and loads markets. Without it, `self._exchange` is `None`, so:
- `_sync_exchange_inventory()` returns immediately (`if self._client.exchange is None`)
- `get_orderbook()` returns empty `{"bids": [], "asks": []}`
- `_tick()` hits `if not bids or not asks: return` and silently skips every tick — zero logs

**Fix**: In `polymarket-bot/strategies/crypto/avellaneda_market_maker.py`, in the `start()` method, add exchange connection before existing logic:
```python
async def start(self) -> None:
    """Start the market making loop."""
    if self._running:
        return
    
    # Ensure exchange is connected before starting
    if self._client.exchange is None:
        connected = await self._client.connect()
        if not connected:
            logger.error("avellaneda_mm_connect_failed", msg="Could not connect to exchange — aborting start")
            return
    
    self._running = True
    self._started_at = time.time()
    # ... rest of existing start() logic continues unchanged
```

## Files to modify
- `polymarket-bot/src/main.py`
- `polymarket-bot/strategies/crypto/avellaneda_market_maker.py`
