#!/usr/bin/env python3
"""
Common API utilities shared across work and trading APIs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def run_command(cmd: list[str], timeout: int = 30, cwd: Path | None = None) -> dict[str, Any]:
    """Run a command and return normalized result."""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
        return {
            "success": p.returncode == 0,
            "output": p.stdout.strip() if p.stdout else "",
            "error": p.stderr.strip() if p.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def run_tool_script(
    base_dir: Path,
    script: str,
    args: list[str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Run a script from tools/ and return normalized result."""
    return run_command(
        ["python3", str(base_dir / "tools" / script)] + (args or []),
        timeout=timeout,
        cwd=base_dir,
    )
