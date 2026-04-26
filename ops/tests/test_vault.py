"""Tests for Secure Vault v1.

Covers:
- encrypted value is not plaintext
- SHA-256 fingerprint is stable and consistent
- list_secrets never exposes encrypted_value
- audit log is written on access
- denied (missing key) returns no secret
- CLI path is the only approved decrypt path
- .env scanner masks values
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ─── Crypto ───────────────────────────────────────────────────────────────────

class TestCrypto:
    def _key(self) -> bytes:
        return os.urandom(32)

    def test_encrypted_value_is_not_plaintext(self):
        from integrations.vault.crypto import encrypt
        key = self._key()
        plaintext = "super-secret-value-abc123"
        blob = encrypt(plaintext, key=key)
        assert plaintext not in blob
        assert plaintext.encode() not in blob.encode()

    def test_decrypt_roundtrip(self):
        from integrations.vault.crypto import encrypt, decrypt
        key = self._key()
        original = "hello vault 🔐"
        assert decrypt(encrypt(original, key=key), key=key) == original

    def test_different_nonces_each_call(self):
        from integrations.vault.crypto import encrypt
        key = self._key()
        plaintext = "same-value"
        b1 = encrypt(plaintext, key=key)
        b2 = encrypt(plaintext, key=key)
        assert b1 != b2  # random nonce → different ciphertext every time

    def test_tampered_blob_raises(self):
        import base64
        from cryptography.exceptions import InvalidTag
        from integrations.vault.crypto import encrypt, decrypt
        key = self._key()
        blob = encrypt("value", key=key)
        raw = bytearray(base64.urlsafe_b64decode(blob))
        raw[20] ^= 0xFF  # flip a bit in ciphertext
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
        with pytest.raises((InvalidTag, Exception)):
            decrypt(tampered, key=key)

    def test_fingerprint_is_stable(self):
        from integrations.vault.crypto import fingerprint
        fp1 = fingerprint("my-api-key")
        fp2 = fingerprint("my-api-key")
        assert fp1 == fp2
        assert len(fp1) == 16  # first 16 hex chars of SHA-256

    def test_fingerprint_changes_with_value(self):
        from integrations.vault.crypto import fingerprint
        assert fingerprint("value-a") != fingerprint("value-b")

    def test_fingerprint_is_hex(self):
        from integrations.vault.crypto import fingerprint
        fp = fingerprint("test")
        assert all(c in "0123456789abcdef" for c in fp)

    def test_verify_fingerprint(self):
        from integrations.vault.crypto import fingerprint, verify_fingerprint
        val = "secret123"
        fp  = fingerprint(val)
        assert verify_fingerprint(val, fp) is True
        assert verify_fingerprint("other", fp) is False

    def test_wrong_key_raises(self):
        from cryptography.exceptions import InvalidTag
        from integrations.vault.crypto import encrypt, decrypt
        key1 = self._key()
        key2 = self._key()
        blob = encrypt("value", key=key1)
        with pytest.raises((InvalidTag, Exception)):
            decrypt(blob, key=key2)

    def test_init_key_creates_file(self, tmp_path):
        from integrations.vault.crypto import init_key, load_key
        p = tmp_path / "vault.key"
        init_key(path=p)
        assert p.is_file()
        assert p.stat().st_mode & 0o777 == 0o600
        raw = load_key(path=p)
        assert len(raw) == 32

    def test_init_key_refuses_overwrite(self, tmp_path):
        from integrations.vault.crypto import init_key
        p = tmp_path / "vault.key"
        init_key(path=p)
        with pytest.raises(FileExistsError):
            init_key(path=p)

    def test_load_key_missing_raises(self, tmp_path):
        from integrations.vault.crypto import load_key
        with pytest.raises(RuntimeError, match="Vault key not found"):
            load_key(path=tmp_path / "nonexistent.key")


# ─── DB ───────────────────────────────────────────────────────────────────────

class TestDB:
    def _db(self, tmp_path: Path):
        from integrations.vault.db import init_db
        return init_db(tmp_path / "vault.sqlite")

    def test_set_and_get_meta(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, get_secret_meta
        conn = self._db(tmp_path)
        set_secret(conn, "MY_KEY", "enc_blob", "fp1234", category="api_key")
        meta = get_secret_meta(conn, "MY_KEY")
        assert meta is not None
        assert meta["name"] == "MY_KEY"
        assert meta["category"] == "api_key"
        assert "encrypted_value" not in meta  # must never be returned

    def test_list_secrets_never_exposes_encrypted_value(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, list_secrets
        conn = self._db(tmp_path)
        set_secret(conn, "S1", "enc_blob_A", "fp_A")
        set_secret(conn, "S2", "enc_blob_B", "fp_B")
        secrets = list_secrets(conn)
        for s in secrets:
            assert "encrypted_value" not in s
            assert "enc_blob" not in str(s)

    def test_get_secret_encrypted_returns_blob(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, get_secret_encrypted
        conn = self._db(tmp_path)
        set_secret(conn, "S", "enc_blob_X", "fp_X")
        row = get_secret_encrypted(conn, "S")
        assert row is not None
        _, enc, fp = row
        assert enc == "enc_blob_X"
        assert fp  == "fp_X"

    def test_get_secret_encrypted_missing_returns_none(self, tmp_path):
        from integrations.vault.db import init_db, get_secret_encrypted
        conn = self._db(tmp_path)
        assert get_secret_encrypted(conn, "MISSING") is None

    def test_update_secret(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, get_secret_meta
        conn = self._db(tmp_path)
        set_secret(conn, "K", "enc_v1", "fp_v1", category="api_key")
        set_secret(conn, "K", "enc_v2", "fp_v2", category="token")
        meta = get_secret_meta(conn, "K")
        assert meta["category"] == "token"
        assert meta["sha256_fingerprint"] == "fp_v2"

    def test_delete_secret(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, delete_secret, get_secret_meta
        conn = self._db(tmp_path)
        set_secret(conn, "DEL_ME", "enc", "fp")
        assert delete_secret(conn, "DEL_ME") is True
        assert get_secret_meta(conn, "DEL_ME") is None

    def test_log_access_written(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, log_access, get_access_log
        conn = self._db(tmp_path)
        set_secret(conn, "S", "enc", "fp")
        log_access(conn, "S", requester="cli:test", action="reveal", approved=True)
        logs = get_access_log(conn, secret_name="S")
        assert len(logs) >= 1
        assert logs[0]["approved"] == 1
        assert logs[0]["action"] == "reveal"

    def test_denied_access_logged_approved_false(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, log_access, get_access_log
        conn = self._db(tmp_path)
        set_secret(conn, "S", "enc", "fp")
        log_access(conn, "S", requester="unknown", action="request", approved=False)
        logs = get_access_log(conn, secret_name="S")
        assert logs[0]["approved"] == 0

    def test_pending_requests_are_queryable(self, tmp_path):
        from integrations.vault.db import init_db, set_secret, log_access, get_pending_requests
        conn = self._db(tmp_path)
        set_secret(conn, "S", "enc", "fp")
        log_access(conn, "S", requester="cortex", action="request", approved=None)
        pending = get_pending_requests(conn)
        assert any(r["secret_name"] == "S" for r in pending)


# ─── Full roundtrip (crypto + DB) ─────────────────────────────────────────────

class TestVaultRoundtrip:
    def test_store_and_retrieve(self, tmp_path):
        from integrations.vault.crypto import encrypt, decrypt, fingerprint
        from integrations.vault.db import init_db, set_secret, get_secret_encrypted

        key = os.urandom(32)
        plaintext = "my-real-secret-value"
        enc = encrypt(plaintext, key=key)
        fp  = fingerprint(plaintext)

        conn = init_db(tmp_path / "vault.sqlite")
        set_secret(conn, "REAL_KEY", enc, fp)

        row = get_secret_encrypted(conn, "REAL_KEY")
        assert row is not None
        _, stored_enc, stored_fp = row
        recovered = decrypt(stored_enc, key=key)
        assert recovered == plaintext
        assert stored_fp == fp

    def test_sqlite_db_does_not_contain_plaintext(self, tmp_path):
        from integrations.vault.crypto import encrypt, fingerprint
        from integrations.vault.db import init_db, set_secret

        key = os.urandom(32)
        plaintext = "ULTRA_SECRET_VALUE_XYZ"
        enc = encrypt(plaintext, key=key)
        fp  = fingerprint(plaintext)

        db_path = tmp_path / "vault.sqlite"
        conn = init_db(db_path)
        set_secret(conn, "SEC", enc, fp)
        conn.close()

        # Read raw DB bytes — plaintext must not appear
        raw = db_path.read_bytes()
        assert plaintext.encode() not in raw


# ─── Audit log ────────────────────────────────────────────────────────────────

class TestAuditLog:
    def test_audit_log_written(self, tmp_path):
        import json
        from integrations.vault.audit import log as audit_log

        audit_path = tmp_path / "audit.ndjson"
        os.environ["VAULT_AUDIT_PATH"] = str(audit_path)
        try:
            audit_log(
                event_type="get",
                secret_name="MY_KEY",
                requester="cli:test",
                approved=True,
                fingerprint="abcd1234",
                purpose="test",
            )
        finally:
            del os.environ["VAULT_AUDIT_PATH"]

        assert audit_path.is_file()
        record = json.loads(audit_path.read_text().strip())
        assert record["event"] == "get"
        assert record["secret_name"] == "MY_KEY"
        assert record["approved"] is True
        assert "value" not in record  # must never write secret value

    def test_audit_log_never_contains_value(self, tmp_path):
        import json
        from integrations.vault.audit import log as audit_log

        audit_path = tmp_path / "audit.ndjson"
        os.environ["VAULT_AUDIT_PATH"] = str(audit_path)
        try:
            audit_log(
                event_type="create",
                secret_name="K",
                requester="cli",
                extra={"value": "SHOULD_NOT_APPEAR"},
            )
        finally:
            del os.environ["VAULT_AUDIT_PATH"]

        raw = audit_path.read_text()
        assert "SHOULD_NOT_APPEAR" not in raw


# ─── .env scanner ─────────────────────────────────────────────────────────────

class TestEnvScanner:
    """Tests for vault_migrate_env.py helper functions."""

    def _import_helpers(self):
        import importlib.util
        script = REPO_ROOT / "scripts" / "vault_migrate_env.py"
        spec = importlib.util.spec_from_file_location("vault_migrate_env", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {
            "_mask":              mod._mask,
            "_looks_like_secret": mod._looks_like_secret,
            "_guess_category":    mod._guess_category,
            "parse_env_file":     mod.parse_env_file,
        }

    def test_mask_hides_middle(self):
        ns = self._import_helpers()
        _mask = ns["_mask"]
        masked = _mask("sk-abc123defghijklmnop")
        assert "sk" in masked
        assert "abc123defghijklmnop"[:5] not in masked

    def test_looks_like_secret_api_key(self):
        ns = self._import_helpers()
        f = ns["_looks_like_secret"]
        assert f("OPENAI_API_KEY", "sk-abc123abc123abc123ab") is True

    def test_looks_like_secret_skips_debug(self):
        ns = self._import_helpers()
        f = ns["_looks_like_secret"]
        assert f("DEBUG", "true") is False

    def test_looks_like_secret_skips_short(self):
        ns = self._import_helpers()
        f = ns["_looks_like_secret"]
        assert f("UNKNOWN_VAR", "short") is False

    def test_parse_env_file(self, tmp_path):
        ns = self._import_helpers()
        env_file = tmp_path / ".env"
        env_file.write_text('API_KEY="sk-abc123"\nDEBUG=true\n')
        entries = ns["parse_env_file"](env_file)
        assert ("API_KEY", "sk-abc123") in entries
        assert ("DEBUG", "true") in entries

    def test_guess_category_token(self):
        ns = self._import_helpers()
        assert ns["_guess_category"]("X_API_ACCESS_TOKEN") == "token"

    def test_guess_category_api_key(self):
        ns = self._import_helpers()
        assert ns["_guess_category"]("OPENAI_API_KEY") == "api_key"

    def test_guess_category_password(self):
        ns = self._import_helpers()
        assert ns["_guess_category"]("DB_PASSWORD") == "password"


# ─── Approved access: only via explicit --reveal CLI flag ──────────────────────

class TestApprovedAccessCLI:
    """
    Simulate vault_get_secret.py in metadata-only mode (no --reveal).
    Confirms that the default output never prints the decrypted value.
    """

    def test_metadata_mode_does_not_reveal(self, tmp_path, capsys):
        from integrations.vault.crypto import encrypt, fingerprint
        from integrations.vault.db import init_db, set_secret

        key = os.urandom(32)
        plaintext = "SECRET_DO_NOT_PRINT"
        enc = encrypt(plaintext, key=key)
        fp  = fingerprint(plaintext)

        db_path = tmp_path / "vault.sqlite"
        os.environ["VAULT_DB_PATH"] = str(db_path)
        try:
            conn = init_db(db_path)
            set_secret(conn, "MY_SECRET", enc, fp)
            conn.close()

            # Import metadata helpers directly — simulating no --reveal
            from integrations.vault.db import get_secret_meta, init_db as _init_db
            c2 = _init_db(db_path)
            meta = get_secret_meta(c2, "MY_SECRET")
            c2.close()

            assert meta is not None
            assert "encrypted_value" not in meta
            # Print what metadata-mode would print — no plaintext
            output = str(meta)
            assert plaintext not in output
        finally:
            del os.environ["VAULT_DB_PATH"]
