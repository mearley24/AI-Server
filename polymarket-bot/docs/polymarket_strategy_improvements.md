# Polymarket Copytrade Bot — Strategy Improvement Specification

**Version:** 1.0  
**Date:** 2026-04-01  
**Status:** Ready for Implementation  
**Codebase:** `/home/user/workspace/AI-Server/polymarket-bot/`

---

## Executive Summary

The bot has executed **434 trades** with a **$402 portfolio** (~$196 deployed across 47 open positions). The core copy-trade mechanism works: whale tracking and METAR-validated weather bets are generating real edge. However, six specific failure modes are destroying P/L that the strategy is otherwise earning.

**Current portfolio composition by category (deployed capital):**

| Category | Deployed | % of Exposure | Signal |
|---|---|---|---|
| Weather | $111.50 | 57% | **WINNING** — METAR edge is real |
| Other | $34.52 | 18% | Mixed |
| US Sports | $29.00 | 15% | Winning (Celtics spreads +$4-5 each) |
| Crypto | $10.00 | 5% | Mixed |
| Geopolitics | $5.26 | 3% | **LOSING** |
| Politics | $3.72 | 2% | **LOSING** (Texas Senate -$2.59) |
| Science | $2.40 | 1% | Uncertain |

**Root cause of losses in order of P/L impact:**

1. **Multi-temperature betting** — buying every adjacent temperature bracket is mathematically guaranteed to be net negative even when one wins
2. **No exit discipline** — 1 exit in 434 trades; losers compound while winners sit idle
3. **Wallet quality floor too low** — admitting 55-65% WR wallets with P/L ~1.0x creates break-even copycat trades after fees
4. **Short-window crypto binaries** — 9:00-9:15AM ETH up/down at 97¢ is pure negative EV
5. **Category-level correlation blindness** — Fed rate bets across multiple outcomes funded simultaneously
6. **Position sizing capped too low** — $10 hard cap prevents the bot from expressing high-confidence METAR bets at appropriate scale

**Estimated P/L improvement (applied retroactively to 434-trade history):**

| Fix | Estimated Impact |
|---|---|
| Temperature dedup | +$45 to +$60 recovered on Shanghai/weather bets |
| Exit discipline | +$25 to +$35 (stop losses on -30% positions) |
| Wallet floor raise | +$15 to $20 (fewer break-even copies) |
| Crypto binary filter | +$8 to +$12 (eliminate vig-negative 15-min bets) |
| Category blacklist | +$8 to +$10 (no more politics/geopolitics bleed) |
| Kelly hard cap raise | +$10 to +$15 (scale into proven METAR edge) |
| **Total** | **~+$111 to +$152 improvement** |

---

## Problem 1: Multi-Temperature Betting

### Diagnosis

The bot copies multiple whale wallets that each hold different temperature brackets for the same city and date — e.g., Shanghai high temperature: 14°C, 15°C, 16°C, 17°C, 18°C, 19°C simultaneously. Because exactly one bracket resolves YES, the combined entry cost is approximately **$58** while the maximum payout is **~$13**. This is a structural -$45 guaranteed loss per weather cluster, regardless of which bracket wins.

**Current code behavior:**  
In `strategies/polymarket_copytrade.py`, the per-market dedup only blocks the exact same `condition_id` (`_active_condition_ids`). It does not detect that adjacent temperature brackets for the same city/date are mutually exclusive outcomes. The `event_slug` guard (`_active_event_slugs`) helps for some markets but does not specifically model the temperature bracket problem.

**METAR and NOAA data already exist:**  
The bot has `src/metar_client.py` and `src/noaa_client.py` already operational. The `strategies/weather_trader.py` has `NOAAClient`, `TEMP_BRACKET_PATTERN`, `TEMP_ABOVE_PATTERN`, `CITY_PATTERNS`, and `NOAA_SIGMA = 3.5` for uncertainty modeling. This data is already being fetched but is not used in `polymarket_copytrade.py` to adjudicate between competing temperature brackets.

### Required Changes

#### `strategies/polymarket_copytrade.py` — Add Temperature Cluster Deduplication

**Step 1:** Add a temperature bracket parser to extract `(city, date, temp_celsius)` from market titles.

```python
import re

_TEMP_CELSIUS_PATTERN = re.compile(
    r"(?:high|low)?\s*(?:temperature|temp)?\s*(?:in|at)?\s*([\w\s]+?)"
    r"\s+(?:on|for)?\s*[\w\s,]+?\s+(?:be\s+)?(\d+)\s*°?\s*[Cc]",
    re.IGNORECASE,
)

def _extract_temp_cluster_key(market_question: str) -> tuple[str, str, int] | None:
    """
    Returns (city_normalized, date_str, temp_celsius) if this is a temperature
    bracket market, else None.
    
    Example: "Will Shanghai high temperature be 17°C on April 3?" 
    → ("shanghai", "april-3", 17)
    """
    # Implementation: parse city + date + integer Celsius temperature
    ...
```

**Step 2:** Maintain a registry of temperature clusters in `__init__`:

```python
# Maps (city, date) → {temp: condition_id} for already-entered brackets
self._temp_cluster_registry: dict[tuple[str, str], dict[int, str]] = {}
```

**Step 3:** In `_should_copy_trade()` (before executing any buy), call `_check_temperature_cluster()`:

```python
def _check_temperature_cluster(
    self,
    market_question: str,
    condition_id: str,
) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    
    Rules:
    - If this is not a temperature market: return (True, "")
    - If no bracket for this city/date is held: fetch NOAA forecast,
      enter the bracket closest to the forecast mean. Return (True, "primary_bracket").
    - If one bracket is already held for this city/date:
      - Allow one adjacent bracket if it's within NOAA ± 1 sigma (i.e., adjacent bracket
        overlaps the 50-84% probability zone). Max 2 brackets total.
    - If two brackets are already held: block all further entries for this city/date.
      Return (False, "temp_cluster_capped").
    """
    ...
```

**Step 4:** In `_execute_copy_trade()`, after the temperature check passes, register the new bracket:

```python
cluster_key = _extract_temp_cluster_key(market_question)
if cluster_key:
    city, date, temp = cluster_key
    self._temp_cluster_registry.setdefault((city, date), {})[temp] = condition_id
```

#### `src/noaa_client.py` — Expose Point Forecast for a City/Date

The NOAA client already fetches 7-day forecasts. Add a helper:

```python
def get_best_temperature_bracket(
    self,
    station: str,
    target_date: datetime.date,
    brackets: list[int],  # e.g. [14, 15, 16, 17, 18, 19]
) -> tuple[int, float]:
    """
    Returns (best_bracket_celsius, probability) where best_bracket is
    the integer from `brackets` closest to the NOAA forecast mean for
    target_date at station. Probability is a rough normal CDF value.
    """
    forecast_temp = self._get_forecast_high(station, target_date)
    # Normal CDF around forecast_temp with sigma=NOAA_SIGMA
    ...
```

### Acceptance Criteria

- **Given** the bot has already entered Shanghai 17°C YES  
  **When** a whale copies Shanghai 18°C  
  **Then** the bot checks NOAA: if 18°C is within ±1 sigma of forecast, allow entry; otherwise block

- **Given** the bot already holds two Shanghai temperature brackets for the same date  
  **When** any new Shanghai temperature bracket signal arrives for that date  
  **Then** block unconditionally (`temp_cluster_capped`)

- **Given** no prior Shanghai positions  
  **When** five whale wallets hold different Shanghai temperatures  
  **Then** bot enters only the single bracket closest to the NOAA point forecast

### Priority: P0 — Highest Impact

**Estimated recovery on 434-trade history:** ~$45-$60. Weather is 57% of deployed capital; temperature clustering is the single largest structural loss.

---

## Problem 2: 5-Minute Crypto Binary Filter

### Diagnosis

Markets like "ETH Up or Down 9:00-9:15 AM" are short-window binary bets entered at ~97¢ total (both outcomes combined). Each individual outcome costs ~50¢. The vig makes the break-even win rate ~52-53%, and crypto 15-minute moves are essentially random. The expected value is **negative regardless of the source wallet's win rate**.

These are frequently entered because the bot monitors wallets that trade these markets, and the short-window resolution creates a misleadingly high "win rate" figure for wallets that bet both sides or simply catch random variance.

**Current code:** No resolution window filter exists. `polymarket_copytrade.py` fetches `endDate` from the Gamma API and stores it as `pos.end_date`, but never uses it to filter out ultra-short-resolution markets before entry.

### Required Changes

#### `strategies/polymarket_copytrade.py` — Add Resolution Window Filter

In `_should_copy_trade()`, before any execution logic, add:

```python
MINIMUM_RESOLUTION_HOURS = 0.5  # 30 minutes

def _check_resolution_window(
    self,
    market_data: dict,
    market_question: str,
) -> tuple[bool, str]:
    """
    Block markets resolving in < 30 minutes.
    
    Returns (allowed, reason).
    """
    end_date_str = market_data.get("endDate", "") or market_data.get("end_date_iso", "")
    if not end_date_str:
        return True, ""  # no data → don't block
    
    try:
        from datetime import datetime, timezone
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_remaining = (end_dt - now).total_seconds() / 3600
        
        if hours_remaining < MINIMUM_RESOLUTION_HOURS:
            return False, f"resolution_window_too_short_{hours_remaining:.1f}h"
    except (ValueError, TypeError):
        pass
    
    return True, ""
```

**Also add a market title pattern-based fast filter** for markets that structurally describe short windows:

```python
_SHORT_WINDOW_PATTERNS = [
    re.compile(r"\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*[AP]M", re.IGNORECASE),  # "9:00-9:15 AM"
    re.compile(r"next\s+\d+\s+minutes?", re.IGNORECASE),                          # "next 15 minutes"
    re.compile(r"\bup\s+or\s+down\b", re.IGNORECASE),                              # "ETH Up or Down"
]

def _is_short_window_market(self, market_question: str) -> bool:
    return any(p.search(market_question) for p in _SHORT_WINDOW_PATTERNS)
```

Add `_is_short_window_market()` as a pre-check in `_should_copy_trade()`. If True, log `skip_reason="short_window_market"` and return without executing.

#### `strategies/correlation_tracker.py` — Add `crypto_updown` Category Hard Block

When category is detected as `crypto_updown` and the title contains a time window pattern, the trade should be blocked at the correlation layer with a dedicated sub-category:

```python
# In CATEGORY_KEYWORDS, add:
"crypto_binary": [
    "up or down", "up-or-down", "pump or dump",
]
```

Then in `PolymarketCopyTrader._CATEGORY_LOSS_LIMITS`, add:

```python
"crypto_binary": 0.0,  # hard block — always negative EV
```

### Acceptance Criteria

- **Given** a market "Will ETH be up or down 9:00-9:15 AM?" at 97¢  
  **When** a whale wallet enters this market  
  **Then** the bot blocks the trade with reason `short_window_market` and logs it

- **Given** a weather market resolving in 2 hours  
  **When** a whale wallet enters this market  
  **Then** the bot allows the trade (weather 2h is reasonable, METAR still has edge)

- **Given** any market with `endDate` > 30 minutes from now  
  **When** a whale wallet enters  
  **Then** resolution window check passes

### Priority: P0

**Estimated recovery on 434-trade history:** ~$8-$12. These are small-stake losses but high frequency; each costs ~$0.50-$3 in expected negative EV.

---

## Problem 3: Wallet Quality Floor

### Diagnosis

The current `_min_win_rate = 0.55` (line 165, `polymarket_copytrade.py`) admits wallets with 55-65% win rates and P/L ratios near 1.0. A wallet with 60% WR and P/L 1.0 means: it wins 60% of the time but makes the same amount on wins as it loses on losses. After Polymarket's 2% fee, this is slightly negative or break-even. These wallets add noise without signal.

**Current `WalletScorer` settings** (line 314-316):
```python
self._wallet_scorer = WalletScorer(
    min_closed_positions=int(os.environ.get("WALLET_MIN_CLOSED", "50")),
)
```

The `min_closed_positions=50` is reasonable but the `_min_win_rate=0.55` applied in `_scan_and_score_wallets()` (line 654) is too low, and there is no explicit P/L ratio minimum enforcement at the scan layer.

**Current P/L ratio filter:** `WalletScorer` does compute `pl_ratio`, but the scan loop in `_scan_and_score_wallets()` only checks `win_rate >= self._min_win_rate` and `total_resolved >= min_trades`. P/L ratio thresholds are soft (composite score weighting) rather than hard gates.

### Required Changes

#### `strategies/polymarket_copytrade.py` — Raise Quality Thresholds

**Change the default `_min_win_rate`:**

```python
# Line 165 — before:
self._min_win_rate: float = getattr(settings, "copytrade_min_win_rate", 0.55)

# After:
self._min_win_rate: float = getattr(settings, "copytrade_min_win_rate", 0.65)
```

**Add minimum P/L ratio filter in `_scan_and_score_wallets()`:**

In the scan loop around line 647-696, after the win rate check, add:

```python
MIN_PL_RATIO = float(os.environ.get("WALLET_MIN_PL_RATIO", "1.5"))
MIN_TRADES_HIGH_WR = int(os.environ.get("WALLET_MIN_TRADES_HIGH_WR", "20"))
MIN_TRADES_MED_WR = int(os.environ.get("WALLET_MIN_TRADES_MED_WR", "30"))

# After computing analysis via score_from_basic_stats:
pl_ratio = analysis.pl_ratio

# Gate 1: P/L ratio hard floor
if pl_ratio < MIN_PL_RATIO and total_resolved < 100:
    # Exception: very high win rate (>= 80%) with large sample
    if win_rate < 0.80:
        logger.debug(
            "wallet_filtered_pl_ratio",
            address=address[:12],
            pl_ratio=round(pl_ratio, 2),
            win_rate=round(win_rate, 3),
        )
        continue

# Gate 2: Tiered quality requirements
# Tier A: High WR with adequate sample
# Tier B: Medium WR only if exceptional P/L ratio
tier_a = win_rate >= 0.70 and total_resolved >= MIN_TRADES_HIGH_WR
tier_b = win_rate >= 0.60 and pl_ratio >= 3.0 and total_resolved >= MIN_TRADES_MED_WR
tier_priority = address in self._PRIORITY_WALLETS  # always allow priority wallets

if not (tier_a or tier_b or tier_priority):
    logger.debug(
        "wallet_filtered_quality_tier",
        address=address[:12],
        win_rate=round(win_rate, 3),
        pl_ratio=round(pl_ratio, 2),
        total_resolved=total_resolved,
    )
    continue
```

#### `strategies/wallet_scoring.py` — Add Hard P/L Filter to `analyze_wallet()`

In `analyze_wallet()`, after computing `pl_ratio`, add an explicit red flag:

```python
# Line ~187 — after computing pl_ratio:
MIN_PL_RATIO_HARD = 1.5
if analysis.pl_ratio < MIN_PL_RATIO_HARD and analysis.total_closed >= 20:
    analysis.red_flags.append(f"low_pl_ratio_{analysis.pl_ratio:.2f}")
    analysis.is_filtered = True
```

#### Environment Variables to Expose

Add to your `.env` or Docker environment:

```bash
WALLET_MIN_PL_RATIO=1.5        # Block wallets with avg_win/avg_loss < 1.5
WALLET_MIN_TRADES_HIGH_WR=20   # Min resolved trades for 70%+ WR wallets
WALLET_MIN_TRADES_MED_WR=30    # Min resolved trades for 60-70% WR + high P/L wallets
WALLET_MIN_CLOSED=20           # Lower this from 50 (20 trades is enough for Tier A)
```

### Before/After Wallet Pool Estimate

| Threshold | Wallets Admitted (est.) | Notes |
|---|---|---|
| Current (WR >= 55%, any P/L) | ~71 | Includes ~25-30 break-even traders |
| Proposed (WR >= 70% OR WR >= 60% + P/L >= 3.0) | ~35-45 | Higher signal density |

### Acceptance Criteria

- **Given** wallet with 62% WR, P/L 1.1, 40 resolved trades  
  **When** scan runs  
  **Then** wallet is excluded (below both tiers: WR < 70%, P/L < 3.0)

- **Given** wallet with 68% WR, P/L 2.5, 25 resolved trades  
  **When** scan runs  
  **Then** wallet admitted via Tier A (WR >= 70% threshold is _not_ met but P/L and trades are strong — adjust threshold to 65% if too aggressive)

- **Given** priority wallet `0xde9f7f4e77a1595623ceb58e469f776257ccd43c` (tradecraft)  
  **When** scan runs regardless of win rate  
  **Then** always admitted (bypasses all quality gates)

### Priority: P1

**Estimated recovery:** ~$15-$20 over 434 trades by eliminating ~30% of trades that copied break-even wallets.

---

## Problem 4: Category Filtering (Whitelist / Graylist / Blacklist)

### Diagnosis

Current live P/L data shows:
- **Geopolitics:** LOSING — Houthi strike, Hungary PM positions are negative
- **Politics:** LOSING — Texas Senate -$2.59
- **Science:** Uncertain — small sample, insufficient data edge

These markets are **informationally efficient** at Polymarket. Political and geopolitical markets aggregate public information faster than the bot can react. The whale wallets being copied in these categories are likely either:
a) themselves losing in these categories
b) capturing rare insider-information moves the bot cannot replicate

**Current `_DEFAULT_CATEGORY_MULTIPLIERS`** (line 522-537) already shows awareness of this problem:
```python
"us_sports": 0.3,      # -$15
"soccer_intl": 0.2,    # -$8
```

But `politics: 1.5` and `geopolitics: 1.2` are too high given live data.

### Required Changes

#### `strategies/polymarket_copytrade.py` — Category Tier System

Replace the soft multiplier approach for losers with a hard **category tier gate**. Add a class-level constant:

```python
# Category tiers — applied before Kelly sizing and copy execution
CATEGORY_TIERS: dict[str, str] = {
    # WHITELIST — trade freely, full Kelly allowed
    "weather": "whitelist",
    "us_sports": "whitelist",    # Celtics/sports spreads winning
    "sports": "whitelist",
    "esports": "whitelist",
    "tennis": "whitelist",
    
    # GRAYLIST — trade only with LLM validation score >= 0.75
    "crypto": "graylist",        # only if resolution > 30 min
    "crypto_updown": "graylist",
    "economics": "graylist",     # Fed rate: high-confidence signals only
    "other": "graylist",
    
    # BLACKLIST — block unless LLM validation score >= 0.9
    "politics": "blacklist",
    "geopolitics": "blacklist",
    "science": "blacklist",
    "entertainment": "blacklist",
    "soccer_intl": "blacklist",  # international friendlies unpredictable
}
```

In `_should_copy_trade()`, add a tier check after category detection:

```python
def _check_category_tier(
    self,
    category: str,
    llm_score: float | None,
    market_question: str,
) -> tuple[bool, str]:
    """
    Enforce category tier rules.
    
    Whitelist: always allow.
    Graylist: allow if LLM score >= 0.75 or LLM validation disabled.
    Blacklist: only allow if LLM score >= 0.90. Otherwise block.
    
    Returns (allowed, reason).
    """
    tier = self.CATEGORY_TIERS.get(category, "graylist")
    
    if tier == "whitelist":
        return True, ""
    
    if tier == "graylist":
        if llm_score is None or llm_score >= 0.75:
            return True, ""
        return False, f"graylist_low_llm_score_{llm_score:.2f}"
    
    if tier == "blacklist":
        if llm_score is not None and llm_score >= 0.90:
            logger.info(
                "blacklist_category_llm_override",
                category=category,
                llm_score=llm_score,
                market=market_question[:60],
            )
            return True, "blacklist_llm_override"
        return False, f"blacklist_category_{category}"
    
    return True, ""  # unknown tier → allow
```

#### `strategies/correlation_tracker.py` — Update `_CATEGORY_LOSS_LIMITS`

In `polymarket_copytrade.py`, update the category loss limits to reflect blacklisting:

```python
self._CATEGORY_LOSS_LIMITS: dict[str, float] = {
    "crypto_updown": 10.0,    # tighter: short binaries filtered, but medium-term OK
    "crypto_binary": 0.0,     # hard block
    "sports": 30.0,
    "weather": 50.0,
    "politics": 5.0,          # down from 50 — near-blacklist, very low tolerance
    "geopolitics": 5.0,       # new: matches politics
    "science": 10.0,          # low tolerance
    "other": 25.0,
}
```

### Acceptance Criteria

- **Given** a "Will Texas Senate pass X bill?" market (politics)  
  **When** a whale wallet enters  
  **Then** bot calls LLM validator; if score < 0.90, blocks with `blacklist_category_politics`

- **Given** a "Will Fed cut rates 25bps in May?" market (economics = graylist)  
  **When** a whale wallet enters  
  **Then** bot calls LLM validator; if score >= 0.75, allows entry

- **Given** a "Will it rain in Denver tomorrow?" market (weather = whitelist)  
  **When** a whale wallet enters  
  **Then** no LLM validation required; proceeds directly to Kelly sizing

### Priority: P1

**Estimated recovery:** ~$8-$10. Preventing politics/geopolitics entries avoids ongoing -$5 to -$8 drawdown per month.

---

## Problem 5: Position Correlation / Same-Event Guard

### Diagnosis

The bot can enter correlated positions that effectively cancel each other or represent the same bet split multiple ways. For example:
- "Will Fed decrease rates by 25bps?" YES + "Will Fed increase rates?" YES + "Will Fed hold rates?" YES
- These three positions together cover nearly the entire probability space; the bot is paying 3× the spread to hold a position equivalent to "I have no view on the Fed"

**Current guard:** `_active_event_slugs` (line 279-282) prevents holding multiple outcomes on the _exact same event_. This works when the Gamma API returns a common `event_slug`. However:
1. Not all correlated markets share the same `event_slug`
2. The guard only prevents same-event entries, not economically-equivalent positions across different events

### Required Changes

#### `strategies/correlation_tracker.py` — Add Semantic Correlation Detector

Add a method that checks whether a proposed trade is semantically correlated with existing open positions:

```python
# Add to correlation_tracker.py

_CORRELATED_KEYWORD_GROUPS: list[list[str]] = [
    # Fed / interest rates — any two of these are correlated
    ["fed rate", "interest rate", "fomc", "rate hike", "rate cut", "rate hold",
     "basis points", "bps", "federal funds"],
    # Inflation clusters
    ["cpi", "inflation", "pce", "core inflation", "consumer prices"],
    # Geopolitical conflict clusters
    ["houthi", "red sea", "yemen", "hamas", "gaza", "hezbollah"],
    # Presidential approval / polling
    ["trump approval", "biden approval", "presidential poll"],
]

def check_semantic_correlation(
    self,
    proposed_question: str,
    max_correlated_positions: int = 1,
) -> tuple[bool, str, list[str]]:
    """
    Check if the proposed market is semantically correlated with existing positions.
    
    Returns (would_exceed_limit, reason, correlated_position_ids).
    
    Rules:
    - For each keyword group, count how many existing positions match.
    - If proposed question also matches that group AND existing count >= max,
      block the trade.
    """
    q_lower = proposed_question.lower()
    
    for group in _CORRELATED_KEYWORD_GROUPS:
        # Does proposed market match this group?
        if not any(kw in q_lower for kw in group):
            continue
        
        # Count existing positions that match this group
        correlated_ids = []
        for pos_id, (cat, _) in self._positions.items():
            # Need access to market_question per position — add to CorrelationTracker
            pos_question = self._position_questions.get(pos_id, "").lower()
            if any(kw in pos_question for kw in group):
                correlated_ids.append(pos_id)
        
        if len(correlated_ids) >= max_correlated_positions:
            return True, f"semantic_correlation_{group[0][:20]}", correlated_ids
    
    return False, "", []
```

**Supporting change** — store market questions in `CorrelationTracker`:

```python
# In __init__:
self._position_questions: dict[str, str] = {}

# In add_position():
def add_position(self, position_id, market_question, size_usd, tags=None):
    category = categorize_market(market_question, tags)
    self._positions[position_id] = (category, size_usd)
    self._position_questions[position_id] = market_question  # ADD THIS
    return category

# In remove_position():
def remove_position(self, position_id):
    self._positions.pop(position_id, None)
    self._position_questions.pop(position_id, None)  # ADD THIS
```

#### `strategies/polymarket_copytrade.py` — Wire Semantic Correlation Check

In `_should_copy_trade()`, after the existing `would_exceed_limit()` check, add:

```python
# Semantic correlation check — prevent economically equivalent positions
correlated, corr_reason, corr_ids = self._correlation_tracker.check_semantic_correlation(
    market_question=trade.get("market_question", ""),
    max_correlated_positions=1,
)
if correlated:
    logger.info(
        "copytrade_skipped_correlated",
        reason=corr_reason,
        existing_positions=corr_ids[:3],
        market=trade.get("market_question", "")[:60],
    )
    return False, corr_reason
```

### Acceptance Criteria

- **Given** bot holds "Fed decrease rates 25bps YES"  
  **When** whale enters "Fed hold rates YES"  
  **Then** blocked with `semantic_correlation_fed rate`

- **Given** bot holds "ETH above $3500 by April YES"  
  **When** whale enters "BTC above $90k by April YES"  
  **Then** allowed (different assets, different correlation group)

- **Given** bot holds "Houthi attacks Red Sea ships YES"  
  **When** whale enters "Yemen ceasefire by June YES"  
  **Then** blocked with `semantic_correlation_houthi`

### Priority: P1

**Estimated recovery:** ~$5-$8 across the 434-trade history. Prevents compounding losses on Fed/geopolitics clusters.

---

## Problem 6: Exit Discipline

### Diagnosis

**Only 1 exit has been executed in 434 trades.**

The `ExitEngine` exists and has correct logic (stop loss at 50%, trailing stop activation at 30%, time-based exit at 48h). The exit engine is registered in `_manage_positions()`. However, exits are not firing. Root causes:

1. **Stop loss is set at 50%** (line 72, `exit_engine.py`): For binary prediction markets, a 50% loss from entry means a position entered at 0.60 has dropped to 0.30. This is deep in the money on a losing bet. At 0.30, the position has already lost 50% of its value and market resolution risk is high. **The stop loss should be 30%**, not 50%.

2. **Time-based exit requires `abs(pnl_pct) < 0.05`** (line 181): This means a position must be nearly flat (within 5% of entry) to trigger the time exit. But a position down 20-40% over 48 hours is not "stale" — it is losing. The time exit should trigger if the position has not _improved_ over the hold window, regardless of whether it has moved.

3. **Take profit mechanics**: The trailing stop activation at +30% is correct (let winners ride), but positions at 95¢+ should be flagged for hard exit since the remaining upside is only 5¢ while downside risk of market reversal is real.

4. **No active sell execution**: Review `_manage_positions()` to confirm `ExitSignal` is being translated into actual sell orders, not just logged.

### Required Changes

#### `strategies/exit_engine.py` — Tighten Stop Loss and Time Exit

```python
# Change defaults:
class ExitEngine:
    def __init__(
        self,
        take_profit_1_pct: float = 0.30,
        take_profit_2_pct: float = 9.99,
        stop_loss_pct: float = 0.30,        # CHANGED: was 0.50
        trailing_stop_pct: float = 0.15,
        time_exit_hours: float = 48.0,
        time_exit_min_move_pct: float = 0.05,
    ) -> None:
```

Update `CATEGORY_EXIT_PARAMS`:

```python
CATEGORY_EXIT_PARAMS: dict[str, dict[str, float]] = {
    "crypto_updown": {"sl": 0.25, "time_hours": 8,   "trailing": 0.10},  # TIGHTER: 8h, 25% SL
    "sports":        {"sl": 0.30, "time_hours": 24,  "trailing": 0.12},  # was sl=0.40
    "weather":       {"sl": 0.35, "time_hours": 48,  "trailing": 0.15},  # was sl=0.50
    "politics":      {"sl": 0.30, "time_hours": 48,  "trailing": 0.20},  # was sl=0.50, time=96
    "geopolitics":   {"sl": 0.30, "time_hours": 48,  "trailing": 0.20},  # new entry
    "other":         {"sl": 0.35, "time_hours": 48,  "trailing": 0.18},
}
```

**Fix the time-based exit logic** in `evaluate()`:

```python
# Replace line 181:
# OLD:
if hold_hours >= effective_time_hours and abs(pnl_pct) < self._time_min_move:

# NEW — time exit fires if:
# (a) stale: held > time_hours and price barely moved (original logic), OR
# (b) deteriorating: held > 50% of time_hours and position is down > 20%
stale = hold_hours >= effective_time_hours and abs(pnl_pct) < self._time_min_move
deteriorating = (
    hold_hours >= effective_time_hours * 0.5 
    and pnl_pct <= -0.20
    and tracker.peak_price <= entry * 1.05  # never showed strength
)
if stale or deteriorating:
    return ExitSignal(
        position_id=position_id,
        reason="time_exit_stale" if stale else "time_exit_deteriorating",
        sell_fraction=1.0,
        current_price=current_price,
        entry_price=entry,
        pnl_pct=pnl_pct,
        hold_time_hours=hold_hours,
        peak_price=tracker.peak_price,
    )
```

**Add high-price take-profit** to capture near-resolution positions:

```python
# Add after trailing stop activation check (step 3):
# 3b. Near-resolution take profit: if position is at 92¢+ and was entered below 80¢,
#     this is likely resolving YES soon — exit to capture premium and free capital
NEAR_RESOLUTION_PRICE = 0.92
if current_price >= NEAR_RESOLUTION_PRICE and entry < 0.80:
    return ExitSignal(
        position_id=position_id,
        reason="near_resolution_takeprofit",
        sell_fraction=0.75,  # sell 75%, keep 25% for full resolution
        current_price=current_price,
        entry_price=entry,
        pnl_pct=pnl_pct,
        hold_time_hours=hold_hours,
        peak_price=tracker.peak_price,
    )
```

#### `strategies/polymarket_copytrade.py` — Verify Sell Execution in `_manage_positions()`

Audit `_manage_positions()` to ensure `ExitSignal` instances are translated into actual sell orders. The relevant flow should be:

```python
async def _manage_positions(self) -> None:
    for pos_id, pos in list(self._positions.items()):
        # Fetch current market price
        current_price = await self._get_current_price(pos.token_id)
        if current_price is None:
            continue
        
        signal = self._exit_engine.evaluate(pos_id, current_price)
        if signal:
            logger.info(
                "exit_signal_fired",
                position_id=pos_id,
                reason=signal.reason,
                pnl_pct=round(signal.pnl_pct * 100, 1),
                sell_fraction=signal.sell_fraction,
            )
            # THIS must actually execute a sell order:
            await self._execute_exit(pos, signal)  # verify this exists and works
```

If `_execute_exit()` is returning early due to `dry_run=True` or a missing sell implementation, **this is the single highest-priority bug to fix.** Log every exit signal even in dry_run mode so the P/L impact can be measured.

#### Environment Variables

```bash
EXIT_SL_PCT=0.30           # Stop loss at 30% (down from 50%)
EXIT_TP1_PCT=0.30          # Trailing stop activation (unchanged)
EXIT_TRAILING_PCT=0.15     # Trail at 15% below peak (unchanged)
EXIT_TIME_HOURS=48         # Time-based exit window (unchanged)
EXIT_TIME_MIN_MOVE=0.05    # Stale threshold (unchanged)
```

### Acceptance Criteria

- **Given** position entered at 0.60, current price 0.42 (30% loss)  
  **When** `evaluate()` is called  
  **Then** `ExitSignal(reason="stop_loss", sell_fraction=1.0)` is returned

- **Given** position entered at 0.50, held for 24 hours, never above 0.53, now at 0.38  
  **When** `evaluate()` is called (24h = 50% of 48h time_hours)  
  **Then** `ExitSignal(reason="time_exit_deteriorating")` returned (down 24%, no strength shown)

- **Given** position entered at 0.45, current price 0.93  
  **When** `evaluate()` is called  
  **Then** `ExitSignal(reason="near_resolution_takeprofit", sell_fraction=0.75)` returned

- **Given** dry_run=True  
  **When** any `ExitSignal` is generated  
  **Then** signal is logged with full details even though no actual sell is placed

### Priority: P0 — Second Highest Impact

**Estimated recovery on 434 trades:** ~$25-$35. With 47 open positions and likely 15-20 of them underwater, cutting losers at -30% instead of -50% saves ~$1.50-$3 per losing position vs. current behavior of holding to zero.

---

## Problem 7: Position Sizing — Raise Kelly Hard Cap

### Diagnosis

`KellySizer.HARD_CAP_USD = 10.0` (line 19, `kelly_sizing.py`) means that no matter how strong the Kelly signal, the maximum single position is $10. For METAR-confirmed weather bets (the best edge in the portfolio), a Kelly fraction of 25% on a $402 portfolio could justify $25-$40 per position, but the hard cap suppresses this.

**Current results:** All bets are $5-$13. Weather is 57% of deployed capital because the bot enters many small positions rather than fewer larger ones. This creates the temperature clustering problem (too many small bets across brackets) and limits the upside when METAR bets win.

**Proposal:** Implement a **tiered hard cap** based on edge confidence, rather than a single flat cap:

| Tier | Criteria | Max Position |
|---|---|---|
| Premium | METAR-confirmed weather + wallet WR >= 75% | $25 |
| Standard | Sports (short-term) or weather without METAR + WR >= 70% | $15 |
| Base | Everything else passing filters | $10 |
| Minimum | All positions | $5 |

### Required Changes

#### `strategies/kelly_sizing.py` — Tiered Hard Cap

```python
class KellySizer:
    # Tiered caps
    HARD_CAP_PREMIUM_USD: float = 25.0   # METAR-confirmed weather
    HARD_CAP_STANDARD_USD: float = 15.0  # sports or validated weather
    HARD_CAP_BASE_USD: float = 10.0      # all other passing trades
    
    def calculate_position_size(
        self,
        wallet_win_rate: float,
        market_price: float,
        bankroll: float,
        category: str = "",
        category_pnl: float = 0.0,
        edge_tier: str = "base",   # NEW PARAMETER: "premium", "standard", "base"
    ) -> float:
        # ... existing Kelly calculation unchanged ...
        
        # Select cap based on edge tier
        if edge_tier == "premium":
            hard_cap = self.HARD_CAP_PREMIUM_USD
        elif edge_tier == "standard":
            hard_cap = self.HARD_CAP_STANDARD_USD
        else:
            hard_cap = self.HARD_CAP_BASE_USD
        
        result = min(result, hard_cap)
        ...
```

#### `strategies/polymarket_copytrade.py` — Determine Edge Tier Before Sizing

Before calling `self._kelly_sizer.calculate_position_size()`, determine the edge tier:

```python
def _determine_edge_tier(
    self,
    category: str,
    wallet_win_rate: float,
    market_question: str,
    metar_confirmed: bool = False,
) -> str:
    """
    Classify trade edge for tiered position sizing.
    
    Returns "premium", "standard", or "base".
    """
    # Premium: METAR/NOAA-confirmed weather + strong wallet
    if category == "weather" and metar_confirmed and wallet_win_rate >= 0.75:
        return "premium"
    
    # Standard: short-term sports with strong wallet, or weather without METAR
    if category in ("us_sports", "sports", "tennis", "esports") and wallet_win_rate >= 0.70:
        return "standard"
    if category == "weather" and wallet_win_rate >= 0.70:
        return "standard"
    
    return "base"
```

The `metar_confirmed` flag comes from a quick METAR lookup — if the market question matches a city/station and the current METAR temperature is within 2°C of the bracket, set `metar_confirmed=True`.

#### Environment Variables

```bash
KELLY_CAP_PREMIUM=25.0    # METAR-confirmed weather
KELLY_CAP_STANDARD=15.0   # Sports/strong weather  
KELLY_CAP_BASE=10.0       # Everything else
KELLY_FRACTION=0.25       # Unchanged
KELLY_MIN_SIZE=5.0        # Raise minimum from $2 to $5
```

### Acceptance Criteria

- **Given** METAR confirms Denver temp within bracket, wallet WR = 0.78, bankroll $400  
  **When** Kelly sizing is calculated  
  **Then** result capped at $25.00, not $10.00

- **Given** Celtics spread bet, wallet WR = 0.71, bankroll $400  
  **When** Kelly sizing is calculated  
  **Then** result capped at $15.00

- **Given** politics category bet, wallet WR = 0.91, bankroll $400  
  **When** Kelly sizing is calculated (assuming LLM override allowed it)  
  **Then** result capped at $10.00 (base tier — politics not elevated)

### Priority: P2

**Estimated uplift:** ~$10-$15 by allowing METAR bets to scale to their full Kelly-justified size. This is upside capture rather than loss prevention, so it is P2 vs. the P0/P1 fixes above.

---

## Implementation Priority Order

| # | Problem | Priority | Est. Recovery | Files | Effort |
|---|---|---|---|---|---|
| 1 | Multi-temperature clustering | **P0** | +$45-60 | `polymarket_copytrade.py`, `noaa_client.py` | 2-3 days |
| 2 | Exit discipline (SL + time exit) | **P0** | +$25-35 | `exit_engine.py`, `polymarket_copytrade.py` | 1-2 days |
| 3 | 5-minute crypto binary filter | **P0** | +$8-12 | `polymarket_copytrade.py`, `correlation_tracker.py` | 0.5 days |
| 4 | Wallet quality floor raise | **P1** | +$15-20 | `polymarket_copytrade.py`, `wallet_scoring.py` | 1 day |
| 5 | Category blacklist / tier system | **P1** | +$8-10 | `polymarket_copytrade.py`, `correlation_tracker.py` | 1 day |
| 6 | Semantic correlation guard | **P1** | +$5-8 | `correlation_tracker.py`, `polymarket_copytrade.py` | 1 day |
| 7 | Tiered Kelly hard cap | **P2** | +$10-15 | `kelly_sizing.py`, `polymarket_copytrade.py` | 0.5 days |

**Total estimated recovery on 434-trade history:** $116-$160  
**Total implementation effort:** ~7-10 engineering days

**Recommended implementation sequence:**
1. Fix exit engine stop loss first (P0, 1 day) — immediately limits downside on existing 47 open positions
2. Deploy temperature clustering fix (P0, 2-3 days) — highest dollar impact going forward
3. Add crypto binary filter (P0, 0.5 days) — trivial to implement
4. Raise wallet quality floor (P1, 1 day)
5. Deploy category tier system (P1, 1 day)
6. Add semantic correlation guard (P1, 1 day)
7. Implement tiered Kelly caps (P2, 0.5 days)

---

## Before/After Projection: 434-Trade Simulation

### Assumptions

- Average position size: ~$4.50 (based on $196 deployed / 47 open + resolved positions)
- Weather bracket clusters: ~6-8 clusters entered with 4-6 brackets each
- Crypto binary trades: estimated ~15-20 trades fitting the short-window pattern
- Wallet quality: ~25-30% of copied trades came from wallets below new thresholds
- Exits not taken: ~15 positions currently > -30% that would have been stopped

### Estimated Impact

| Category | Current Est. P/L | After All Fixes |
|---|---|---|
| Weather (multi-temp fixed) | -$40 recovered as $13 net loss | +$27 improvement |
| Weather (METAR sizing) | $11 realized | +$15 improvement via larger bets |
| US Sports | $29 deployed, ~$6 net profit | +$3 from wallet filtering |
| Crypto binaries | -$10 in negative EV bets | +$10 recovered |
| Politics/Geopolitics | -$9 current | +$9 recovered (blacklisted) |
| Exit savings (SL) | -$25 unrealized on losers | +$25 via -30% stops |
| Wallet quality improvement | ~30% fewer low-edge trades | +$15-20 net |
| **Total** | **~$2-5 net** | **~$85-110 net improvement** |

**Note:** These are retrospective estimates. Forward performance will depend on market conditions and whether the whale wallet quality improvement is as effective as modeled. The weather category improvement is the highest-confidence estimate because it corrects a deterministic structural error (buying guaranteed-losing temperature clusters).

---

## Risk Management Summary

### Current Risks Not Addressed by These Fixes

1. **Whale wallet concentration:** Two priority wallets (`tradecraft`, `coldmath`) are always tracked. If these wallets change strategy or go cold, P/L will deteriorate. Add a 30-day rolling performance gate: if a priority wallet's last-30-day WR drops below 60%, demote it to standard tracking.

2. **Market liquidity:** Small markets (< $5k volume) have wide bid-ask spreads that make exit near-impossible. Add a minimum market volume filter of $10k to `_should_copy_trade()`:
   ```python
   market_volume = float(trade.get("volume", 0))
   if market_volume < 10_000:
       return False, "insufficient_liquidity"
   ```

3. **Redemption lag:** Winning positions are not redeemed automatically — the redeemer runs every 5 minutes. Confirm that `src/redeemer.py` is running as a separate loop and that all resolved winning positions are being redeemed promptly. Unredeemed winners tie up capital unnecessarily.

4. **Bankroll tracking drift:** The internal bankroll tracker (line 302: `COPYTRADE_BANKROLL=300`) diverges from on-chain USDC balance as resolved positions are redeemed. Periodically sync the bankroll to `on-chain USDC + estimated market value of open positions` rather than on-chain USDC alone (which excludes deployed capital).

### New Risks Introduced by These Fixes

1. **Temperature clustering may block valid spreads:** If NOAA forecast confidence is low (e.g., forecast is 16°C ± 3.5°C sigma), blocking brackets beyond ±1 sigma may still miss. Consider: if sigma > 4°C, allow entry in two adjacent brackets rather than one.

2. **Wallet quality floor may over-filter:** Raising the threshold from 55% to 65-70% WR will reduce the wallet pool significantly. If fewer than 20 wallets qualify, the bot loses signal diversity. Add a fallback: if qualified wallets < 20, lower threshold to 60% WR with P/L >= 2.0.

3. **Category blacklist is binary:** An LLM score threshold of 0.90 for politics is very strict. Some political markets (election outcome at 98¢ with clear winner) have genuine edge. Consider: add a "price certainty" exception — if market price >= 0.92 on a political outcome that LLM rates >= 0.70, allow entry for small size ($5 cap).

---

## Code-Level Quick Reference

### Files to Modify

| File | Changes Needed | Problem Addressed |
|---|---|---|
| `strategies/polymarket_copytrade.py` | Temperature cluster check, crypto binary filter, category tier gate, edge tier determination, wallet quality gates | 1, 2, 4, 5, 7 |
| `strategies/exit_engine.py` | Lower SL to 30%, add deteriorating time exit, add near-resolution take-profit | 6 |
| `strategies/kelly_sizing.py` | Add `edge_tier` parameter, tiered hard caps, raise min size to $5 | 7 |
| `strategies/wallet_scoring.py` | Add P/L ratio hard floor red flag, lower `min_closed_positions` to 20 | 3 |
| `strategies/correlation_tracker.py` | Add semantic correlation groups, store position questions, add `check_semantic_correlation()` | 5 |
| `src/noaa_client.py` | Add `get_best_temperature_bracket()` helper | 1 |

### New Environment Variables

```bash
# Temperature clustering
TEMP_CLUSTER_MAX_BRACKETS=2          # max brackets per city/date

# Wallet quality
WALLET_MIN_PL_RATIO=1.5
WALLET_MIN_TRADES_HIGH_WR=20
WALLET_MIN_TRADES_MED_WR=30
WALLET_MIN_CLOSED=20

# Exit engine
EXIT_SL_PCT=0.30                     # was 0.50
EXIT_TIME_HOURS=48                   # unchanged
EXIT_TIME_MIN_MOVE=0.05              # unchanged

# Sizing
KELLY_CAP_PREMIUM=25.0
KELLY_CAP_STANDARD=15.0
KELLY_CAP_BASE=10.0
KELLY_MIN_SIZE=5.0

# Category filtering
CATEGORY_BLACKLIST_LLM_THRESHOLD=0.90
CATEGORY_GRAYLIST_LLM_THRESHOLD=0.75

# Resolution window
MIN_RESOLUTION_HOURS=0.5

# Liquidity
MIN_MARKET_VOLUME_USD=10000
```

---

## Open Questions

| # | Question | Owner | Blocking? |
|---|---|---|---|
| 1 | Is `_execute_exit()` in `_manage_positions()` actually calling sell orders in live mode? Review the last 434 trades for any sell order transactions on-chain. | Engineering | **YES — P0 before deploying exit changes** |
| 2 | Do NOAA forecasts cover all the cities in active weather markets? Shanghai is a Chinese city — NOAA may not have reliable forecasts. Is the METAR client using an international data source for Asian markets? | Engineering | YES — affects temperature clustering fix |
| 3 | Which of the 71 tracked wallets would be dropped by the new P/L >= 1.5 floor? Run a retrospective analysis on the wallet cache (`/data/copytrade_wallets.json`) to quantify wallet reduction. | Data | No |
| 4 | The `both_sides_trader` flag in `WalletAnalysis` — is it currently being used to filter wallets? If not, it should be. | Engineering | No |
| 5 | Can the Gamma API return `endDate` in a reliable format for all markets? Some markets have rolling resolution windows. | Engineering | Yes — affects crypto binary filter |

---

*Generated from codebase analysis of `/home/user/workspace/AI-Server/polymarket-bot/` on 2026-04-01.*
