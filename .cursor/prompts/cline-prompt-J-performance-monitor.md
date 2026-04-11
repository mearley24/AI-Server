# Cline Prompt J: Hourly Performance Monitor + P&L Alerting

Work in `/Users/bob/AI-Server/`. Read `.clinerules` first. Commit and push after completion.

## Context

The bot runs 10+ strategies but there is no consolidated performance dashboard that shows real-time P&L by strategy, win rates by price bracket, and alerts when things go wrong. The heartbeat runner exists (`heartbeat/runner.py`) and sends hourly iMessage updates, but it does not include the bracket-level analytics we need.

## Step 1: Create a performance snapshot script

Create `polymarket-bot/scripts/performance_snapshot.py`:

```python
"""Generate a performance snapshot from live position and trade data.

Outputs a structured summary suitable for iMessage alerts or logging.
Runs inside the polymarket-bot container.
"""

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import httpx


def main():
    data_dir = os.environ.get("DATA_DIR", "/data")
    wallet = os.environ.get("POLY_PROXY_ADDRESS", os.environ.get("POLY_SAFE_ADDRESS", ""))

    if not wallet:
        print("No wallet configured")
        return

    # 1. Fetch current positions from API
    r = httpx.get("https://data-api.polymarket.com/positions", params={"user": wallet})
    positions = r.json() if r.status_code == 200 else []

    # 2. Load trade history
    trades_csv = Path(data_dir) / "trades.csv"
    trades = []
    if trades_csv.exists():
        import csv
        with open(trades_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)

    # 3. Categorize positions
    active = []
    redeemable = []
    resolved_losses = []
    dust = []

    for p in positions:
        cur_price = float(p.get("curPrice", 0) or 0)
        current_value = float(p.get("currentValue", 0) or 0)
        initial_value = float(p.get("initialValue", 0) or 0)

        if p.get("redeemable") and current_value > 0:
            redeemable.append(p)
        elif cur_price in (0.0, 1.0):
            if current_value < 0.50:
                dust.append(p)
            else:
                resolved_losses.append(p)
        elif current_value > 0:
            active.append(p)
        else:
            dust.append(p)

    # 4. Bracket analysis for active positions
    brackets = defaultdict(lambda: {"count": 0, "cost": 0.0, "value": 0.0})
    for p in active:
        entry = float(p.get("avgPrice", 0) or 0)
        value = float(p.get("currentValue", 0) or 0)
        cost = float(p.get("initialValue", 0) or 0)
        if entry <= 0.10:
            b = "0-10c"
        elif entry <= 0.25:
            b = "10-25c"
        elif entry <= 0.50:
            b = "25-50c"
        elif entry <= 0.75:
            b = "50-75c"
        else:
            b = "75c+"
        brackets[b]["count"] += 1
        brackets[b]["cost"] += cost
        brackets[b]["value"] += value

    # 5. USDC balance
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
        usdc_e = w3.eth.contract(
            address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
            abi=[{"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}],
        )
        liquid = usdc_e.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    except Exception:
        liquid = 0

    # 6. Print summary
    active_value = sum(float(p.get("currentValue", 0) or 0) for p in active)
    active_cost = sum(float(p.get("initialValue", 0) or 0) for p in active)
    redeemable_value = sum(float(p.get("currentValue", 0) or 0) for p in redeemable)
    total_value = liquid + active_value + redeemable_value

    print(f"POLYMARKET PERFORMANCE SNAPSHOT")
    print(f"{'=' * 40}")
    print(f"Liquid USDC.e:     ${liquid:.2f}")
    print(f"Active positions:  {len(active)} (${active_value:.2f} value, ${active_cost:.2f} cost)")
    print(f"Unredeemed wins:   {len(redeemable)} (${redeemable_value:.2f})")
    print(f"Resolved losses:   {len(resolved_losses)}")
    print(f"Dust:              {len(dust)}")
    print(f"TOTAL PORTFOLIO:   ${total_value:.2f}")
    print()
    print(f"BRACKET BREAKDOWN (active only):")
    for b in ["0-10c", "10-25c", "25-50c", "50-75c", "75c+"]:
        d = brackets.get(b, {"count": 0, "cost": 0, "value": 0})
        if d["count"] > 0:
            pnl = d["value"] - d["cost"]
            roi = (pnl / d["cost"] * 100) if d["cost"] > 0 else 0
            print(f"  {b:8s}: {d['count']:3d} positions, ${d['cost']:.2f} cost, ${d['value']:.2f} value, {roi:+.1f}% ROI")
    print()

    # 7. Recent trades (last 2 hours)
    cutoff = time.time() - 7200
    recent = [t for t in trades if float(t.get("timestamp", 0) or 0) > cutoff]
    buys = [t for t in recent if t.get("side") == "BUY"]
    sells = [t for t in recent if t.get("side") == "SELL"]
    print(f"LAST 2 HOURS: {len(buys)} buys, {len(sells)} sells")

    # 8. Alerts
    alerts = []
    if len(redeemable) > 10:
        alerts.append(f"WARNING: {len(redeemable)} unredeemed wins piling up (${redeemable_value:.2f})")
    if liquid < 50:
        alerts.append(f"WARNING: Low liquid balance (${liquid:.2f})")
    if len(recent) == 0:
        alerts.append("WARNING: No trades in last 2 hours -- bot may be stuck")
    if active_cost > 0 and (active_value - active_cost) / active_cost < -0.30:
        alerts.append(f"WARNING: Active positions down {((active_value - active_cost) / active_cost * 100):.1f}%")

    if alerts:
        print("ALERTS:")
        for a in alerts:
            print(f"  {a}")


if __name__ == "__main__":
    main()
```

## Step 2: Wire into the heartbeat runner

In `polymarket-bot/heartbeat/runner.py`, find the `run_full_review` method. Add a call to the performance snapshot data (not the script -- import the logic) so the hourly iMessage update includes bracket breakdown and alerts.

If the heartbeat runner is too complex to modify, create a simpler integration:

Add to the hourly heartbeat job:

```python
# At the end of run_full_review, append performance data
try:
    import subprocess
    result = subprocess.run(
        ["python", "scripts/performance_snapshot.py"],
        capture_output=True, text=True, timeout=30,
    )
    if result.stdout:
        # Append to the heartbeat message
        self._append_to_heartbeat(result.stdout)
except Exception:
    pass
```

## Step 3: Add a cron-style log entry

In the copytrade main loop (the `run()` method), add a periodic performance log every 30 minutes:

Find the main loop and add:

```python
        self._last_perf_log: float = 0.0
```

In the loop body:

```python
            # Performance snapshot every 30 minutes
            if time.time() - self._last_perf_log > 1800:
                self._last_perf_log = time.time()
                try:
                    active_count = len(self._positions)
                    total_exposure = sum(p.size_usd for p in self._positions.values())
                    daily_pnl = self._daily_wins - self._daily_realized_losses
                    logger.info(
                        "copytrade_performance_30min",
                        active_positions=active_count,
                        total_exposure=round(total_exposure, 2),
                        daily_pnl=round(daily_pnl, 2),
                        daily_trades=self._daily_trades,
                        daily_spend=round(self._daily_spend, 2),
                        bankroll=round(self._bankroll, 2),
                        halted_categories=list(self._halted_categories),
                    )
                except Exception:
                    pass
```

## Step 4: Verify and push

```bash
python3 -m py_compile polymarket-bot/scripts/performance_snapshot.py
python3 -m py_compile polymarket-bot/strategies/polymarket_copytrade.py
cd /Users/bob/AI-Server && git add -A && git commit -m "feat: performance monitoring -- snapshot script, 30min perf logs, bracket breakdown" && git push origin main
docker compose up -d --build polymarket-bot
```

Test the snapshot:
```bash
docker exec polymarket-bot python scripts/performance_snapshot.py
```
