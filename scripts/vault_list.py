#!/usr/bin/env python3
"""Vault CLI — list stored secrets (metadata only, no values).

Usage:
  python3 scripts/vault_list.py
  python3 scripts/vault_list.py --category api_key
  python3 scripts/vault_list.py --json
"""
from __future__ import annotations

import argparse
import json
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

from integrations.vault.db import init_db, list_secrets


def main() -> int:
    parser = argparse.ArgumentParser(description="Vault — list secrets (metadata only)")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    args = parser.parse_args()

    conn = init_db()
    secrets = list_secrets(conn)
    conn.close()

    if args.category:
        secrets = [s for s in secrets if s["category"] == args.category]

    # Strip encrypted_value just in case (db.list_secrets never returns it, but belt+suspenders)
    safe = []
    for s in secrets:
        safe.append({
            "name":             s["name"],
            "category":         s["category"],
            "access_policy":    s["access_policy"],
            "sha256_fingerprint": s["sha256_fingerprint"],
            "created_at":       s["created_at"],
            "updated_at":       s["updated_at"],
            "last_accessed_at": s["last_accessed_at"],
            "notes":            s.get("notes"),
        })

    if args.as_json:
        print(json.dumps(safe, indent=2))
        return 0

    if not safe:
        print("No secrets found.")
        return 0

    col_name = max(len(s["name"]) for s in safe)
    col_cat  = max(len(s["category"]) for s in safe)
    fmt = f"{{:<{col_name}}}  {{:<{col_cat}}}  {{:<16}}  {{}}"
    print(fmt.format("NAME", "CATEGORY", "FINGERPRINT", "LAST ACCESSED"))
    print("-" * (col_name + col_cat + 40))
    for s in safe:
        print(fmt.format(
            s["name"],
            s["category"],
            s["sha256_fingerprint"],
            s["last_accessed_at"] or "never",
        ))

    print(f"\n{len(safe)} secret(s) total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
