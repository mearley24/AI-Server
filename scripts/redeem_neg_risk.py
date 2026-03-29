"""Redeem Neg Risk positions — approve NegRiskAdapter then redeem via CTF.

For Neg Risk markets, the standard CTF redeemPositions still works,
but the parentCollectionId must be the questionId from the neg risk event,
NOT zero bytes. The NegRiskAdapter wraps multiple binary markets into one
multi-outcome event.

Actually, for Neg Risk: we need to call redeemPositions on the CTF contract
but with the correct parentCollectionId derived from the neg risk event.
OR we just need to ensure the CTF contract has approval to burn our tokens.
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import httpx
import os
import time
import json

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

pk = os.environ.get("POLY_PRIVATE_KEY", "")
if not pk.startswith("0x"):
    pk = "0x" + pk
account = w3.eth.account.from_key(pk)
eoa = account.address

USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
NEG_RISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

CTF_ABI = [
    {"constant": False, "inputs": [{"name": "collateralToken", "type": "address"}, {"name": "parentCollectionId", "type": "bytes32"}, {"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "bytes32"}], "name": "payoutDenominator", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "bytes32"}, {"name": "", "type": "uint256"}], "name": "payoutNumerators", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "a", "type": "address"}, {"name": "id", "type": "uint256"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "account", "type": "address"}, {"name": "operator", "type": "address"}], "name": "isApprovedForAll", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "operator", "type": "address"}, {"name": "approved", "type": "bool"}], "name": "setApprovalForAll", "outputs": [], "type": "function"},
]

USDC_ABI = [{"constant": True, "inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]

ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=CTF_ABI)
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=USDC_ABI)

zero32 = b"\x00" * 32

print(f"Wallet: {eoa}")
usdc_before = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"USDC before: ${usdc_before:.2f}")

# Check if NegRiskAdapter has approval
approved = ctf.functions.isApprovedForAll(
    Web3.to_checksum_address(eoa),
    Web3.to_checksum_address(NEG_RISK_ADAPTER)
).call()
print(f"NegRiskAdapter approved: {approved}")

if not approved:
    print("Approving NegRiskAdapter...")
    tx = ctf.functions.setApprovalForAll(
        Web3.to_checksum_address(NEG_RISK_ADAPTER), True
    ).build_transaction({
        "from": eoa,
        "nonce": w3.eth.get_transaction_count(eoa),
        "gas": 100000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 137,
    })
    signed = w3.eth.account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    print(f"Approval tx: {w3.to_hex(tx_hash)} status={'OK' if receipt.status==1 else 'FAIL'}")
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
    is_neg_risk = pos.get("negativeRisk", False)
    asset = pos.get("asset", "")
    outcome_index = pos.get("outcomeIndex", 0)

    if not cid_hex:
        continue

    cid = bytes.fromhex(cid_hex[2:]) if cid_hex.startswith("0x") else bytes.fromhex(cid_hex)

    # Check we actually hold tokens
    if asset:
        bal = ctf.functions.balanceOf(Web3.to_checksum_address(eoa), int(asset)).call()
        if bal == 0:
            print(f"  SKIP {title} - 0 tokens in EOA")
            continue
        print(f"  {title}: {bal/1e6:.2f} tokens, negRisk={is_neg_risk}, outcome={outcome_index}")

    # Check payout
    denom = ctf.functions.payoutDenominator(cid).call()
    if denom == 0:
        print(f"  SKIP {title} - not resolved on-chain")
        continue

    p0 = ctf.functions.payoutNumerators(cid, 0).call()
    p1 = ctf.functions.payoutNumerators(cid, 1).call()
    our_payout = p1 if outcome_index == 1 else p0
    print(f"    Payouts: [{p0},{p1}], our index={outcome_index}, our_payout={our_payout}")

    if our_payout == 0:
        print(f"    LOSING SIDE - redemption would return $0")
        continue

    try:
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(eoa)

        # Standard CTF redemption with zero parentCollectionId
        # This should work for both standard and neg risk IF we hold winning tokens
        tx = ctf.functions.redeemPositions(
            Web3.to_checksum_address(USDC_E),
            zero32,
            cid,
            [1, 2]
        ).build_transaction({
            "from": eoa,
            "nonce": nonce,
            "gas": 300000,
            "gasPrice": gas_price,
            "chainId": 137,
        })

        signed = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        status = "OK" if receipt.status == 1 else "FAIL"
        if receipt.status == 1:
            redeemed += 1
        print(f"    Redeem: {status} tx={w3.to_hex(tx_hash)[:20]}...")
        time.sleep(1)

    except Exception as e:
        print(f"    ERR: {str(e)[:120]}")

usdc_after = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"\nRedeemed: {redeemed}/{len(redeemable)}")
print(f"USDC: ${usdc_before:.2f} -> ${usdc_after:.2f} (recovered ${usdc_after-usdc_before:.2f})")
