#!/usr/bin/env python3
"""Vault CLI — scan .env and propose vault migration (dry-run only).

Never writes to the vault automatically. Shows what WOULD be migrated.
Run with --apply to actually store each value interactively.

Usage:
  python3 scripts/vault_migrate_env.py              # dry-run: show proposals
  python3 scripts/vault_migrate_env.py --apply      # store each secret interactively
  python3 scripts/vault_migrate_env.py --env .env.local
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import os
_env_bootstrap = REPO_ROOT / ".env"
if _env_bootstrap.is_file():
    for line in _env_bootstrap.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from integrations.vault.crypto import encrypt, fingerprint
from integrations.vault.db import init_db, set_secret, get_secret_meta
from integrations.vault.audit import log as audit_log

# Keys that look like real secrets (not config values)
_SECRET_HINTS = {
    "key", "secret", "token", "password", "passwd", "pass", "api_key",
    "apikey", "credential", "auth", "bearer", "private", "access",
}

# Keys that are definitely NOT secrets (skip them)
_CONFIG_SKIP = {
    "debug", "env", "environment", "port", "host", "log_level",
    "log_format", "tz", "timezone", "node_env", "python_path",
    "pythonpath", "path",
}


def _guess_category(key: str) -> str:
    kl = key.lower()
    if any(h in kl for h in ("token", "bearer", "access_token", "refresh_token")):
        return "token"
    if any(h in kl for h in ("api_key", "apikey")):
        return "api_key"
    if any(h in kl for h in ("password", "passwd", "pass")):
        return "password"
    if any(h in kl for h in ("secret", "private")):
        return "credential"
    return "general"


def _looks_like_secret(key: str, value: str) -> bool:
    kl = key.lower()
    if any(skip in kl for skip in _CONFIG_SKIP):
        return False
    if any(hint in kl for hint in _SECRET_HINTS):
        return True
    # Long random-looking values
    if len(value) >= 20 and not value.startswith("http") and " " not in value:
        return True
    return False


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def parse_env_file(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        entries.append((k, v))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Vault — propose .env migration")
    parser.add_argument("--env",   default=".env", help=".env file path (relative to repo root)")
    parser.add_argument("--apply", action="store_true", help="Store secrets interactively")
    args = parser.parse_args()

    env_path = REPO_ROOT / args.env
    if not env_path.is_file():
        print(f"Error: {env_path} not found.", file=sys.stderr)
        return 1

    entries = parse_env_file(env_path)
    candidates = [(k, v) for k, v in entries if _looks_like_secret(k, v)]

    if not candidates:
        print("No secret-like entries found in .env.")
        return 0

    conn = init_db()

    print(f"{'DRY RUN' if not args.apply else 'APPLY MODE'}: scanning {env_path.name}")
    print(f"Found {len(candidates)} candidate secret(s):\n")
    print(f"  {'KEY':<40}  {'MASKED VALUE':<20}  {'CATEGORY':<12}  STATUS")
    print("  " + "-" * 85)

    for key, value in candidates:
        cat = _guess_category(key)
        existing = get_secret_meta(conn, key)
        status = "already in vault" if existing else "new"
        print(f"  {key:<40}  {_mask(value):<20}  {cat:<12}  {status}")

    print()

    if not args.apply:
        print("Run with --apply to store these secrets interactively.")
        conn.close()
        return 0

    # Apply mode: prompt for each new secret
    stored = 0
    skipped = 0
    for key, env_value in candidates:
        existing = get_secret_meta(conn, key)
        if existing:
            print(f"  SKIP {key} (already in vault, fingerprint: {existing['sha256_fingerprint']})")
            skipped += 1
            continue

        print(f"\nStore '{key}' ({_guess_category(key)})?")
        print(f"  Env value (masked): {_mask(env_value)}")
        print("  Options: [y] use env value  [n] skip  [m] enter manually")
        try:
            choice = input("  > ").strip().lower()
        except KeyboardInterrupt:
            print("\nCancelled.")
            conn.close()
            return 1

        if choice == "n":
            print(f"  Skipped.")
            skipped += 1
            continue
        elif choice == "m":
            try:
                value = getpass.getpass(f"  Value for '{key}' (input hidden): ")
                confirm = getpass.getpass("  Confirm: ")
            except KeyboardInterrupt:
                print("\nCancelled.")
                conn.close()
                return 1
            if value != confirm:
                print("  Values do not match — skipping.")
                skipped += 1
                continue
        else:
            value = env_value

        if not value:
            print("  Empty value — skipping.")
            skipped += 1
            continue

        cat = _guess_category(key)
        enc = encrypt(value)
        fp  = fingerprint(value)
        set_secret(conn, name=key, encrypted_value=enc, sha256_fingerprint=fp,
                   category=cat, access_policy="medium_risk")
        audit_log(event_type="create", secret_name=key,
                  requester="cli:vault_migrate_env",
                  fingerprint=fp, purpose=f"migrated from {env_path.name}")
        print(f"  ✓ Stored '{key}' (fingerprint: {fp})")
        stored += 1

    conn.close()
    print(f"\nDone. {stored} stored, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
