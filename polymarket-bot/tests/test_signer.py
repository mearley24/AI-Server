"""Tests for EIP-712 order signing — signer.py.

Run from polymarket-bot/ with:
    .venv-tests/bin/python3 -m pytest tests/test_signer.py -v
"""

from __future__ import annotations

import pytest

from src.signer import (
    DOMAIN_DATA,
    EXCHANGE_ADDRESS,
    NEG_RISK_EXCHANGE_ADDRESS,
    ORDER_TYPES,
    SIDE_BUY,
    SIDE_SELL,
    OrderSigner,
    _token_id_to_int,
)

# Deterministic private key for tests (64 hex chars, no 0x prefix)
_TEST_KEY = "a" * 64

# Realistic Polymarket token IDs
_TOKEN_DEC = "71321045679252212594626385532706912750332728571942532289631379312455583992410"
_TOKEN_HEX = "0x1f73b16b95d50a7b80a04b70695853820a6ccc85ae8e5d534d7c5a71e4f64a4d"
_TOKEN_HEX_UPPER = "0X1F73B16B95D50A7B80A04B70695853820A6CCC85AE8E5D534D7C5A71E4F64A4D"


@pytest.fixture
def signer():
    return OrderSigner(_TEST_KEY)


@pytest.fixture
def signer_0x():
    """Signer constructed with 0x-prefixed private key."""
    return OrderSigner("0x" + _TEST_KEY)


# ── _token_id_to_int ──────────────────────────────────────────────────────────

class TestTokenIdToInt:

    def test_decimal_string(self):
        assert _token_id_to_int("12345") == 12345

    def test_large_decimal(self):
        n = _token_id_to_int(_TOKEN_DEC)
        assert n == int(_TOKEN_DEC)
        assert n > 0

    def test_hex_lowercase_prefix(self):
        n = _token_id_to_int(_TOKEN_HEX)
        assert n == int(_TOKEN_HEX, 16)
        assert n > 0

    def test_hex_uppercase_prefix(self):
        n = _token_id_to_int(_TOKEN_HEX_UPPER)
        assert n == int(_TOKEN_HEX_UPPER, 16)

    def test_hex_and_decimal_same_value(self):
        """0x-prefixed and decimal forms of the same number must match."""
        dec_val = 255
        assert _token_id_to_int("255") == dec_val
        assert _token_id_to_int("0xff") == dec_val
        assert _token_id_to_int("0xFF") == dec_val

    def test_strips_whitespace(self):
        assert _token_id_to_int("  12345  ") == 12345

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            _token_id_to_int("not_a_number")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _token_id_to_int("")


# ── OrderSigner construction ──────────────────────────────────────────────────

class TestOrderSignerConstruction:

    def test_address_derived(self, signer):
        assert signer.address.startswith("0x")
        assert len(signer.address) == 42

    def test_0x_prefix_stripped(self, signer, signer_0x):
        """Signer with and without 0x prefix must produce the same address."""
        assert signer.address == signer_0x.address

    def test_domain_chain_id(self, signer):
        assert signer._domain["chainId"] == 137

    def test_domain_contract(self, signer):
        assert signer._domain["verifyingContract"] == EXCHANGE_ADDRESS

    def test_neg_risk_domain_contract(self, signer):
        assert signer._neg_risk_domain["verifyingContract"] == NEG_RISK_EXCHANGE_ADDRESS


# ── build_order ───────────────────────────────────────────────────────────────

class TestBuildOrder:

    def test_decimal_token_id(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["tokenId"] == int(_TOKEN_DEC)

    def test_hex_token_id_normalised(self, signer):
        order = signer.build_order(token_id=_TOKEN_HEX, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["tokenId"] == int(_TOKEN_HEX, 16)

    def test_hex_upper_token_id_normalised(self, signer):
        order = signer.build_order(token_id=_TOKEN_HEX_UPPER, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["tokenId"] == int(_TOKEN_HEX_UPPER, 16)

    def test_buy_amounts(self, signer):
        """BUY: makerAmount = size * price (USDC wei), takerAmount = size (share wei)."""
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.50, size=10.0, side=SIDE_BUY)
        # size * price = 5.0 USDC → 5_000_000 μUSDC
        assert order["makerAmount"] == 5_000_000
        # size = 10 shares → 10_000_000 μshares
        assert order["takerAmount"] == 10_000_000

    def test_sell_amounts(self, signer):
        """SELL: makerAmount = size (shares), takerAmount = size * price (USDC)."""
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.50, size=10.0, side=SIDE_SELL)
        assert order["makerAmount"] == 10_000_000
        assert order["takerAmount"] == 5_000_000

    def test_required_fields_present(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        for field in ("salt", "maker", "signer", "taker", "tokenId",
                      "makerAmount", "takerAmount", "expiration",
                      "nonce", "feeRateBps", "side", "signatureType"):
            assert field in order, f"Missing field: {field}"

    def test_salt_is_positive_int(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        assert isinstance(order["salt"], int)
        assert order["salt"] > 0

    def test_maker_equals_signer_address(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["maker"] == signer.address
        assert order["signer"] == signer.address

    def test_signature_type_eoa(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["signatureType"] == 0  # EOA


# ── sign_order ────────────────────────────────────────────────────────────────

class TestSignOrder:

    def test_sign_produces_hex_signature(self, signer):
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        sig = signer.sign_order(order)
        # EIP-712 signature is 65 bytes = 130 hex chars (no 0x prefix)
        assert len(sig) == 130
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_with_hex_token_id(self, signer):
        order = signer.build_order(token_id=_TOKEN_HEX, price=0.45, size=10.0, side=SIDE_BUY)
        sig = signer.sign_order(order)
        assert len(sig) == 130

    def test_sign_is_deterministic(self, signer):
        """Same order (same salt) must produce the same signature."""
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        order["salt"] = 12345  # fix salt for determinism
        sig1 = signer.sign_order(order)
        sig2 = signer.sign_order(order)
        assert sig1 == sig2

    def test_sign_neg_risk(self, signer):
        """neg_risk orders use a different contract address in the domain."""
        order = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        order["salt"] = 99999
        sig_normal = signer.sign_order(order, neg_risk=False)
        sig_neg = signer.sign_order(order, neg_risk=True)
        # Different domain → different signature
        assert sig_normal != sig_neg

    def test_sign_different_keys_differ(self):
        """Different private keys must produce different signatures."""
        signer1 = OrderSigner("a" * 64)
        signer2 = OrderSigner("b" * 64)
        order = signer1.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        order["salt"] = 1
        order["maker"] = signer2.address
        order["signer"] = signer2.address
        sig1 = signer1.sign_order(order)
        sig2 = signer2.sign_order(order)
        assert sig1 != sig2

    def test_buy_and_sell_signatures_differ(self, signer):
        order_buy = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        order_sell = signer.build_order(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_SELL)
        order_buy["salt"] = 1
        order_sell["salt"] = 1
        sig_buy = signer.sign_order(order_buy)
        sig_sell = signer.sign_order(order_sell)
        assert sig_buy != sig_sell


# ── build_and_sign ────────────────────────────────────────────────────────────

class TestBuildAndSign:

    def test_round_trip_decimal_token(self, signer):
        order, sig = signer.build_and_sign(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["tokenId"] == int(_TOKEN_DEC)
        assert len(sig) == 130

    def test_round_trip_hex_token(self, signer):
        order, sig = signer.build_and_sign(token_id=_TOKEN_HEX, price=0.45, size=10.0, side=SIDE_BUY)
        assert order["tokenId"] == int(_TOKEN_HEX, 16)
        assert len(sig) == 130

    def test_round_trip_neg_risk(self, signer):
        order, sig = signer.build_and_sign(token_id=_TOKEN_DEC, price=0.50, size=5.0, side=SIDE_SELL, neg_risk=True)
        assert len(sig) == 130

    def test_generate_signed_payload_no_http_call(self, signer):
        """Verify we can generate a complete signed payload without sending it.

        This is the dry-run verification step: the payload should look like
        what the CLOB API expects, minus the HTTP request.
        """
        order, sig = signer.build_and_sign(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)

        # Build the full POST payload as client.py would
        payload = {
            "order": order,
            "signature": sig,
            "owner": signer.address,
            "orderType": "GTC",
        }

        # Validate payload structure
        assert "order" in payload
        assert "signature" in payload
        assert "owner" in payload
        assert "orderType" in payload

        # Validate signature format
        assert isinstance(payload["signature"], str)
        assert len(payload["signature"]) == 130

        # Validate order structure matches CLOB spec
        order_data = payload["order"]
        assert isinstance(order_data["tokenId"], int)
        assert isinstance(order_data["makerAmount"], int)
        assert isinstance(order_data["takerAmount"], int)
        assert isinstance(order_data["salt"], int)
        assert order_data["side"] in (SIDE_BUY, SIDE_SELL)


# ── verify signature recovers signer address ─────────────────────────────────

class TestSignatureVerification:

    def test_recovered_address_matches_signer(self, signer):
        """The signature must recover the signer's address."""
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        order, sig = signer.build_and_sign(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)

        structured = {
            "types": ORDER_TYPES,
            "primaryType": "Order",
            "domain": DOMAIN_DATA,
            "message": order,
        }
        encoded = encode_typed_data(full_message=structured)
        recovered = Account.recover_message(encoded, signature=bytes.fromhex(sig))
        assert recovered.lower() == signer.address.lower()

    def test_recovered_address_differs_with_wrong_key(self, signer):
        """Different key should not recover the same address."""
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        other_signer = OrderSigner("b" * 64)
        order, sig = signer.build_and_sign(token_id=_TOKEN_DEC, price=0.45, size=10.0, side=SIDE_BUY)

        structured = {
            "types": ORDER_TYPES,
            "primaryType": "Order",
            "domain": DOMAIN_DATA,
            "message": order,
        }
        encoded = encode_typed_data(full_message=structured)
        recovered = Account.recover_message(encoded, signature=bytes.fromhex(sig))
        assert recovered.lower() != other_signer.address.lower()
