"""Tests for X intake quality gate (work-only mode).

Covers:
- political content → blocked
- rant content → blocked
- neutral/irrelevant content → blocked
- tech/work content → eligible
- blocked items never appear in Cortex default items view
- classification fields persisted to DB
- learning pipeline only receives eligible items
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _run(coro):
    return asyncio.run(coro)


# ─── Classifier unit tests ─────────────────────────────────────────────────────

class TestClassifierCategories:

    def test_ai_tech_tweet_is_work_eligible(self):
        from integrations.x_api.classifier import classify
        text = "Just shipped a new RAG pipeline with embeddings and LLM inference — 3x faster retrieval."
        clf = classify(text, item_type="post")
        assert clf.content_category == "work"
        assert clf.work_relevance_score >= 0.7
        assert clf.promoted_status == "eligible"
        assert not clf.quality_flags

    def test_smart_home_tweet_is_work_eligible(self):
        from integrations.x_api.classifier import classify
        text = "Smart home integration using Z-Wave controller — home automation done right."
        clf = classify(text, item_type="post")
        assert clf.content_category == "work"
        assert clf.promoted_status == "eligible"

    def test_political_tweet_is_non_work_blocked(self):
        from integrations.x_api.classifier import classify
        text = "Trump just signed the new executive order — Democrats are furious. Vote them out!"
        clf = classify(text, item_type="post")
        assert clf.content_category == "non_work"
        assert clf.promoted_status == "blocked"
        assert "political" in clf.quality_flags

    def test_political_flag_always_blocks(self):
        from integrations.x_api.classifier import classify
        # Even if text has some work terms mixed in
        text = "The Republican senate vote on AI regulation is terrible policy for software developers."
        clf = classify(text, item_type="post")
        assert "political" in clf.quality_flags
        assert clf.promoted_status == "blocked"

    def test_rant_is_blocked(self):
        from integrations.x_api.classifier import classify
        # Long text with lots of exclamation marks
        text = (
            "I CANNOT BELIEVE this garbage!!!! They are DESTROYING everything we worked for!!! "
            "This is absolutely INSANE and nobody is talking about it!!!! Wake up people!!!! "
            "This needs to STOP immediately before it's too late!!!!"
        )
        clf = classify(text, item_type="post")
        assert "rant" in clf.quality_flags or "emotional" in clf.quality_flags
        assert clf.promoted_status == "blocked"

    def test_emotional_caps_flagged(self):
        from integrations.x_api.classifier import classify
        text = "THIS IS COMPLETELY WRONG and NOBODY should accept THIS BEHAVIOR from anyone!"
        clf = classify(text, item_type="post")
        assert "emotional" in clf.quality_flags
        assert clf.promoted_status == "blocked"

    def test_irrelevant_neutral_tweet_is_blocked_or_pending(self):
        from integrations.x_api.classifier import classify
        text = "Great weather today! Enjoying my coffee ☕"
        clf = classify(text, item_type="post")
        # Not work-relevant — should be blocked or at best pending (neutral)
        assert clf.promoted_status in ("blocked", "pending")
        assert clf.content_category != "work" or clf.work_relevance_score < 0.7

    def test_low_signal_tweet_flagged(self):
        from integrations.x_api.classifier import classify
        text = "lol"
        clf = classify(text, item_type="post")
        assert "low_signal" in clf.quality_flags
        assert clf.promoted_status == "blocked"

    def test_unsafe_content_blocked_with_offensive_flag(self):
        from integrations.x_api.classifier import classify
        text = "kys you absolute loser"
        clf = classify(text, item_type="post")
        assert clf.content_category == "unsafe"
        assert clf.promoted_status == "blocked"
        assert "offensive" in clf.quality_flags

    def test_maga_politics_blocked(self):
        from integrations.x_api.classifier import classify
        text = "MAGA 2024! Trump is the only candidate who can save America from the radical left!"
        clf = classify(text, item_type="post")
        assert clf.promoted_status == "blocked"
        assert "political" in clf.quality_flags

    def test_war_news_blocked(self):
        from integrations.x_api.classifier import classify
        text = "Ceasefire talks in Gaza have collapsed again as Hamas rejects the proposal."
        clf = classify(text, item_type="post")
        assert clf.promoted_status == "blocked"

    def test_software_engineering_eligible(self):
        from integrations.x_api.classifier import classify
        text = "New open source framework for building multi-agent AI pipelines. Python SDK available."
        clf = classify(text, item_type="post")
        assert clf.content_category == "work"
        assert clf.promoted_status == "eligible"

    def test_startup_saas_work_score(self):
        from integrations.x_api.classifier import classify
        text = "We just hit $100k ARR with our B2B SaaS product. Automation workflows are our biggest driver."
        clf = classify(text, item_type="post")
        assert clf.content_category == "work"
        assert clf.work_relevance_score >= 0.5

    def test_empty_text_is_low_signal(self):
        from integrations.x_api.classifier import classify
        clf = classify(None, item_type="post")
        assert "low_signal" in clf.quality_flags
        assert clf.promoted_status == "blocked"

    def test_classification_reason_is_populated(self):
        from integrations.x_api.classifier import classify
        text = "Building a new LLM agent with RAG embeddings and vector search."
        clf = classify(text, item_type="post")
        assert "score=" in clf.classification_reason
        assert len(clf.classification_reason) > 10


class TestClassifierScoreRange:

    def test_score_always_between_0_and_1(self):
        from integrations.x_api.classifier import classify
        samples = [
            "TRUMP MAGA MAGA MAGA ELECTION VOTE REPUBLICAN DEMOCRAT!!!",
            "AI LLM RAG agents Claude Anthropic OpenAI transformer pipeline",
            "",
            "hello world",
            "kys garbage",
        ]
        for text in samples:
            clf = classify(text)
            assert 0.0 <= clf.work_relevance_score <= 1.0, f"Score out of range for: {text!r}"

    def test_promoted_status_always_valid(self):
        from integrations.x_api.classifier import classify
        for text in ["lol", "LLM agents are great", "Trump won the election vote MAGA"]:
            clf = classify(text)
            assert clf.promoted_status in ("eligible", "pending", "blocked")


# ─── Intake integration: classifier wired in ──────────────────────────────────

class TestIntakeQualityGate:
    """run_intake classifies and sets processed_status correctly."""

    def _make_tweet(self, text: str, post_id: str = "1") -> dict:
        return {
            "x_post_id":     post_id,
            "text":          text,
            "author_handle": "testuser",
            "author_name":   "Test",
            "created_at":    None,
            "urls":          [],
            "source":        "post",
        }

    def _env(self):
        return {
            "X_ENABLED": "1",
            "X_API_BEARER_TOKEN": "fake",
            "X_USER_ID": "123",
        }

    def test_work_tweet_stored_as_eligible(self, tmp_path):
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        tweets = [self._make_tweet(
            "Built a new RAG pipeline using LLM embeddings and vector search. Python SDK.",
            post_id="100"
        )]
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                result = run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                                    db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        assert result["eligible"] >= 1
        conn = sqlite3.connect(str(tmp_path / "db.sqlite"))
        row = conn.execute("SELECT processed_status, category FROM x_items WHERE x_post_id='100'").fetchone()
        conn.close()
        assert row[0] == "eligible"
        assert row[1] == "work"

    def test_political_tweet_stored_as_blocked(self, tmp_path):
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        tweets = [self._make_tweet(
            "Trump just won the election again — Democrats can't believe it! MAGA 2024!",
            post_id="200"
        )]
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                result = run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                                    db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        assert result["blocked"] >= 1
        conn = sqlite3.connect(str(tmp_path / "db.sqlite"))
        row = conn.execute(
            "SELECT processed_status, quality_flags FROM x_items WHERE x_post_id='200'"
        ).fetchone()
        conn.close()
        assert row[0] == "blocked"
        flags = json.loads(row[1])
        assert "political" in flags

    def test_rant_tweet_stored_as_blocked(self, tmp_path):
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        tweets = [self._make_tweet(
            "I CANNOT BELIEVE this GARBAGE!!!! They are DESTROYING everything!!!! "
            "WAKE UP PEOPLE this is ABSOLUTELY INSANE and nobody cares!!!!",
            post_id="300"
        )]
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                result = run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                                    db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        conn = sqlite3.connect(str(tmp_path / "db.sqlite"))
        row = conn.execute("SELECT processed_status FROM x_items WHERE x_post_id='300'").fetchone()
        conn.close()
        assert row[0] == "blocked"

    def test_work_relevance_score_persisted(self, tmp_path):
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        tweets = [self._make_tweet("LLM agent pipeline with RAG and embeddings.", post_id="400")]
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                           db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        conn = sqlite3.connect(str(tmp_path / "db.sqlite"))
        row = conn.execute(
            "SELECT work_relevance_score, classification_reason FROM x_items WHERE x_post_id='400'"
        ).fetchone()
        conn.close()
        assert row[0] is not None
        assert row[0] > 0
        assert row[1] is not None and "score=" in row[1]

    def test_learning_pipeline_skips_blocked_items(self, tmp_path):
        """Blocked URL items must NOT be routed to the learning pipeline."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        political_tweet = {
            "x_post_id":     "500",
            "text":          "Trump signs MAGA bill, Republicans cheer — vote your conscience",
            "author_handle": "news",
            "author_name":   "News",
            "created_at":    None,
            "urls":          ["https://example.com/article"],
            "source":        "post",
        }
        routed_paths: list[str] = []
        original_route = __import__(
            "integrations.x_api.intake", fromlist=["_maybe_route_to_learning"]
        )._maybe_route_to_learning

        def spy_route(item):
            routed_paths.append(item.x_item_id)
            return original_route(item)

        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=[political_tweet]):
                with patch(
                    "integrations.x_api.intake._maybe_route_to_learning",
                    side_effect=spy_route
                ):
                    run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                               db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        # _maybe_route_to_learning must not have been called for blocked items
        assert routed_paths == [], f"Blocked item was routed: {routed_paths}"

    def test_dry_run_includes_classification_counts(self, tmp_path):
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        tweets = [
            self._make_tweet(
                "New LLM agent pipeline with RAG embeddings, vector search, and Python SDK open source.",
                post_id="601"
            ),
            self._make_tweet("Trump MAGA vote election Republican Democrat!", post_id="602"),
        ]
        with patch.dict(os.environ, self._env(), clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=tweets):
                result = run_intake(dry_run=True, fetch_posts=True, fetch_likes=False,
                                    db_path=tmp_path / "db.sqlite", fetch_bookmarks=False)

        assert "blocked" in result
        assert "eligible" in result
        assert result["blocked"] >= 1
        assert result["eligible"] >= 1


# ─── Cortex endpoint: blocked items hidden by default ─────────────────────────

class TestCortexItemsGate:

    def _seed_db(self, db_path: Path):
        """Insert eligible and blocked items into a test DB."""
        from integrations.x_api.models import init_db, XItem, insert_item
        conn = init_db(db_path)
        insert_item(conn, XItem(
            x_item_id="eligible:1", item_type="post",
            text="LLM agent pipeline", processed_status="eligible",
            category="work", work_relevance_score=0.85,
            quality_flags=[], classification_reason="score=0.85",
        ))
        insert_item(conn, XItem(
            x_item_id="blocked:1", item_type="post",
            text="Trump MAGA vote", processed_status="blocked",
            category="non_work", work_relevance_score=0.1,
            quality_flags=["political"], classification_reason="score=0.1; flags=[political]",
        ))
        conn.close()

    def test_default_view_hides_blocked(self, tmp_path):
        """GET /api/x-api/items (no status param) must not return blocked items."""
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed_db(db_path)

        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, item_type="", status=""))

        item_ids = [i["x_item_id"] for i in result["items"]]
        assert "blocked:1" not in item_ids
        assert "eligible:1" in item_ids

    def test_status_blocked_shows_blocked_items(self, tmp_path):
        """GET /api/x-api/items?status=blocked returns only blocked items."""
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed_db(db_path)

        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, item_type="", status="blocked"))

        item_ids = [i["x_item_id"] for i in result["items"]]
        assert "blocked:1" in item_ids
        assert "eligible:1" not in item_ids

    def test_classification_fields_in_response(self, tmp_path):
        """Response items include category, score, flags, reason."""
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed_db(db_path)

        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50))

        eligible_items = [i for i in result["items"] if i["x_item_id"] == "eligible:1"]
        assert eligible_items
        item = eligible_items[0]
        assert item["category"] == "work"
        assert item["work_relevance_score"] == 0.85
        assert "classification_reason" in item


# ─── Reclassification of existing pending items ───────────────────────────────

class TestReclassifyExisting:
    """Existing pending items must be classified on --apply or --classify-existing."""

    def _insert_pending(self, db_path, x_item_id: str, text: str, item_type: str = "post"):
        """Insert a row as 'pending' (pre-quality-gate state)."""
        from integrations.x_api.models import init_db, XItem, insert_item
        conn = init_db(db_path)
        insert_item(conn, XItem(
            x_item_id=x_item_id,
            item_type=item_type,
            text=text,
            processed_status="pending",
        ))
        conn.close()

    def test_apply_reclassifies_pending_on_duplicate(self, tmp_path):
        """When --apply re-fetches an existing pending item, it must update its status."""
        from integrations.x_api.intake import run_intake
        from integrations.x_api.client import XReadOnlyClient

        db_path = tmp_path / "db.sqlite"
        # Pre-insert as 'pending' (simulating old pre-gate item)
        self._insert_pending(db_path, "post:777", "Trump wins MAGA vote Republican Democrat!")

        env = {"X_ENABLED": "1", "X_API_BEARER_TOKEN": "fake", "X_USER_ID": "123"}
        # Return the same tweet from the API
        tweet = {
            "x_post_id": "777",
            "text": "Trump wins MAGA vote Republican Democrat!",
            "author_handle": "user", "author_name": "User",
            "created_at": None, "urls": [], "source": "post",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(XReadOnlyClient, "get_user_tweets", return_value=[tweet]):
                run_intake(dry_run=False, fetch_posts=True, fetch_likes=False,
                           db_path=db_path, fetch_bookmarks=False)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT processed_status, category FROM x_items WHERE x_item_id='post:777'"
        ).fetchone()
        conn.close()
        # Must be reclassified to blocked (political content)
        assert row[0] == "blocked", f"Expected 'blocked', got {row[0]!r}"
        assert row[1] == "non_work"

    def test_classify_existing_updates_pending_rows(self, tmp_path):
        """classify_pending_items() must reclassify all pending rows."""
        from integrations.x_api.intake import classify_pending_items

        db_path = tmp_path / "db.sqlite"
        # Insert two pending rows with different content
        self._insert_pending(db_path, "post:A", "LLM RAG pipeline agent open source embeddings.")
        self._insert_pending(db_path, "post:B", "Trump MAGA Republican Democrat vote election!")

        os.environ["X_API_DB_PATH"] = str(db_path)
        try:
            result = classify_pending_items(db_path)
        finally:
            del os.environ["X_API_DB_PATH"]

        assert result["rows_processed"] == 2
        assert result["blocked"] >= 1   # political tweet
        assert result["eligible"] >= 0  # LLM tweet may be eligible

        conn = sqlite3.connect(str(db_path))
        rows = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT x_item_id, processed_status FROM x_items"
            ).fetchall()
        }
        conn.close()
        # Neither row should still be 'pending'
        assert rows.get("post:A") != "pending", f"post:A still pending: {rows}"
        assert rows.get("post:B") == "blocked", f"post:B not blocked: {rows}"

    def test_classify_existing_leaves_no_pending(self, tmp_path):
        """After classify_pending_items(), no rows remain pending."""
        from integrations.x_api.intake import classify_pending_items

        db_path = tmp_path / "db.sqlite"
        texts = [
            "lol", "Great weather", "Trump MAGA vote",
            "LLM agents and RAG embeddings pipeline",
        ]
        for i, text in enumerate(texts):
            self._insert_pending(db_path, f"post:{i}", text)

        result = classify_pending_items(db_path)
        assert result["rows_processed"] == 4
        assert result["pending_remain"] == 0

        conn = sqlite3.connect(str(db_path))
        still_pending = conn.execute(
            "SELECT COUNT(*) FROM x_items WHERE processed_status='pending'"
        ).fetchone()[0]
        conn.close()
        assert still_pending == 0

    def test_classify_existing_returns_summary(self, tmp_path):
        """Result dict has expected keys."""
        from integrations.x_api.intake import classify_pending_items
        result = classify_pending_items(tmp_path / "db.sqlite")
        assert "rows_processed" in result
        assert "blocked" in result
        assert "eligible" in result
        assert "pending_remain" in result
        assert result["status"] == "ok"


# ─── Status endpoint field names ──────────────────────────────────────────────

class TestStatusFieldNames:
    """Status endpoint must use eligible_items/pending_items/blocked_items."""

    def test_status_field_names(self, tmp_path):
        import cortex.engine as eng
        from integrations.x_api.models import init_db, XItem, insert_item

        db_path = tmp_path / "x_items.sqlite"
        conn = init_db(db_path)
        insert_item(conn, XItem(
            x_item_id="e:1", item_type="post", text="LLM pipeline",
            processed_status="eligible", category="work",
        ))
        insert_item(conn, XItem(
            x_item_id="b:1", item_type="post", text="Trump vote",
            processed_status="blocked", category="non_work",
        ))
        conn.close()

        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            with patch.dict(os.environ, {"X_ENABLED": "1"}, clear=False):
                result = _run(eng.x_api_status())

        assert "eligible_items" in result, f"Missing eligible_items in {list(result)}"
        assert "pending_items"  in result
        assert "blocked_items"  in result
        assert result["eligible_items"] == 1
        assert result["blocked_items"]  == 1
        # Old field names must not appear
        assert "items_eligible" not in result
        assert "items_pending"  not in result
        assert "items_blocked"  not in result


# ─── Status filter correctness ────────────────────────────────────────────────

class TestItemsStatusFilter:
    """?status= query param must correctly filter by processed_status."""

    def _seed(self, db_path):
        from integrations.x_api.models import init_db, XItem, insert_item
        conn = init_db(db_path)
        for sid, status, cat in [
            ("e:1", "eligible", "work"),
            ("b:1", "blocked",  "non_work"),
            ("b:2", "blocked",  "non_work"),
            ("p:1", "pending",  None),
        ]:
            insert_item(conn, XItem(
                x_item_id=sid, item_type="post", text="x",
                processed_status=status, category=cat,
            ))
        conn.close()

    def test_no_filter_hides_blocked(self, tmp_path):
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed(db_path)
        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, status=""))
        ids = {i["x_item_id"] for i in result["items"]}
        assert "b:1" not in ids and "b:2" not in ids
        assert "e:1" in ids
        assert "p:1" in ids

    def test_status_blocked_returns_only_blocked(self, tmp_path):
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed(db_path)
        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, status="blocked"))
        ids = {i["x_item_id"] for i in result["items"]}
        assert ids == {"b:1", "b:2"}

    def test_status_eligible_returns_only_eligible(self, tmp_path):
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed(db_path)
        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, status="eligible"))
        ids = {i["x_item_id"] for i in result["items"]}
        assert ids == {"e:1"}

    def test_status_pending_returns_only_pending(self, tmp_path):
        import cortex.engine as eng
        db_path = tmp_path / "x_items.sqlite"
        self._seed(db_path)
        with patch.object(eng, "_x_api_db_path", return_value=db_path):
            result = _run(eng.x_api_items(limit=50, status="pending"))
        ids = {i["x_item_id"] for i in result["items"]}
        assert ids == {"p:1"}
