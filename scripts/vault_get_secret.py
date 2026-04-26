#!/usr/bin/env python3
"""Vault CLI — retrieve a secret.

Usage:
  python3 scripts/vault_get_secret.py --name MY_SECRET --reveal
      Decrypt and print the value.

  python3 scripts/vault_get_secret.py --name MY_SECRET --export-env
      Print: export MY_SECRET="<value>"  (suitable for eval)

  python3 scripts/vault_get_secret.py --name MY_SECRET
      Show metadata only (no value printed — default safe mode).

Options:
  --name        Secret name (required)
  --reveal      Print the decrypted value to stdout
  --export-env  Print as shell export statement
"""
from __future__ import annotations

import argparse
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

from integrations.vault.crypto import decrypt, verify_fingerprint
from integrations.vault.db import init_db, get_secret_encrypted, get_secret_meta, log_access
from integrations.vault.audit import log as audit_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Vault — retrieve a secret")
    parser.add_argument("--name",       required=True, help="Secret name")
    parser.add_argument("--reveal",     action="store_true", help="Print decrypted value")
    parser.add_argument("--export-env", action="store_true", dest="export_env",
                        help="Print as shell export (implies --reveal)")
    args = parser.parse_args()

    conn = init_db()

    if not args.reveal and not args.export_env:
        # Safe mode: metadata only
        meta = get_secret_meta(conn, args.name)
        conn.close()
        if not meta:
            print(f"Error: secret '{args.name}' not found.", file=sys.stderr)
            return 1
        print(f"Name:         {meta['name']}")
        print(f"Category:     {meta['category']}")
        print(f"Policy:       {meta['access_policy']}")
        print(f"Fingerprint:  {meta['sha256_fingerprint']}")
        print(f"Created:      {meta['created_at']}")
        print(f"Updated:      {meta['updated_at']}")
        print(f"Last access:  {meta['last_accessed_at'] or 'never'}")
        if meta.get("notes"):
            print(f"Notes:        {meta['notes']}")
        print()
        print("(Use --reveal or --export-env to access the value.)")
        return 0

    # Decrypt path
    row = get_secret_encrypted(conn, args.name)
    if not row:
        conn.close()
        print(f"Error: secret '{args.name}' not found.", file=sys.stderr)
        audit_log(
            event_type="get_failed",
            secret_name=args.name,
            requester="cli:vault_get_secret",
            purpose="not_found",
        )
        return 1

    secret_id, enc_value, stored_fp = row

    try:
        plaintext = decrypt(enc_value)
    except Exception as e:
        conn.close()
        print(f"Error: decryption failed — {e}", file=sys.stderr)
        audit_log(
            event_type="decrypt_failed",
            secret_name=args.name,
            requester="cli:vault_get_secret",
        )
        return 1

    if not verify_fingerprint(plaintext, stored_fp):
        conn.close()
        print("Error: fingerprint mismatch — vault entry may be corrupted.", file=sys.stderr)
        return 1

    log_access(
        conn,
        secret_name=args.name,
        requester="cli:vault_get_secret",
        action="reveal" if args.reveal else "export_env",
        approved=True,
        fingerprint=stored_fp,
    )
    conn.close()

    audit_log(
        event_type="get",
        secret_name=args.name,
        requester="cli:vault_get_secret",
        approved=True,
        fingerprint=stored_fp,
        purpose="reveal" if args.reveal else "export_env",
    )

    if args.export_env:
        safe_name = args.name.replace("-", "_").upper()
        print(f'export {safe_name}="{plaintext}"')
    else:
        print(plaintext)

    return 0


if __name__ == "__main__":
    sys.exit(main())
