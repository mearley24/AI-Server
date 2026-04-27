"""Tests for the Polymarket live-trading gate in polymarket-bot/src/main.py.

The gate requires TWO conditions to allow live trading:
  1. POLY_DRY_RUN=false  (explicit opt-out of paper mode)
  2. POLY_ALLOW_LIVE=I_UNDERSTAND_REAL_MONEY_RISK  (explicit passphrase)

If either condition is missing the gate forces dry_run=True.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Minimal stub so we can import _enforce_live_gate without the full
# polymarket-bot dependency tree.
# ---------------------------------------------------------------------------

_GATE_MODULE_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../polymarket-bot/src/main.py",
)

def _load_gate_function():
    """Import only the _enforce_live_gate function from main.py."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("poly_main", _GATE_MODULE_PATH)
    module = types.ModuleType("poly_main")

    # Stub every top-level import that main.py needs so we don't pull in the
    # full dependency tree.
    stub_names = [
        "fastapi", "fastapi.responses", "contextlib", "asyncio",
        "structlog", "aiohttp", "redis.asyncio", "redis",
        "src.config", "src.sandbox", "src.platform_clients",
        "src.copytrade", "src.strategies", "src.latency_detector",
        "src.debate_engine", "src.exit_engine", "src.paper_ledger",
        "src.parameter_tuner", "src.redeemer", "src.kalshi_platform",
        "src.crypto_platform", "src.order_flow", "src.weather_trader",
        "src.sports_arb",
    ]
    for name in stub_names:
        parts = name.split(".")
        # Register each prefix so "from x.y import z" doesn't fail
        for i in range(1, len(parts) + 1):
            stub = types.ModuleType(".".join(parts[:i]))
            sys.modules.setdefault(".".join(parts[:i]), stub)

    # Execute the module source but catch ImportError for missing real deps
    try:
        loader = importlib.util.loader_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        # If full import fails, extract just the function via source parsing
        import ast, textwrap

        with open(_GATE_MODULE_PATH) as f:
            source = f.read()

        # Find and extract _enforce_live_gate + its constant
        tree = ast.parse(source)
        needed = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "_LIVE_GATE_PASSPHRASE":
                        needed.append(ast.get_source_segment(source, node))
            if isinstance(node, ast.FunctionDef) and node.name == "_enforce_live_gate":
                needed.append(ast.get_source_segment(source, node))

        exec(  # noqa: S102
            textwrap.dedent("\n".join(needed)),
            {"os": os},
            module.__dict__,
        )

    return module._enforce_live_gate, module._LIVE_GATE_PASSPHRASE


_enforce_live_gate, _PASSPHRASE = _load_gate_function()


def _make_settings(dry_run: bool):
    s = MagicMock()
    s.dry_run = dry_run
    return s


def _make_log():
    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()
    log.critical = MagicMock()
    return log


class TestLiveGate(unittest.TestCase):

    def setUp(self):
        # Clear gate env var before each test
        os.environ.pop("POLY_ALLOW_LIVE", None)
        os.environ.pop("POLY_DRY_RUN", None)

    def tearDown(self):
        os.environ.pop("POLY_ALLOW_LIVE", None)
        os.environ.pop("POLY_DRY_RUN", None)

    def test_dry_run_true_passes_through(self):
        """dry_run=True: gate is a no-op, settings unchanged, returns False."""
        settings = _make_settings(dry_run=True)
        log = _make_log()
        result = _enforce_live_gate(settings, log)
        self.assertFalse(result)
        self.assertTrue(settings.dry_run)
        log.critical.assert_not_called()

    def test_dry_run_false_with_correct_passphrase_allows_live(self):
        """dry_run=False + correct passphrase: live trading allowed, returns True."""
        os.environ["POLY_ALLOW_LIVE"] = _PASSPHRASE
        settings = _make_settings(dry_run=False)
        log = _make_log()
        result = _enforce_live_gate(settings, log)
        self.assertTrue(result)
        self.assertFalse(settings.dry_run)
        log.warning.assert_called_once()
        log.critical.assert_not_called()

    def test_dry_run_false_no_passphrase_forced_to_dry_run(self):
        """dry_run=False with no POLY_ALLOW_LIVE: forced back to dry_run=True."""
        settings = _make_settings(dry_run=False)
        log = _make_log()
        result = _enforce_live_gate(settings, log)
        self.assertFalse(result)
        self.assertTrue(settings.dry_run, "gate must override dry_run back to True")
        log.critical.assert_called_once()

    def test_dry_run_false_wrong_passphrase_forced_to_dry_run(self):
        """dry_run=False with wrong POLY_ALLOW_LIVE value: forced to paper mode."""
        os.environ["POLY_ALLOW_LIVE"] = "yes_i_want_live"
        settings = _make_settings(dry_run=False)
        log = _make_log()
        result = _enforce_live_gate(settings, log)
        self.assertFalse(result)
        self.assertTrue(settings.dry_run, "wrong passphrase must not unlock live mode")
        log.critical.assert_called_once()

    def test_dry_run_false_empty_string_passphrase_forced_to_dry_run(self):
        """Empty string POLY_ALLOW_LIVE counts as not set — paper mode enforced."""
        os.environ["POLY_ALLOW_LIVE"] = ""
        settings = _make_settings(dry_run=False)
        log = _make_log()
        result = _enforce_live_gate(settings, log)
        self.assertFalse(result)
        self.assertTrue(settings.dry_run)

    def test_passphrase_constant_value(self):
        """Passphrase constant must be the exact documented value."""
        self.assertEqual(_PASSPHRASE, "I_UNDERSTAND_REAL_MONEY_RISK")


class TestSandboxConservativeDefaults(unittest.TestCase):
    """Verify the sandbox defaults loaded from config.yaml are conservative."""

    def test_max_single_trade_default(self):
        """Default max single trade must not exceed $10."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../polymarket-bot/src"))
        try:
            from config import Settings  # type: ignore
            s = Settings()
            self.assertLessEqual(
                s.security_max_single_trade, 10.0,
                f"security_max_single_trade default ({s.security_max_single_trade}) exceeds $10 safety cap",
            )
        except ImportError:
            self.skipTest("polymarket-bot dependencies not installed")
        finally:
            sys.path.pop(0)

    def test_max_daily_volume_default(self):
        """Default max daily volume must not exceed $100."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../polymarket-bot/src"))
        try:
            from config import Settings  # type: ignore
            s = Settings()
            self.assertLessEqual(
                s.security_max_daily_volume, 100.0,
                f"security_max_daily_volume default ({s.security_max_daily_volume}) exceeds $100 safety cap",
            )
        except ImportError:
            self.skipTest("polymarket-bot dependencies not installed")
        finally:
            sys.path.pop(0)

    def test_max_daily_loss_default(self):
        """Default max daily loss kill switch must not exceed $50."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../polymarket-bot/src"))
        try:
            from config import Settings  # type: ignore
            s = Settings()
            self.assertLessEqual(
                s.security_max_daily_loss, 50.0,
                f"security_max_daily_loss default ({s.security_max_daily_loss}) exceeds $50 safety cap",
            )
        except ImportError:
            self.skipTest("polymarket-bot dependencies not installed")
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
