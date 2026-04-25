"""
Tests for scripts/review_client_threads.py — named/unnamed contact filters,
summary counts, snippet controls, and display format.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.review_client_threads as mod


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _create_thread_db(path: Path, threads: list[dict]) -> Path:
    db = path / "threads.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY,
            chat_guid TEXT NOT NULL DEFAULT '',
            contact_handle TEXT NOT NULL,
            message_count INTEGER DEFAULT 10,
            date_first TEXT DEFAULT '2026-01-01T00:00:00+00:00',
            date_last  TEXT DEFAULT '2026-04-01T00:00:00+00:00',
            category TEXT DEFAULT 'work',
            work_confidence REAL DEFAULT 0.8,
            reason_codes TEXT DEFAULT '[]',
            is_reviewed INTEGER DEFAULT -1,
            relationship_type TEXT DEFAULT 'unknown',
            created_at TEXT DEFAULT '2026-01-01T00:00:00+00:00'
        )
    """)
    for t in threads:
        tid = t.get("thread_id", "t1")
        conn.execute("""
            INSERT INTO threads
              (thread_id, chat_guid, contact_handle, message_count,
               date_first, date_last, category, work_confidence, reason_codes, is_reviewed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tid,
            t.get("chat_guid", f"guid-{tid}"),
            t["contact_handle"],
            t.get("message_count", 10),
            t.get("date_first", "2026-01-01"),
            t.get("date_last", "2026-04-01"),
            t.get("category", "work"),
            t.get("work_confidence", 0.8),
            t.get("reason_codes", "[]"),
            t.get("is_reviewed", -1),
        ))
    conn.commit()
    conn.close()
    return db


def _create_fake_chat_db(path: Path, guid: str, messages: list[str]) -> Path:
    """Minimal chat.db for snippet tests."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY, guid TEXT NOT NULL, chat_identifier TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, attributedBody BLOB,
            is_from_me INTEGER DEFAULT 0, date INTEGER DEFAULT 0
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
    """)
    conn.execute("INSERT INTO chat VALUES (1, ?, '+15550000000')", (guid,))
    for i, msg in enumerate(messages, 1):
        conn.execute(
            "INSERT INTO message VALUES (?, ?, NULL, 0, ?)",
            (i, msg, i * 1_000_000_000),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (i,))
    conn.commit()
    conn.close()
    return path


def _open_conn(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _named_for(handle: str) -> str:
    """Mock: +1970* → 'John Smith', +1303* → 'Jane Doe', else ''."""
    if handle.startswith("+1970"):
        return "John Smith"
    if handle.startswith("+1303"):
        return "Jane Doe"
    return ""


def _fake_row(handle: str = "+19705551234", conf: float = 0.8) -> dict:
    return {
        "contact_handle": handle,
        "work_confidence": conf,
        "message_count": 10,
        "date_first": "2026-01-01",
        "date_last": "2026-04-01",
        "reason_codes": '["strong:control4"]',
        "chat_guid": f"guid-{handle}",
        "thread_id": handle,
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    mod._clear_contact_cache()
    yield
    mod._clear_contact_cache()


# ── _apply_contact_filter ─────────────────────────────────────────────────────

class TestApplyContactFilter:

    def test_named_only_excludes_raw_numbers(self):
        resolved = [
            (_fake_row("+19705551234"), "John Smith", "exact"),
            (_fake_row("+15559991111"), "", "none"),
            (_fake_row("+13035550000"), "Jane Doe", "exact"),
        ]
        result = mod._apply_contact_filter(resolved, named_only=True, unnamed_only=False, names_first=False)
        handles = [r[0]["contact_handle"] for r in result]
        assert "+15559991111" not in handles
        assert len(result) == 2

    def test_unnamed_only_excludes_resolved_contacts(self):
        resolved = [
            (_fake_row("+19705551234"), "John Smith", "exact"),
            (_fake_row("+15559991111"), "", "none"),
            (_fake_row("+15559992222"), "", "none"),
        ]
        result = mod._apply_contact_filter(resolved, named_only=False, unnamed_only=True, names_first=False)
        handles = [r[0]["contact_handle"] for r in result]
        assert "+19705551234" not in handles
        assert len(result) == 2

    def test_names_first_puts_named_before_unnamed(self):
        """Named contact with lower confidence must come before unnamed with higher."""
        resolved = [
            (_fake_row("+15559991111", conf=0.95), "", "none"),
            (_fake_row("+19705551234", conf=0.70), "John Smith", "exact"),
        ]
        result = mod._apply_contact_filter(resolved, named_only=False, unnamed_only=False, names_first=True)
        assert result[0][1] == "John Smith"
        assert result[1][1] == ""

    def test_names_first_preserves_confidence_within_group(self):
        resolved = [
            (_fake_row("+19705550001", conf=0.7), "Alice", "exact"),
            (_fake_row("+19705550002", conf=0.9), "Bob", "exact"),
            (_fake_row("+15550001", conf=0.8), "", "none"),
        ]
        result = mod._apply_contact_filter(resolved, named_only=False, unnamed_only=False, names_first=True)
        names = [r[1] for r in result]
        assert names.index("Bob") < names.index("Alice")
        assert names.index("Alice") < names.index("")

    def test_names_first_default_true(self):
        """Calling with no explicit flags uses names_first=True."""
        resolved = [
            (_fake_row("+15559991111", conf=0.9), "", "none"),
            (_fake_row("+19705551234", conf=0.7), "John", "exact"),
        ]
        result = mod._apply_contact_filter(resolved)
        assert result[0][1] == "John"

    def test_named_only_empty_result(self):
        resolved = [(_fake_row("+15559991111"), "", "none")]
        assert mod._apply_contact_filter(resolved, named_only=True) == []

    def test_unnamed_only_empty_result(self):
        resolved = [(_fake_row("+19705551234"), "John Smith", "exact")]
        assert mod._apply_contact_filter(resolved, unnamed_only=True) == []

    def test_no_filter_preserves_input_order(self):
        resolved = [
            (_fake_row("+15559991111", conf=0.9), "", "none"),
            (_fake_row("+19705551234", conf=0.7), "John", "exact"),
        ]
        result = mod._apply_contact_filter(resolved, named_only=False, unnamed_only=False, names_first=False)
        assert result[0][0]["contact_handle"] == "+15559991111"


# ── Summary counts ────────────────────────────────────────────────────────────

class TestSummaryCounts:

    def test_pending_named_unnamed_counts(self, tmp_path, capsys):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+19705551234", "is_reviewed": -1},
            {"thread_id": "t2", "contact_handle": "+19705559876", "is_reviewed": -1},
            {"thread_id": "t3", "contact_handle": "+15559991111", "is_reviewed": -1},
        ])
        with patch.object(mod, "_lookup_contact_name", _named_for):
            conn = _open_conn(db)
            mod.print_summary(conn)
            conn.close()
        out = capsys.readouterr().out
        assert "named=2" in out
        assert "unnamed=1" in out

    def test_approved_named_unnamed_counts(self, tmp_path, capsys):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+19705551234", "is_reviewed": 1},
            {"thread_id": "t2", "contact_handle": "+15559991111", "is_reviewed": 1},
            {"thread_id": "t3", "contact_handle": "+15559992222", "is_reviewed": 1},
        ])
        with patch.object(mod, "_lookup_contact_name", _named_for):
            conn = _open_conn(db)
            mod.print_summary(conn)
            conn.close()
        out = capsys.readouterr().out
        assert "named=1" in out
        assert "unnamed=2" in out

    def test_all_unnamed_when_no_contacts(self, tmp_path, capsys):
        db = _create_thread_db(tmp_path, [
            {"thread_id": "t1", "contact_handle": "+15559991111", "is_reviewed": -1},
            {"thread_id": "t2", "contact_handle": "+15559992222", "is_reviewed": -1},
        ])
        with patch.object(mod, "_lookup_contact_name", lambda h: ""):
            conn = _open_conn(db)
            mod.print_summary(conn)
            conn.close()
        out = capsys.readouterr().out
        assert "named=0" in out
        assert "unnamed=2" in out

    def test_summary_zero_pending_when_empty(self, tmp_path, capsys):
        db = _create_thread_db(tmp_path, [])
        conn = _open_conn(db)
        mod.print_summary(conn)
        conn.close()
        out = capsys.readouterr().out
        assert "named=0" in out


# ── Snippet cleaning ──────────────────────────────────────────────────────────

class TestSnippetCleaning:

    def test_removes_bom_garbage(self):
        result = mod._clean_snippet("ï¿¼ hello world")
        assert "ï¿¼" not in result
        assert "hello world" in result

    def test_removes_iI_fragments(self):
        result = mod._clean_snippet("iI some real text")
        assert result == "some real text"

    def test_removes_plusamp_runs(self):
        result = mod._clean_snippet("before +& text +&& after")
        assert "+&" not in result
        assert "before" in result
        assert "text" in result

    def test_removes_underscore_tokens(self):
        result = mod._clean_snippet("__kIMMessagePartAttributeName some message")
        assert "__kIMMessagePartAttributeName" not in result
        assert "some message" in result

    def test_truncates_to_width(self):
        assert len(mod._clean_snippet("a" * 200, width=100)) == 100

    def test_empty_input(self):
        assert mod._clean_snippet("") == ""

    def test_none_input(self):
        assert mod._clean_snippet(None) == ""  # type: ignore

    def test_is_junk_short(self):
        assert mod._is_junk_snippet("hi") is True
        assert mod._is_junk_snippet("abc") is True

    def test_is_junk_mostly_symbols(self):
        assert mod._is_junk_snippet("!@#$%^&*()") is True

    def test_is_junk_valid_text(self):
        assert mod._is_junk_snippet("Control4 proposal sent") is False

    def test_is_junk_exactly_five_chars(self):
        assert mod._is_junk_snippet("hello") is False


# ── Snippet controls (display) ────────────────────────────────────────────────

class TestSnippetDisplay:

    def test_no_snippets_hides_content(self, capsys):
        with patch.object(mod, "_fetch_snippets",
                          return_value=[{"direction": "sent", "text": "Control4 proposal"}]):
            mod._print_thread_full(1, 5, _fake_row(), show_snippets=False)
        out = capsys.readouterr().out
        assert "Control4 proposal" not in out
        assert "recent:" not in out

    def test_snippets_shown_when_enabled(self, capsys):
        with patch.object(mod, "_fetch_snippets",
                          return_value=[{"direction": "sent", "text": "Control4 proposal"}]):
            mod._print_thread_full(1, 5, _fake_row(), show_snippets=True)
        assert "Control4 proposal" in capsys.readouterr().out

    def test_snippets_n_forwarded_to_fetch(self):
        calls: list[int] = []
        def _mock_fetch(chat_guid, n=mod.SNIPPET_DEFAULT, width=mod.SNIPPET_WIDTH):
            calls.append(n)
            return []
        with patch.object(mod, "_fetch_snippets", _mock_fetch):
            mod._print_thread_full(1, 5, _fake_row(), snippets=4, show_snippets=True)
        assert calls == [4]

    def test_snippet_limit_from_fake_db(self, tmp_path):
        """_fetch_snippets returns at most n snippets from a real SQLite DB."""
        db_path = tmp_path / "chat.db"
        _create_fake_chat_db(
            db_path, "test-guid",
            [f"Message number {i} about the Control4 system" for i in range(6)],
        )
        orig = mod.CHAT_DB
        mod.CHAT_DB = db_path
        try:
            result_1 = mod._fetch_snippets("test-guid", n=1)
            result_2 = mod._fetch_snippets("test-guid", n=2)
        finally:
            mod.CHAT_DB = orig
        assert len(result_1) <= 1
        assert len(result_2) <= 2


# ── Display format ────────────────────────────────────────────────────────────

class TestDisplayFormat:

    def test_full_named_shows_name_and_number(self, capsys):
        with patch.object(mod, "_fetch_snippets", return_value=[]):
            mod._print_thread_full(1, 50, _fake_row(), name="John Smith", match_type="exact")
        out = capsys.readouterr().out
        assert "John Smith" in out
        assert "+19705551234" in out
        assert "contact_match=exact" in out

    def test_full_unnamed_shows_number_only(self, capsys):
        with patch.object(mod, "_fetch_snippets", return_value=[]):
            mod._print_thread_full(2, 50, _fake_row("+15612519041"), name="", match_type="none")
        out = capsys.readouterr().out
        assert "+15612519041" in out
        assert "contact_match=none" in out
        # No accidental name leakage
        assert "John" not in out

    def test_safe_masks_phone(self, capsys):
        mod._print_thread_safe(1, 50, _fake_row("+19705551234"), name="John Smith", match_type="exact")
        out = capsys.readouterr().out
        assert "+19705551234" not in out
        assert "***" in out
        assert "named=yes" in out
        assert "contact_match=exact" in out

    def test_safe_unnamed_shows_no(self, capsys):
        mod._print_thread_safe(2, 50, _fake_row("+15612519041"), name="", match_type="none")
        out = capsys.readouterr().out
        assert "named=no" in out
        assert "contact_match=none" in out


# ── Review assist intelligence ────────────────────────────────────────────────

class TestAnalyzeThreadAssist:

    def test_required_keys(self):
        intel = mod.analyze_thread_assist("Test Person", ["hello world about Control4 systems"], [])
        required = {
            "suggested_relationship_type", "inferred_domain", "review_priority",
            "review_reason", "confidence", "risk_flags", "evidence",
        }
        assert required.issubset(set(intel.keys()))

    def test_gc_suffix_does_not_infer_builder(self):
        intel = mod.analyze_thread_assist("Travis GC", [], [])
        assert intel["suggested_relationship_type"] != "builder"
        assert "gc_suffix_ambiguous" in intel["risk_flags"]

    def test_gc_suffix_with_restaurant_signals_infers_restaurant_work(self):
        texts = ["The reservation is set for Friday dinner", "game creek has a new menu this season"]
        intel = mod.analyze_thread_assist("Travis GC", texts, [])
        assert intel["suggested_relationship_type"] == "restaurant_work"
        assert intel["inferred_domain"] == "restaurant_work"
        assert "gc_suffix_ambiguous" in intel["risk_flags"]

    def test_gc_suffix_with_tech_signals_infers_trade_partner_not_builder(self):
        texts = ["Control4 proposal for the rack", "keypad programming is done"]
        intel = mod.analyze_thread_assist("Travis GC", texts, ["strong:c4", "strong:finish"])
        assert intel["suggested_relationship_type"] == "trade_partner"
        assert intel["suggested_relationship_type"] != "builder"
        assert intel["inferred_domain"] == "smart_home_work"
        assert "gc_suffix_ambiguous" in intel["risk_flags"]

    def test_no_gc_suffix_with_builder_signals_infers_builder(self):
        texts = [
            "The jobsite framing is complete",
            "need permit inspection tomorrow",
            "hvac rough-in done and ready",
        ]
        intel = mod.analyze_thread_assist("John Contractor", texts, [])
        assert intel["suggested_relationship_type"] == "builder"
        assert "gc_suffix_ambiguous" not in intel["risk_flags"]

    def test_strong_tech_signals_infers_client(self):
        texts = [
            "Control4 system is working great",
            "Can you update the lighting scenes?",
            "The Sonos is having trouble with the theater zone",
        ]
        intel = mod.analyze_thread_assist("Jane Smith", texts, ["strong:c4"])
        assert intel["suggested_relationship_type"] == "client"
        assert intel["inferred_domain"] == "smart_home_work"

    def test_confidence_in_range(self):
        cases = [
            ("Unknown", []),
            ("Travis GC", ["game creek restaurant kitchen"]),
            ("Bob Smith", ["Control4 keypad dimmer lighting sonos theater composer"]),
        ]
        for name, texts in cases:
            intel = mod.analyze_thread_assist(name, texts, [])
            assert 0.0 <= intel["confidence"] <= 1.0, f"confidence out of range for {name}"

    def test_priority_is_valid(self):
        intel = mod.analyze_thread_assist("Test", [], [])
        assert intel["review_priority"] in ("high", "medium", "low")

    def test_no_auto_approve_keys(self):
        """analyze_thread_assist must never include is_reviewed or approval fields."""
        intel = mod.analyze_thread_assist(
            "John Smith",
            ["Control4 proposal Sonos install keypad programming lighting shades"],
            ["strong:c4"],
        )
        assert "is_reviewed" not in intel
        assert "approved" not in intel

    def test_has_gc_suffix_detection(self):
        assert mod._has_gc_suffix("Travis GC") is True
        assert mod._has_gc_suffix("Eagle GC") is True
        assert mod._has_gc_suffix("John Smith") is False
        assert mod._has_gc_suffix("GC Construction") is False
        assert mod._has_gc_suffix("") is False
        assert mod._has_gc_suffix("AGC") is False

    def test_gc_suffix_and_tech_signals_yields_high_priority(self):
        texts = ["Control4 programming done", "keypad installed at rack location"]
        intel = mod.analyze_thread_assist("Travis GC", texts, ["strong:c4", "strong:finish"])
        assert intel["review_priority"] == "high"

    def test_reason_codes_boost_tech_score(self):
        """reason_codes with c4/control4 should push classification toward tech domain."""
        intel_no_codes = mod.analyze_thread_assist("Unknown", [], [])
        intel_with_codes = mod.analyze_thread_assist("Unknown", [], ["strong:c4", "strong:control4"])
        assert intel_with_codes["inferred_domain"] == "smart_home_work"
        assert intel_with_codes["confidence"] >= intel_no_codes["confidence"]

    def test_vendor_signals_infer_vendor(self):
        texts = [
            "shipment from distributor arrived today",
            "purchase order is attached for the catalog items",
        ]
        intel = mod.analyze_thread_assist("Supply Co", texts, [])
        assert intel["suggested_relationship_type"] == "vendor"
        assert intel["inferred_domain"] == "vendor_supply"


# ── Count helper ──────────────────────────────────────────────────────────────

class TestCountNamedUnnamed:

    def test_count_with_mixed_handles(self):
        with patch.object(mod, "_lookup_contact_name", _named_for):
            named, unnamed = mod._count_named_unnamed([
                "+19705551234", "+13035550000", "+15559991111",
            ])
        assert named == 2
        assert unnamed == 1

    def test_count_all_unnamed(self):
        with patch.object(mod, "_lookup_contact_name", lambda h: ""):
            named, unnamed = mod._count_named_unnamed(["+15550001", "+15550002"])
        assert named == 0
        assert unnamed == 2

    def test_count_empty_list(self):
        named, unnamed = mod._count_named_unnamed([])
        assert named == 0
        assert unnamed == 0
