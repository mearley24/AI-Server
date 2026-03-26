"""Polymarket Position Redeemer.

Automatically redeems resolved winning positions from the ConditionalTokens
contract on Polygon, converting winning outcome tokens back into USDC.e.

Uses web3.py to call `redeemPositions()` directly on the CTF contract.
Works with EOA wallets (signature_type=0).

Reference: https://github.com/Polymarket/conditional-token-examples-py
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


class PolymarketRedeemer:
    """Redeems resolved winning Polymarket positions for USDC.e."""

    def __init__(
        self,
        private_key: str,
        check_interval: float = 300.0,  # 5 minutes
        rpc_url: str = "",
    ) -> None:
        self._private_key = private_key if private_key.startswith("0x") else f"0x{private_key}"
        self._check_interval = check_interval
        self._rpc_url = rpc_url or ""
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

        # Last resort — return first one even if not tested
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
        """Find and redeem all resolved winning positions.

        Returns summary of redemptions attempted.
        """
        assert self._http is not None

        # 1. Get current USDC.e balance before
        balance_before = self._get_usdc_balance()

        # 2. Fetch positions from Polymarket Data API
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

        # 3. Filter to redeemable winning positions
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

        # 4. Group by condition_id (one tx per condition)
        by_condition: dict[str, list[dict]] = {}
        for pos in redeemable:
            cid = pos["conditionId"]
            if cid not in by_condition:
                by_condition[cid] = []
            by_condition[cid].append(pos)

        total_value = sum(float(p.get("currentValue", 0)) for p in redeemable)
        logger.info(
            "redeemer_found_redeemable",
            conditions=len(by_condition),
            positions=len(redeemable),
            total_value=round(total_value, 2),
        )

        # 5. Redeem each condition
        redeemed_count = 0
        errors = []

        for condition_id, cond_positions in by_condition.items():
            title = cond_positions[0].get("title", "")
            value = sum(float(p.get("currentValue", 0)) for p in cond_positions)
            neg_risk = cond_positions[0].get("negativeRisk", False)

            try:
                tx_hash = await self._redeem_condition(condition_id, neg_risk=neg_risk)
                if tx_hash:
                    self._redeemed_conditions.add(condition_id)
                    redeemed_count += 1
                    logger.info(
                        "redeemer_redeemed",
                        condition_id=condition_id[:20] + "...",
                        title=title[:50],
                        value=round(value, 2),
                        tx_hash=tx_hash,
                    )
                else:
                    logger.warning(
                        "redeemer_redeem_no_tx",
                        condition_id=condition_id[:20] + "...",
                        title=title[:50],
                    )
            except Exception as exc:
                err_msg = str(exc)
                errors.append({"condition_id": condition_id[:20], "error": err_msg[:100]})
                logger.error(
                    "redeemer_redeem_error",
                    condition_id=condition_id[:20] + "...",
                    title=title[:50],
                    error=err_msg[:120],
                )

        # 6. Check balance after
        balance_after = self._get_usdc_balance()
        recovered = balance_after - balance_before

        logger.info(
            "redeemer_summary",
            redeemed=redeemed_count,
            total_conditions=len(by_condition),
            errors=len(errors),
            balance_before=round(balance_before, 2),
            balance_after=round(balance_after, 2),
            recovered=round(recovered, 2),
        )

        return {
            "redeemed": redeemed_count,
            "total_conditions": len(by_condition),
            "errors": errors,
            "balance_before": round(balance_before, 2),
            "balance_after": round(balance_after, 2),
            "recovered": round(recovered, 2),
        }

    async def _redeem_condition(
        self, condition_id: str, neg_risk: bool = False
    ) -> Optional[str]:
        """Call redeemPositions on the CTF contract for one condition.

        Args:
            condition_id: The market's condition ID (hex string with 0x prefix)
            neg_risk: Whether this is a neg-risk market

        Returns:
            Transaction hash string, or None on failure
        """
        loop = asyncio.get_event_loop()

        def _do_redeem() -> str:
            usdc_address = Web3.to_checksum_address(USDC_E_ADDRESS)

            # For Polymarket binary markets, indexSets is always [1, 2]
            # indexSet 1 = 0b01 = first outcome (Yes/Up)
            # indexSet 2 = 0b10 = second outcome (No/Down)
            index_sets = [1, 2]

            # Build the transaction
            nonce = self._w3.eth.get_transaction_count(self._wallet_address)
            gas_price = self._w3.eth.gas_price

            # Estimate gas with a safety margin
            try:
                gas_estimate = self._ctf.functions.redeemPositions(
                    usdc_address,
                    ZERO_BYTES32,
                    bytes.fromhex(condition_id[2:]) if condition_id.startswith("0x") else bytes.fromhex(condition_id),
                    index_sets,
                ).estimate_gas({"from": self._wallet_address})
                gas_limit = int(gas_estimate * 1.3)  # 30% buffer
            except Exception as gas_err:
                logger.warning("redeemer_gas_estimate_failed", error=str(gas_err)[:80])
                gas_limit = 200_000  # fallback

            tx = self._ctf.functions.redeemPositions(
                usdc_address,
                ZERO_BYTES32,
                bytes.fromhex(condition_id[2:]) if condition_id.startswith("0x") else bytes.fromhex(condition_id),
                index_sets,
            ).build_transaction({
                "from": self._wallet_address,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": 137,
            })

            # Sign and send
            signed_tx = self._w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = self._w3.to_hex(tx_hash)

            # Wait for receipt (timeout 60s)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            if receipt.status != 1:
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            return tx_hash_hex

        return await loop.run_in_executor(None, _do_redeem)

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
        return {
            "running": self._running,
            "wallet": self._wallet_address,
            "usdc_balance": self._get_usdc_balance(),
            "redeemed_conditions": len(self._redeemed_conditions),
            "check_interval": self._check_interval,
        }
