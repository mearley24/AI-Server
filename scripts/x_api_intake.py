#!/usr/bin/env python3
"""X API Intake CLI — read-only fetch from Matt's X account.

Usage:
  python3 scripts/x_api_intake.py --dry-run [--limit 25]
  python3 scripts/x_api_intake.py --apply  [--limit 25]

Flags:
  --dry-run      Fetch and preview without writing to DB (default)
  --apply        Fetch and write to DB
  --limit N      Max items per endpoint (default: 25)
  --bookmarks    Also fetch bookmarks (requires OAuth user auth + Basic plan)
  --posts-only   Only fetch own posts
  --likes-only   Only fetch liked tweets

Environment (add to .env):
  X_API_BEARER_TOKEN   Bearer token from developer.x.com
  X_API_CLIENT_ID      OAuth 2.0 client ID (for bookmarks)
  X_API_CLIENT_SECRET  OAuth 2.0 client secret
  X_API_ACCESS_TOKEN   OAuth 1.0a access token
  X_API_REFRESH_TOKEN  OAuth 1.0a access token secret
  X_USER_ID            Matt's numeric X user ID
  X_DAILY_READ_LIMIT   Max API requests per day (default: 100)
  X_ENABLED            Set to 1 to enable (default: 0)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Repo root on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Load .env if present
_env_file = REPO_ROOT / ".env"
if _env_file.is_file():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# Resolve VAULT_REF values for X API secrets
_X_API_VAULT_KEYS = (
    "X_API_BEARER_TOKEN",
    "X_API_CLIENT_ID",
    "X_API_CLIENT_SECRET",
    "X_API_ACCESS_TOKEN",
    "X_API_REFRESH_TOKEN",
)
for _k in _X_API_VAULT_KEYS:
    _v = os.environ.get(_k, "")
    if _v.startswith("VAULT_REF:"):
        try:
            from integrations.vault.crypto import resolve_vault_ref
            os.environ[_k] = resolve_vault_ref(_v)
        except RuntimeError as _e:
            print(f"Warning: could not resolve {_k} from vault — {_e}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="X API read-only intake",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default mode: posts-only when only Bearer Token is configured.\n"
            "Likes and bookmarks require OAuth user-context credentials."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run",  action="store_true", default=True,
                      help="Preview without writing (default)")
    mode.add_argument("--apply",    action="store_true",
                      help="Fetch and write to DB")
    parser.add_argument("--limit",     type=int, default=25,
                        help="Max items per endpoint (default: 25)")
    parser.add_argument("--bookmarks", action="store_true",
                        help="Also fetch bookmarks (requires OAuth + Basic plan)")

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--posts-only", action="store_true",
                              help="Only fetch own posts (bearer-token safe)")
    source_group.add_argument("--likes-only", action="store_true",
                              help="Only fetch liked tweets (requires OAuth user-context)")
    source_group.add_argument("--no-likes", action="store_true",
                              help="Fetch posts only, skip likes (same as --posts-only)")
    args = parser.parse_args()

    dry_run = not args.apply

    from integrations.x_api.client import XCredentials
    creds = XCredentials.from_env()

    # Determine what to fetch
    if args.likes_only:
        fetch_posts = False
        fetch_likes = True
        likes_explicitly_requested = True
    elif args.posts_only or args.no_likes:
        fetch_posts = True
        fetch_likes = False
        likes_explicitly_requested = False
    else:
        # Default: posts always; likes only if OAuth user-context is configured.
        # This prevents avoidable 403s when only a Bearer Token is present.
        fetch_posts = True
        fetch_likes = creds.has_user_auth()
        likes_explicitly_requested = False

    fetch_bookmarks = args.bookmarks

    from integrations.x_api.intake import run_intake

    mode_label = "likes-only" if args.likes_only else ("posts+likes" if fetch_likes else "posts-only")
    print(f"X API Intake — {'DRY RUN' if dry_run else 'APPLY'}  [{mode_label}]")
    print(f"  limit={args.limit}  posts={fetch_posts}  likes={fetch_likes}  bookmarks={fetch_bookmarks}")
    print()

    result = run_intake(
        limit=args.limit,
        dry_run=dry_run,
        fetch_posts=fetch_posts,
        fetch_likes=fetch_likes,
        fetch_bookmarks=fetch_bookmarks,
        likes_explicitly_requested=likes_explicitly_requested,
    )

    print(json.dumps(result, indent=2))

    if result["status"] == "missing_credentials":
        print("\n" + result["message"], file=sys.stderr)
        return 1
    if result["status"] == "disabled":
        print("\nHint: set X_ENABLED=1 in .env to enable.", file=sys.stderr)
        return 0
    for note in result.get("skipped_auth", []):
        print(f"  note: {note}", file=sys.stderr)
    if result["errors"]:
        print(f"\n{len(result['errors'])} error(s):", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
