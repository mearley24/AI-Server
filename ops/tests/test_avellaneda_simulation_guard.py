"""Delegation test: Avellaneda simulation guard for ops/tests pytest suite.

The real tests live in polymarket-bot/tests/test_avellaneda_simulation_guard.py.
This module delegates to those tests via subprocess so that
`python3 -m pytest ops/tests/` picks them up without import-namespace conflicts.

Run directly with:
    python3 -m pytest ops/tests/test_avellaneda_simulation_guard.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

_POLY_BOT_DIR = os.path.join(os.path.dirname(__file__), "../../polymarket-bot")
_POLY_TESTS = os.path.join(_POLY_BOT_DIR, "tests/test_avellaneda_simulation_guard.py")
_VENV_PYTHON = os.path.join(_POLY_BOT_DIR, ".venv-tests/bin/python3")


class TestAvellanedaSimulationGuardDelegated(unittest.TestCase):
    """Delegate Avellaneda simulation guard tests to polymarket-bot test environment."""

    @classmethod
    def _poly_python(cls):
        if os.path.exists(_VENV_PYTHON):
            return _VENV_PYTHON
        return sys.executable

    def test_all_avellaneda_simulation_guard_tests_pass(self):
        """Run all Avellaneda simulation guard tests inside polymarket-bot environment."""
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
                f"Avellaneda simulation guard tests failed:\n{result.stdout}\n{result.stderr}"
            )
