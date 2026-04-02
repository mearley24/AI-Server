# Multi-Strategy Polymarket Trading Architecture

> **Inspired by @zostaff's competing Claude bots** — multiple independent agents betting against each other to find the true edge.

---

## Overview

The bot runs three independent trading strategies simultaneously, each with its own bankroll allocation, P/L tracking, and market universe. A central `StrategyManager` orchestrates them, enforces non-overlap, and monitors cross-strategy correlation.

```
┌─────────────────────────────────────────────────────────┐
│                    StrategyManager                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Weather    │  │  Copytrade   │  │     Arb      │  │
│  │  40% bankroll│  │  35% bankroll│  │  25% bankroll│  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │           │
│  ┌──────▼─────────────────▼──────────────────▼───────┐  │
│  │            Shared Position Registry                │  │
│  │         (prevents any market overlap)              │  │
│  └────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │         Correlation Monitor (>0.3 → alert)        │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │    P/L Dashboard (logged hourly, per-strategy)    │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## Strategy Allocations

| Strategy | Allocation | Markets | Edge Type |
|----------|-----------|---------|-----------|
| **weather_trader** | 40% | Temperature brackets, precipitation | Physics/forecast model vs crowd |
| **copytrade** | 35% | Any (follows whale wallets) | Information asymmetry from high-win-rate wallets |
| **arb** | 25% | Correlated markets (crypto, politics) | Cross-market price discrepancy |

Allocations are **soft limits** — if a strategy has zero opportunities, its bankroll sits idle. The manager does **not** reallocate capital to other strategies automatically (that would defeat the independent tracking purpose).

---

## Strategy 1: Weather Cheap Brackets

### Philosophy (neobrother / Hans323 approach)

The original bot was **buying the most likely bracket at 80-97¢** — terrible risk/reward. The correct approach, proven by top weather traders ($1.1M+ volume), is:

> **Buy the cheap adjacent brackets at 0.2-15¢ and let the 400-1000% winner cover all the small losses.**

Weather forecasts have ~3.5°F standard deviation. When GFS predicts 78°F for Denver, the market correctly prices:
- 75-80°F bracket: ~60¢ (skip)
- 80-85°F bracket: ~55¢ (skip)  
- 70-75°F bracket: ~15¢ ← **BUY THIS**
- 65-70°F bracket: ~5¢ ← **BUY THIS**
- 85-90°F bracket: ~12¢ ← **BUY THIS**

If the forecast is off by just 4-6°F (happens ~30% of the time), you win 600-1500%.

### Entry Logic
1. Fetch NOAA forecast for city → get modal temperature
2. Skip the highest-probability bracket (the one trading at >25¢)
3. Buy ALL brackets within ±15°F that are priced **under 25¢**
4. Hard maximum: $3-5 per bracket, never exceed $15 total per city/date
5. Deploy the ladder densely: 5-8 cheap brackets per market event

### Position Sizing (Weather)
- Default: $3 per bracket
- Strong confidence (multiple models agree): $5 per bracket
- Max per city/date: $15 total
- Max open weather positions: 30

---

## Strategy 2: Copytrade (Existing)

Tracks high-win-rate whale wallets on Polymarket. Each copied trade:
- Uses quarter-Kelly sizing based on the source wallet's historical win rate
- Enforces 5% max bankroll per position (hard cap $10)
- Categorizes by market type (sports, politics, crypto, weather)
- **CRITICAL**: Weather copytrades are now BLOCKED — the whale may be buying 90¢ brackets (bad idea)

### Copytrade × Weather Interaction
When copytrade detects a whale buying a weather bracket:
1. Check if WE already have a position in that market → if yes, skip (position registry)
2. Check the bracket price: if price > 25¢ → skip (bad risk/reward regardless of whale)
3. If price ≤ 25¢ AND the weather strategy hasn't covered this market → allow (rare synergy)

---

## Strategy 3: Arbitrage (Planned)

Targets cross-market price discrepancies:
- **Crypto correlated**: BTC price > $100K market trading cheap relative to BTC/ETH spread markets
- **Political**: Same political outcome priced differently across related markets
- **Sports**: Implied vs. explicit probabilities (team wins conference AND wins championship — bracket arbitrage)

Arb strategy fires on detected discrepancies >5¢ on the synthetic position. Very low frequency (1-3 trades/day) but high confidence.

---

## Shared Position Registry

The registry prevents any market from being entered by two strategies simultaneously.

```python
# Key: token_id (Polymarket) or ticker (Kalshi)
# Value: {strategy_name, entry_price, entry_time, size}
registry = SharedPositionRegistry()

# Before any entry:
if registry.is_claimed(token_id):
    return  # Another strategy already owns this position

# On entry:
registry.claim(token_id, strategy="weather_trader", ...)

# On exit:
registry.release(token_id)
```

**Why this matters**: Without the registry, copytrade might copy a whale entering a weather market that weather_trader also wants to enter — doubling exposure in a single market in an uncoordinated way.

---

## Correlation Monitoring

Every 15 minutes, the manager computes the rolling return correlation between strategies using the last 20 closed trades from each.

**Alert threshold**: Pearson correlation > 0.3 across any two strategies → iMessage alert.

A correlation > 0.3 means the strategies are no longer independently diversified — likely because:
- Copytrade started chasing weather markets (stop copytrade from weather)
- Both arb and copytrade are trading the same political event
- A black swan is moving all markets simultaneously

**Response**: Alert fires, human reviews. No automatic trading pause (that would be overfit).

---

## P/L Dashboard (Hourly Log)

```
══════════════════════════════════════════════
POLYMARKET BOT — HOURLY P/L SNAPSHOT
2026-04-02 07:00 UTC
══════════════════════════════════════════════
Strategy        Bankroll  Trades  Win%   P/L
─────────────────────────────────────────────
weather_trader  $400      47      34%    +$82.40
copytrade       $350      23      71%    +$31.20
arb             $250       6     100%     +$8.80
─────────────────────────────────────────────
TOTAL           $1000     76      52%   +$122.40
──────────────────────────────────────────────
Strategy Correlation Matrix:
  weather × copytrade: 0.12 (healthy)
  weather × arb:       0.04 (healthy)
  copytrade × arb:     0.21 (healthy)
══════════════════════════════════════════════
```

---

## Producer-Consumer Ideas Queue (MoonDev RBI System)

Inspired by MoonDev's RBI (Research → Backtest → Implement) pattern.

**File**: `/home/user/workspace/AI-Server/polymarket-bot/ideas.txt`

### Format
```
IDEA: [short title]
DATE: 2026-04-02
DESCRIPTION: [what you want to try]
HYPOTHESIS: [why this should work]
STATUS: pending | researching | backtesting | implementing | live | rejected
NOTES: [findings as you go]
---
```

### Workflow
1. **Observe** something on Polymarket (a price pattern, a whale wallet, a new market type)
2. **Write it** to `ideas.txt` with STATUS: pending
3. **Research** it (manually or with an LLM) → update STATUS: researching
4. **Backtest** against historical Polymarket data → update STATUS: backtesting
5. **Implement** as a new strategy or parameter tweak → update STATUS: implementing
6. **Deploy** to a 10% bankroll trial → STATUS: live
7. If P/L is negative after 2 weeks → STATUS: rejected

### Current Ideas Queue
```
IDEA: MeanReversion — fade extreme overnight moves
DATE: 2026-04-01
DESCRIPTION: When a market moves from 50¢ to 85¢ overnight with low volume, fade it back to 65¢
HYPOTHESIS: Thin overnight orderbooks allow manipulation, price reverts to fair value by morning
STATUS: pending
---

IDEA: PresolutionScalp — buy cheap side 2 hours before resolution
DATE: 2026-04-01
DESCRIPTION: If a market hasn't resolved and is at 95¢ with 2 hours left, buy the 5¢ side
HYPOTHESIS: Tail risk is consistently underpriced near resolution
STATUS: pending
---

IDEA: BracketLadder — systematic cheap bracket buying (neobrother strategy)
DATE: 2026-04-02
DESCRIPTION: Buy multiple cheap temperature brackets around the forecast rather than the likely bracket
HYPOTHESIS: 400-1000% wins on mispriced adjacent brackets cover all the cheap losses
STATUS: implementing → see weather_trader.py CheapBracketStrategy
---
```

---

## iMessage Alerts

The bot sends iMessage alerts for significant events. Uses the `osascript` bridge on macOS.

### Alert Types

| Event | Trigger | Priority |
|-------|---------|----------|
| `HIGH_CORRELATION` | Any two strategies correlate > 0.3 | HIGH |
| `STRATEGY_DOWN` | A strategy crashes or stops | HIGH |
| `BIG_WIN` | Single position P/L > +$20 | MEDIUM |
| `BIG_LOSS` | Single position P/L < -$15 | MEDIUM |
| `DAILY_SUMMARY` | Every day at 8pm local time | LOW |
| `IDEA_QUEUE_READY` | ideas.txt has 3+ pending items | LOW |

### Configuration
Set `IMESSAGE_RECIPIENT` env var to your phone number or email for iMessage delivery.

---

## File Structure

```
polymarket-bot/
├── src/
│   ├── main.py                  # Entry point, wires everything together
│   ├── client.py                # Polymarket CLOB client
│   ├── config.py                # Settings (env vars)
│   ├── metar_client.py          # METAR aviation weather data
│   ├── noaa_client.py           # NOAA weather forecasts
│   └── ...
├── strategies/
│   ├── base.py                  # BaseStrategy abstract class
│   ├── strategy_manager.py      # ← NEW: Orchestrates all strategies
│   ├── weather_trader.py        # ← UPGRADED: Cheap bracket strategy
│   ├── polymarket_copytrade.py  # Whale wallet following
│   ├── kelly_sizing.py          # Kelly criterion position sizing
│   ├── exit_engine.py           # Take-profit, stop-loss, trailing stops
│   └── correlation_tracker.py  # Category-based exposure tracking
├── docs/
│   └── multi_strategy_architecture.md  # ← THIS FILE
└── ideas.txt                    # Producer-consumer strategy ideas queue
```

---

## Implementation Notes

### Bankroll Accounting
- Total bankroll read from on-chain USDC.e balance at startup
- Split into three sub-bankrolls: `weather_bankroll`, `copytrade_bankroll`, `arb_bankroll`
- Each strategy only sees its own sub-bankroll for sizing calculations
- Realized P/L flows back to total bankroll, re-split daily at midnight

### Thread Safety
- All strategies run as `asyncio` tasks in a single event loop (no threads)
- The shared position registry uses a simple `dict` protected by an `asyncio.Lock`
- No race conditions: all operations are awaited sequentially within the async loop

### Dry-Run Mode
- All strategies respect `Settings.dry_run = True`
- Paper trades logged to `PaperLedger` as always
- Correlation tracking and hourly dashboard still operate on paper positions
- iMessage alerts fire in dry-run (labelled `[PAPER]`)
