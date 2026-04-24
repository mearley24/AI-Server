"""Unit tests for x-intake offline/manual import and queue dedupe.

Covers:
  - canonical_url(): x.com/twitter.com collapse, query junk stripping
  - extract_tweet_id(): valid/invalid URLs
  - queue_db.enqueue(): idempotent by canonical URL across source/ts variance
  - manual_import.import_url() / import_many(): inserted vs already_present,
    non-tweet URLs skipped, empty lines & comments ignored
  - recovery script: imports the known 4 backlog URLs end-to-end

Run from repo root::

    python -m pytest tests/test_x_intake_manual_import.py -v
    # or stdlib only:
    python -m unittest tests.test_x_intake_manual_import
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "integrations" / "x_intake"))
sys.path.insert(0, str(ROOT))


class _TmpDBTestCase(unittest.TestCase):
    """Base that points X_INTAKE_DB_PATH at a temp file per test."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = Path(self._tmpdir.name) / "queue.db"
        os.environ["X_INTAKE_DB_PATH"] = str(self.db_path)
        # Reload modules so they pick up the new DB path.
        import queue_db  # noqa: F401
        import manual_import  # noqa: F401

        importlib.reload(queue_db)
        importlib.reload(manual_import)
        self.queue_db = queue_db
        self.manual_import = manual_import


class CanonicalURLTests(unittest.TestCase):
    def setUp(self) -> None:
        import queue_db

        importlib.reload(queue_db)
        self.queue_db = queue_db

    def test_x_and_twitter_collapse(self) -> None:
        a = self.queue_db.canonical_url("https://x.com/Foo/status/123?s=42")
        b = self.queue_db.canonical_url("https://twitter.com/foo/status/123")
        self.assertEqual(a, "https://x.com/foo/status/123")
        self.assertEqual(a, b)

    def test_strips_query_and_trailing_slash(self) -> None:
        got = self.queue_db.canonical_url(
            "https://x.com/NousResearch/status/2047495677651918885?s=42"
        )
        self.assertEqual(
            got, "https://x.com/nousresearch/status/2047495677651918885"
        )

    def test_non_tweet_url_preserved_but_trimmed(self) -> None:
        # Non-tweet URLs are kept as-is with only trailing /?# stripped —
        # this is a lightweight normalize, not a full URL parser.
        got = self.queue_db.canonical_url("https://example.com/path/?#")
        self.assertEqual(got, "https://example.com/path")

    def test_empty(self) -> None:
        self.assertEqual(self.queue_db.canonical_url(""), "")

    def test_extract_tweet_id(self) -> None:
        self.assertEqual(
            self.queue_db.extract_tweet_id(
                "https://x.com/openswarm_/status/2047034226806292493?s=42"
            ),
            "2047034226806292493",
        )
        self.assertIsNone(self.queue_db.extract_tweet_id("https://example.com"))
        self.assertIsNone(self.queue_db.extract_tweet_id(""))


class EnqueueDedupeTests(_TmpDBTestCase):
    def test_same_url_returns_same_row(self) -> None:
        rid1 = self.queue_db.enqueue(
            url="https://x.com/Foo/status/123?s=42",
            author="Foo",
            source="manual",
        )
        rid2 = self.queue_db.enqueue(
            url="https://twitter.com/foo/status/123",  # different scheme/host
            author="Foo",
            source="imessage",
        )
        self.assertGreater(rid1, 0)
        self.assertEqual(rid1, rid2, "dedupe by canonical URL should return the same row id")

        stats = self.queue_db.get_stats()
        self.assertEqual(stats["total"], 1)

    def test_different_urls_distinct(self) -> None:
        rid1 = self.queue_db.enqueue(url="https://x.com/a/status/1")
        rid2 = self.queue_db.enqueue(url="https://x.com/b/status/2")
        self.assertNotEqual(rid1, rid2)
        self.assertEqual(self.queue_db.get_stats()["total"], 2)

    def test_find_by_url(self) -> None:
        self.queue_db.enqueue(
            url="https://x.com/Foo/status/999?s=42", summary="test gist"
        )
        row = self.queue_db.find_by_url("https://twitter.com/foo/status/999")
        self.assertIsNotNone(row)
        assert row is not None  # for type-checkers
        self.assertEqual(row["summary"], "test gist")

    def test_find_by_url_returns_none_for_missing(self) -> None:
        self.assertIsNone(
            self.queue_db.find_by_url("https://x.com/zzz/status/111")
        )


class ManualImportTests(_TmpDBTestCase):
    def test_import_url_inserts_then_dedupes(self) -> None:
        r1 = self.manual_import.import_url(
            "https://x.com/OpenSwarm_/status/2047034226806292493?s=42",
            note="gist v1",
        )
        self.assertEqual(r1.status, "inserted")
        self.assertGreater(r1.row_id, 0)

        r2 = self.manual_import.import_url(
            "https://twitter.com/openswarm_/status/2047034226806292493",
            note="gist v2",  # ignored, already_present
        )
        self.assertEqual(r2.status, "already_present")
        self.assertEqual(r2.row_id, r1.row_id)

    def test_import_url_skips_non_tweet(self) -> None:
        r = self.manual_import.import_url("https://example.com/article")
        self.assertEqual(r.status, "skipped")
        self.assertIn("not a tweet", r.reason)

    def test_import_url_skips_empty(self) -> None:
        r = self.manual_import.import_url("   ")
        self.assertEqual(r.status, "skipped")

    def test_import_many_ignores_blanks_and_comments(self) -> None:
        urls = [
            "https://x.com/a/status/1",
            "",
            "   ",
            "# this is a comment",
            "https://x.com/b/status/2",
            "https://x.com/a/status/1",  # duplicate
        ]
        results = self.manual_import.import_many(urls)
        statuses = [r.status for r in results]
        # expect 3 results: 2 inserted + 1 already_present (blanks/comments skipped before loop)
        self.assertEqual(len(results), 3)
        self.assertEqual(statuses.count("inserted"), 2)
        self.assertEqual(statuses.count("already_present"), 1)

    def test_import_stores_note_as_summary(self) -> None:
        self.manual_import.import_url(
            "https://x.com/jameszmsun/status/2047522852854026378?s=42",
            note="James Sun: browser use inside Codex",
        )
        rows = self.queue_db.get_queue()
        self.assertEqual(len(rows), 1)
        self.assertIn("browser use", rows[0]["summary"])
        self.assertEqual(rows[0]["source"], "manual")


class RecoveryScriptTests(_TmpDBTestCase):
    def test_recovery_script_imports_four_urls(self) -> None:
        # Import the recovery module fresh so it binds to our temp DB path.
        sys.path.insert(0, str(ROOT / "scripts"))
        import x_intake_recover_offline

        importlib.reload(x_intake_recover_offline)

        self.assertEqual(len(x_intake_recover_offline.BACKLOG), 4)

        exit_code = x_intake_recover_offline.main()
        self.assertEqual(exit_code, 0)

        stats = self.queue_db.get_stats()
        self.assertEqual(stats["total"], 4)

        # Re-running should be idempotent.
        exit_code2 = x_intake_recover_offline.main()
        self.assertEqual(exit_code2, 0)
        self.assertEqual(self.queue_db.get_stats()["total"], 4)


if __name__ == "__main__":
    unittest.main()
