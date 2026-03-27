"""Scan Polymarket positions and sell any with big gains.

Usage:
    python3 scripts/sell_winners.py              (show all positions with P/L)
    python3 scripts/sell_winners.py --sell 100    (sell all positions up 100%+)
    python3 scripts/sell_winners.py --sell 50     (sell all positions up 50%+)
"""

import os
import sys
import json
import httpx
import time

WALLET = "0xa791E3090312981A1E18ed93238e480a03E7C0d2"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


def get_positions():
    resp = httpx.get(f"{DATA_API}/positions", params={"user": WALLET.lower()}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_market_price(token_id):
    try:
        resp = httpx.get(f"{CLOB_API}/midpoint", params={"token_id": token_id}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("mid", 0))
    except Exception:
        pass
    return 0


def sell_position(token_id, size_shares, price):
    pk = os.environ.get("POLY_PRIVATE_KEY", "")
    if not pk:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("POLY_PRIVATE_KEY="):
                    pk = line.strip().split("=", 1)[1].strip('"').strip("'")
    if not pk:
        print("  ERROR: POLY_PRIVATE_KEY not set")
        return False
    if not pk.startswith("0x"):
        pk = f"0x{pk}"

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs, PartialCreateOrderOptions

        api_key = os.environ.get("POLY_BUILDER_API_KEY", "")
        api_secret = os.environ.get("POLY_BUILDER_API_SECRET", "")
        api_passphrase = os.environ.get("POLY_BUILDER_API_PASSPHRASE", "")

        if not api_key:
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            if os.path.exists(env_path):
                for line in open(env_path):
                    line = line.strip()
                    if line.startswith("POLY_BUILDER_API_KEY="):
                        api_key = line.split("=", 1)[1].strip('"').strip("'")
                    elif line.startswith("POLY_BUILDER_API_SECRET="):
                        api_secret = line.split("=", 1)[1].strip('"').strip("'")
                    elif line.startswith("POLY_BUILDER_API_PASSPHRASE="):
                        api_passphrase = line.split("=", 1)[1].strip('"').strip("'")

        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
        client = ClobClient(CLOB_API, key=pk, chain_id=137, creds=creds, signature_type=0)

        sell_price = round(round(price / 0.01) * 0.01, 2)
        if sell_price <= 0:
            sell_price = 0.01

        order_args = OrderArgs(
            token_id=token_id,
            price=sell_price,
            size=round(size_shares, 2),
            side="SELL",
        )
        options = PartialCreateOrderOptions(tick_size="0.01", neg_risk=False)
        resp = client.create_and_post_order(order_args, options)
        order_id = resp.get("orderID", "") if isinstance(resp, dict) else str(resp)
        status = resp.get("status", "") if isinstance(resp, dict) else ""
        print(f"  SOLD: order={order_id[:20]}... status={status}")
        return True
    except Exception as exc:
        print(f"  SELL ERROR: {str(exc)[:120]}")
        return False


def main():
    sell_threshold = None
    if "--sell" in sys.argv:
        idx = sys.argv.index("--sell")
        if idx + 1 < len(sys.argv):
            sell_threshold = float(sys.argv[idx + 1])

    print(f"Wallet: {WALLET}")
    print(f"Fetching positions...\n")

    positions = get_positions()
    if not positions:
        print("No positions found.")
        return

    winners = []
    losers = []
    pending = []

    for p in positions:
        size = float(p.get("size", 0))
        if size <= 0:
            continue

        token_id = p.get("asset", p.get("token_id", ""))
        title = p.get("title", p.get("market", ""))
        outcome = p.get("outcome", "")
        avg_price = float(p.get("avgPrice", p.get("avg_price", 0)))
        cur_price = float(p.get("curPrice", p.get("cur_price", 0)))
        current_value = float(p.get("currentValue", p.get("current_value", 0)))
        initial_value = float(p.get("initialValue", p.get("initial_value", 0)))
        redeemable = p.get("redeemable", False)

        if avg_price > 0 and cur_price > 0:
            pnl_pct = ((cur_price - avg_price) / avg_price) * 100
        elif initial_value > 0 and current_value > 0:
            pnl_pct = ((current_value - initial_value) / initial_value) * 100
        else:
            pnl_pct = 0

        pnl_usd = current_value - initial_value if initial_value > 0 else 0

        entry = {
            "title": title[:55],
            "outcome": outcome,
            "token_id": token_id,
            "size": size,
            "avg_price": avg_price,
            "cur_price": cur_price,
            "current_value": current_value,
            "initial_value": initial_value,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "redeemable": redeemable,
        }

        if redeemable or cur_price == 0:
            if current_value == 0:
                losers.append(entry)
            else:
                winners.append(entry)
        elif pnl_pct > 0:
            winners.append(entry)
        else:
            pending.append(entry)

    all_positions = sorted(winners + pending + losers, key=lambda x: x["pnl_pct"], reverse=True)

    print(f"{'P/L':>8} {'Value':>8} {'Cost':>8} {'Price':>6} {'Entry':>6}  Market")
    print("-" * 90)

    total_value = 0
    total_cost = 0
    sold_count = 0

    for p in all_positions:
        pnl_str = f"{p['pnl_pct']:+.0f}%"
        emoji = "+" if p["pnl_pct"] > 0 else "-" if p["pnl_pct"] < -10 else " "
        print(f"{emoji}{pnl_str:>7} ${p['current_value']:>6.2f} ${p['initial_value']:>6.2f} {p['cur_price']:>6.3f} {p['avg_price']:>6.3f}  {p['title']}")

        total_value += p["current_value"]
        total_cost += p["initial_value"]

        if sell_threshold is not None and p["pnl_pct"] >= sell_threshold and p["cur_price"] > 0 and not p["redeemable"]:
            print(f"  Selling {p['size']:.2f} shares at {p['cur_price']:.3f}...")
            sell_position(p["token_id"], p["size"], p["cur_price"])
            sold_count += 1
            time.sleep(1)

    print("-" * 90)
    print(f"Total value: ${total_value:.2f} | Total cost: ${total_cost:.2f} | P/L: ${total_value - total_cost:+.2f}")
    print(f"Positions: {len(all_positions)} ({len(winners)} winning, {len(pending)} pending, {len(losers)} losing)")

    if sell_threshold is not None:
        print(f"\nSold {sold_count} positions above {sell_threshold}% gain.")
    else:
        print(f"\nTo sell winners, run: python3 scripts/sell_winners.py --sell 100")


if __name__ == "__main__":
    main()
