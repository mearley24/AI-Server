#!/usr/bin/env python3
"""X Insight Extraction CLI — extract structured insights from eligible X items.

Usage:
  python3 scripts/x_insight_extract.py --from-existing [--limit 500] [--si-cards]

Flags:
  --from-existing  Process all eligible items in the local DB (no API calls)
  --limit N        Max eligible items to process (default: 500)
  --si-cards       Write self-improvement card stubs for new insights
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_env_file = REPO_ROOT / ".env"
if _env_file.is_file():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract structured insights from eligible X API items",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--from-existing", action="store_true", required=True,
                        help="Process eligible items from local DB (no API calls)")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max eligible items to process (default: 500)")
    parser.add_argument("--si-cards", action="store_true",
                        help="Write self-improvement card stubs for new insights")
    args = parser.parse_args()

    from integrations.x_api.insight_pipeline import run_insight_extraction
    print("X Insight Extraction — FROM EXISTING ELIGIBLE ITEMS")
    print(f"  limit={args.limit}  si_cards={args.si_cards}")
    print()

    result = run_insight_extraction(
        dry_run=False,
        create_si_cards=args.si_cards,
        limit=args.limit,
    )

    print(json.dumps(result, indent=2))

    if result["errors"]:
        print(f"\n{len(result['errors'])} error(s):", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
