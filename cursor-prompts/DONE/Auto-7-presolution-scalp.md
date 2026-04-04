# Auto-7: Pre-Resolution Scalp Strategy

## The Problem

Binary prediction markets misprice the losing side in the final 1-3 hours before resolution. When a market is 97% to resolve YES, the NO side often trades at 3-8 cents — not because anyone thinks it will win, but because no one wants to hold a losing position through resolution. That creates a specific edge: buy the cheap side at 5 cents, hold through resolution. If it resolves YES (your "win"), you collect $1 per share — a 20x return. If it resolves NO (your "loss"), you lose 5 cents. The math only needs ~5% of these to hit to be profitable.

The strategy is already documented in `polymarket-bot/ideas.txt` but was never implemented. This prompt builds it.

## Context Files to Read First

- `polymarket-bot/strategies/base.py` — BaseStrategy ABC, `on_tick()` contract, `OpenOrder` dataclass, how strategies integrate with the client and scanner
- `polymarket-bot/strategies/strategy_manager.py` — `STRATEGY_ALLOCATIONS`, `SharedPositionRegistry`, how new strategies are registered and run
- `polymarket-bot/strategies/llm_validator.py` — `ValidationResult` dataclass, how `validate_trade()` works, the `approved` / `reasoning` fields to reuse
- `polymarket-bot/strategies/polymarket_copytrade.py` — patterns for scanning markets with the Gamma API (`end_date_iso`), placing limit orders, deduplicating positions with `_active_condition_ids`
- `polymarket-bot/src/client.py` — `get_markets()`, `place_order()`, `get_positions()`, `ORDER_TYPE_GTC`

## Prompt

Build the `PresolutionScalp` strategy in `polymarket-bot/strategies/presolution_scalp.py`. This is a completely new file — nothing exists. Subclass `BaseStrategy` and implement `on_tick()`.

### 1. Strategy Overview and Edge

```
Edge: Near-certain markets misprice the losing side at 3-8¢ due to resolution risk aversion.
Expected win rate: ~4-8% (these mostly resolve against us — that's fine)
Required payoff at 5¢ entry: 20:1 (we collect $0.95 profit per share on a win)
Volume play: many small bets, not a few large ones
Hold period: 1-3 hours (hold through resolution — no manual exit needed)
```

### 2. Market Scanner Loop

In `on_tick()`, run every 5 minutes (this is faster than other strategies — use a 300-second tick interval):

```python
async def on_tick(self) -> None:
    """Scan for markets approaching resolution with mispriced cheap side."""
    now_utc = datetime.now(timezone.utc)
    
    # Fetch markets resolving within 1-3 hours
    markets = await self._scan_presolution_window(
        min_minutes=60,   # at least 1 hour out (earlier = more time for price to shift)
        max_minutes=180,  # no more than 3 hours out
    )
    
    for market in markets:
        await self._evaluate_market(market, now_utc)
```

For `_scan_presolution_window()`:
- Query the Gamma API for active markets (`active=true`, `closed=false`)
- Filter by `end_date_iso`: parse the ISO timestamp, compute minutes until resolution
- Only return markets where `60 <= minutes_until_resolution <= 180`
- Minimum market volume: `$10,000` (ensures there is actual liquidity — skip illiquid tail markets)
- Skip markets already in `_active_condition_ids` (no double entries)

### 3. Cheap Side Detection

For each market in the window, identify the cheap side:

```python
def _find_cheap_side(self, market: dict) -> tuple[str, float] | None:
    """
    Returns (token_id, price) for the cheap side if it qualifies, else None.
    
    A market qualifies when one side is <= MAX_ENTRY_PRICE (0.08).
    The cheap side must have enough liquidity to fill a small order.
    """
```

- Fetch the current orderbook for both YES and NO tokens
- If YES price <= `MAX_ENTRY_PRICE` (0.08): cheap side is YES, expensive side is NO
- If NO price <= `MAX_ENTRY_PRICE` (0.08): cheap side is NO, expensive side is YES
- If both or neither qualify: skip
- Confirm the cheap side has at least `MIN_AVAILABLE_SHARES` (100 shares) at the ask price
- Return `(token_id, ask_price)` for the cheap side, or `None`

Constants at top of file:
```python
MAX_ENTRY_PRICE = 0.08       # 8 cents — maximum price we'll pay for the cheap side
MIN_AVAILABLE_SHARES = 100   # minimum shares available at ask (ensures fill)
POSITION_SIZE_USD = 3.00     # $3 per scalp (volume play — keep it tiny)
MAX_POSITIONS = 20           # max concurrent presolution positions
MAX_TOTAL_EXPOSURE = 100.00  # $100 total exposure cap across all presolution bets
TICK_INTERVAL_SECONDS = 300  # scan every 5 minutes
```

### 4. LLM Validation — "Is This Virtually Certain?"

Before entering any position, validate with the LLM:

```python
async def _validate_with_llm(self, market: dict, cheap_side: str, price: float) -> bool:
    """
    Ask the LLM: is the expensive side virtually certain to win?
    
    We only want to buy the cheap side when the expensive side is near-certain.
    The cheap side is a tail-risk bet — we need to be honest about expected loss rate.
    """
    prompt = f"""
Market: {market['question']}
Resolution in: {minutes_remaining} minutes
Current prices: YES={yes_price:.2f}, NO={no_price:.2f}
We want to buy the {cheap_side} side at {price:.2f}¢

Is the {expensive_side} outcome virtually certain (>90% confidence)?
Answer YES or NO, then explain in one sentence.
Key question: is there any realistic scenario where {cheap_side} resolves correctly?
If yes (even small chance), say YES to buying the cheap side.
If the outcome is 100% locked in (e.g., sports game already played, price already crossed), say NO — skip it.
"""
```

- Use `llm_validator.py`'s OpenAI client (reuse the existing `httpx` client and API key pattern)
- Model: `gpt-4o-mini` (fast and cheap — this runs every 5 minutes)
- Timeout: 5 seconds (never block the tick loop)
- If LLM is unavailable or times out: default to `approved=True` (don't miss opportunities due to API issues)
- Cache LLM results per `condition_id` — don't re-validate the same market on the next tick

### 5. Safety Guards

Before placing any order, check all guards:

```python
def _passes_safety_checks(self) -> bool:
    """All guards must pass before entering a presolution position."""
    # Guard 1: Position count limit
    if len(self._presolution_positions) >= MAX_POSITIONS:
        logger.warning("presolution_scalp.max_positions_reached", count=len(self._presolution_positions))
        return False
    
    # Guard 2: Total exposure cap
    total_exposure = sum(p.cost_basis for p in self._presolution_positions.values())
    if total_exposure + POSITION_SIZE_USD > MAX_TOTAL_EXPOSURE:
        logger.warning("presolution_scalp.exposure_cap_reached", total=total_exposure)
        return False
    
    # Guard 3: Available bankroll
    if self._available_bankroll < POSITION_SIZE_USD * 2:
        logger.warning("presolution_scalp.low_bankroll", bankroll=self._available_bankroll)
        return False
    
    return True
```

### 6. Order Entry

Place a limit order (GTC) at the current ask for the cheap side:

```python
async def _enter_position(self, market: dict, token_id: str, price: float) -> None:
    """Place a small limit order on the cheap side."""
    shares = POSITION_SIZE_USD / price
    
    order = await self.client.place_order(
        token_id=token_id,
        side="BUY",
        price=price,
        size=shares,
        order_type=ORDER_TYPE_GTC,
    )
    
    if order:
        position = PresolutionPosition(
            condition_id=market["condition_id"],
            market_question=market["question"],
            token_id=token_id,
            side=cheap_side,
            entry_price=price,
            shares=shares,
            cost_basis=POSITION_SIZE_USD,
            resolution_time=end_time,
            entered_at=time.time(),
        )
        self._presolution_positions[market["condition_id"]] = position
        self._active_condition_ids.add(market["condition_id"])
        
        # Publish signal to Redis for tracking
        await self._publish_signal(position)
        
        logger.info(
            "presolution_scalp.entered",
            market=market["question"][:60],
            side=cheap_side,
            price=price,
            shares=shares,
            cost=POSITION_SIZE_USD,
            resolves_in_minutes=minutes_remaining,
        )
```

### 7. PresolutionPosition Dataclass

```python
@dataclass
class PresolutionPosition:
    condition_id: str
    market_question: str
    token_id: str
    side: str          # "YES" or "NO"
    entry_price: float
    shares: float
    cost_basis: float  # USD spent
    resolution_time: datetime
    entered_at: float  # unix timestamp
    
    # Filled in after resolution
    outcome: str | None = None          # "WIN" or "LOSS"
    pnl: float | None = None            # USD profit/loss
    resolved_at: float | None = None
```

### 8. Exit — Hold Through Resolution

These positions do NOT need active exit management. The Polymarket CLOB auto-resolves markets. The redeemer in `src/redeemer.py` handles token redemption.

The strategy only needs to:
- Detect when a position's market has resolved (check `market["closed"]` on each scan tick)
- Mark the position as `outcome=WIN` or `outcome=LOSS`, compute `pnl`
- Remove from `_presolution_positions` and `_active_condition_ids`
- Update win rate tracking

```python
async def _check_resolutions(self) -> None:
    """Check if any held presolution positions have resolved."""
    for condition_id, pos in list(self._presolution_positions.items()):
        market = await self._fetch_market(condition_id)
        if not market or not market.get("closed"):
            continue
        
        # Determine outcome
        winning_token = market.get("winning_outcome")  # "YES" or "NO"
        won = (pos.side == winning_token)
        
        if won:
            pnl = pos.shares * (1.0 - pos.entry_price)  # profit per share
            pos.outcome = "WIN"
        else:
            pnl = -pos.cost_basis  # lost the bet
            pos.outcome = "LOSS"
        
        pos.pnl = pnl
        pos.resolved_at = time.time()
        
        self._record_resolution(pos)
        del self._presolution_positions[condition_id]
        self._active_condition_ids.discard(condition_id)
        
        logger.info(
            "presolution_scalp.resolved",
            market=pos.market_question[:60],
            outcome=pos.outcome,
            pnl=pos.pnl,
            entry_price=pos.entry_price,
        )
```

### 9. Win Rate and P/L Tracking

Maintain running stats and persist to Redis:

```python
@dataclass
class ScalpStats:
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    total_wagered: float = 0.0
    total_pnl: float = 0.0
    
    @property
    def win_rate(self) -> float:
        return self.wins / self.total_bets if self.total_bets > 0 else 0.0
    
    @property
    def avg_return_per_bet(self) -> float:
        return self.total_pnl / self.total_bets if self.total_bets > 0 else 0.0
    
    @property
    def roi(self) -> float:
        return self.total_pnl / self.total_wagered if self.total_wagered > 0 else 0.0
```

- Persist stats to Redis key `signals:presolution_scalp:stats` (JSON)
- Persist individual resolution events to Redis list `signals:presolution_scalp:history` (LPUSH, LTRIM to 500)
- Log a daily summary at midnight: total bets, win rate, net P/L, ROI

### 10. Registration in strategy_manager.py

Add `PresolutionScalp` to the strategy manager following the same pattern as existing strategies:

In `strategy_manager.py`:
```python
from strategies.presolution_scalp import PresolutionScalp

# Add to STRATEGY_ALLOCATIONS:
STRATEGY_ALLOCATIONS = {
    "weather_trader": 0.35,    # reduced slightly to make room
    "copytrade": 0.30,
    "cvd_arb": 0.20,
    "presolution_scalp": 0.15, # fixed small allocation — this strategy self-limits via MAX_TOTAL_EXPOSURE
}
```

The `PresolutionScalp` strategy's bankroll allocation feeds `_available_bankroll`, but the strategy itself is capped by `MAX_TOTAL_EXPOSURE = $100`. The allocation just ensures it has enough to operate.

### 11. Logging and Observability

Use `structlog` throughout. Key log events:
- `presolution_scalp.scan_complete` — markets scanned, candidates found
- `presolution_scalp.candidate_found` — market name, price, minutes remaining
- `presolution_scalp.llm_approved` / `presolution_scalp.llm_rejected` — market, reasoning
- `presolution_scalp.guard_blocked` — which guard triggered
- `presolution_scalp.entered` — all entry details
- `presolution_scalp.resolved` — outcome, pnl, entry price
- `presolution_scalp.daily_summary` — stats at midnight

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.
