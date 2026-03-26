#!/usr/bin/env python3
"""One-shot script to redeem ALL winning Polymarket positions.

Sends individual redeemPositions transactions (not Multicall3, because
the CTF contract redeems for msg.sender and Multicall3 changes msg.sender).

Performs on-chain verification of:
  1. CTF token balance (ERC1155)
  2. Condition resolution status (payoutDenominator > 0)
  3. Whether user holds the winning outcome

Run on Bob:
    cd ~/AI-Server
    pip3 install --break-system-packages web3 httpx
    python3 scripts/redeem_now.py
    python3 scripts/redeem_now.py --debug   # verbose output
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

PRIVATE_KEY = os.environ.get("POLY_PRIVATE_KEY", "")
if not PRIVATE_KEY:
    print("ERROR: POLY_PRIVATE_KEY not found in .env or environment")
    sys.exit(1)

if not PRIVATE_KEY.startswith("0x"):
    PRIVATE_KEY = f"0x{PRIVATE_KEY}"

import httpx
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
ZERO = b"\x00" * 32
RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
]

REDEEM_ABI = [{
    "constant": False,
    "inputs": [
        {"name": "collateralToken", "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId", "type": "bytes32"},
        {"name": "indexSets", "type": "uint256[]"},
    ],
    "name": "redeemPositions",
    "outputs": [],
    "payable": False,
    "stateMutability": "nonpayable",
    "type": "function",
}]

ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]

# ERC1155 balanceOf for CTF tokens
ERC1155_BALANCE_ABI = [{
    "constant": True,
    "inputs": [
        {"name": "account", "type": "address"},
        {"name": "id", "type": "uint256"},
    ],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]

# Resolution status from CTF contract
PAYOUT_NUMERATORS_ABI = [{
    "constant": True,
    "inputs": [
        {"name": "", "type": "bytes32"},
        {"name": "", "type": "uint256"},
    ],
    "name": "payoutNumerators",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]

PAYOUT_DENOMINATOR_ABI = [{
    "constant": True,
    "inputs": [{"name": "", "type": "bytes32"}],
    "name": "payoutDenominator",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]


def connect_rpc():
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.eth.chain_id == 137:
                print(f"Connected to {url}")
                return w3
        except Exception:
            continue
    print("ERROR: Could not connect to any Polygon RPC")
    sys.exit(1)


def get_onchain_resolution(ctf_contract, condition_id_hex: str) -> dict:
    """Check on-chain resolution status for a condition.
    
    Returns dict with:
        resolved: bool - whether the condition has been resolved
        payout_numerators: list[int] - payout for each outcome slot
        payout_denominator: int - denominator for payout fractions
    """
    cid_bytes = bytes.fromhex(condition_id_hex[2:]) if condition_id_hex.startswith("0x") else bytes.fromhex(condition_id_hex)
    try:
        denom = ctf_contract.functions.payoutDenominator(cid_bytes).call()
        p0 = ctf_contract.functions.payoutNumerators(cid_bytes, 0).call()
        p1 = ctf_contract.functions.payoutNumerators(cid_bytes, 1).call()
        return {
            "resolved": denom > 0,
            "payout_numerators": [p0, p1],
            "payout_denominator": denom,
        }
    except Exception as e:
        return {"resolved": False, "payout_numerators": [0, 0], "payout_denominator": 0, "error": str(e)}


def get_ctf_token_balance(ctf_contract, wallet: str, token_id: str) -> int:
    """Get on-chain ERC1155 balance for a CTF token."""
    try:
        return ctf_contract.functions.balanceOf(
            Web3.to_checksum_address(wallet),
            int(token_id),
        ).call()
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description="Redeem winning Polymarket positions")
    parser.add_argument("--debug", action="store_true", help="Verbose debug output")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be redeemed without sending transactions")
    parser.add_argument("--include-losers", action="store_true", help="Also redeem losing positions (burns tokens, costs gas, no USDC returned)")
    args = parser.parse_args()

    debug = args.debug

    w3 = connect_rpc()
    account = w3.eth.account.from_key(PRIVATE_KEY)
    wallet = account.address
    print(f"Wallet: {wallet}")

    usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    usdc_before = usdc_contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    pol_balance = float(w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(wallet)), "ether"))
    print(f"USDC.e: ${usdc_before:.2f}")
    print(f"POL: {pol_balance:.4f}")
    print()

    # Setup CTF contract with all needed ABIs
    ctf_abi = REDEEM_ABI + ERC1155_BALANCE_ABI + PAYOUT_NUMERATORS_ABI + PAYOUT_DENOMINATOR_ABI
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=ctf_abi)

    # Fetch positions from Data API
    print("Fetching positions from Polymarket Data API...")
    with httpx.Client(timeout=30) as http:
        resp = http.get(
            "https://data-api.polymarket.com/positions",
            params={"user": wallet.lower()},
        )
        positions = resp.json()

    print(f"Found {len(positions)} positions from API")
    print()

    # Analyze each position with on-chain verification
    redeemable_winners = []
    redeemable_losers = []
    pending = []
    skipped = []

    for p in positions:
        title = p.get("title", "Unknown")[:60]
        asset = p.get("asset", "")
        condition_id = p.get("conditionId", "")
        outcome_index = p.get("outcomeIndex", -1)
        outcome = p.get("outcome", "?")
        api_redeemable = p.get("redeemable", False)
        api_cur_price = float(p.get("curPrice", 0))
        api_current_value = float(p.get("currentValue", 0))

        if not condition_id or not asset:
            if debug:
                print(f"  SKIP (no conditionId/asset): {title}")
            skipped.append({"title": title, "reason": "missing conditionId or asset"})
            continue

        # On-chain checks
        token_balance_raw = get_ctf_token_balance(ctf, wallet, asset)
        token_balance = token_balance_raw / 1e6
        resolution = get_onchain_resolution(ctf, condition_id)

        if debug:
            print(f"Position: {title}")
            print(f"  Outcome: {outcome} (index={outcome_index})")
            print(f"  API: redeemable={api_redeemable}, curPrice={api_cur_price}, currentValue={api_current_value}")
            print(f"  On-chain: balance={token_balance:.6f} tokens, resolved={resolution['resolved']}")
            print(f"  Payouts: numerators={resolution['payout_numerators']}, denom={resolution['payout_denominator']}")

        if token_balance_raw == 0:
            if debug:
                print(f"  -> SKIP: No on-chain token balance")
            skipped.append({"title": title, "reason": "zero on-chain balance"})
            if debug:
                print()
            continue

        if not resolution["resolved"]:
            if debug:
                print(f"  -> PENDING: Market not yet resolved on-chain (balance={token_balance:.4f})")
            pending.append({
                "title": title,
                "condition_id": condition_id,
                "balance": token_balance,
                "api_cur_price": api_cur_price,
                "api_current_value": api_current_value,
            })
            if debug:
                print()
            continue

        # Market is resolved and user has balance - check if winner
        payout_nums = resolution["payout_numerators"]
        payout_denom = resolution["payout_denominator"]
        user_payout = payout_nums[outcome_index] if 0 <= outcome_index < len(payout_nums) else 0
        is_winner = user_payout > 0
        expected_usdc = (token_balance_raw * user_payout) / (payout_denom * 1e6) if payout_denom > 0 else 0

        if debug:
            print(f"  -> {'WINNER' if is_winner else 'LOSER'}: payout for outcome {outcome_index} = {user_payout}/{payout_denom}, expected=${expected_usdc:.4f}")
            print()

        entry = {
            "title": title,
            "condition_id": condition_id,
            "balance": token_balance,
            "expected_usdc": expected_usdc,
            "outcome": outcome,
            "outcome_index": outcome_index,
        }

        if is_winner:
            redeemable_winners.append(entry)
        else:
            redeemable_losers.append(entry)

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_expected = sum(r["expected_usdc"] for r in redeemable_winners)
    print(f"  Winning positions to redeem: {len(redeemable_winners)} (${total_expected:.2f} expected)")
    print(f"  Losing positions (resolved): {len(redeemable_losers)} ($0 - token burn only)")
    print(f"  Pending (not resolved):      {len(pending)}")
    print(f"  Skipped (no balance):         {len(skipped)}")
    print()

    if pending:
        print("PENDING POSITIONS (not yet resolved on-chain):")
        for p in pending:
            print(f"  {p['title']}")
            print(f"    Balance: {p['balance']:.4f} tokens, API price: {p['api_cur_price']}, Est value: ${p['api_current_value']:.2f}")
        print()

    # Build redemption list
    to_redeem = list(redeemable_winners)
    if args.include_losers:
        to_redeem.extend(redeemable_losers)
        print(f"Including {len(redeemable_losers)} losing positions for cleanup (--include-losers)")
        print()

    if not to_redeem:
        if redeemable_losers and not args.include_losers:
            print("No winning positions to redeem.")
            print(f"There are {len(redeemable_losers)} losing positions that can be cleaned up.")
            print("Run with --include-losers to burn losing tokens (costs gas, returns $0).")
        else:
            print("No redeemable positions found!")
            if pending:
                print(f"  {len(pending)} position(s) are pending resolution. Try again after the market resolves.")
        return

    if args.dry_run:
        print("DRY RUN - would redeem:")
        for r in to_redeem:
            print(f"  {r['title']} (${r['expected_usdc']:.4f})")
        return

    # Deduplicate by condition_id
    seen = set()
    unique = []
    for r in to_redeem:
        cid = r["condition_id"]
        if cid not in seen:
            seen.add(cid)
            unique.append(r)

    print(f"Redeeming {len(unique)} conditions...")
    print()

    usdc_addr = Web3.to_checksum_address(USDC_E)
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(wallet))
    redeemed = 0

    for i, r in enumerate(unique):
        cid = r["condition_id"]
        title = r["title"][:50]
        expected = r["expected_usdc"]
        cid_bytes = bytes.fromhex(cid[2:]) if cid.startswith("0x") else bytes.fromhex(cid)

        print(f"[{i+1}/{len(unique)}] ${expected:.4f}  {title}")

        try:
            gas_est = ctf.functions.redeemPositions(
                usdc_addr, ZERO, cid_bytes, [1, 2]
            ).estimate_gas({"from": wallet})

            gas_price = w3.eth.gas_price
            tx = ctf.functions.redeemPositions(
                usdc_addr, ZERO, cid_bytes, [1, 2]
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gas": int(gas_est * 1.3),
                "gasPrice": gas_price,
                "chainId": 137,
            })

            signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hex = w3.to_hex(tx_hash)
            print(f"  TX: {tx_hex}")

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status == 1:
                print(f"  Confirmed (gas: {receipt.gasUsed:,})")
                redeemed += 1
                nonce += 1
            else:
                print(f"  Reverted")
                nonce += 1

            time.sleep(1)  # Brief pause between txns

        except Exception as e:
            print(f"  Error: {str(e)[:120]}")

    # Final balance
    usdc_after = usdc_contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    recovered = usdc_after - usdc_before
    print()
    print(f"Redeemed: {redeemed}/{len(unique)}")
    print(f"USDC.e before: ${usdc_before:.2f}")
    print(f"USDC.e after:  ${usdc_after:.2f}")
    print(f"Recovered:     ${recovered:.2f}")


if __name__ == "__main__":
    main()
