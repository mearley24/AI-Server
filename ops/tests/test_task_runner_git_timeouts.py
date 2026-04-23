#!/usr/bin/env python3
"""
ops/tests/test_task_runner_git_timeouts.py — smoke test for the bounded-git
contract introduced 2026-04-23 (see docs/audits/bob-freezing-runtime-hangs-
2026-04-23.md).

Contract:
  - GIT_TIMEOUT is defined.
  - Every git subprocess helper (git, handle_git_pull, has_changes,
    pull_latest) passes a timeout to subprocess.run.
  - When subprocess.run raises subprocess.TimeoutExpired, the helper
    degrades gracefully instead of propagating the exception or wedging
    the fcntl lock.
  - The non-interactive git env is applied (GIT_TERMINAL_PROMPT=0 etc).

Run directly: ``python3 ops/tests/test_task_runner_git_timeouts.py``.
Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "ops"))

import task_runner  # noqa: E402


FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}")


def make_timeout_stub(captured: list[dict]):
    """Return a subprocess.run stub that records its kwargs and raises."""

    def _stub(cmd, **kwargs):
        captured.append({"cmd": cmd, "kwargs": kwargs})
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    return _stub


def test_git_timeout_constant_exists() -> None:
    print("test_git_timeout_constant_exists")
    check(hasattr(task_runner, "GIT_TIMEOUT"), "GIT_TIMEOUT symbol defined")
    check(
        isinstance(task_runner.GIT_TIMEOUT, (int, float))
        and task_runner.GIT_TIMEOUT > 0,
        "GIT_TIMEOUT is a positive number",
    )
    check(
        task_runner.GIT_TIMEOUT <= 300,
        "GIT_TIMEOUT is <= 300s (bounded enough to not wedge a 120s launchd tick for long)",
    )


def test_git_env_is_non_interactive() -> None:
    print("test_git_env_is_non_interactive")
    env = task_runner._git_env()
    check(env.get("GIT_TERMINAL_PROMPT") == "0", "GIT_TERMINAL_PROMPT=0")
    check("/usr/bin/true" in env.get("GIT_ASKPASS", ""), "GIT_ASKPASS short-circuited")
    check(
        "BatchMode=yes" in env.get("GIT_SSH_COMMAND", ""),
        "GIT_SSH_COMMAND forces BatchMode=yes",
    )


def test_git_helper_returns_on_timeout(monkey_args: list) -> None:
    print("test_git_helper_returns_on_timeout")
    captured: list[dict] = []
    original = subprocess.run
    subprocess.run = make_timeout_stub(captured)
    try:
        # check=False so the helper returns a CompletedProcess-shaped failure
        # instead of raising CalledProcessError.
        result = task_runner.git("status", "--porcelain", check=False)
    except Exception as exc:  # pragma: no cover - failure path
        FAILURES.append(f"git() raised on timeout: {exc!r}")
        print(f"  FAIL  git() raised on timeout: {exc!r}")
        return
    finally:
        subprocess.run = original

    check(
        isinstance(result, subprocess.CompletedProcess),
        "git() returns CompletedProcess on timeout",
    )
    check(result.returncode == 124, "git() returncode == 124 on timeout")
    check(
        any(kw["kwargs"].get("timeout") == task_runner.GIT_TIMEOUT for kw in captured),
        "git() passed GIT_TIMEOUT to subprocess.run",
    )
    check(
        any(
            (kw["kwargs"].get("env") or {}).get("GIT_TERMINAL_PROMPT") == "0"
            for kw in captured
        ),
        "git() passed non-interactive env",
    )


def test_handle_git_pull_returns_124_on_timeout() -> None:
    print("test_handle_git_pull_returns_124_on_timeout")
    captured: list[dict] = []
    original = subprocess.run
    subprocess.run = make_timeout_stub(captured)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.txt"
            rc = task_runner.handle_git_pull({}, result_path)
            body = result_path.read_text(encoding="utf-8")
    except Exception as exc:
        FAILURES.append(f"handle_git_pull raised on timeout: {exc!r}")
        print(f"  FAIL  handle_git_pull raised on timeout: {exc!r}")
        return
    finally:
        subprocess.run = original

    check(rc == 124, "handle_git_pull returned 124 on timeout")
    check("TIMEOUT" in body, "handle_git_pull wrote TIMEOUT to result file")
    check(
        captured and captured[0]["kwargs"].get("timeout") == task_runner.GIT_TIMEOUT,
        "handle_git_pull passed GIT_TIMEOUT",
    )


def test_has_changes_returns_false_on_timeout() -> None:
    print("test_has_changes_returns_false_on_timeout")
    captured: list[dict] = []
    original = subprocess.run
    subprocess.run = make_timeout_stub(captured)
    try:
        changed = task_runner.has_changes()
    except Exception as exc:
        FAILURES.append(f"has_changes raised on timeout: {exc!r}")
        print(f"  FAIL  has_changes raised on timeout: {exc!r}")
        return
    finally:
        subprocess.run = original

    check(changed is False, "has_changes() returns False on timeout (skip commit)")
    check(
        captured and captured[0]["kwargs"].get("timeout") == task_runner.GIT_TIMEOUT,
        "has_changes passed GIT_TIMEOUT",
    )


def test_pull_latest_survives_timeout() -> None:
    print("test_pull_latest_survives_timeout")
    captured: list[dict] = []
    original = subprocess.run
    subprocess.run = make_timeout_stub(captured)
    try:
        task_runner.pull_latest()
    except Exception as exc:
        FAILURES.append(f"pull_latest raised on timeout: {exc!r}")
        print(f"  FAIL  pull_latest raised on timeout: {exc!r}")
        return
    finally:
        subprocess.run = original

    # pull_latest is void; the contract is "does not raise, does not
    # crash the tick." Verify at least one call was made with the bound.
    check(
        captured and captured[0]["kwargs"].get("timeout") == task_runner.GIT_TIMEOUT,
        "pull_latest passed GIT_TIMEOUT",
    )


if __name__ == "__main__":
    test_git_timeout_constant_exists()
    test_git_env_is_non_interactive()
    test_git_helper_returns_on_timeout([])
    test_handle_git_pull_returns_124_on_timeout()
    test_has_changes_returns_false_on_timeout()
    test_pull_latest_survives_timeout()

    if FAILURES:
        print(f"\nFAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nALL PASS")
    sys.exit(0)
