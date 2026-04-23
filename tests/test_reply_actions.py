"""
Unit tests for the reply_actions Phase 1 foundation.

Covers:
  - parse_reply(): all accepted forms, ambiguity, unrecognized, out-of-range
  - ActionStore: create/lookup/mark_used/prune (uses tmp SQLite, no Docker dep)
  - formatter: format_card() output structure, strip_options_block()

Run from repo root:
    python -m pytest tests/test_reply_actions.py -v
    # or stdlib only:
    python -m unittest tests.test_reply_actions
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "integrations" / "x_intake"))

from reply_actions.parser import ParsedReply, parse_reply
from reply_actions.action_store import ActionStore
from reply_actions.formatter import format_card, strip_options_block

_VALID = frozenset({1, 2, 3})


class TestParseReply(unittest.TestCase):

    # ------------------------------------------------------------------
    # Exact accepted forms
    # ------------------------------------------------------------------
    def _match(self, raw: str, expected_slot: int) -> None:
        result = parse_reply(raw, _VALID)
        self.assertEqual(result.status, "matched", f"expected match for {raw!r}")
        self.assertEqual(result.slot, expected_slot)
        self.assertTrue(result.matched)

    def test_bare_digit(self):
        self._match("1", 1)
        self._match("2", 2)
        self._match("3", 3)

    def test_reply_space_digit(self):
        self._match("reply 1", 1)
        self._match("reply 2", 2)

    def test_reply_no_space(self):
        self._match("reply1", 1)
        self._match("reply3", 3)

    def test_r_prefix(self):
        self._match("r1", 1)
        self._match("r2", 2)
        self._match("r3", 3)

    def test_case_insensitive(self):
        self._match("R1", 1)
        self._match("Reply 2", 2)
        self._match("REPLY 3", 3)

    def test_trailing_text_ignored(self):
        self._match("1 yes please", 1)
        self._match("reply 2 please do it", 2)
        self._match("r3 go ahead", 3)

    # ------------------------------------------------------------------
    # Ambiguity
    # ------------------------------------------------------------------
    def test_two_valid_slots_is_ambiguous(self):
        result = parse_reply("1 or 2", _VALID)
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.slot)

    def test_three_valid_slots_is_ambiguous(self):
        result = parse_reply("1 2 3", _VALID)
        self.assertEqual(result.status, "ambiguous")

    def test_valid_plus_invalid_not_ambiguous(self):
        # 4 is not a valid slot; only 1 valid slot present → matched
        big_valid = frozenset({1, 2, 3, 4})
        result = parse_reply("1 or 4", big_valid)
        self.assertEqual(result.status, "ambiguous")  # both are valid in big_valid

    # ------------------------------------------------------------------
    # Unrecognized
    # ------------------------------------------------------------------
    def test_plain_text_unrecognized(self):
        result = parse_reply("hello", _VALID)
        self.assertEqual(result.status, "unrecognized")
        self.assertFalse(result.matched)

    def test_out_of_range_slot(self):
        result = parse_reply("7", _VALID)
        self.assertEqual(result.status, "unrecognized")

    def test_yes_token_unrecognized(self):
        # YES is a confirmation token, not an action slot
        result = parse_reply("YES", _VALID)
        self.assertEqual(result.status, "unrecognized")

    def test_empty_string_unrecognized(self):
        result = parse_reply("", _VALID)
        self.assertEqual(result.status, "unrecognized")

    def test_whitespace_only_unrecognized(self):
        result = parse_reply("   ", _VALID)
        self.assertEqual(result.status, "unrecognized")

    def test_no_prefix_large_number(self):
        result = parse_reply("999", _VALID)
        self.assertEqual(result.status, "unrecognized")


class TestActionStore(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test_reply_actions.db"
        self.store = ActionStore(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_create_returns_12char_hex(self):
        action_id = self.store.create([1, 2, 3], {"url": "https://x.com/foo/status/1"})
        self.assertEqual(len(action_id), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in action_id))

    def test_lookup_returns_context(self):
        ctx = {"url": "https://x.com/bar/status/2", "author": "testuser"}
        action_id = self.store.create([1, 2], ctx, expiry_seconds=3600)
        result = self.store.lookup(action_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.action_id, action_id)
        self.assertEqual(result.context["url"], ctx["url"])
        self.assertEqual(result.valid_slots, frozenset({1, 2}))
        self.assertFalse(result.expired)
        self.assertFalse(result.used)

    def test_lookup_missing_returns_none(self):
        self.assertIsNone(self.store.lookup("nonexistent"))

    def test_lookup_expired_action_shows_expired(self):
        action_id = self.store.create([1], {}, expiry_seconds=1)
        time.sleep(1.1)
        result = self.store.lookup(action_id)
        self.assertIsNotNone(result)
        self.assertTrue(result.expired)

    def test_mark_used_prevents_reuse(self):
        action_id = self.store.create([1, 2], {"url": "x"})
        ok = self.store.mark_used(action_id, slot=1)
        self.assertTrue(ok)
        # Second call returns False (already used)
        ok2 = self.store.mark_used(action_id, slot=2)
        self.assertFalse(ok2)
        result = self.store.lookup(action_id)
        self.assertTrue(result.used)
        self.assertEqual(result.used_slot, 1)

    def test_prune_removes_expired(self):
        action_id = self.store.create([1], {}, expiry_seconds=1)
        time.sleep(1.1)
        removed = self.store.prune()
        self.assertEqual(removed, 1)
        self.assertIsNone(self.store.lookup(action_id))

    def test_prune_keeps_live(self):
        self.store.create([1], {}, expiry_seconds=3600)
        removed = self.store.prune()
        self.assertEqual(removed, 0)

    def test_ids_are_unique(self):
        ids = {self.store.create([1], {}) for _ in range(50)}
        self.assertEqual(len(ids), 50)


class TestFormatter(unittest.TestCase):

    def test_format_card_contains_summary(self):
        summary = "💡 @user\nSome insight about AI agents."
        result = format_card(summary, "abc123def456")
        self.assertIn(summary, result)

    def test_format_card_contains_action_id(self):
        result = format_card("summary", "abc123def456")
        self.assertIn("ID:abc123def456", result)

    def test_format_card_contains_expiry(self):
        result = format_card("summary", "abc123def456", expiry_seconds=86400)
        self.assertIn("exp 24h", result)

    def test_format_card_contains_divider(self):
        result = format_card("summary", "abc123def456")
        self.assertIn("──────────", result)

    def test_format_card_contains_reply_prefix(self):
        result = format_card("summary", "abc123def456", slots=[1, 2, 3])
        self.assertIn("Reply 1", result)

    def test_format_card_1h_expiry(self):
        result = format_card("summary", "abc123def456", expiry_seconds=3600)
        self.assertIn("exp 1h", result)

    def test_strip_options_block_round_trip(self):
        summary = "💡 @user\nSome insight."
        formatted = format_card(summary, "abc123def456")
        stripped = strip_options_block(formatted)
        self.assertEqual(stripped, summary)

    def test_strip_options_block_noop_on_plain(self):
        plain = "No action block here."
        self.assertEqual(strip_options_block(plain), plain)

    def test_format_card_structure_order(self):
        summary = "SUMMARY"
        result = format_card(summary, "aabbccddee11", slots=[1, 2])
        lines = result.split("\n")
        # Summary comes first
        self.assertEqual(lines[0], "SUMMARY")
        # Divider follows blank line
        divider_idx = next(i for i, l in enumerate(lines) if "──────────" in l)
        self.assertGreater(divider_idx, 0)
        # ID line is last
        self.assertIn("ID:", lines[-1])


if __name__ == "__main__":
    unittest.main()
