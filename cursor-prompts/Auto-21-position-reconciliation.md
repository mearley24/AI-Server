# Auto-21: Position Reconciliation — Single Source of Truth

## The Problem

The bot's internal position tracking drifts from on-chain reality. Polymarket shows $1,126.51 in held positions, but the bot's internal tracker only knows about trades it personally entered during the current process lifetime. After restarts, manual trades, or missed events, the bot's view of the world diverges from reality. The bankroll calculation only reads USDC.e balance (~$217), ignoring position value (~$1,126), so the bot thinks it has much less capital than it actually does.

## Context Files to Read First
- polymarket-bot/src/client.py (get_positions, get_balance methods)
- polymarket-bot/src/pnl_tracker.py (_open_positions dict)
- polymarket-bot/strategies/polymarket_copytrade.py (_active_condition_ids, _bankroll, _bankroll_refresh_interval)
- polymarket-bot/strategies/kelly_sizing.py (fetch_onchain_bankroll)
- polymarket-bot/strategies/strategy_manager.py (SharedPositionRegistry)
- polymarket-bot/src/redeemer.py
- polymarket-bot/heartbeat/briefing.py

## Prompt

Build a position reconciliation system that makes on-chain data the source of truth:

### 1. Position Syncer (`polymarket-bot/src/position_syncer.py`)

Create a new module that periodically fetches ALL positions from the Polymarket CLOB API and reconciles with internal state:

```
async def sync_positions(client: PolymarketClient) -> PositionSnapshot:
```

- Call `client.get_positions()` to get every position the wallet holds on-chain
- For each position, also fetch current market price from Gamma API to calculate market value
- Return a `PositionSnapshot` dataclass:
  ```python
  @dataclass
  class PositionSnapshot:
      timestamp: float
      usdc_balance: float          # on-chain USDC.e
      positions: list[Position]    # all held positions with current value
      total_position_value: float  # sum of (shares × current_price) for all positions
      total_portfolio_value: float # usdc_balance + total_position_value
      unrealized_pnl: float       # total_position_value - total_cost_basis (if known)
  ```

- Run every 5 minutes in an async loop
- Save each snapshot to Redis key `portfolio:snapshot` (latest) and append to `portfolio:history` (capped list, last 1000)
- Save to a local JSON file `data/portfolio_snapshots.json` (append, rotate daily)

### 2. Reconciliation with Internal State

On each sync:

a) **PnLTracker reconciliation** — Compare `position_syncer` results with `pnl_tracker._open_positions`:
   - Positions on-chain but NOT in internal tracker → log as `position_discovered` (likely from before restart or manual trade). Add to internal tracker with `entry_price=unknown`, mark as `manual_or_pre_restart`.
   - Positions in internal tracker but NOT on-chain → log as `position_vanished` (resolved, redeemed, or sold externally). Remove from internal tracker.
   - Positions in both → update current price and unrealized P/L.

b) **Active sets reconciliation** — Rebuild `_active_condition_ids` and `_active_event_slugs` from on-chain positions, not from memory. This prevents the bot from re-entering markets it already holds after a restart.

c) **SharedPositionRegistry** — Sync the multi-strategy position registry with on-chain state so all strategies know the current holdings.

### 3. True Bankroll Calculation

Replace the bankroll refresh in `polymarket_copytrade.py`:

```python
# OLD: bankroll = on-chain USDC.e only
# NEW: bankroll = on-chain USDC.e (available to trade)
# But ALSO track total portfolio value for reporting
```

- `available_bankroll` = on-chain USDC.e balance (this is what we can actually spend on new trades)
- `total_portfolio_value` = USDC.e + market value of all positions (this is the real net worth)
- Both values should be in every notification and briefing
- Kelly sizer should use `available_bankroll` for sizing (can't spend money that's in positions)
- But strategy allocation percentages should be based on `total_portfolio_value` (so allocation grows as positions grow)

### 4. Startup Recovery

On bot startup:
- FIRST: run position sync before any strategy starts
- Populate `_active_condition_ids`, `_active_event_slugs`, `_open_positions` from on-chain data
- Log: "Recovered X positions worth $Y from on-chain state"
- This means restarts no longer lose position awareness

### 5. Notifications — Real Numbers

Update ALL notifications (iMessage trade cards, briefings, heartbeat) to show:
- Available: $XXX (USDC.e balance)
- Positions: $X,XXX.XX (market value of held positions)
- Portfolio: $X,XXX.XX (total)
- P/L: +$XX.XX (if we can track cost basis)

Format: `💰 Available: $217 | Positions: $1,126 | Portfolio: $1,343`

### 6. Drift Alerting

- If `total_portfolio_value` changes by more than 10% in a single 5-min window → alert Matt via iMessage
- If `total_portfolio_value` drops below $500 → alert Matt immediately
- If available USDC.e drops below $50 → alert (almost out of trading capital)
- Log all drift events with before/after values

### 7. Redis Keys

- `portfolio:snapshot` — latest PositionSnapshot as JSON
- `portfolio:history` — list of recent snapshots (LPUSH, LTRIM to 1000)
- `portfolio:positions` — hash of condition_id → position JSON (for quick lookups)
- `portfolio:alerts` — recent drift alerts

### 8. API Endpoint

Add `GET /api/portfolio` to the trading API (`polymarket-bot/api/routes.py`):
- Returns the latest PositionSnapshot
- Include each position with: market title, side (YES/NO), shares, avg entry price, current price, unrealized P/L, market status
- This is what the iOS app and Mission Control will consume

### 9. Persistence

On clean shutdown (SIGTERM):
- Dump current position state to `data/position_state.json`
- On next startup, load this as the initial state BEFORE the on-chain sync runs
- This gives immediate awareness even if the first on-chain sync is slow

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
