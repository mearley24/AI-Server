"""Encrypted credential vault — PBKDF2 + Fernet (AES-128-CBC).

Encrypts all sensitive environment variables at rest. The bot loads credentials
from the vault at startup instead of reading plaintext .env files.

CLI usage:
    python -m src.security.vault init     # Interactive vault creation
    python -m src.security.vault rotate   # Re-encrypt with new passphrase
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = structlog.get_logger(__name__)

# Keys that the vault encrypts
VAULT_KEYS = [
    "POLY_PRIVATE_KEY",
    "POLY_BUILDER_API_KEY",
    "POLY_BUILDER_API_SECRET",
    "POLY_BUILDER_API_PASSPHRASE",
    "ANTHROPIC_API_KEY",
    "ACCUWEATHER_API_KEY",
]

DEFAULT_VAULT_PATH = Path.home() / ".polymarket-bot" / "vault.enc"
PBKDF2_ITERATIONS = 600_000
SALT_SIZE = 16


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a passphrase via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def _mask_value(value: str) -> str:
    """Mask a secret for logging — show first 4 and last 4 chars only."""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


class CredentialVault:
    """Encrypted credential vault backed by a Fernet-encrypted JSON file.

    On first run the user provides a passphrase which is used (via PBKDF2
    with 600 000 iterations) to derive a Fernet key.  All sensitive env
    vars are encrypted and stored in a single file with 0600 permissions.
    """

    def __init__(self, vault_path: str | Path | None = None) -> None:
        self._vault_path = Path(vault_path) if vault_path else DEFAULT_VAULT_PATH
        self._credentials: dict[str, str] = {}
        self._fernet: Fernet | None = None

    @property
    def vault_path(self) -> Path:
        return self._vault_path

    @property
    def is_initialized(self) -> bool:
        return self._vault_path.exists()

    def initialize(self, passphrase: str, credentials: dict[str, str] | None = None) -> None:
        """Create a new vault with the given passphrase.

        If credentials are not provided, reads them from the current
        environment variables.
        """
        if credentials is None:
            credentials = {}
            for key in VAULT_KEYS:
                val = os.environ.get(key, "")
                if val:
                    credentials[key] = val

        if not credentials:
            logger.warning("vault_no_credentials", msg="No credentials found to encrypt")

        salt = os.urandom(SALT_SIZE)
        derived = _derive_key(passphrase, salt)
        fernet = Fernet(derived)

        # Encrypt the credential payload
        payload = json.dumps(credentials).encode("utf-8")
        encrypted = fernet.encrypt(payload)

        # Write vault file: salt (16 bytes) + encrypted blob
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        raw = salt + encrypted
        self._vault_path.write_bytes(raw)

        # Set file permissions to 0600 (owner read/write only)
        self._vault_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        self._credentials = credentials
        self._fernet = fernet

        logger.info(
            "vault_initialized",
            path=str(self._vault_path),
            keys=list(credentials.keys()),
        )

    def unlock(self, passphrase: str) -> dict[str, str]:
        """Decrypt and return credentials from the vault."""
        if not self._vault_path.exists():
            raise FileNotFoundError(f"Vault not found: {self._vault_path}")

        raw = self._vault_path.read_bytes()
        if len(raw) < SALT_SIZE + 1:
            raise ValueError("Vault file is corrupted (too small)")

        salt = raw[:SALT_SIZE]
        encrypted = raw[SALT_SIZE:]

        derived = _derive_key(passphrase, salt)
        fernet = Fernet(derived)

        try:
            decrypted = fernet.decrypt(encrypted)
        except InvalidToken:
            raise ValueError("Invalid passphrase — cannot decrypt vault")

        self._credentials = json.loads(decrypted.decode("utf-8"))
        self._fernet = fernet

        logger.info(
            "vault_unlocked",
            path=str(self._vault_path),
            keys=[_mask_value(k) for k in self._credentials.keys()],
        )
        return dict(self._credentials)

    def get(self, key: str) -> str:
        """Get a single credential by key. Returns empty string if not found."""
        return self._credentials.get(key, "")

    def inject_into_env(self) -> None:
        """Inject decrypted credentials into os.environ (for Pydantic Settings).

        This is the primary way the bot consumes vault credentials — call
        this before ``load_settings()`` so that Pydantic picks them up via
        its env-var reader.

        Credentials are NEVER logged or printed in plaintext.
        """
        for key, value in self._credentials.items():
            os.environ[key] = value
            logger.debug("vault_env_injected", key=key, masked=_mask_value(value))

    def rotate(self, old_passphrase: str, new_passphrase: str) -> None:
        """Re-encrypt the vault with a new passphrase."""
        credentials = self.unlock(old_passphrase)
        self.initialize(new_passphrase, credentials)
        logger.info("vault_rotated", path=str(self._vault_path))

    def add_credential(self, key: str, value: str, passphrase: str) -> None:
        """Add or update a single credential in the vault."""
        if self.is_initialized:
            self.unlock(passphrase)
        self._credentials[key] = value
        self.initialize(passphrase, self._credentials)

    def list_keys(self) -> list[str]:
        """Return the names of stored credentials (not the values)."""
        return list(self._credentials.keys())


# ── CLI entry point ─────────────────────────────────────────────────────────

def _cli_init() -> None:
    """Interactive vault initialization."""
    vault = CredentialVault()
    if vault.is_initialized:
        confirm = input(f"Vault already exists at {vault.vault_path}. Overwrite? [y/N]: ")
        if confirm.lower() != "y":
            print("Aborted.")
            return

    passphrase = getpass.getpass("Enter vault passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        print("Passphrases do not match.")
        sys.exit(1)

    if not passphrase:
        print("Passphrase cannot be empty.")
        sys.exit(1)

    # Collect credentials from env or prompt
    credentials: dict[str, str] = {}
    for key in VAULT_KEYS:
        env_val = os.environ.get(key, "")
        if env_val:
            credentials[key] = env_val
            print(f"  {key}: loaded from environment")
        else:
            val = getpass.getpass(f"  {key} (press Enter to skip): ")
            if val:
                credentials[key] = val

    vault.initialize(passphrase, credentials)
    print(f"\nVault created at {vault.vault_path}")
    print(f"Encrypted {len(credentials)} credential(s).")
    print("You can now remove plaintext secrets from .env")


def _cli_rotate() -> None:
    """Interactive passphrase rotation."""
    vault = CredentialVault()
    if not vault.is_initialized:
        print("No vault found. Run 'init' first.")
        sys.exit(1)

    old = getpass.getpass("Current passphrase: ")
    new = getpass.getpass("New passphrase: ")
    confirm = getpass.getpass("Confirm new passphrase: ")
    if new != confirm:
        print("Passphrases do not match.")
        sys.exit(1)

    vault.rotate(old, new)
    print("Vault passphrase rotated successfully.")


if __name__ == "__main__":
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    if len(sys.argv) < 2:
        print("Usage: python -m src.security.vault [init|rotate]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "init":
        _cli_init()
    elif cmd == "rotate":
        _cli_rotate()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m src.security.vault [init|rotate]")
        sys.exit(1)
