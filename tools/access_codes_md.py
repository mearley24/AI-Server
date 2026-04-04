#!/usr/bin/env python3
"""Parse access_codes.md files written by integrations/apple_notes/notes_indexer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_access_codes_md(path: Path) -> list[dict[str, Any]]:
    """
    Read a markdown table with columns System | Credential | Value | Notes.

    Returns a list of dicts with keys system, credential, value, notes.
    """
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        low = "|".join(cells).lower()
        if "system" in low and "credential" in low and "value" in low:
            in_table = True
            continue
        if re.match(r"^[\|\s\-:]+$", line):
            continue
        if not in_table:
            continue
        while len(cells) < 4:
            cells.append("")
        rows.append(
            {
                "system": cells[0],
                "credential": cells[1],
                "value": cells[2],
                "notes": cells[3],
            }
        )
    return rows
