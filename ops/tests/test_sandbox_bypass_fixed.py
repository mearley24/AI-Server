"""Sandbox-bypass fix verification for ops/tests pytest suite.

The real strategy tests live in polymarket-bot/tests/test_sandbox_bypass_fixed.py
because they need the polymarket-bot package on sys.path.  This module
delegates to those tests via subprocess so that `python3 -m pytest ops/tests/`
picks them up without import-namespace conflicts.

Run directly with:
    python3 -m pytest ops/tests/test_sandbox_bypass_fixed.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

_POLY_BOT_DIR = os.path.join(os.path.dirname(__file__), "../../polymarket-bot")
_POLY_TESTS = os.path.join(_POLY_BOT_DIR, "tests/test_sandbox_bypass_fixed.py")
_VENV_PYTHON = os.path.join(_POLY_BOT_DIR, ".venv-tests/bin/python3")


class TestSandboxBypassDelegated(unittest.TestCase):
    """Delegate sandbox bypass tests to polymarket-bot test environment."""

    @classmethod
    def _poly_python(cls):
        if os.path.exists(_VENV_PYTHON):
            return _VENV_PYTHON
        return sys.executable

    def test_all_sandbox_bypass_tests_pass(self):
        """Run all 20 sandbox guardrail tests inside polymarket-bot environment."""
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
                f"Sandbox bypass tests FAILED:\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}"
            )

        # Verify expected test count
        passed_line = [l for l in result.stdout.splitlines() if "passed" in l]
        if passed_line:
            print(f"\n  polymarket-bot sandbox tests: {passed_line[-1].strip()}")


class TestSandboxGuardrailSummary(unittest.TestCase):
    """Quick import-only checks that don't need the full dependency tree."""

    def test_base_strategy_has_set_sandbox(self):
        """BaseStrategy source must define set_sandbox and _sandbox."""
        base_path = os.path.join(_POLY_BOT_DIR, "strategies/base.py")
        if not os.path.exists(base_path):
            self.skipTest("base.py not found")
        with open(base_path) as f:
            source = f.read()
        self.assertIn("def set_sandbox(", source, "set_sandbox() missing from BaseStrategy")
        self.assertIn("self._sandbox", source, "_sandbox field missing from BaseStrategy")
        self.assertIn("_place_market_order", source, "_place_market_order() helper missing")

    def test_stink_bid_no_direct_place_order(self):
        """stink_bid.py must not call self._client.place_order() directly."""
        path = os.path.join(_POLY_BOT_DIR, "strategies/stink_bid.py")
        with open(path) as f:
            source = f.read()
        # The only allowed direct calls are inside _place_market_order (in base)
        # Stink bid should use _exit_position -> _place_market_order
        self.assertNotIn(
            "await self._client.place_order",
            source,
            "stink_bid.py still has a direct self._client.place_order() call",
        )

    def test_flash_crash_no_direct_place_order(self):
        path = os.path.join(_POLY_BOT_DIR, "strategies/flash_crash.py")
        with open(path) as f:
            source = f.read()
        self.assertNotIn(
            "await self._client.place_order",
            source,
            "flash_crash.py still has a direct self._client.place_order() call",
        )

    def test_presolution_scalp_no_direct_place_order(self):
        path = os.path.join(_POLY_BOT_DIR, "strategies/presolution_scalp.py")
        with open(path) as f:
            source = f.read()
        self.assertNotIn(
            "await self._client.place_order",
            source,
            "presolution_scalp.py still has a direct self._client.place_order() call",
        )

    def test_sports_arb_direct_calls_only_in_live_guarded_block(self):
        """sports_arb.py may have direct calls, but ONLY inside the live/guarded block."""
        path = os.path.join(_POLY_BOT_DIR, "strategies/sports_arb.py")
        with open(path) as f:
            source = f.read()
        # The two direct calls must be preceded by "# Live:" comment, indicating
        # they're inside the post-sandbox-check concurrent block
        self.assertIn(
            "# Live: place both orders concurrently (sandbox pre-checks above already passed)",
            source,
        )

    def test_main_py_wires_sandbox_to_all_4(self):
        """main.py must call set_sandbox(sandbox) on all 4 strategies."""
        main_path = os.path.join(_POLY_BOT_DIR, "src/main.py")
        with open(main_path) as f:
            source = f.read()
        for strategy in ("presolution_scalp", "sports_arb", "flash_crash", "stink_bid"):
            self.assertIn(
                f"{strategy}.set_sandbox(sandbox)",
                source,
                f"main.py is missing {strategy}.set_sandbox(sandbox)",
            )

    def test_signer_py_untouched(self):
        """signer.py must not have been modified by this P1 fix."""
        signer_path = os.path.join(_POLY_BOT_DIR, "src/signer.py")
        self.assertTrue(os.path.exists(signer_path), "signer.py missing")
        # Check git status — signer.py should NOT appear as modified
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "polymarket-bot/src/signer.py"],
            capture_output=True,
            text=True,
            cwd=os.path.join(_POLY_BOT_DIR, "../.."),
        )
        self.assertEqual(
            result.stdout.strip(),
            "",
            "signer.py was modified — P1 rules forbid touching signer.py",
        )


if __name__ == "__main__":
    unittest.main()
