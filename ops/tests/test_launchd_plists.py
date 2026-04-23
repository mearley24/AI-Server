"""
Lint every setup/launchd/*.plist:
  - plutil -lint must exit 0 (Darwin only; falls back to xml.etree on Linux)
  - Each plist must contain a <key>Label</key> followed by a non-empty <string>
"""
from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

LAUNCHD_DIR = Path(__file__).resolve().parent.parent.parent / "setup" / "launchd"
PLISTS = sorted(LAUNCHD_DIR.glob("*.plist"))


@pytest.mark.parametrize("plist", PLISTS, ids=lambda p: p.name)
def test_plist_lint(plist: Path) -> None:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["plutil", "-lint", str(plist)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"plutil -lint failed for {plist.name}:\n{result.stderr}"
    else:
        # Fallback on Linux CI: well-formed XML check
        try:
            ET.fromstring(plist.read_text(encoding="utf-8"))
        except ET.ParseError as exc:
            pytest.fail(f"XML parse error in {plist.name}: {exc}")


@pytest.mark.parametrize("plist", PLISTS, ids=lambda p: p.name)
def test_plist_has_label(plist: Path) -> None:
    tree = ET.parse(str(plist))
    root = tree.getroot()
    # plist root -> dict -> key/string pairs
    plist_dict = root.find("dict")
    assert plist_dict is not None, f"No <dict> in {plist.name}"
    children = list(plist_dict)
    label_value = None
    for i, child in enumerate(children):
        if child.tag == "key" and child.text == "Label":
            if i + 1 < len(children) and children[i + 1].tag == "string":
                label_value = children[i + 1].text
            break
    assert label_value, f"Missing or empty Label string in {plist.name}"
    # Label should match the filename stem
    assert label_value == plist.stem, (
        f"{plist.name}: Label '{label_value}' does not match filename stem '{plist.stem}'"
    )
