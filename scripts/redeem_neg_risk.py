"""Redeem ALL winning positions via NegRiskAdapter.

For neg risk markets: call NegRiskAdapter.redeemPositions(conditionId, amounts)
where amounts = [0, balance] for No tokens or [balance, 0] for Yes tokens.
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

NEG_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

adapter_abi = [{"constant": False, "inputs": [{"name": "_conditionId", "type": "bytes32"}, {"name": "_amounts", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "type": "function"}]
ctf_abi = [
    {"constant": True, "inputs": [{"name": "a", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "bytes32"}], "name": "payoutDenominator", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "account", "type": "address"}, {"name": "operator", "type": "address"}], "name": "isApprovedForAll", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}], "name": "setApprovalForAll", "outputs": [], "type": "function"},
]
usdc_abi = [{"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]

adapter = w3.eth.contract(address=Web3.to_checksum_address(NEG_ADAPTER), abi=adapter_abi)
ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=ctf_abi)
usdc_c = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=usdc_abi)

print(f"Wallet: {eoa}")
usdc_before = usdc_c.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"USDC before: ${usdc_before:.2f}")

# Ensure approval
approved = ctf.functions.isApprovedForAll(Web3.to_checksum_address(eoa), Web3.to_checksum_address(NEG_ADAPTER)).call()
if not approved:
    print("Approving NegRiskAdapter...")
    tx = ctf.functions.setApprovalForAll(Web3.to_checksum_address(NEG_ADAPTER), True).build_transaction({"from": eoa, "nonce": w3.eth.get_transaction_count(eoa), "gas": 100000, "gasPrice": w3.eth.gas_price, "chainId": 137})
    signed = w3.eth.account.sign_transaction(tx, pk)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), timeout=60)
    time.sleep(2)

# Get redeemable positions
resp = httpx.get("https://data-api.polymarket.com/positions", params={"user": eoa.lower()}, timeout=30)
positions = resp.json()
redeemable = [p for p in positions if p.get("redeemable") and float(p.get("currentValue", 0)) > 0]
print(f"Redeemable: {len(redeemable)}")

redeemed = 0

for pos in redeemable:
    cid_hex = pos.get("conditionId", "")
    title = pos.get("title", "")[:50]
    value = float(pos.get("currentValue", 0))
    outcome_index = pos.get("outcomeIndex", 0)
    asset = pos.get("asset", "")
    is_neg_risk = pos.get("negativeRisk", False)

    if not cid_hex or not asset:
        continue

    cid = bytes.fromhex(cid_hex[2:]) if cid_hex.startswith("0x") else bytes.fromhex(cid_hex)

    # Check token balance
    bal = ctf.functions.balanceOf(Web3.to_checksum_address(eoa), int(asset)).call()
    if bal == 0:
        print(f"  SKIP {title} - no tokens")
        continue

    # Check resolved
    denom = ctf.functions.payoutDenominator(cid).call()
    if denom == 0:
        print(f"  SKIP {title} - not resolved")
        continue

    try:
        # Build amounts array: [Yes_amount, No_amount]
        if outcome_index == 0:
            amounts = [bal, 0]
        else:
            amounts = [0, bal]

        tx = adapter.functions.redeemPositions(cid, amounts).build_transaction({
            "from": eoa,
            "nonce": w3.eth.get_transaction_count(eoa),
            "gas": 500000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 137,
        })
        signed = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)

        if receipt.status == 1:
            redeemed += 1
            print(f"  OK {title} (${value:.2f})")
        else:
            print(f"  FAIL {title}")
        time.sleep(1)

    except Exception as e:
        print(f"  ERR {title}: {str(e)[:100]}")

usdc_after = usdc_c.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"\nRedeemed: {redeemed}/{len(redeemable)}")
print(f"USDC: ${usdc_before:.2f} -> ${usdc_after:.2f}")
print(f"Recovered: ${usdc_after - usdc_before:.2f}")
