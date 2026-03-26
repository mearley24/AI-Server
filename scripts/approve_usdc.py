"""Approve USDC.e spending for Polymarket Exchange contract.

Sets unlimited allowance so trades don't fail with 'not enough allowance'.
Run once on Bob: python3 scripts/approve_usdc.py
"""

import os
import sys
from web3 import Web3

RPC_URL = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
EXCHANGE = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
MAX_UINT256 = 2**256 - 1

ERC20_ABI = [
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


def main():
    pk = os.environ.get("POLY_PRIVATE_KEY", "")
    if not pk:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("POLY_PRIVATE_KEY="):
                    pk = line.strip().split("=", 1)[1].strip('"').strip("'")
    if not pk:
        print("ERROR: POLY_PRIVATE_KEY not set")
        sys.exit(1)
    if not pk.startswith("0x"):
        pk = f"0x{pk}"

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = w3.eth.account.from_key(pk)
    wallet = account.address
    print(f"Wallet: {wallet}")

    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    balance = usdc.functions.balanceOf(wallet).call()
    print(f"USDC.e balance: ${balance / 1e6:.2f}")

    for name, spender in [("Exchange", EXCHANGE), ("CTF Exchange", CTF_EXCHANGE)]:
        spender_cs = Web3.to_checksum_address(spender)
        current = usdc.functions.allowance(wallet, spender_cs).call()
        print(f"\n{name} ({spender}):")
        print(f"  Current allowance: ${current / 1e6:.2f}")

        if current >= 1_000_000 * 10**6:
            print(f"  Already has sufficient allowance, skipping.")
            continue

        print(f"  Setting unlimited allowance...")
        nonce = w3.eth.get_transaction_count(wallet)
        tx = usdc.functions.approve(spender_cs, MAX_UINT256).build_transaction({
            "from": wallet,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 137,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  TX: https://polygonscan.com/tx/{tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        print(f"  Status: {'SUCCESS' if receipt.status == 1 else 'FAILED'}")
        print(f"  Gas used: {receipt.gasUsed}")
        nonce += 1

    print("\nDone. Allowance set for both Exchange contracts.")


if __name__ == "__main__":
    main()
