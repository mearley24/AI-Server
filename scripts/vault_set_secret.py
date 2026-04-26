#!/usr/bin/env python3
"""Vault CLI — add or update a secret.

Usage:
  python3 scripts/vault_set_secret.py --init
      Generate vault key + initialise DB (run once).

  python3 scripts/vault_set_secret.py --name MY_SECRET --category api_key
      Prompt for value (no echo), encrypt, store.

  python3 scripts/vault_set_secret.py --name MY_SECRET --value "..." --category api_key
      Set value non-interactively (avoid: shell history may capture it).

Options:
  --name      Secret name (required)
  --category  Category: api_key | token | password | credential | config | general
  --policy    Risk policy: low_risk | medium_risk | high_risk (default: medium_risk)
  --notes     Human-readable notes (no secret values)
  --value     Value (prefer interactive prompt — this may appear in shell history)
  --init      Generate vault key + init DB and exit
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import os
_env = REPO_ROOT / ".env"
if _env.is_file():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from integrations.vault.crypto import init_key, key_exists, key_path, encrypt, fingerprint
from integrations.vault.db import init_db, get_db_path, set_secret, get_secret_meta
from integrations.vault.audit import log as audit_log

VALID_CATEGORIES = {"api_key", "token", "password", "credential", "config", "general"}
VALID_POLICIES   = {"low_risk", "medium_risk", "high_risk"}


def cmd_init() -> int:
    if key_exists():
        print(f"✓ Vault key already exists: {key_path()}")
    else:
        p = init_key()
        print(f"✓ Vault key generated: {p}  (mode 0600)")

    db_path = get_db_path()
    conn = init_db(db_path)
    conn.close()
    print(f"✓ Vault DB initialised: {db_path}")
    print()
    print("Next steps:")
    print("  python3 scripts/vault_list.py")
    print("  python3 scripts/vault_set_secret.py --name MY_API_KEY --category api_key")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Vault — set/update a secret")
    parser.add_argument("--init",     action="store_true", help="Generate key + init DB")
    parser.add_argument("--name",     help="Secret name")
    parser.add_argument("--category", default="general",
                        choices=list(VALID_CATEGORIES), help="Category")
    parser.add_argument("--policy",   default="medium_risk",
                        choices=list(VALID_POLICIES), help="Access risk policy")
    parser.add_argument("--notes",    default="", help="Notes (no secret values here)")
    parser.add_argument("--value",    help="Value (prefer interactive prompt)")
    args = parser.parse_args()

    if args.init:
        return cmd_init()

    if not args.name:
        parser.error("--name is required")

    # Get value
    if args.value:
        value = args.value
        print("⚠  Value provided via --value flag. It may appear in shell history.")
    else:
        try:
            value = getpass.getpass(f"Value for '{args.name}' (input hidden): ")
            confirm = getpass.getpass("Confirm value: ")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 1
        if value != confirm:
            print("Error: values do not match.", file=sys.stderr)
            return 1

    if not value:
        print("Error: value cannot be empty.", file=sys.stderr)
        return 1

    # Encrypt + store
    try:
        enc = encrypt(value)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    fp = fingerprint(value)
    conn = init_db()
    existing = get_secret_meta(conn, args.name)
    action = "update" if existing else "create"

    set_secret(
        conn,
        name=args.name,
        encrypted_value=enc,
        sha256_fingerprint=fp,
        category=args.category,
        access_policy=args.policy,
        notes=args.notes or None,
    )
    conn.close()

    audit_log(
        event_type=action,
        secret_name=args.name,
        requester="cli:vault_set_secret",
        fingerprint=fp,
        purpose=f"category={args.category} policy={args.policy}",
    )

    print(f"✓ Secret '{args.name}' {action}d.")
    print(f"  Category:    {args.category}")
    print(f"  Policy:      {args.policy}")
    print(f"  Fingerprint: {fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
