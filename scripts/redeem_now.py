from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import os

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
ctf_addr = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
usdc_addr = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

abi = [
    {"constant":True,"inputs":[{"name":"","type":"bytes32"},{"name":"","type":"uint256"}],"name":"payoutNumerators","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":True,"inputs":[{"name":"","type":"bytes32"}],"name":"payoutDenominator","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":True,"inputs":[{"name":"a","type":"address"},{"name":"id","type":"uint256"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":False,"inputs":[{"name":"collateralToken","type":"address"},{"name":"parentCollectionId","type":"bytes32"},{"name":"conditionId","type":"bytes32"},{"name":"indexSets","type":"uint256[]"}],"name":"redeemPositions","outputs":[],"type":"function"}
]
c = w3.eth.contract(address=Web3.to_checksum_address(ctf_addr), abi=abi)
usdc_abi = [{"constant":True,"inputs":[{"name":"a","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}]
usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc_addr), abi=usdc_abi)

pk = os.environ.get("POLY_PRIVATE_KEY", "")
if not pk.startswith("0x"):
    pk = "0x" + pk
account = w3.eth.account.from_key(pk)
eoa = account.address
zero32 = b"\x00" * 32

print(f"Wallet: {eoa}")
usdc_before = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"USDC before: ${usdc_before:.2f}")

# Get all redeemable positions from Polymarket API
import httpx
resp = httpx.get("https://data-api.polymarket.com/positions", params={"user": eoa.lower()}, timeout=30)
positions = resp.json()
redeemable = [p for p in positions if p.get("redeemable") and float(p.get("currentValue", 0)) > 0]
print(f"Redeemable positions: {len(redeemable)}")

redeemed = 0
for pos in redeemable:
    cid_hex = pos.get("conditionId", "")
    title = pos.get("title", "")[:50]
    value = float(pos.get("currentValue", 0))
    
    if not cid_hex:
        continue
    
    cid = bytes.fromhex(cid_hex[2:]) if cid_hex.startswith("0x") else bytes.fromhex(cid_hex)
    
    # Check if resolved on-chain
    denom = c.functions.payoutDenominator(cid).call()
    if denom == 0:
        print(f"  SKIP {title} - not resolved on-chain yet")
        continue
    
    try:
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(eoa)
        
        tx = c.functions.redeemPositions(
            Web3.to_checksum_address(usdc_addr),
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
        signed = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        status = "OK" if receipt.status == 1 else "FAIL"
        redeemed += 1
        print(f"  {status} {title} (${value:.2f}) tx={w3.to_hex(tx_hash)[:16]}...")
    except Exception as e:
        print(f"  ERR {title}: {str(e)[:80]}")

usdc_after = usdc.functions.balanceOf(Web3.to_checksum_address(eoa)).call() / 1e6
print(f"\nRedeemed: {redeemed}/{len(redeemable)}")
print(f"USDC before: ${usdc_before:.2f}")
print(f"USDC after:  ${usdc_after:.2f}")
print(f"Recovered:   ${usdc_after - usdc_before:.2f}")
