# X-Intake Full Loop — Wire Signals Into Trading Decisions

## Context

The x-intake analysis pipeline is well-built — GPT-4o-mini analyzes posts, extracts Polymarket signals, classifies relevance, and publishes to Redis. But there are four critical disconnects:

1. **x-alpha-collector is NOT in docker-compose** — the automated monitor for 40+ curated X accounts never runs. Only manually-forwarded iMessage links get analyzed.
2. **RSSHub is NOT in docker-compose** — the collector depends on it for RSS feeds from X accounts.
3. **The trading bot ignores x_intel signals** — `XIntelProcessor.get_market_boost()` is fully implemented but `polymarket_copytrade.py` never calls it. Signals accumulate in a 2-hour rolling window that no strategy reads.
4. **No closed feedback loop** — we don't track which X signals led to profitable trades, so we can't learn which authors/signal types are most valuable.

This prompt fixes all four.

---

## Task 1: Add x-alpha-collector + RSSHub to docker-compose.yml

Add these two service blocks to `docker-compose.yml`. Place them after the `x-intake` service block.

```yaml
  rsshub:
    image: diygod/rsshub:latest
    container_name: rsshub
    restart: unless-stopped
    environment:
      - NODE_ENV=production
      - CACHE_TYPE=memory
      - CACHE_EXPIRE=600
      - REQUEST_TIMEOUT=30000
      - PROXY_URI=
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:1200"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - default
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  x-alpha-collector:
    build:
      context: ./integrations/x_alpha_collector
    container_name: x-alpha-collector
    restart: unless-stopped
    environment:
      - RSSHUB_URL=http://rsshub:1200
      - X_INTAKE_URL=http://x-intake:8101
      - REDIS_URL=redis://:d19c9b0faebeee9927555eb8d6b28ec9@redis:6379
      - POLL_INTERVAL_SECONDS=600
      - SEEN_DB_PATH=/data/x_alpha_seen.json
      - IMESSAGE_BRIDGE_URL=http://host.docker.internal:8199
    volumes:
      - ./data/x_intake:/data
    depends_on:
      rsshub:
        condition: service_healthy
      x-intake:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - default
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**Update the container count** in CLAUDE.md — find the current count (18 or 19) and add 2 (rsshub + x-alpha-collector).

**Add to CLAUDE.md service table:**
```
| rsshub | 1200 (internal) | Node.js | RSS feed proxy for X accounts |
| x-alpha-collector | — | Python | Monitors 40+ X accounts every 10 min via RSSHub |
```

### Verification
```zsh
docker compose config --quiet && echo "compose valid" || echo "BROKEN"
grep -c "rsshub" docker-compose.yml
grep -c "x-alpha-collector" docker-compose.yml
```

---

## Task 2: Wire x_intel Boosts Into Copytrade Strategy

This is the critical missing link. The `XIntelProcessor` already maintains a `get_market_boost()` method that returns boost info when a market title matches X intel keywords. But `polymarket_copytrade.py` never queries it.

### 2a. Pass XIntelProcessor reference to copytrade

In `polymarket-bot/src/main.py`, find where the copytrade strategy is instantiated. After the `XIntelProcessor` is created (~line 496), pass it to the copytrade strategy. Look for where the copytrade strategy is created and add:

```python
# After x_intel is created:
if hasattr(deps, 'x_intel') and hasattr(copytrade_strategy, 'set_x_intel'):
    copytrade_strategy.set_x_intel(deps.x_intel)
```

### 2b. Add x_intel integration to polymarket_copytrade.py

Add a method to accept the XIntelProcessor reference. Find the `__init__` method and add:

```python
self._x_intel = None  # Set via set_x_intel() after startup
```

Add the setter method:

```python
def set_x_intel(self, x_intel) -> None:
    """Wire the X Intel Processor for signal-aware trading."""
    self._x_intel = x_intel
    logger.info("x_intel_wired_to_copytrade")
```

### 2c. Apply x_intel boost in the trade evaluation

Find the section in copytrade where `confidence_score` or `size_usd` is calculated before placing a trade. This is likely in the method that evaluates whether to execute a copy trade (look for `confidence` calculation near `category_multiplier`).

Add this boost logic AFTER the category multiplier is applied but BEFORE the final trade execution:

```python
# ── X-Intel signal boost ──
if self._x_intel is not None:
    market_title = signal.market_title or ""  # or however the market title is accessed
    x_boost = self._x_intel.get_market_boost(market_title)
    if x_boost is not None:
        x_confidence = x_boost.get("confidence", 0)
        x_direction = x_boost.get("direction", "")
        x_author = x_boost.get("author", "unknown")

        # Boost: if x-intel agrees with trade direction, increase confidence
        # Suppress: if x-intel disagrees, reduce confidence
        trade_side = "yes"  # or however the trade side is determined
        if x_direction == trade_side:
            # Intel agrees — boost confidence by up to 20%
            boost_pct = min(x_confidence * 0.2, 0.20)
            conf *= (1.0 + boost_pct)
            logger.info(
                "x_intel_boost_applied",
                market=market_title[:60],
                author=x_author,
                x_confidence=round(x_confidence, 2),
                boost_pct=round(boost_pct, 3),
                new_conf=round(conf, 1),
            )
        elif x_direction and x_direction != trade_side:
            # Intel disagrees — suppress by 30%
            conf *= 0.70
            logger.info(
                "x_intel_suppress_applied",
                market=market_title[:60],
                author=x_author,
                x_direction=x_direction,
                trade_side=trade_side,
                new_conf=round(conf, 1),
            )
```

IMPORTANT: Adapt variable names to match the actual code. The key variables to find are:
- The confidence/score variable used for trade sizing
- The market title string
- The trade direction (yes/no or buy side)
- Where the final "should we execute?" decision is made

The boost should be CONSERVATIVE — max 20% increase, 30% decrease. We can tune later once we see which signals actually correlate with wins.

---

## Task 3: Signal Performance Tracking (Feedback Loop)

Create a new file `polymarket-bot/src/signal_tracker.py`:

```python
"""Signal Tracker — records which X intel signals influenced trades and their outcomes.

Enables learning: which X accounts, signal types, and keywords lead to profitable trades?
Data stored in SQLite for analysis and auto-tuning.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

DB_PATH = Path(os.environ.get("SIGNAL_TRACKER_DB", "/data/polymarket/signal_tracker.db"))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_author TEXT NOT NULL,
            signal_keyword TEXT,
            signal_direction TEXT,
            signal_confidence REAL,
            signal_relevance INTEGER,
            signal_timestamp REAL,
            trade_market TEXT,
            trade_side TEXT,
            trade_price REAL,
            trade_size_usd REAL,
            trade_timestamp REAL,
            outcome TEXT DEFAULT 'open',
            pnl REAL DEFAULT 0,
            resolved_at REAL,
            created_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS author_performance (
            author TEXT PRIMARY KEY,
            total_signals INTEGER DEFAULT 0,
            trades_influenced INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            avg_relevance REAL DEFAULT 0,
            last_signal_at REAL,
            updated_at REAL DEFAULT (unixepoch())
        )
    """)
    conn.commit()
    return conn


def record_signal_trade(
    signal: dict[str, Any],
    trade: dict[str, Any],
) -> None:
    """Record that an X signal influenced a trade decision."""
    try:
        conn = _get_conn()
        conn.execute("""
            INSERT INTO signal_trades
                (signal_author, signal_keyword, signal_direction, signal_confidence,
                 signal_relevance, signal_timestamp, trade_market, trade_side,
                 trade_price, trade_size_usd, trade_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.get("author", ""),
            signal.get("keyword", ""),
            signal.get("direction", ""),
            signal.get("confidence", 0),
            signal.get("relevance", 0),
            signal.get("timestamp", 0),
            trade.get("market", ""),
            trade.get("side", ""),
            trade.get("price", 0),
            trade.get("size_usd", 0),
            time.time(),
        ))
        conn.commit()
        conn.close()
        logger.info("signal_trade_recorded", author=signal.get("author"), market=trade.get("market", "")[:50])
    except Exception as exc:
        logger.warning("signal_trade_record_failed", error=str(exc)[:100])


def update_trade_outcome(trade_market: str, outcome: str, pnl: float) -> None:
    """Update the outcome of a signal-influenced trade after resolution."""
    try:
        conn = _get_conn()
        conn.execute("""
            UPDATE signal_trades
            SET outcome = ?, pnl = ?, resolved_at = ?
            WHERE trade_market = ? AND outcome = 'open'
        """, (outcome, pnl, time.time(), trade_market))

        # Update author performance
        conn.execute("""
            INSERT INTO author_performance (author, total_signals, trades_influenced, wins, losses, total_pnl, last_signal_at)
            SELECT
                signal_author,
                COUNT(*),
                COUNT(*),
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END),
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END),
                SUM(pnl),
                MAX(signal_timestamp)
            FROM signal_trades
            WHERE signal_author IN (SELECT signal_author FROM signal_trades WHERE trade_market = ?)
            GROUP BY signal_author
            ON CONFLICT(author) DO UPDATE SET
                trades_influenced = excluded.trades_influenced,
                wins = excluded.wins,
                losses = excluded.losses,
                total_pnl = excluded.total_pnl,
                last_signal_at = excluded.last_signal_at,
                updated_at = unixepoch()
        """, (trade_market,))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("signal_outcome_update_failed", error=str(exc)[:100])


def get_author_leaderboard(limit: int = 20) -> list[dict]:
    """Get top-performing X signal authors by P&L."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT author, trades_influenced, wins, losses, total_pnl,
                   CASE WHEN trades_influenced > 0
                        THEN ROUND(100.0 * wins / trades_influenced, 1)
                        ELSE 0 END as win_rate
            FROM author_performance
            WHERE trades_influenced >= 3
            ORDER BY total_pnl DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_signal_summary() -> dict[str, Any]:
    """Dashboard-friendly signal performance summary."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM signal_trades").fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'open'").fetchone()[0]
        wins = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'win'").fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM signal_trades WHERE outcome = 'loss'").fetchone()[0]
        total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) FROM signal_trades WHERE outcome != 'open'").fetchone()[0]
        conn.close()
        return {
            "total_signal_trades": total,
            "open": open_count,
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(100 * wins / max(wins + losses, 1), 1),
        }
    except Exception:
        return {}
```

### Wire signal_tracker into copytrade

In the section where the x_intel boost is applied (Task 2c), add recording after a trade executes:

```python
from src.signal_tracker import record_signal_trade

# After trade execution succeeds:
if x_boost is not None:
    record_signal_trade(
        signal={
            "author": x_boost.get("author", ""),
            "keyword": matched_keyword,
            "direction": x_boost.get("direction", ""),
            "confidence": x_boost.get("confidence", 0),
            "relevance": x_boost.get("relevance", 0),
            "timestamp": x_boost.get("timestamp", 0),
        },
        trade={
            "market": market_title,
            "side": trade_side,
            "price": entry_price,
            "size_usd": size_usd,
        },
    )
```

Adapt variable names to match the actual trade execution context.

---

## Task 4: Add Signal Tracker API Endpoints

Add to `polymarket-bot/api/routes.py`:

```python
@router.get("/api/x-intel/performance")
async def x_intel_performance():
    """Signal tracking performance metrics."""
    try:
        from src.signal_tracker import get_signal_summary, get_author_leaderboard
        return {
            "summary": get_signal_summary(),
            "leaderboard": get_author_leaderboard(10),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}
```

---

## Task 5: Update Watchlist

Review the current `integrations/x_alpha_collector/watchlist.json`. Some handles look garbled (e.g., `kaborneogadget`, `windaborneog`, `replaborneog`, `CMaborneogGroup`, `zaborneog`, `NickTimaborneog`, `coaborneogadget`). These are clearly corrupted. Either:
- Remove them if the original handle is unknown
- Replace with correct handles if you can identify them

Also add these high-value accounts if not already present:
- `Polymarket` category: `theo_polymarket`, `norbertmilisits`, `StarPoly_`
- Trading alpha: `0xMert_`, `taikimaeda2`
- AI/tools: `LangChainAI`, `e2aborneog_labs`

If the handles are too garbled to fix, just remove the corrupted entries and add the new ones.

---

## Task 6: Mount signal_tracker.db volume

Ensure the polymarket-bot service in `docker-compose.yml` has `./data/polymarket:/data/polymarket` in its volumes (it may already be there). The signal tracker writes to `/data/polymarket/signal_tracker.db`.

---

## Verification

```zsh
docker compose config --quiet && echo "compose valid"

echo "Services:"
grep -c "rsshub" docker-compose.yml
grep -c "x-alpha-collector" docker-compose.yml

echo "X-intel wiring:"
grep "x_intel" polymarket-bot/strategies/polymarket_copytrade.py | head -5

echo "Signal tracker:"
ls -la polymarket-bot/src/signal_tracker.py

echo "Watchlist cleanup:"
python3 -c "import json; w=json.load(open('integrations/x_alpha_collector/watchlist.json')); print(f'Total handles: {sum(len(d[\"handles\"]) for d in w[\"accounts\"].values())}')"
```

---

## Commit

```
git add -A
git commit -m "feat: complete x-intake loop — collector in compose, x-intel boosts copytrade, signal performance tracking"
git push origin main
```

After pushing, build and start the new services:
```zsh
docker compose up -d --build x-alpha-collector rsshub
docker compose up -d --build polymarket-bot
```
