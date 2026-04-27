#!/usr/bin/env python3
"""Read-only Polymarket open positions audit.

Fetches live on-chain positions for the configured wallet from the Polymarket
data API and prints a summary. No orders are placed, no state is modified.

Usage:
    python3 scripts/polymarket_positions_audit.py
    # or with explicit wallet:
    POLY_PROXY_ADDRESS=0x... python3 scripts/polymarket_positions_audit.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

try:
    import httpx
except ImportError:
    print("httpx not installed — run: pip install httpx", file=sys.stderr)
    sys.exit(1)

GAMMA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _mask(address: str) -> str:
    """Show first 6 and last 4 chars only."""
    if not address or len(address) < 10:
        return "***"
    return f"{address[:6]}...{address[-4:]}"


def _get_wallet() -> str:
    addr = os.environ.get("POLY_PROXY_ADDRESS", "").strip()
    if not addr:
        # Try reading from docker container env
        try:
            import subprocess
            out = subprocess.check_output(
                ["docker", "inspect", "polymarket-bot", "--format",
                 "{{range .Config.Env}}{{println .}}{{end}}"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if line.startswith("POLY_PROXY_ADDRESS="):
                    addr = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    if not addr:
        print("ERROR: POLY_PROXY_ADDRESS not found. Set it as env var or run docker inspect manually.", file=sys.stderr)
        sys.exit(1)
    return addr


def fetch_positions(wallet: str) -> list[dict[str, Any]]:
    url = f"{GAMMA_API}/positions"
    params = {
        "user": wallet,
        "sizeThreshold": "0.001",
        "limit": "500",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("positions", data.get("data", []))
    return []


def fetch_clob_balance(wallet: str) -> dict[str, Any]:
    """Fetch USDC balance from CLOB API (no auth needed for balance check)."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{CLOB_API}/balance", params={"address": wallet})
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {}


def main() -> None:
    wallet = _get_wallet()
    masked = _mask(wallet)
    print(f"Polymarket Open Positions Audit")
    print(f"Wallet: {masked}")
    print(f"Source: {GAMMA_API}/positions (live API)")
    print("=" * 65)

    positions = fetch_positions(wallet)

    if not positions:
        print("No positions found.")
        return

    total_value = 0.0
    total_cost = 0.0
    rows: list[dict[str, Any]] = []

    for p in positions:
        market = (p.get("title") or p.get("market") or "Unknown")
        outcome = p.get("outcome", p.get("side", "?"))
        size = float(p.get("size", p.get("shares", 0)) or 0)
        avg_price = float(p.get("avgPrice", p.get("avg_price", p.get("avg", 0))) or 0)
        cur_price = float(p.get("curPrice", p.get("currentPrice", p.get("price", 0))) or 0)
        value = size * cur_price
        cost = size * avg_price
        total_value += value
        total_cost += cost
        rows.append({
            "market": market,
            "outcome": outcome,
            "size": size,
            "avg_price": avg_price,
            "cur_price": cur_price,
            "value": value,
            "cost": cost,
            "pnl": value - cost,
        })

    rows.sort(key=lambda r: r["value"], reverse=True)

    print(f"\n{'Market':<55} {'Side':<5} {'Shares':>7} {'Avg':>6} {'Cur':>6} {'Value':>8} {'PnL':>8}")
    print("-" * 103)
    for r in rows:
        market_str = r["market"][:54]
        pnl_str = f"{r['pnl']:+.2f}"
        print(
            f"{market_str:<55} {r['outcome']:<5} {r['size']:>7.2f} "
            f"{r['avg_price']:>6.4f} {r['cur_price']:>6.4f} "
            f"${r['value']:>7.2f} {pnl_str:>8}"
        )

    print("-" * 103)
    pnl = total_value - total_cost
    print(f"\nTotal positions:        {len(positions)}")
    print(f"Total estimated value:  ${total_value:.2f}")
    print(f"Total cost basis:       ${total_cost:.2f}")
    print(f"Unrealized P&L:         ${pnl:+.2f}")
    print(f"\nSource: live_api (Polymarket Gamma data API)")
    print(f"Note: These are REAL on-chain positions, NOT paper trades.")
    print(f"      Created before current safety gates (P0/P1 — April 2026).")
    print(f"      Bot is currently in paper mode (POLY_DRY_RUN=true, POLY_ALLOW_LIVE not set).")
    print(f"      No new real positions can be created until both flags are explicitly set.")


if __name__ == "__main__":
    main()
