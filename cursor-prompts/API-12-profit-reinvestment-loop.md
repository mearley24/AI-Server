# API-12: Profit Reinvestment Loop — Trading Funds Business, Business Funds Trading

## The Vision

Right now trading and business are two parallel tracks. The real power move is connecting them into a flywheel:

Trading profits → fund equipment procurement → complete projects → project profit → increase trading bankroll → bigger positions → more trading profit → repeat

Bob should manage this loop automatically.

## Context Files to Read First
- polymarket-bot/src/pnl_tracker.py
- polymarket-bot/strategies/kelly_sizing.py
- clawwork/v2/earnings_dashboard.py
- proposals/pricing_calculator.py
- AGENTS.md

## Prompt

Build the financial loop that connects trading revenue to business operations:

### 1. Treasury Manager (`core/treasury.py`)

Central financial tracking across all revenue streams:

```python
treasury = {
    "accounts": {
        "polymarket": {"balance": 217.00, "positions": 1126.00, "total": 1343.00},
        "clawwork": {"earned_total": 0, "earned_mtd": 0, "pending_payout": 0},
        "symphony": {"receivable": 34609.85, "deposited": 0, "expenses_pending": 0}
    },
    "monthly_targets": {
        "trading_profit": 500,
        "clawwork_revenue": 1500,
        "operating_expenses": 200  # API costs, hosting, etc.
    },
    "reinvestment_rules": {
        "trading_profit_to_bankroll": 0.70,  # 70% of trading profit stays in bankroll
        "trading_profit_to_reserve": 0.30,   # 30% goes to reserve
        "clawwork_to_trading": 0.50,         # 50% of ClawWork earnings boost trading bankroll
        "reserve_minimum": 500               # always keep $500 in reserve
    }
}
```

### 2. Auto-Scaling Trading Bankroll

- When weekly trading P/L is positive for 3 consecutive weeks → increase max position size by 10%
- When weekly trading P/L is negative for 2 consecutive weeks → decrease max position size by 20%
- When a Symphony deposit lands ($34,609 for Topletz) → temporarily increase trading bankroll by $500 (funded by reserve)
- When ClawWork earns $100+ in a week → move 50% to trading bankroll
- Daily P/L limit scales with bankroll: 5% of total portfolio value

### 3. Expense Tracking

- Track all API costs: OpenAI, Perplexity, Twilio, domain fees
- Track gas fees from Polymarket trades
- Monthly expense report via iMessage on the 1st
- If monthly expenses exceed $200 → alert and suggest where to cut (switch to local Ollama, reduce API calls)

### 4. Financial Dashboard

Add to Mission Control (API-5):
- Revenue waterfall: trading P/L + ClawWork + Symphony → total monthly revenue
- Expense breakdown: APIs, gas fees, infrastructure
- Net profit tracking with month-over-month trend
- Reinvestment flow visualization (where money moves between accounts)
- Runway: at current burn rate, how many months can Bob operate without new Symphony projects?

### 5. Weekly Financial Report

Every Sunday via iMessage:
- Trading: weekly P/L, cumulative P/L, bankroll growth
- ClawWork: tasks completed, revenue earned, effective hourly rate
- Symphony: pipeline value, receivables, deposits expected
- Net: total revenue across all streams, expenses, profit
- Recommendation: "Increase trading bankroll by $X" or "Reduce risk, pipeline is thin"

### 6. Goal Tracking

- Monthly revenue goal: $2,000 (trading + ClawWork)
- Quarterly goal: $6,000
- Annual goal: $24,000 from bot operations alone
- Track progress, project run rate, alert when on/off track

Wire into the event bus (API-11) so financial events flow through the context engine.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
