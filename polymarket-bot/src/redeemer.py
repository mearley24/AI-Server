"""Polymarket Position Redeemer.

Automatically redeems resolved winning positions from the ConditionalTokens
contract on Polygon, converting winning outcome tokens back into USDC.e.

Uses Multicall3 to batch ALL redemptions into a single transaction,
dramatically reducing gas costs (~1.4M gas total vs ~3.1M for 25 individual txns).

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
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

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

# Multicall3 aggregate3 ABI
MULTICALL3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "payable",
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
MAX_GAS_PRICE_GWEI = 200  # Don't transact above this
MAX_SINGLE_TX_MATIC = 0.3  # Safety cap per transaction


class PolymarketRedeemer:
    """Redeems resolved winning Polymarket positions for USDC.e.

    Uses Multicall3 to batch all redemptions into a single transaction.
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
        self._mc3 = self._w3.eth.contract(
            address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
            abi=MULTICALL3_ABI,
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
        """Find and redeem all resolved winning positions in a single batch tx.

        Returns summary of redemption attempt.
        """
        assert self._http is not None

        # 1. Check MATIC balance and gas price
        matic_balance = self._get_matic_balance()
        gas_price = self._w3.eth.gas_price
        gas_gwei = float(self._w3.from_wei(gas_price, "gwei"))

        if gas_gwei > MAX_GAS_PRICE_GWEI:
            logger.info("redeemer_gas_too_high", gas_gwei=round(gas_gwei, 1),
                        max_gwei=MAX_GAS_PRICE_GWEI)
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

        # Deduplicate by condition_id (multiple positions per condition)
        unique_conditions: dict[str, float] = {}
        for pos in redeemable:
            cid = pos["conditionId"]
            val = float(pos.get("currentValue", 0))
            unique_conditions[cid] = unique_conditions.get(cid, 0) + val

        total_value = sum(unique_conditions.values())
        logger.info(
            "redeemer_found_redeemable",
            conditions=len(unique_conditions),
            total_value=round(total_value, 2),
            matic_balance=round(matic_balance, 6),
            gas_gwei=round(gas_gwei, 1),
        )

        # 5. Estimate gas for batch redemption
        condition_ids = list(unique_conditions.keys())

        try:
            gas_estimate, tx_cost_matic = await self._estimate_batch_gas(
                condition_ids, gas_price
            )
        except Exception as exc:
            logger.error("redeemer_gas_estimate_failed", error=str(exc))
            return {"error": f"Gas estimate failed: {exc}"}

        if tx_cost_matic > matic_balance:
            logger.warning(
                "redeemer_insufficient_matic",
                need=round(tx_cost_matic, 6),
                have=round(matic_balance, 6),
                shortfall=round(tx_cost_matic - matic_balance, 6),
                to_recover=round(total_value, 2),
            )
            return {
                "status": "insufficient_matic",
                "need_matic": round(tx_cost_matic, 6),
                "have_matic": round(matic_balance, 6),
                "to_recover_usdc": round(total_value, 2),
            }

        if tx_cost_matic > MAX_SINGLE_TX_MATIC:
            logger.warning("redeemer_tx_cost_too_high", cost=round(tx_cost_matic, 6))
            return {"status": "tx_cost_safety_cap", "cost": round(tx_cost_matic, 6)}

        # 6. Execute batch redemption
        try:
            tx_hash = await self._execute_batch_redeem(
                condition_ids, gas_estimate, gas_price
            )
        except Exception as exc:
            logger.error("redeemer_batch_redeem_failed", error=str(exc))
            return {"error": f"Batch redeem failed: {exc}"}

        # Mark all as redeemed
        for cid in condition_ids:
            self._redeemed_conditions.add(cid)

        # 7. Check balance after
        usdc_after = self._get_usdc_balance()
        recovered = usdc_after - usdc_before

        logger.info(
            "redeemer_batch_complete",
            tx_hash=tx_hash,
            conditions_redeemed=len(condition_ids),
            usdc_before=round(usdc_before, 2),
            usdc_after=round(usdc_after, 2),
            recovered=round(recovered, 2),
            gas_used_matic=round(tx_cost_matic, 6),
        )

        return {
            "status": "redeemed",
            "tx_hash": tx_hash,
            "conditions": len(condition_ids),
            "usdc_before": round(usdc_before, 2),
            "usdc_after": round(usdc_after, 2),
            "recovered": round(recovered, 2),
        }

    async def _estimate_batch_gas(
        self, condition_ids: list[str], gas_price: int
    ) -> tuple[int, float]:
        """Estimate gas for a Multicall3 batch of redemptions.

        Returns (gas_estimate, cost_in_matic).
        """
        loop = asyncio.get_event_loop()

        def _estimate() -> tuple[int, float]:
            calls = self._build_multicall_data(condition_ids)
            gas_est = self._mc3.functions.aggregate3(calls).estimate_gas(
                {"from": self._wallet_address}
            )
            gas_with_buffer = int(gas_est * 1.2)  # 20% buffer
            cost_wei = gas_with_buffer * gas_price
            cost_matic = float(self._w3.from_wei(cost_wei, "ether"))
            return gas_with_buffer, cost_matic

        return await loop.run_in_executor(None, _estimate)

    async def _execute_batch_redeem(
        self, condition_ids: list[str], gas_limit: int, gas_price: int
    ) -> str:
        """Execute batch redemption via Multicall3.

        Returns transaction hash.
        """
        loop = asyncio.get_event_loop()

        def _execute() -> str:
            calls = self._build_multicall_data(condition_ids)
            nonce = self._w3.eth.get_transaction_count(self._wallet_address)

            tx = self._mc3.functions.aggregate3(calls).build_transaction({
                "from": self._wallet_address,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": 137,
            })

            signed_tx = self._w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = self._w3.to_hex(tx_hash)

            logger.info("redeemer_tx_sent", tx_hash=tx_hash_hex,
                        conditions=len(condition_ids))

            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status != 1:
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            logger.info("redeemer_tx_confirmed", tx_hash=tx_hash_hex,
                        gas_used=receipt.gasUsed)
            return tx_hash_hex

        return await loop.run_in_executor(None, _execute)

    def _build_multicall_data(self, condition_ids: list[str]) -> list[tuple]:
        """Build Multicall3 call tuples for batch redemption."""
        usdc_address = Web3.to_checksum_address(USDC_E_ADDRESS)
        ctf_address = Web3.to_checksum_address(CTF_ADDRESS)
        calls = []

        for cid in condition_ids:
            cid_bytes = bytes.fromhex(cid[2:]) if cid.startswith("0x") else bytes.fromhex(cid)
            call_data = self._ctf.functions.redeemPositions(
                usdc_address, ZERO_BYTES32, cid_bytes, [1, 2]
            )._encode_transaction_data()
            # (target, allowFailure, callData)
            calls.append((ctf_address, True, bytes.fromhex(call_data[2:])))

        return calls

    def _get_matic_balance(self) -> float:
        """Get MATIC balance in human-readable format."""
        try:
            raw = self._w3.eth.get_balance(Web3.to_checksum_address(self._wallet_address))
            return float(self._w3.from_wei(raw, "ether"))
        except Exception:
            return 0.0

    def _get_usdc_balance(self) -> float:
        """Get current USDC.e balance in human-readable format."""
        try:
            raw_balance = self._usdc.functions.balanceOf(
                Web3.to_checksum_address(self._wallet_address)
            ).call()
            return raw_balance / 1e6  # USDC.e has 6 decimals
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
