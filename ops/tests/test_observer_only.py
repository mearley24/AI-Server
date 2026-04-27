"""Observer-only mode verification for ops/tests pytest suite.

The real strategy tests live in polymarket-bot/tests/test_observer_only.py
because they need the polymarket-bot package on sys.path.  This module
delegates to those tests via subprocess so that `python3 -m pytest ops/tests/`
picks them up without import-namespace conflicts.

Run directly with:
    python3 -m pytest ops/tests/test_observer_only.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

_POLY_BOT_DIR = os.path.join(os.path.dirname(__file__), "../../polymarket-bot")
_POLY_TESTS = os.path.join(_POLY_BOT_DIR, "tests/test_observer_only.py")
_VENV_PYTHON = os.path.join(_POLY_BOT_DIR, ".venv-tests/bin/python3")


class TestObserverOnlyDelegated(unittest.TestCase):
    """Delegate observer-only tests to polymarket-bot test environment."""

    @classmethod
    def _poly_python(cls):
        if os.path.exists(_VENV_PYTHON):
            return _VENV_PYTHON
        return sys.executable

    def test_all_observer_only_tests_pass(self):
        """Run all 12 observer-only guardrail tests inside polymarket-bot environment."""
        if not os.path.exists(_POLY_TESTS):
            self.skipTest(f"polymarket-bot test file not found: {_POLY_TESTS}")

        result = subprocess.run(
            [self._poly_python(), "-m", "pytest", _POLY_TESTS, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=_POLY_BOT_DIR,
        )
        if result.returncode != 0:
            self.fail(
                f"Observer-only tests failed:\n{result.stdout}\n{result.stderr}"
            )
