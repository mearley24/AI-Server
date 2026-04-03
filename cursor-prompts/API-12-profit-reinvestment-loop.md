# API-12: Profit Reinvestment Loop — Trading Funds Business, Business Funds Trading

## The Vision

Trading and business currently run as two independent tracks with no connection. The goal is a flywheel: business revenue funds the trading bankroll → trading profits cover operating expenses → operations win more business → repeat. Bob should manage this loop automatically, tracking balances across all three accounts, auto-scaling the bankroll based on performance, and alerting Matt when the flywheel speeds up or breaks down.

The loop: Polymarket profits → operating reserve → API costs paid → more uptime → more trading → more profit.

## Context Files to Read First

- `openclaw/orchestrator.py` — overall service orchestration; treasury integrates here for daily summary injection
- `openclaw/payment_tracker.py` — existing payment/deposit tracking with Redis + SQLite; treasury piggybacks on this pattern
- `polymarket-bot/heartbeat/briefing.py` — `BriefingGenerator` class where the treasury daily summary section gets injected (Auto-17 integration point)
- `polymarket-bot/strategies/kelly_sizing.py` — bankroll management; treasury's `available_bankroll` feeds `fetch_onchain_bankroll()` override

## Prompt

Build `openclaw/treasury.py` — the central financial tracking module. This is a new file. Wire it into the daily briefing, the `/api/treasury` endpoint, and the bankroll calculation.

### 1. Three-Account Model

```python
@dataclass
class TreasuryState:
    """Complete financial state snapshot."""
    timestamp: float
    
    # Account 1: Trading bankroll
    trading_usdc_balance: float      # on-chain USDC.e (from Auto-21 position syncer)
    trading_position_value: float    # market value of all open positions
    trading_total: float             # usdc_balance + position_value
    
    # Account 2: Operating fund (monthly costs)
    operating_reserve: float         # cash set aside for monthly ops
    monthly_burn_rate: float         # sum of all subscriptions + API costs
    months_runway: float             # operating_reserve / monthly_burn_rate
    
    # Account 3: Business revenue (Symphony Smart Homes)
    business_receivable: float       # outstanding invoices not yet deposited
    business_deposited_mtd: float    # cash received this month
    business_pipeline_value: float   # active proposals × close probability
    
    # Computed
    net_worth: float                 # trading_total + operating_reserve
    monthly_pnl: float               # revenue - expenses for current month
```

### 2. Monthly Operating Costs (Fixed)

These are the known recurring costs. Hard-code them with a note to update as subscriptions change:

```python
MONTHLY_EXPENSES = {
    "perplexity_pro":  200.00,   # Perplexity AI Pro subscription
    "dtools":           99.00,   # D-Tools SI (proposal/project management)
    "openai_target":    50.00,   # OpenAI API (target after cost optimization — Auto-23)
    "mullvad_vpn":       5.00,   # Mullvad VPN
    "twilio":           20.00,   # Twilio SMS/iMessage (varies — use this as estimate)
    "hosting_misc":     15.00,   # domains, misc cloud
}

MONTHLY_BURN_RATE = sum(MONTHLY_EXPENSES.values())  # $389/month baseline
OPERATING_RESERVE_MINIMUM = 500.00   # never let reserve fall below this
OPERATING_RESERVE_TARGET = MONTHLY_BURN_RATE * 2    # 2 months runway as healthy buffer
```

### 3. Redis Storage

```python
REDIS_KEYS = {
    "balances":       "treasury:balances",            # latest TreasuryState as JSON
    "monthly":        "treasury:monthly:{YYYY-MM}",   # monthly P&L aggregate
    "expenses":       "treasury:expenses",            # expense log (hash)
    "revenue":        "treasury:revenue:{YYYY-MM}",   # revenue log by source
    "bankroll_log":   "treasury:bankroll:history",    # list of bankroll snapshots (LPUSH/LTRIM 1000)
    "alerts":         "treasury:alerts",              # recent alerts
}
```

Monthly P&L hash schema:
```json
{
  "trading_profit": 0.0,
  "trading_loss": 0.0,
  "trading_net": 0.0,
  "business_revenue": 0.0,
  "operating_expenses": 0.0,
  "net_profit": 0.0,
  "reinvested_to_bankroll": 0.0,
  "added_to_reserve": 0.0
}
```

### 4. Bankroll Auto-Scaling

The treasury watches trading performance and adjusts bankroll allocation automatically:

```python
class BankrollScaler:
    """Auto-scales trading position limits based on trailing performance."""
    
    SCALE_UP_THRESHOLD = 3      # 3 consecutive profitable weeks → scale up
    SCALE_DOWN_THRESHOLD = 2    # 2 consecutive losing weeks → scale down
    SCALE_UP_PCT = 0.10         # increase max position size by 10%
    SCALE_DOWN_PCT = 0.20       # decrease max position size by 20%
    REINVEST_PCT = 0.50         # 50% of trading profits go back into bankroll (configurable)
    
    async def evaluate_weekly(self, weekly_pnl_history: list[float]) -> ScalingDecision:
        """
        Evaluate trailing weekly P/L and return scaling recommendation.
        
        Returns ScalingDecision with:
        - action: "scale_up" | "scale_down" | "hold"
        - new_max_position_pct: float
        - reason: str (for logging/alerting)
        """
```

Publish scaling decisions to Redis `treasury:bankroll:scaling_log` and notify Matt via iMessage for any scale-up or scale-down event:
```
📈 Bankroll scaled UP: 3 consecutive profitable weeks
New max position size: 11% of bankroll (was 10%)
This week's P/L: +$47.23 | 3-week P/L: +$134.11
```

### 5. Profit Split Logic

When trading generates a profit (detected via pnl_tracker or position syncer):

```python
async def allocate_profit(self, trading_profit: float) -> None:
    """Split trading profits between bankroll and reserve."""
    reinvest = trading_profit * REINVEST_PCT          # default 50% back to bankroll
    to_reserve = trading_profit * (1 - REINVEST_PCT)  # 50% to operating reserve
    
    # If reserve is already above target, send excess to bankroll instead
    current_reserve = await self._get_operating_reserve()
    if current_reserve >= OPERATING_RESERVE_TARGET:
        reinvest = trading_profit      # 100% to bankroll — reserve is full
        to_reserve = 0.0
    
    # Log the allocation
    await self._log_allocation(trading_profit, reinvest, to_reserve)
```

These are accounting entries only — Bob doesn't move actual on-chain USDC. The treasury tracks what *should* happen; actual bankroll size comes from the position syncer (Auto-21).

### 6. Alert Rules

```python
ALERT_RULES = [
    {
        "name": "low_reserve",
        "condition": lambda s: s.operating_reserve < OPERATING_RESERVE_MINIMUM,
        "message": "⚠️ Operating reserve below $500. Current: ${reserve:.2f}. Monthly burn: ${burn:.2f}/month.",
        "severity": "high",
    },
    {
        "name": "low_runway",
        "condition": lambda s: s.months_runway < 2.0,
        "message": "⚠️ Less than 2 months operating runway. Reduce expenses or add to reserve.",
        "severity": "high",
    },
    {
        "name": "strong_flywheel",
        "condition": lambda s: s.monthly_pnl > MONTHLY_BURN_RATE,
        "message": "🚀 Flywheel active: monthly profit exceeds burn rate. Bot is self-sustaining.",
        "severity": "info",
    },
    {
        "name": "bankroll_growth",
        "condition": lambda s: s.trading_total > 2000.0,
        "message": "📈 Trading portfolio crossed $2,000. Consider increasing position limits.",
        "severity": "info",
    },
]
```

Publish all alerts to Redis channel `notifications:alerts` and iMessage Matt for `high` severity. Log `info` severity to the daily briefing only.

### 7. API Endpoint

Add to `openclaw/main.py`:

```python
@app.get("/api/treasury")
async def get_treasury():
    """Return full treasury state for Mission Control dashboard."""
    state = await treasury.get_current_state()
    return {
        "accounts": {
            "trading": {
                "usdc_balance": state.trading_usdc_balance,
                "position_value": state.trading_position_value,
                "total": state.trading_total,
            },
            "operating": {
                "reserve": state.operating_reserve,
                "monthly_burn": state.monthly_burn_rate,
                "months_runway": state.months_runway,
                "expense_breakdown": MONTHLY_EXPENSES,
            },
            "business": {
                "receivable": state.business_receivable,
                "deposited_mtd": state.business_deposited_mtd,
                "pipeline": state.business_pipeline_value,
            },
        },
        "summary": {
            "net_worth": state.net_worth,
            "monthly_pnl": state.monthly_pnl,
            "flywheel_active": state.monthly_pnl > state.monthly_burn_rate,
        },
        "trailing": {
            "30d": await treasury.get_period_summary(days=30),
            "60d": await treasury.get_period_summary(days=60),
            "90d": await treasury.get_period_summary(days=90),
        },
        "goals": {
            "monthly_target_usd": 2000.0,
            "quarterly_target_usd": 6000.0,
            "annual_target_usd": 24000.0,
            "current_run_rate_annual": state.monthly_pnl * 12,
            "on_track": state.monthly_pnl * 12 >= 24000.0,
        },
    }
```

### 8. Daily Briefing Integration

In `polymarket-bot/heartbeat/briefing.py`, the `BriefingGenerator.generate()` method builds the daily iMessage. Add a treasury section:

```python
# In BriefingGenerator.generate():
treasury_section = await self._build_treasury_section()

# Treasury section format:
"""
💰 Treasury Update
Trading: $217 liquid + $1,126 positions = $1,343 total
Reserve: $612 (1.6mo runway)
MTD: +$47 trading | $0 business | -$389 expenses = -$342 net
Flywheel: NOT YET ACTIVE (need $342 more profit to cover burn)
"""
```

Inject this section into the daily briefing between the trading summary and the market overview.

### 9. D-Tools Revenue Stub

The eventual source of business revenue data is the D-Tools API (project deposits, invoices). Stub the interface now so the real implementation can drop in later:

```python
class DToolsRevenueSource:
    """Stub for D-Tools revenue data. Replace with real API calls when D-Tools integration is built."""
    
    async def get_mtd_revenue(self) -> float:
        """Return total revenue deposited this month. Currently manual entry via Redis."""
        return float(await self.redis.get("treasury:manual:revenue_mtd") or 0)
    
    async def get_receivables(self) -> float:
        """Return outstanding invoice value. Currently manual entry via Redis."""
        return float(await self.redis.get("treasury:manual:receivables") or 0)
    
    async def set_manual_revenue(self, amount: float) -> None:
        """Manual revenue entry until D-Tools API is integrated."""
        await self.redis.set("treasury:manual:revenue_mtd", amount)
```

Manual entry via Redis CLI until API-13 (client lifecycle) provides real deposit data:
```bash
redis-cli -h 172.18.0.100 set treasury:manual:revenue_mtd 34609.85
redis-cli -h 172.18.0.100 set treasury:manual:receivables 34609.85
```

### 10. Auto-21 Integration (Position Syncer)

The treasury reads trading balances from the position syncer, not from on-chain directly:

```python
async def _get_trading_balances(self) -> tuple[float, float]:
    """Read latest balances from position syncer via Redis."""
    snapshot_json = await self.redis.get("portfolio:snapshot")
    if not snapshot_json:
        return 0.0, 0.0
    snapshot = json.loads(snapshot_json)
    return snapshot["usdc_balance"], snapshot["total_position_value"]
```

This means treasury never makes its own CLOB API calls — it reads what Auto-21 has already synced. Single source of truth.

### 11. Goal Tracking and Weekly Report

Every Sunday at 8 AM (add to the briefing schedule or use a separate task in orchestrator):

```
📊 Weekly Financial Report — Week of Apr 3, 2026

Trading:
  This week: +$47.23 (3 wins, 8 losses)
  MTD: +$89.50
  Bankroll: $1,343 total ($217 liquid)

Business (Symphony):
  Revenue this week: $0
  Receivables: $34,609.85 (Topletz deposit pending)
  Pipeline: $34,609.85

Operations:
  Weekly expenses: ~$97 (1/4 of monthly $389)
  Net this week: +$47.23 - $97 = -$49.77

Monthly Goal: $2,000 | Run Rate: $357/month | On Track: ❌

Recommendation: Pipeline is strong ($34K receivable). Once Topletz deposits,
add $500 to operating reserve and $500 to trading bankroll.
```

Use standard logging. Redis at `redis://172.18.0.100:6379` inside Docker.
