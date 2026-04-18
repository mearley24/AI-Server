#!/usr/bin/env python3
"""
ops/launchd_inventory.py — Symphony launchd inventory + missing-target sweeper.

Scans ``~/Library/LaunchAgents/com.symphony.*.plist`` and reports:

  * Total count of Symphony launchd plists
  * Which of them are currently loaded (`launchctl list`)
  * Which reference a ``ProgramArguments`` script path that does not exist on
    disk (silent drift — policy #23 in CLAUDE.md)

Writes a human-readable inventory table to stdout and, when
``--write`` is passed, persists it to
``ops/verification/<stamp>-launchd-inventory.txt``.

Exit codes:
    0  OK (zero missing-target plists)
    1  at least one plist references a missing script
    2  internal error

Safe to run as a low-risk diagnostic. No network, no privileged ops.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "ops" / "verification"
LAUNCHAGENTS = Path.home() / "Library" / "LaunchAgents"
LABEL_PREFIX = "com.symphony."

# Interpreter basenames that indicate the real target is the NEXT
# ProgramArguments entry, not the interpreter itself.
INTERPRETER_BASENAMES = {
    "bash", "sh", "zsh",
    "python", "python3",
    "python3.10", "python3.11", "python3.12", "python3.13", "python3.14",
    "/opt/homebrew/bin/python3",
    "node", "osascript",
}


@dataclass
class PlistInfo:
    label: str
    path: Path
    interpreter: str
    target: str
    target_exists: bool
    loaded: bool


def _now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def _launchctl_loaded_labels() -> set[str]:
    """Set of labels currently loaded according to ``launchctl list``."""
    try:
        proc = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10
        )
    except Exception:  # noqa: BLE001
        return set()
    if proc.returncode != 0:
        return set()
    labels: set[str] = set()
    for line in proc.stdout.splitlines():
        # launchctl list emits: "PID  STATUS  Label"
        parts = line.strip().split()
        if len(parts) >= 3 and parts[-1].startswith(LABEL_PREFIX):
            labels.add(parts[-1])
    return labels


def _pick_target(args: list[str]) -> tuple[str, str]:
    """Return (interpreter, target_script_path)."""
    if not args:
        return ("", "")
    first = args[0]
    first_bn = Path(first).name
    if first_bn in INTERPRETER_BASENAMES and len(args) >= 2:
        return (first, args[1])
    return (first, first)


def _scan_plist(path: Path, loaded: set[str]) -> PlistInfo | None:
    try:
        with path.open("rb") as f:
            data = plistlib.load(f)
    except Exception as exc:  # noqa: BLE001
        return PlistInfo(
            label=path.stem,
            path=path,
            interpreter="<parse-error>",
            target=f"parse error: {exc}",
            target_exists=False,
            loaded=path.stem in loaded,
        )
    label = data.get("Label") or path.stem
    args = data.get("ProgramArguments") or []
    if isinstance(args, list):
        args = [str(a) for a in args]
    else:
        args = [str(data.get("Program", ""))]
    interpreter, target = _pick_target(args)
    # Only flag as missing when the target is an absolute path we can stat.
    target_exists = True
    if target and target.startswith("/"):
        target_exists = Path(target).exists()
    return PlistInfo(
        label=label,
        path=path,
        interpreter=interpreter,
        target=target,
        target_exists=target_exists,
        loaded=label in loaded,
    )


def run(write: bool = False, quiet: bool = False) -> int:
    loaded = _launchctl_loaded_labels()
    if not LAUNCHAGENTS.exists():
        print(f"launchd_inventory: missing {LAUNCHAGENTS}", file=sys.stderr)
        return 2
    plists = sorted(LAUNCHAGENTS.glob("com.symphony.*.plist"))
    infos: list[PlistInfo] = []
    for p in plists:
        info = _scan_plist(p, loaded)
        if info is not None:
            infos.append(info)

    missing = [i for i in infos if i.target and i.target.startswith("/") and not i.target_exists]
    loaded_count = sum(1 for i in infos if i.loaded)
    total = len(infos)

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"Symphony launchd inventory — {datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"LaunchAgents dir: {LAUNCHAGENTS}")
    lines.append(f"Total com.symphony.*.plist: {total}")
    lines.append(f"Currently loaded by launchctl list: {loaded_count}")
    lines.append(f"Plists referencing a missing script (silent drift): {len(missing)}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"{'LABEL':<52} {'LOADED':<7} {'TARGET EXISTS':<14} TARGET")
    lines.append("-" * 140)
    for info in infos:
        exists_flag = "OK" if info.target_exists else "MISSING"
        loaded_flag = "yes" if info.loaded else "no"
        label = info.label[:52]
        lines.append(
            f"{label:<52} {loaded_flag:<7} {exists_flag:<14} {info.target}"
        )
    lines.append("")
    if missing:
        lines.append("Missing-target plists (ordered):")
        for info in missing:
            lines.append(f"  {info.label}  ->  {info.target}")
        lines.append("")
        lines.append("Next action: for each missing target, either restore the script or")
        lines.append("unload the plist (`launchctl bootout gui/$(id -u) <plist>`) and remove")
        lines.append("the plist file. Silent drift is CLAUDE.md lesson #23.")
    else:
        lines.append("No missing targets detected. All Symphony plists reference files on disk.")
    text = "\n".join(lines) + "\n"

    if not quiet:
        print(text)

    if write:
        VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
        out = VERIFICATION_DIR / f"{_now_stamp()}-launchd-inventory.txt"
        out.write_text(text, encoding="utf-8")
        if not quiet:
            print(f"[launchd_inventory] wrote {out}")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="also persist a timestamped report under ops/verification/")
    parser.add_argument("--quiet", action="store_true", help="suppress stdout (still writes file with --write)")
    args = parser.parse_args(argv)
    try:
        return run(write=args.write, quiet=args.quiet)
    except Exception as exc:  # noqa: BLE001
        print(f"launchd_inventory: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
