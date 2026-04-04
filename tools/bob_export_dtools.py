#!/usr/bin/env python3
"""
Export D-Tools project data for SOW/proposal generation.
Defaults ambiguous categories to Control4 ecosystem.

Usage (from host):
  python3 tools/bob_export_dtools.py --search "Smith"
  python3 tools/bob_export_dtools.py --pipeline
"""

import argparse
import json
import os
import sys

import httpx

DTOOLS_BASE = os.environ.get("DTOOLS_API_URL", "http://127.0.0.1:8096")
CONTROL4_FALLBACK_KEYWORDS = ("generic", "unknown", "tbd", "unspecified", "")


def _get(path: str, params: dict | None = None) -> dict:
    resp = httpx.get(f"{DTOOLS_BASE}{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def apply_control4_fallback(items: list[dict]) -> list[dict]:
    """Default ambiguous manufacturers to Control4."""
    for item in items:
        mfr = (item.get("manufacturer") or "").lower().strip()
        if mfr in CONTROL4_FALLBACK_KEYWORDS:
            item["manufacturer"] = "Control4"
            item["_fallback_applied"] = True
    return items


def search_before_create(client_name: str) -> dict:
    """Search D-Tools for existing client/project to avoid duplicates."""
    clients = _get("/clients")
    pipeline = _get("/pipeline")
    matching = [
        c
        for c in (clients if isinstance(clients, list) else clients.get("data", []))
        if client_name.lower() in json.dumps(c).lower()
    ]
    return {"matching_clients": matching, "pipeline": pipeline}


def show_pipeline() -> None:
    data = _get("/pipeline")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="D-Tools export helper")
    parser.add_argument("--search", help="Search for client/project before creating")
    parser.add_argument("--pipeline", action="store_true", help="Show active pipeline")
    args = parser.parse_args()

    if args.search:
        result = search_before_create(args.search)
        print(json.dumps(result, indent=2))
    elif args.pipeline:
        show_pipeline()
    else:
        parser.print_help()
        sys.exit(1)
