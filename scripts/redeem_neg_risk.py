"""Redeem all winning positions including Neg Risk markets.

For Neg Risk markets, redemption goes through the NegRiskAdapter contract
at 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296 instead of the standard CTF.

This script handles both standard and neg risk redemptions.
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import httpx
import os
import time

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

pk = os.environ.get("POLY_PRIVATE_KEY", "")
if not pk.startswith("0x"):
    pk = "0x" + pk
account = w3.eth.account.from_key(pk)
eoa = account.address

# Contract addresses
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

# ABIs
CTF_ABI = [
    {"constant": False, "inputs": [{"name": "collateralToken", "type": "address"}, {"name": "parentCollectionId", "type": "bytes32"}, {"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "bytes32"}], "name": "payoutDenominator", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

# NegRiskAdapter ABI - redeemPositions has same signature but routes through adapter
NEG_RISK_ABI = [
    {"constant": False, "inputs": [{"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "type": "function"},
]

USDC_ABI = [{"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]

ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=CTF_ABI)
neg_adapter = w3.eth.contract(address=Web3.to_checksum_address(NEG_RISK_ADAPTER), abi=NEG_RISK_ABI)
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=USDC_ABI)

zero32 = b"\x00" * 32

print(f"Wallet: {eoa}")
usdc_before = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"USDC before: ${usdc_before:.2f}")

# Get redeemable positions
resp = httpx.get("https://data-api.polymarket.com/positions", params={"user": eoa.lower()}, timeout=30)
positions = resp.json()
redeemable = [p for p in positions if p.get("redeemable") and float(p.get("currentValue", 0)) > 0]
print(f"Redeemable: {len(redeemable)} positions")

redeemed = 0
errors = 0

for pos in redeemable:
    cid_hex = pos.get("conditionId", "")
    title = pos.get("title", "")[:50]
    value = float(pos.get("currentValue", 0))
    is_neg_risk = pos.get("negativeRisk", False)
    asset = pos.get("asset", "")

    if not cid_hex:
        continue

    cid = bytes.fromhex(cid_hex[2:]) if cid_hex.startswith("0x") else bytes.fromhex(cid_hex)

    # Check on-chain balance
    if asset:
        try:
            bal = ctf.functions.balanceOf(Web3.to_checksum_address(eoa), int(asset)).call()
            if bal == 0:
                print(f"  SKIP {title} - no tokens (already redeemed or in proxy)")
                continue
        except:
            pass

    try:
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(eoa)

        if is_neg_risk:
            # Use NegRiskAdapter for neg risk markets
            tx = neg_adapter.functions.redeemPositions(
                cid,
                [1, 2]
            ).build_transaction({
                "from": eoa,
                "nonce": nonce,
                "gas": 300000,
                "gasPrice": gas_price,
                "chainId": 137,
            })
            method = "NegRisk"
        else:
            # Standard CTF redemption
            tx = ctf.functions.redeemPositions(
                Web3.to_checksum_address(USDC_E),
                zero32,
                cid,
                [1, 2]
            ).build_transaction({
                "from": eoa,
                "nonce": nonce,
                "gas": 200000,
                "gasPrice": gas_price,
                "chainId": 137,
            })
            method = "Standard"

        signed = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        status = "OK" if receipt.status == 1 else "FAIL"
        if receipt.status == 1:
            redeemed += 1
        else:
            errors += 1
        print(f"  {status} [{method}] {title} (${value:.2f}) tx={w3.to_hex(tx_hash)[:16]}...")
        time.sleep(1)  # avoid nonce issues

    except Exception as e:
        errors += 1
        print(f"  ERR {title}: {str(e)[:100]}")

usdc_after = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"\nRedeemed: {redeemed}/{len(redeemable)} (errors: {errors})")
print(f"USDC before: ${usdc_before:.2f}")
print(f"USDC after:  ${usdc_after:.2f}")
print(f"Recovered:   ${usdc_after - usdc_before:.2f}")
