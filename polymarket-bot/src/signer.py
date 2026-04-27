"""EIP-712 order signing for Polymarket CLOB on Polygon."""

from __future__ import annotations

import time
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

# Polymarket CLOB exchange contract on Polygon
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
# Conditional Tokens Framework (CTF) on Polygon
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# EIP-712 domain for Polymarket CTF Exchange
DOMAIN_DATA = {
    "name": "Polymarket CTF Exchange",
    "version": "1",
    "chainId": 137,
    "verifyingContract": EXCHANGE_ADDRESS,
}

# Neg Risk CTF Exchange on Polygon (multi-outcome / neg-risk markets)
NEG_RISK_EXCHANGE_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
NEG_RISK_DOMAIN_DATA = {
    "name": "Polymarket CTF Exchange",
    "version": "1",
    "chainId": 137,
    "verifyingContract": NEG_RISK_EXCHANGE_ADDRESS,
}

# Order type definition for EIP-712
ORDER_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"},
        {"name": "taker", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "expiration", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "feeRateBps", "type": "uint256"},
        {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
    ],
}

# Side enum
SIDE_BUY = 0
SIDE_SELL = 1


def _generate_salt() -> int:
    """Generate a unique salt for order signing."""
    return int(time.time() * 1_000_000)


def _to_wei(amount: float, decimals: int = 6) -> int:
    """Convert a float amount to integer wei (USDC has 6 decimals)."""
    return int(amount * (10**decimals))


def _token_id_to_int(token_id: str) -> int:
    """Convert a Polymarket token_id string to int.

    Token IDs from the CLOB API arrive as large decimal strings.
    Some API responses (or blockchain event logs) may use 0x-prefixed hex.
    Both formats are normalised here before being placed in the EIP-712 struct.
    """
    s = str(token_id).strip()
    if s.startswith(("0x", "0X")):
        return int(s, 16)
    return int(s)


class OrderSigner:
    """Signs Polymarket CLOB orders using EIP-712."""

    def __init__(self, private_key: str, chain_id: int = 137) -> None:
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        self._private_key = private_key
        self._account = Account.from_key(bytes.fromhex(private_key))
        self.address = self._account.address
        self._domain = {**DOMAIN_DATA, "chainId": chain_id}
        self._neg_risk_domain = {**NEG_RISK_DOMAIN_DATA, "chainId": chain_id}

    def build_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: int,
        fee_rate_bps: int = 0,
        nonce: int = 0,
        expiration: int = 0,
        taker: str = "0x0000000000000000000000000000000000000000",
    ) -> dict[str, Any]:
        """Build an unsigned order struct.

        For a BUY: makerAmount = size * price (USDC), takerAmount = size (shares)
        For a SELL: makerAmount = size (shares), takerAmount = size * price (USDC)
        """
        if side == SIDE_BUY:
            maker_amount = _to_wei(size * price)
            taker_amount = _to_wei(size)
        else:
            maker_amount = _to_wei(size)
            taker_amount = _to_wei(size * price)

        return {
            "salt": _generate_salt(),
            "maker": self.address,
            "signer": self.address,
            "taker": taker,
            "tokenId": _token_id_to_int(token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": expiration,
            "nonce": nonce,
            "feeRateBps": fee_rate_bps,
            "side": side,
            "signatureType": 0,  # EOA
        }

    def sign_order(self, order: dict[str, Any], neg_risk: bool = False) -> str:
        """Sign an order using EIP-712 and return the hex signature."""
        domain = self._neg_risk_domain if neg_risk else self._domain
        structured = {
            "types": ORDER_TYPES,
            "primaryType": "Order",
            "domain": domain,
            "message": order,
        }
        # eth_account >= 0.9 requires full_message= keyword; positional passes
        # the dict as domain_data, causing "Invalid domain key: types".
        encoded = encode_typed_data(full_message=structured)
        signed = self._account.sign_message(encoded)
        return signed.signature.hex()

    def build_and_sign(
        self,
        token_id: str,
        price: float,
        size: float,
        side: int,
        fee_rate_bps: int = 0,
        nonce: int = 0,
        expiration: int = 0,
        neg_risk: bool = False,
    ) -> tuple[dict[str, Any], str]:
        """Build and sign an order in one call. Returns (order, signature)."""
        order = self.build_order(
            token_id=token_id,
            price=price,
            size=size,
            side=side,
            fee_rate_bps=fee_rate_bps,
            nonce=nonce,
            expiration=expiration,
        )
        sig = self.sign_order(order, neg_risk=neg_risk)
        return order, sig
