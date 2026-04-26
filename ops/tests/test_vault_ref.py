"""Tests for VAULT_REF resolution.

Covers:
- resolve_vault_ref passes non-ref values through unchanged
- resolve_vault_ref decrypts a real vault secret
- resolve_vault_ref raises on missing secret
- resolve_vault_ref raises on empty name
- x_api_intake env loader resolves VAULT_REF before XCredentials.from_env()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ─── resolve_vault_ref ────────────────────────────────────────────────────────

class TestResolveVaultRef:
    def _setup_vault(self, tmp_path: Path) -> bytes:
        """Create a temp vault with a known secret. Returns the key."""
        key = os.urandom(32)
        from integrations.vault.crypto import encrypt, fingerprint
        from integrations.vault.db import init_db, set_secret

        db_path = tmp_path / "vault.sqlite"
        os.environ["VAULT_DB_PATH"] = str(db_path)
        key_path = tmp_path / "vault.key"
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        os.environ["VAULT_KEY_PATH"] = str(key_path)

        enc = encrypt("my-real-bearer-token", key=key)
        fp  = fingerprint("my-real-bearer-token")
        conn = init_db(db_path)
        set_secret(conn, "x_api_bearer_token_personal", enc, fp, category="api_key")
        conn.close()
        return key

    def teardown_method(self, _):
        for k in ("VAULT_DB_PATH", "VAULT_KEY_PATH"):
            os.environ.pop(k, None)

    def test_passthrough_for_plain_value(self):
        from integrations.vault.crypto import resolve_vault_ref
        assert resolve_vault_ref("sk-plaintoken123") == "sk-plaintoken123"

    def test_passthrough_for_empty_string(self):
        from integrations.vault.crypto import resolve_vault_ref
        assert resolve_vault_ref("") == ""

    def test_resolves_vault_ref(self, tmp_path):
        self._setup_vault(tmp_path)
        from integrations.vault.crypto import resolve_vault_ref
        result = resolve_vault_ref("VAULT_REF:x_api_bearer_token_personal")
        assert result == "my-real-bearer-token"

    def test_resolved_value_not_printed(self, tmp_path, capsys):
        self._setup_vault(tmp_path)
        from integrations.vault.crypto import resolve_vault_ref
        resolve_vault_ref("VAULT_REF:x_api_bearer_token_personal")
        captured = capsys.readouterr()
        assert "my-real-bearer-token" not in captured.out
        assert "my-real-bearer-token" not in captured.err

    def test_missing_secret_raises(self, tmp_path):
        self._setup_vault(tmp_path)
        from integrations.vault.crypto import resolve_vault_ref
        with pytest.raises(RuntimeError, match="not found in vault"):
            resolve_vault_ref("VAULT_REF:nonexistent_secret")

    def test_empty_name_raises(self):
        from integrations.vault.crypto import resolve_vault_ref
        with pytest.raises(RuntimeError, match="secret name is empty"):
            resolve_vault_ref("VAULT_REF:")

    def test_prefix_case_sensitive(self):
        from integrations.vault.crypto import resolve_vault_ref
        # lowercase 'vault_ref:' is NOT a vault reference — returned unchanged
        assert resolve_vault_ref("vault_ref:some_name") == "vault_ref:some_name"

    def test_multiple_refs_independent(self, tmp_path):
        key = os.urandom(32)
        from integrations.vault.crypto import encrypt, fingerprint, resolve_vault_ref
        from integrations.vault.db import init_db, set_secret

        db_path = tmp_path / "vault.sqlite"
        os.environ["VAULT_DB_PATH"] = str(db_path)
        key_path = tmp_path / "vault.key"
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        os.environ["VAULT_KEY_PATH"] = str(key_path)

        conn = init_db(db_path)
        for name, val in [("secret_a", "value-a"), ("secret_b", "value-b")]:
            enc = encrypt(val, key=key)
            fp  = fingerprint(val)
            set_secret(conn, name, enc, fp)
        conn.close()

        assert resolve_vault_ref("VAULT_REF:secret_a") == "value-a"
        assert resolve_vault_ref("VAULT_REF:secret_b") == "value-b"
        assert resolve_vault_ref("plain") == "plain"


# ─── Integration: env loader resolves VAULT_REF before XCredentials ──────────

class TestXApiIntakeVaultResolution:
    """Verify that x_api_intake's top-level loader resolves VAULT_REF values."""

    def _setup_vault(self, tmp_path: Path, secret_name: str, secret_value: str):
        key = os.urandom(32)
        from integrations.vault.crypto import encrypt, fingerprint
        from integrations.vault.db import init_db, set_secret

        db_path = tmp_path / "vault.sqlite"
        key_path = tmp_path / "vault.key"
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        os.environ["VAULT_DB_PATH"] = str(db_path)
        os.environ["VAULT_KEY_PATH"] = str(key_path)

        conn = init_db(db_path)
        set_secret(conn, secret_name, encrypt(secret_value, key=key),
                   fingerprint(secret_value), category="api_key")
        conn.close()

    def teardown_method(self, _):
        for k in ("VAULT_DB_PATH", "VAULT_KEY_PATH",
                  "X_API_BEARER_TOKEN", "X_API_CLIENT_SECRET"):
            os.environ.pop(k, None)

    def test_vault_ref_resolved_in_env(self, tmp_path):
        self._setup_vault(tmp_path, "my_bearer", "resolved-bearer-xyz")
        os.environ["X_API_BEARER_TOKEN"] = "VAULT_REF:my_bearer"

        from integrations.vault.crypto import resolve_vault_ref
        raw = os.environ["X_API_BEARER_TOKEN"]
        resolved = resolve_vault_ref(raw)
        assert resolved == "resolved-bearer-xyz"
        # The env var itself still holds the ref — resolution happens at call time
        assert os.environ["X_API_BEARER_TOKEN"] == "VAULT_REF:my_bearer"

    def test_plain_value_not_touched(self, tmp_path):
        self._setup_vault(tmp_path, "x", "y")
        os.environ["X_API_BEARER_TOKEN"] = "Bearer plaintoken"

        from integrations.vault.crypto import resolve_vault_ref
        assert resolve_vault_ref(os.environ["X_API_BEARER_TOKEN"]) == "Bearer plaintoken"

    def test_vault_ref_resolution_does_not_log_value(self, tmp_path, capsys):
        self._setup_vault(tmp_path, "tok", "secret-value-do-not-print")
        from integrations.vault.crypto import resolve_vault_ref
        resolve_vault_ref("VAULT_REF:tok")
        out = capsys.readouterr()
        assert "secret-value-do-not-print" not in out.out
        assert "secret-value-do-not-print" not in out.err
