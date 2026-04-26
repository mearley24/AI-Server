"""AES-256-GCM encryption for the local vault.

Key management
--------------
The 32-byte master key lives at VAULT_KEY_PATH (default ~/.config/bob/vault.key).
It is NEVER stored in the repo, never mounted in Docker containers, and never
logged or printed.

Wire format for encrypted blobs
--------------------------------
  base64url( nonce[12] || aesgcm_ciphertext_with_tag )

AESGCM.encrypt() appends a 16-byte authentication tag to the ciphertext, so
the stored blob is:  12 + len(plaintext) + 16  bytes, base64url-encoded.

Decryption raises cryptography.exceptions.InvalidTag if the data is modified.
"""
from __future__ import annotations

import base64
import hashlib
import os
import stat
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --------------------------------------------------------------------------- #
# Key path resolution
# --------------------------------------------------------------------------- #

_DEFAULT_KEY_PATH = Path.home() / ".config" / "bob" / "vault.key"


def key_path() -> Path:
    env = os.environ.get("VAULT_KEY_PATH")
    return Path(env) if env else _DEFAULT_KEY_PATH


def key_exists() -> bool:
    return key_path().is_file()


def init_key(path: Optional[Path] = None) -> Path:
    """Generate and save a new random 32-byte key.

    Refuses to overwrite an existing key. Sets file permissions to 0600.
    Returns the path where the key was saved.
    """
    p = path or key_path()
    if p.is_file():
        raise FileExistsError(
            f"Vault key already exists at {p}. "
            "Delete it manually only if you want to re-encrypt everything."
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    p.write_bytes(key)
    p.chmod(0o600)
    return p


def load_key(path: Optional[Path] = None) -> bytes:
    """Load the 32-byte key from disk.

    Raises RuntimeError with setup instructions if the key file is missing.
    """
    p = path or key_path()
    if not p.is_file():
        raise RuntimeError(
            f"Vault key not found at {p}.\n"
            "Run:  python3 scripts/vault_set_secret.py --init\n"
            "This generates a new vault key and initialises the vault DB."
        )
    raw = p.read_bytes()
    if len(raw) != 32:
        raise RuntimeError(f"Vault key at {p} has unexpected length {len(raw)} (expected 32).")
    return raw


# --------------------------------------------------------------------------- #
# Encrypt / Decrypt
# --------------------------------------------------------------------------- #

def encrypt(plaintext: str, key: Optional[bytes] = None) -> str:
    """Encrypt plaintext → base64url blob. Key loaded from disk if not provided."""
    k = key if key is not None else load_key()
    aesgcm = AESGCM(k)
    nonce = os.urandom(12)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = nonce + ct_with_tag
    return base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt(blob_b64: str, key: Optional[bytes] = None) -> str:
    """Decrypt base64url blob → plaintext. Raises InvalidTag if tampered."""
    k = key if key is not None else load_key()
    blob = base64.urlsafe_b64decode(blob_b64)
    nonce = blob[:12]
    ct_with_tag = blob[12:]
    aesgcm = AESGCM(k)
    plaintext_bytes = aesgcm.decrypt(nonce, ct_with_tag, None)
    return plaintext_bytes.decode("utf-8")


# --------------------------------------------------------------------------- #
# Fingerprint (integrity, not secrecy)
# --------------------------------------------------------------------------- #

def fingerprint(plaintext: str) -> str:
    """Return the first 16 hex chars of SHA-256(plaintext).

    Used to verify a secret's identity without revealing the full value.
    SHA-256 is used here only for integrity fingerprinting, not for secrecy.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]


def verify_fingerprint(plaintext: str, expected_fp: str) -> bool:
    return fingerprint(plaintext) == expected_fp


_VAULT_REF_PREFIX = "VAULT_REF:"


def resolve_vault_ref(value: str) -> str:
    """If value starts with 'VAULT_REF:<name>', decrypt and return the secret.

    For any other value, return it unchanged.
    Raises RuntimeError if the vault key or secret is missing.
    Never logs or prints the resolved value.
    """
    if not value.startswith(_VAULT_REF_PREFIX):
        return value
    secret_name = value[len(_VAULT_REF_PREFIX):].strip()
    if not secret_name:
        raise RuntimeError("VAULT_REF: secret name is empty")
    from integrations.vault.db import init_db, get_secret_encrypted
    conn = init_db()
    row = get_secret_encrypted(conn, secret_name)
    conn.close()
    if row is None:
        raise RuntimeError(
            f"VAULT_REF: secret '{secret_name}' not found in vault.\n"
            f"Store it with: python3 scripts/vault_set_secret.py --name {secret_name} --category api_key"
        )
    _, enc_value, _ = row
    return decrypt(enc_value)
