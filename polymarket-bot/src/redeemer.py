"""Polymarket Position Redeemer.

Automatically redeems resolved winning positions from the ConditionalTokens
contract on Polygon, converting winning outcome tokens back into USDC.e.

Sends individual redeemPositions transactions directly from the EOA wallet.
(Multicall3 doesn't work because CTF redeems for msg.sender, and Multicall3
changes msg.sender to its own address.)

Performs on-chain verification of:
  1. CTF token balance (ERC1155)
  2. Condition resolution status (payoutDenominator > 0)
  3. Whether user holds the winning outcome

Works with EOA wallets (signature_type=0).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
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

# ERC1155 balanceOf for CTF tokens
ERC1155_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# On-chain resolution status ABIs
PAYOUT_NUMERATORS_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "", "type": "bytes32"},
            {"name": "", "type": "uint256"},
        ],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

PAYOUT_DENOMINATOR_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Zero bytes32 — always used as parentCollectionId for Polymarket top-level positions
ZERO_BYTES32 = b"\x00" * 32

# NegRiskAdapter for multi-outcome market redemptions
NEG_RISK_ADAPTER_ADDRESS = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
NEG_RISK_ADAPTER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_conditionId", "type": "bytes32"},
            {"name": "_amounts", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "type": "function",
    }
]

# Polygon RPC endpoints (fallback list)
POLYGON_RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
]

# Gas settings
MAX_GAS_PRICE_GWEI = 800  # Polygon can spike; 800 Gwei is still < $0.05 per tx


class PolymarketRedeemer:
    """Redeems resolved winning Polymarket positions for USDC.e.

    Sends individual redeemPositions calls directly from the wallet.
    Monitors gas price and POL balance to ensure transactions succeed.
    Uses on-chain verification (payoutDenominator, payoutNumerators, ERC1155 balance)
    instead of relying solely on Data API fields.
    """

    def __init__(
        self,
        private_key: str,
        check_interval: float = 300.0,  # 5 minutes
        rpc_url: str = "",
        data_dir: str = "/data",
    ) -> None:
        self._private_key = private_key if private_key.startswith("0x") else f"0x{private_key}"
        self._check_interval = check_interval
        self._http: Optional[httpx.AsyncClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._data_dir = Path(data_dir)
        self._redeemed_path = self._data_dir / "redeemed_conditions.json"
        self._last_cycle_at: float = 0.0
        self._last_cycle_summary: dict[str, Any] = {}

        # Initialize web3 with RPC fallback
        self._w3 = self._connect_rpc(rpc_url)

        self._account = self._w3.eth.account.from_key(self._private_key)
        self._wallet_address = self._account.address

        # Contracts - include all needed ABIs
        ctf_abi = REDEEM_ABI + ERC1155_BALANCE_ABI + PAYOUT_NUMERATORS_ABI + PAYOUT_DENOMINATOR_ABI
        self._ctf = self._w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=ctf_abi,
        )
        self._usdc = self._w3.eth.contract(
            address=Web3.to_checksum_address(USDC_E_ADDRESS),
            abi=ERC20_BALANCE_ABI,
        )

        # Track already-redeemed condition IDs (persisted — survives restarts)
        self._redeemed_conditions: set[str] = self._load_redeemed()

        # Nonce tracker — avoids race conditions when sending multiple txns
        self._next_nonce: Optional[int] = None

        # NegRiskAdapter for neg risk market redemptions
        self._neg_adapter = self._w3.eth.contract(
            address=Web3.to_checksum_address(NEG_RISK_ADAPTER_ADDRESS),
            abi=NEG_RISK_ADAPTER_ABI,
        )

    def _load_redeemed(self) -> set[str]:
        try:
            if self._redeemed_path.is_file():
                raw = json.loads(self._redeemed_path.read_text(encoding="utf-8"))
                ids = raw.get("condition_ids")
                if isinstance(ids, list):
                    n = len(ids)
                    logger.info("redeemer_loaded_redeemed", count=n)
                    return set(str(x) for x in ids if x)
        except Exception as exc:
            logger.warning("redeemer_load_redeemed_failed", error=str(exc)[:120])
        return set()

    def _save_redeemed(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            ids = sorted(self._redeemed_conditions)
            if len(ids) > 50_000:
                ids = ids[-50_000:]
                self._redeemed_conditions = set(ids)
            self._redeemed_path.write_text(
                json.dumps({"condition_ids": ids, "updated_at": time.time()}, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("redeemer_save_redeemed_failed", error=str(exc)[:120])

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

            logger.debug("redeemer_heartbeat", ts=time.time(), interval=self._check_interval)

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break

    def _get_onchain_resolution(self, condition_id_hex: str) -> dict:
        """Check on-chain resolution status for a condition.

        Returns dict with:
            resolved: bool - whether the condition has been resolved
            payout_numerators: list[int] - payout for each outcome slot
            payout_denominator: int - denominator for payout fractions
        """
        cid_bytes = (
            bytes.fromhex(condition_id_hex[2:])
            if condition_id_hex.startswith("0x")
            else bytes.fromhex(condition_id_hex)
        )
        try:
            denom = self._ctf.functions.payoutDenominator(cid_bytes).call()
            p0 = self._ctf.functions.payoutNumerators(cid_bytes, 0).call()
            p1 = self._ctf.functions.payoutNumerators(cid_bytes, 1).call()
            return {
                "resolved": denom > 0,
                "payout_numerators": [p0, p1],
                "payout_denominator": denom,
            }
        except Exception as e:
            logger.warning("redeemer_resolution_check_error", condition_id=condition_id_hex[:20], error=str(e)[:80])
            return {"resolved": False, "payout_numerators": [0, 0], "payout_denominator": 0}

    def _get_ctf_token_balance(self, token_id: str) -> int:
        """Get on-chain ERC1155 balance for a CTF token."""
        try:
            return self._ctf.functions.balanceOf(
                Web3.to_checksum_address(self._wallet_address),
                int(token_id),
            ).call()
        except Exception:
            return 0

    async def redeem_all_winning(self) -> dict[str, Any]:
        """Find and redeem all resolved winning positions one by one.

        Uses on-chain verification instead of relying solely on Data API fields.

        Returns summary of redemption attempt.
        """
        assert self._http is not None

        # Reset nonce tracker at start of each cycle
        self._next_nonce = None

        # 1. Check gas price (head-of-cycle; each tx also refreshes inside _redeem_single)
        gas_price = self._w3.eth.gas_price
        gas_gwei = float(self._w3.from_wei(gas_price, "gwei"))

        if gas_gwei > MAX_GAS_PRICE_GWEI:
            logger.info("redeemer_gas_too_high", gas_gwei=round(gas_gwei, 1))
            self._last_cycle_at = time.time()
            self._last_cycle_summary = {"status": "gas_too_high", "gas_gwei": round(gas_gwei, 1)}
            return {"status": "gas_too_high", "gas_gwei": round(gas_gwei, 1)}

        # Check gas token balance
        matic_balance = self._get_matic_balance()
        if matic_balance < 0.05:
            logger.warning("redeemer_low_gas", matic_balance=round(matic_balance, 4))
            return {"error": "insufficient_gas_token", "matic_balance": round(matic_balance, 4)}

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
            self._last_cycle_at = time.time()
            self._last_cycle_summary = {"error": str(exc)[:200]}
            return {"error": str(exc)}

        logger.info("redeemer_fetched_positions", count=len(positions))

        # 4. Verify each position on-chain and find redeemable winners
        redeemable = []
        pending_count = 0
        loser_count = 0

        for pos in positions:
            condition_id = pos.get("conditionId", "")
            asset = pos.get("asset", "")
            outcome_index = int(pos.get("outcomeIndex", 0))

            if not condition_id or not asset:
                logger.debug("redeemer_skip_missing_fields", title=pos.get("title", "?")[:40], has_cid=bool(condition_id), has_asset=bool(asset))
                continue
            if condition_id in self._redeemed_conditions:
                continue

            # On-chain token balance check
            token_balance_raw = await asyncio.get_event_loop().run_in_executor(
                None, self._get_ctf_token_balance, asset
            )
            if token_balance_raw == 0:
                continue

            # On-chain resolution check
            resolution = await asyncio.get_event_loop().run_in_executor(
                None, self._get_onchain_resolution, condition_id
            )

            if not resolution["resolved"]:
                pending_count += 1
                logger.debug(
                    "redeemer_position_pending",
                    title=pos.get("title", "")[:50],
                    balance=token_balance_raw / 1e6,
                )
                continue

            # Check if user holds the winning outcome
            payout_nums = resolution["payout_numerators"]
            payout_denom = resolution["payout_denominator"]
            if outcome_index < 0 or outcome_index >= len(payout_nums):
                logger.warning("redeemer_invalid_outcome_index", condition_id=condition_id[:20], outcome_index=outcome_index, payout_count=len(payout_nums))
                continue
            user_payout = payout_nums[outcome_index]

            if user_payout == 0:
                loser_count += 1
                # Redeem losers too — burns tokens and clears them from UI
                redeemable.append({
                    **pos,
                    "_expected_usdc": 0,
                    "_token_balance": token_balance_raw / 1e6,
                    "_is_loser": True,
                })
                continue

            # This is a winning position with on-chain balance
            expected_usdc = (token_balance_raw * user_payout) / (payout_denom * 1e6) if payout_denom > 0 else 0
            redeemable.append({
                **pos,
                "_expected_usdc": expected_usdc,
                "_token_balance": token_balance_raw / 1e6,
            })

        if not redeemable:
            logger.debug(
                "redeemer_nothing_to_redeem",
                total_positions=len(positions),
                pending=pending_count,
                losers=loser_count,
            )
            out = {"redeemed": 0, "total_value": 0, "pending": pending_count, "losers": loser_count}
            self._last_cycle_at = time.time()
            self._last_cycle_summary = {**out, "status": "idle"}
            return out

        # Deduplicate by condition_id
        seen_cids: set[str] = set()
        unique: list[dict] = []
        for pos in redeemable:
            cid = pos["conditionId"]
            if cid not in seen_cids:
                seen_cids.add(cid)
                unique.append(pos)

        total_value = sum(p.get("_expected_usdc", 0) for p in unique)
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
            value = pos.get("_expected_usdc", 0)

            for attempt in range(3):
                try:
                    is_neg_risk = pos.get("neg_risk", pos.get("negativeRisk", False))
                    outcome_index = int(pos.get("outcomeIndex", 0))
                    token_balance_raw = int(pos.get("_token_balance", 0) * 1e6)
                    tx_hash = await self._redeem_single(
                        condition_id,
                        neg_risk=is_neg_risk,
                        outcome_index=outcome_index,
                        token_balance=token_balance_raw,
                    )
                    if tx_hash:
                        self._redeemed_conditions.add(condition_id)
                        self._save_redeemed()
                        redeemed_count += 1
                        logger.info(
                            "redeemer_redeemed",
                            title=title,
                            value=round(value, 2),
                            tx_hash=tx_hash,
                        )
                    break  # Success, move to next position
                except Exception as exc:
                    err_msg = str(exc)
                    if "nonce" in err_msg.lower() and attempt < 2:
                        logger.warning("redeemer_nonce_retry", attempt=attempt + 1, error=err_msg[:80])
                        self._next_nonce = None  # Force nonce refresh
                        await asyncio.sleep(5)
                        continue
                    self._next_nonce = None
                    errors.append({"condition_id": condition_id[:20], "error": err_msg[:80]})
                    logger.error("redeemer_redeem_error", title=title, error=err_msg[:120])
                    break

            await asyncio.sleep(4)  # 4s between redemptions for nonce propagation

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

        result = {
            "status": "redeemed",
            "redeemed": redeemed_count,
            "total": len(unique),
            "errors": len(errors),
            "usdc_before": round(usdc_before, 2),
            "usdc_after": round(usdc_after, 2),
            "recovered": round(recovered, 2),
        }
        self._last_cycle_at = time.time()
        self._last_cycle_summary = result
        return result

    async def _redeem_single(
        self,
        condition_id: str,
        neg_risk: bool = False,
        outcome_index: int = 0,
        token_balance: int = 0,
    ) -> Optional[str]:
        """Call redeemPositions — routes through NegRiskAdapter for neg risk markets.

        Returns transaction hash string, or None on failure.
        """
        loop = asyncio.get_event_loop()

        def _do_redeem() -> str:
            gas_price = self._w3.eth.gas_price
            gas_gwei = float(self._w3.from_wei(gas_price, "gwei"))
            if gas_gwei > MAX_GAS_PRICE_GWEI:
                raise RuntimeError(f"gas_too_high:{gas_gwei:.1f}gwei")

            cid_bytes = bytes.fromhex(condition_id[2:]) if condition_id.startswith("0x") else bytes.fromhex(condition_id)
            # Use tracked nonce to avoid race conditions between rapid txns
            if self._next_nonce is not None:
                nonce = self._next_nonce
            else:
                nonce = self._w3.eth.get_transaction_count(self._wallet_address)

            if neg_risk and token_balance > 0:
                # Neg risk: use NegRiskAdapter.redeemPositions(conditionId, amounts)
                # amounts = [Yes_balance, No_balance] based on outcome_index
                if outcome_index == 0:
                    amounts = [token_balance, 0]
                else:
                    amounts = [0, token_balance]

                tx = self._neg_adapter.functions.redeemPositions(
                    cid_bytes, amounts
                ).build_transaction({
                    "from": self._wallet_address,
                    "nonce": nonce,
                    "gas": 500_000,
                    "gasPrice": gas_price,
                    "chainId": 137,
                })
            else:
                # Standard CTF redemption
                usdc_address = Web3.to_checksum_address(USDC_E_ADDRESS)
                try:
                    gas_estimate = self._ctf.functions.redeemPositions(
                        usdc_address, ZERO_BYTES32, cid_bytes, [1, 2]
                    ).estimate_gas({"from": self._wallet_address})
                    gas_limit = int(gas_estimate * 1.3)
                except Exception:
                    gas_limit = 200_000

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

            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                self._next_nonce = None  # Reset on failure
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            # Increment tracked nonce for next txn
            self._next_nonce = nonce + 1
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
            "redeemed_conditions_persisted": self._redeemed_path.is_file(),
            "check_interval": self._check_interval,
            "last_cycle_at": self._last_cycle_at,
            "last_cycle_summary": self._last_cycle_summary,
        }
