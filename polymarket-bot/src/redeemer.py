"""Polymarket Position Redeemer.

Automatically redeems resolved winning positions from the ConditionalTokens
contract on Polygon, converting winning outcome tokens back into USDC.e.

Sends individual redeemPositions transactions directly from the EOA wallet.
(Multicall3 doesn't work because CTF redeems for msg.sender, and Multicall3
changes msg.sender to its own address.)

Works with EOA wallets (signature_type=0).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

logger = structlog.get_logger(__name__)

# Contract addresses on Polygon
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Minimal ABI for redeemPositions
REDEEM_ABI = [
    {
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
    }
]

# ERC20 balanceOf ABI
ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Zero bytes32 — always used as parentCollectionId for Polymarket top-level positions
ZERO_BYTES32 = b"\x00" * 32

# Polygon RPC endpoints (fallback list)
POLYGON_RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
]

# Gas settings
MAX_GAS_PRICE_GWEI = 300  # Don't transact above this


class PolymarketRedeemer:
    """Redeems resolved winning Polymarket positions for USDC.e.

    Sends individual redeemPositions calls directly from the wallet.
    Monitors gas price and MATIC balance to ensure transactions succeed.
    """

    def __init__(
        self,
        private_key: str,
        check_interval: float = 300.0,  # 5 minutes
        rpc_url: str = "",
    ) -> None:
        self._private_key = private_key if private_key.startswith("0x") else f"0x{private_key}"
        self._check_interval = check_interval
        self._http: Optional[httpx.AsyncClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Initialize web3 with RPC fallback
        self._w3 = self._connect_rpc(rpc_url)

        self._account = self._w3.eth.account.from_key(self._private_key)
        self._wallet_address = self._account.address

        # Contracts
        self._ctf = self._w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=REDEEM_ABI,
        )
        self._usdc = self._w3.eth.contract(
            address=Web3.to_checksum_address(USDC_E_ADDRESS),
            abi=ERC20_BALANCE_ABI,
        )

        # Track already-redeemed condition IDs to avoid redundant txns
        self._redeemed_conditions: set[str] = set()

    @staticmethod
    def _connect_rpc(preferred_url: str = "") -> Web3:
        """Connect to a Polygon RPC with fallback."""
        urls_to_try = [preferred_url] if preferred_url else []
        urls_to_try.extend(POLYGON_RPCS)

        for url in urls_to_try:
            if not url:
                continue
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                chain_id = w3.eth.chain_id
                if chain_id == 137:
                    logger.info("redeemer_rpc_connected", rpc=url)
                    return w3
            except Exception:
                continue

        # Last resort
        w3 = Web3(Web3.HTTPProvider(POLYGON_RPCS[0], request_kwargs={"timeout": 30}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("redeemer_started", wallet=self._wallet_address)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("redeemer_stopped")

    async def _run_loop(self) -> None:
        """Periodically check for and redeem winning positions."""
        while self._running:
            try:
                await self.redeem_all_winning()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("redeemer_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

    async def redeem_all_winning(self) -> dict[str, Any]:
        """Find and redeem all resolved winning positions one by one.

        Returns summary of redemption attempt.
        """
        assert self._http is not None

        # 1. Check gas price
        gas_price = self._w3.eth.gas_price
        gas_gwei = float(self._w3.from_wei(gas_price, "gwei"))

        if gas_gwei > MAX_GAS_PRICE_GWEI:
            logger.info("redeemer_gas_too_high", gas_gwei=round(gas_gwei, 1))
            return {"status": "gas_too_high", "gas_gwei": round(gas_gwei, 1)}

        # 2. Get current USDC.e balance before
        usdc_before = self._get_usdc_balance()

        # 3. Fetch positions from Polymarket Data API
        try:
            resp = await self._http.get(
                "https://data-api.polymarket.com/positions",
                params={"user": self._wallet_address.lower()},
            )
            resp.raise_for_status()
            positions = resp.json()
        except Exception as exc:
            logger.error("redeemer_fetch_positions_error", error=str(exc))
            return {"error": str(exc)}

        # 4. Filter to redeemable winning positions
        redeemable = []
        for pos in positions:
            condition_id = pos.get("conditionId", "")
            if not condition_id:
                continue
            if condition_id in self._redeemed_conditions:
                continue
            if not pos.get("redeemable", False):
                continue
            cur_price = float(pos.get("curPrice", 0))
            current_value = float(pos.get("currentValue", 0))
            if cur_price != 1.0 or current_value <= 0:
                continue
            redeemable.append(pos)

        if not redeemable:
            logger.debug("redeemer_nothing_to_redeem")
            return {"redeemed": 0, "total_value": 0}

        # Deduplicate by condition_id
        seen_cids: set[str] = set()
        unique: list[dict] = []
        for pos in redeemable:
            cid = pos["conditionId"]
            if cid not in seen_cids:
                seen_cids.add(cid)
                unique.append(pos)

        total_value = sum(float(p.get("currentValue", 0)) for p in redeemable)
        logger.info(
            "redeemer_found_redeemable",
            conditions=len(unique),
            total_value=round(total_value, 2),
        )

        # 5. Redeem each condition individually
        redeemed_count = 0
        errors = []

        for pos in unique:
            condition_id = pos["conditionId"]
            title = pos.get("title", "")[:50]
            value = float(pos.get("currentValue", 0))

            try:
                tx_hash = await self._redeem_single(condition_id, gas_price)
                if tx_hash:
                    self._redeemed_conditions.add(condition_id)
                    redeemed_count += 1
                    logger.info(
                        "redeemer_redeemed",
                        title=title,
                        value=round(value, 2),
                        tx_hash=tx_hash,
                    )
            except Exception as exc:
                err_msg = str(exc)
                errors.append({"condition_id": condition_id[:20], "error": err_msg[:80]})
                logger.error(
                    "redeemer_redeem_error",
                    title=title,
                    error=err_msg[:120],
                )

        # 6. Check balance after
        usdc_after = self._get_usdc_balance()
        recovered = usdc_after - usdc_before

        logger.info(
            "redeemer_complete",
            redeemed=redeemed_count,
            total=len(unique),
            errors=len(errors),
            usdc_before=round(usdc_before, 2),
            usdc_after=round(usdc_after, 2),
            recovered=round(recovered, 2),
        )

        return {
            "status": "redeemed",
            "redeemed": redeemed_count,
            "total": len(unique),
            "errors": len(errors),
            "usdc_before": round(usdc_before, 2),
            "usdc_after": round(usdc_after, 2),
            "recovered": round(recovered, 2),
        }

    async def _redeem_single(
        self, condition_id: str, gas_price: int
    ) -> Optional[str]:
        """Call redeemPositions directly from the wallet for one condition.

        Returns transaction hash string, or None on failure.
        """
        loop = asyncio.get_event_loop()

        def _do_redeem() -> str:
            usdc_address = Web3.to_checksum_address(USDC_E_ADDRESS)
            cid_bytes = bytes.fromhex(condition_id[2:]) if condition_id.startswith("0x") else bytes.fromhex(condition_id)

            # Estimate gas
            try:
                gas_estimate = self._ctf.functions.redeemPositions(
                    usdc_address, ZERO_BYTES32, cid_bytes, [1, 2]
                ).estimate_gas({"from": self._wallet_address})
                gas_limit = int(gas_estimate * 1.3)
            except Exception:
                gas_limit = 200_000  # fallback

            nonce = self._w3.eth.get_transaction_count(self._wallet_address)

            tx = self._ctf.functions.redeemPositions(
                usdc_address, ZERO_BYTES32, cid_bytes, [1, 2]
            ).build_transaction({
                "from": self._wallet_address,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": 137,
            })

            signed_tx = self._w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = self._w3.to_hex(tx_hash)

            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status != 1:
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            return tx_hash_hex

        return await loop.run_in_executor(None, _do_redeem)

    def _get_matic_balance(self) -> float:
        """Get MATIC/POL balance."""
        try:
            raw = self._w3.eth.get_balance(Web3.to_checksum_address(self._wallet_address))
            return float(self._w3.from_wei(raw, "ether"))
        except Exception:
            return 0.0

    def _get_usdc_balance(self) -> float:
        """Get current USDC.e balance."""
        try:
            raw_balance = self._usdc.functions.balanceOf(
                Web3.to_checksum_address(self._wallet_address)
            ).call()
            return raw_balance / 1e6
        except Exception:
            return 0.0

    def get_status(self) -> dict[str, Any]:
        """Return current redeemer status."""
        try:
            gas_price = self._w3.eth.gas_price
            gas_gwei = float(self._w3.from_wei(gas_price, "gwei"))
        except Exception:
            gas_gwei = 0.0

        return {
            "running": self._running,
            "wallet": self._wallet_address,
            "matic_balance": round(self._get_matic_balance(), 6),
            "usdc_balance": round(self._get_usdc_balance(), 2),
            "gas_price_gwei": round(gas_gwei, 1),
            "redeemed_conditions": len(self._redeemed_conditions),
            "check_interval": self._check_interval,
        }
