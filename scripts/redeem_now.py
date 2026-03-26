#!/usr/bin/env python3
"""One-shot script to redeem ALL winning Polymarket positions via Multicall3.

Run on Bob:
    cd ~/AI-Server
    pip3 install web3 httpx
    python3 scripts/redeem_now.py

Reads POLY_PRIVATE_KEY from .env file in the repo root.
"""

import json
import os
import sys
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

# --- Config ---
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
MC3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
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

MC3_ABI = [{
    "inputs": [{"components": [
        {"name": "target", "type": "address"},
        {"name": "allowFailure", "type": "bool"},
        {"name": "callData", "type": "bytes"}
    ], "name": "calls", "type": "tuple[]"}],
    "name": "aggregate3",
    "outputs": [{"components": [
        {"name": "success", "type": "bool"},
        {"name": "returnData", "type": "bytes"}
    ], "name": "returnData", "type": "tuple[]"}],
    "stateMutability": "payable",
    "type": "function"
}]

ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
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


def main():
    w3 = connect_rpc()
    account = w3.eth.account.from_key(PRIVATE_KEY)
    wallet = account.address
    print(f"Wallet: {wallet}")

    # Check balances
    usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    usdc_before = usdc_contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    pol_balance = float(w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(wallet)), "ether"))
    print(f"USDC.e: ${usdc_before:.2f}")
    print(f"POL: {pol_balance:.4f}")
    print()

    # Fetch redeemable positions
    print("Fetching positions from Polymarket...")
    with httpx.Client(timeout=30) as http:
        resp = http.get(
            "https://data-api.polymarket.com/positions",
            params={"user": wallet.lower()},
        )
        positions = resp.json()

    redeemable = [
        p for p in positions
        if p.get("redeemable")
        and float(p.get("currentValue", 0)) > 0
        and float(p.get("curPrice", 0)) == 1.0
    ]

    if not redeemable:
        print("No redeemable positions found!")
        return

    total_value = sum(float(p.get("currentValue", 0)) for p in redeemable)
    print(f"Found {len(redeemable)} redeemable positions worth ${total_value:.2f}")
    print()

    # Deduplicate by condition_id
    condition_ids = list(set(p["conditionId"] for p in redeemable))
    print(f"Unique conditions to redeem: {len(condition_ids)}")

    # Build multicall
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=REDEEM_ABI)
    mc3 = w3.eth.contract(address=Web3.to_checksum_address(MC3), abi=MC3_ABI)
    usdc_addr = Web3.to_checksum_address(USDC_E)
    ctf_addr = Web3.to_checksum_address(CTF)

    calls = []
    for cid in condition_ids:
        cid_bytes = bytes.fromhex(cid[2:]) if cid.startswith("0x") else bytes.fromhex(cid)
        call_data = ctf.functions.redeemPositions(
            usdc_addr, ZERO, cid_bytes, [1, 2]
        )._encode_transaction_data()
        calls.append((ctf_addr, True, bytes.fromhex(call_data[2:])))

    # Estimate gas
    print("Estimating gas...")
    gas_est = mc3.functions.aggregate3(calls).estimate_gas({"from": wallet})
    gas_with_buffer = int(gas_est * 1.3)
    gas_price = w3.eth.gas_price
    cost_pol = float(w3.from_wei(gas_with_buffer * gas_price, "ether"))
    print(f"Gas estimate: {gas_est:,} (with buffer: {gas_with_buffer:,})")
    print(f"Gas price: {w3.from_wei(gas_price, 'gwei'):.1f} gwei")
    print(f"Cost: {cost_pol:.6f} POL")

    if cost_pol > pol_balance:
        print(f"ERROR: Not enough POL! Need {cost_pol:.6f}, have {pol_balance:.4f}")
        return

    # Send transaction
    print()
    print(f"Redeeming {len(condition_ids)} conditions in one batch...")
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(wallet))
    tx = mc3.functions.aggregate3(calls).build_transaction({
        "from": wallet,
        "nonce": nonce,
        "gas": gas_with_buffer,
        "gasPrice": gas_price,
        "chainId": 137,
    })

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hex = w3.to_hex(tx_hash)
    print(f"TX sent: {tx_hex}")
    print(f"View: https://polygonscan.com/tx/{tx_hex}")
    print()

    print("Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 1:
        print(f"✓ SUCCESS! Gas used: {receipt.gasUsed:,}")
    else:
        print(f"✗ REVERTED!")
        return

    # Check new balance
    usdc_after = usdc_contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call() / 1e6
    recovered = usdc_after - usdc_before
    print()
    print(f"USDC.e before: ${usdc_before:.2f}")
    print(f"USDC.e after:  ${usdc_after:.2f}")
    print(f"Recovered:     ${recovered:.2f}")
    print()
    print("Done!")


if __name__ == "__main__":
    main()
