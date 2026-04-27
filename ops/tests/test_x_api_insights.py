"""Tests for X Insight Extraction v1.

Covers:
- eligible item with work content → insight created
- blocked item → no insight (returns None)
- pending item → no insight (returns None)
- low relevance score → no insight (returns None)
- generic/short summary → no insight (returns None)
- topic detection maps keywords correctly
- insight_type detection works
- DB insert/duplicate guard
- pipeline processes eligible items only
- pipeline skips blocked items
- Cortex /api/x-api/insights endpoint returns correct shape
- summaries are short and non-generic
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _run(coro):
    return asyncio.run(coro)


def _make_item(
    x_item_id="post:123",
    text="Just shipped a new LLM agent pipeline with RAG embeddings and vector search.",
    processed_status="eligible",
    work_relevance_score=0.85,
    url=None,
    author_handle="testuser",
    item_type="post",
) -> dict:
    return {
        "x_item_id":            x_item_id,
        "item_type":            item_type,
        "text":                 text,
        "processed_status":     processed_status,
        "work_relevance_score": work_relevance_score,
        "url":                  url,
        "author_handle":        author_handle,
        "created_at":           "2026-04-26T12:00:00+00:00",
        "source":               "post",
    }


# ─── Extractor unit tests ──────────────────────────────────────────────────────

class TestExtractInsight:

    def test_eligible_item_creates_insight(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item()
        result = extract_insight(item)
        assert result is not None
        assert result.x_item_id == "post:123"
        assert result.relevance_score == 0.85
        assert len(result.summary) >= 30
        assert result.topic in ("ai_ml", "engineering", "smart_home", "av", "business", "general")
        assert result.insight_type in (
            "troubleshooting_tip", "workflow_improvement", "product_idea", "general_knowledge"
        )

    def test_blocked_item_returns_none(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item(processed_status="blocked", work_relevance_score=0.90)
        assert extract_insight(item) is None

    def test_pending_item_returns_none(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item(processed_status="pending", work_relevance_score=0.90)
        assert extract_insight(item) is None

    def test_low_score_returns_none(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item(
            processed_status="eligible",
            work_relevance_score=0.50,
            text="Some mildly technical post about software development.",
        )
        assert extract_insight(item) is None

    def test_generic_text_returns_none(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item(
            text="lol",
            processed_status="eligible",
            work_relevance_score=0.85,
        )
        assert extract_insight(item) is None

    def test_very_short_text_returns_none(self):
        from integrations.x_api.insight_extractor import extract_insight
        item = _make_item(
            text="See link",
            processed_status="eligible",
            work_relevance_score=0.85,
        )
        assert extract_insight(item) is None

    def test_summary_is_under_150_chars(self):
        from integrations.x_api.insight_extractor import extract_insight
        long_text = (
            "Building a new LLM agent pipeline with RAG embeddings, vector search, and Python SDK. "
            "The retrieval layer uses Postgres with pgvector. "
            "Inference is handled by Claude claude via Anthropic API. "
            "Integration with MCP enables tool use at runtime. "
            "Benchmarks show 3x improvement over the baseline."
        )
        item = _make_item(text=long_text, work_relevance_score=0.92)
        result = extract_insight(item)
        assert result is not None
        assert len(result.summary) <= 150

    def test_key_points_capped_at_three(self):
        from integrations.x_api.insight_extractor import extract_insight
        text = (
            "Building a new LLM agent pipeline. "
            "The retrieval layer uses Postgres. "
            "Inference is done by Claude. "
            "Integration with MCP enables tool use. "
            "Benchmarks show 3x improvement."
        )
        item = _make_item(text=text, work_relevance_score=0.90)
        result = extract_insight(item)
        if result:
            assert len(result.key_points) <= 3


class TestTopicDetection:

    def _topic(self, text: str) -> str:
        from integrations.x_api.insight_extractor import _detect_topic
        return _detect_topic(text.lower())

    def test_smart_home_keywords(self):
        assert self._topic("Z-Wave home automation setup with zigbee sensors") == "smart_home"

    def test_ai_ml_keywords(self):
        assert self._topic("RAG pipeline with LLM embeddings and vector search") == "ai_ml"

    def test_engineering_keywords(self):
        assert self._topic("Docker deployment with Postgres and Redis backend") == "engineering"

    def test_business_keywords(self):
        assert self._topic("SaaS startup raised seed round from investors") == "business"

    def test_unknown_falls_back_to_general(self):
        assert self._topic("Had a great lunch today at the office") == "general"


class TestInsightTypeDetection:

    def _itype(self, text: str) -> str:
        from integrations.x_api.insight_extractor import _detect_insight_type
        return _detect_insight_type(text.lower())

    def test_troubleshooting_tip(self):
        assert self._itype("Fixed the Docker error by rebuilding the image") == "troubleshooting_tip"

    def test_workflow_improvement(self):
        assert self._itype("This tip saves hours — automate your deployment pipeline") == "workflow_improvement"

    def test_product_idea(self):
        assert self._itype("Just launched a new feature for smart home control") == "product_idea"

    def test_default_general_knowledge(self):
        assert self._itype("LLM agents are fundamentally different from regular software") == "general_knowledge"


# ─── Insight models tests ──────────────────────────────────────────────────────

class TestInsightModels:

    def _make_db(self, tmp_path: Path):
        from integrations.x_api.insight_models import init_db
        return init_db(tmp_path / "x_insights.sqlite")

    def test_init_creates_table(self, tmp_path):
        conn = self._make_db(tmp_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in tables}
        assert "x_insights" in names
        conn.close()

    def test_insert_and_retrieve(self, tmp_path):
        from integrations.x_api.insight_models import XInsight, insert_insight, get_insights
        conn = self._make_db(tmp_path)
        insight = XInsight(
            x_item_id="post:999",
            topic="ai_ml",
            insight_type="general_knowledge",
            summary="RAG pipelines dramatically improve LLM retrieval accuracy.",
            key_points=["Use vector embeddings", "Chunk documents carefully"],
            relevance_score=0.88,
            source_url="https://example.com/rag",
            author_handle="testuser",
        )
        assert insert_insight(conn, insight) is True
        results = get_insights(conn)
        assert len(results) == 1
        assert results[0]["x_item_id"] == "post:999"
        assert results[0]["topic"] == "ai_ml"
        assert isinstance(results[0]["key_points"], list)
        conn.close()

    def test_duplicate_insert_returns_false(self, tmp_path):
        from integrations.x_api.insight_models import XInsight, insert_insight
        conn = self._make_db(tmp_path)
        insight = XInsight(
            x_item_id="post:dupe",
            topic="general",
            insight_type="general_knowledge",
            summary="Duplicate test insight for idempotency checking.",
            relevance_score=0.75,
        )
        assert insert_insight(conn, insight) is True
        assert insert_insight(conn, insight) is False
        conn.close()

    def test_get_insights_topic_filter(self, tmp_path):
        from integrations.x_api.insight_models import XInsight, insert_insight, get_insights
        conn = self._make_db(tmp_path)
        for i, topic in enumerate(["ai_ml", "business", "ai_ml"]):
            insert_insight(conn, XInsight(
                x_item_id=f"post:{i}",
                topic=topic,
                insight_type="general_knowledge",
                summary=f"Test insight number {i} about relevant work topics.",
                relevance_score=0.80,
            ))
        ai_results = get_insights(conn, topic="ai_ml")
        assert len(ai_results) == 2
        biz_results = get_insights(conn, topic="business")
        assert len(biz_results) == 1
        conn.close()


# ─── Pipeline tests ────────────────────────────────────────────────────────────

class TestInsightPipeline:

    def _make_items_db(self, tmp_path: Path, items: list[dict]) -> Path:
        from integrations.x_api.models import init_db, XItem, insert_item
        db_path = tmp_path / "x_items.sqlite"
        conn = init_db(db_path)
        for item in items:
            xi = XItem(
                x_item_id=            item["x_item_id"],
                item_type=            item.get("item_type", "post"),
                text=                 item.get("text"),
                processed_status=     item.get("processed_status", "eligible"),
                work_relevance_score= item.get("work_relevance_score", 0.85),
                author_handle=        item.get("author_handle", "test"),
                source=               item.get("source", "post"),
            )
            insert_item(conn, xi)
        conn.close()
        return db_path

    def test_eligible_item_is_extracted(self, tmp_path):
        from integrations.x_api.insight_pipeline import run_insight_extraction
        items_db = self._make_items_db(tmp_path, [_make_item()])
        insights_db = tmp_path / "x_insights.sqlite"
        result = run_insight_extraction(
            items_db_path=items_db,
            insights_db_path=insights_db,
            dry_run=False,
        )
        assert result["status"] == "ok"
        assert result["processed"] == 1
        assert result["errors"] == []

    def test_blocked_item_never_extracted(self, tmp_path):
        from integrations.x_api.insight_pipeline import run_insight_extraction
        items_db = self._make_items_db(tmp_path, [
            _make_item(processed_status="blocked", x_item_id="post:blocked1"),
        ])
        insights_db = tmp_path / "x_insights.sqlite"
        result = run_insight_extraction(
            items_db_path=items_db,
            insights_db_path=insights_db,
            dry_run=False,
        )
        assert result["created"] == 0
        assert result["errors"] == []

    def test_dry_run_does_not_write(self, tmp_path):
        from integrations.x_api.insight_pipeline import run_insight_extraction
        from integrations.x_api.insight_models import init_db, get_insights
        items_db = self._make_items_db(tmp_path, [_make_item()])
        insights_db = tmp_path / "x_insights.sqlite"
        result = run_insight_extraction(
            items_db_path=items_db,
            insights_db_path=insights_db,
            dry_run=True,
        )
        assert result["status"] == "dry_run"
        # DB should be empty (nothing written)
        conn = init_db(insights_db)
        assert get_insights(conn) == []
        conn.close()

    def test_mixed_statuses_only_eligible_extracted(self, tmp_path):
        from integrations.x_api.insight_pipeline import run_insight_extraction
        from integrations.x_api.insight_models import init_db, get_insights
        items_db = self._make_items_db(tmp_path, [
            _make_item(x_item_id="post:e1", processed_status="eligible"),
            _make_item(x_item_id="post:b1", processed_status="blocked"),
            _make_item(x_item_id="post:p1", processed_status="pending"),
        ])
        insights_db = tmp_path / "x_insights.sqlite"
        run_insight_extraction(
            items_db_path=items_db,
            insights_db_path=insights_db,
            dry_run=False,
        )
        conn = init_db(insights_db)
        results = get_insights(conn)
        conn.close()
        # Only eligible item should appear; blocked/pending items are not in
        # x_items as eligible so they won't be fetched by the pipeline query
        for r in results:
            assert r["x_item_id"] != "post:b1"
            assert r["x_item_id"] != "post:p1"


# ─── Cortex endpoint tests ─────────────────────────────────────────────────────

class TestCortexInsightsEndpoint:

    def _populated_insights_db(self, tmp_path: Path) -> Path:
        from integrations.x_api.insight_models import XInsight, init_db, insert_insight
        db_path = tmp_path / "x_insights.sqlite"
        conn = init_db(db_path)
        insert_insight(conn, XInsight(
            x_item_id="post:i1",
            topic="ai_ml",
            insight_type="general_knowledge",
            summary="RAG pipelines dramatically improve LLM retrieval quality and speed.",
            key_points=["Use vector embeddings", "Chunk documents at 512 tokens"],
            relevance_score=0.88,
            source_url="https://example.com/rag",
            author_handle="researcher",
        ))
        insert_insight(conn, XInsight(
            x_item_id="post:i2",
            topic="smart_home",
            insight_type="troubleshooting_tip",
            summary="Fixed Z-Wave pairing failure by resetting node and re-including with S2 security.",
            key_points=["Reset Z-Wave node first", "Use S2 Authenticated security level"],
            relevance_score=0.91,
            author_handle="smarthomedev",
        ))
        conn.close()
        return db_path

    def test_insights_endpoint_returns_correct_shape(self, tmp_path):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        db_path = self._populated_insights_db(tmp_path)

        from unittest.mock import patch
        with patch(
            "cortex.engine._x_insights_db_path",
            return_value=db_path,
        ):
            from cortex.engine import x_api_insights
            result = _run(x_api_insights())

        assert result["status"] == "ok"
        assert result["count"] == 2
        insight = result["insights"][0]
        for key in ("x_item_id", "topic", "insight_type", "summary",
                    "key_points", "relevance_score", "source_url", "extracted_at"):
            assert key in insight

    def test_insights_endpoint_no_db_returns_empty(self, tmp_path):
        from unittest.mock import patch
        with patch("cortex.engine._x_insights_db_path", return_value=None):
            from cortex.engine import x_api_insights
            result = _run(x_api_insights())
        assert result["status"] == "no_db"
        assert result["insights"] == []

    def test_insights_endpoint_topic_filter(self, tmp_path):
        db_path = self._populated_insights_db(tmp_path)
        from unittest.mock import patch
        with patch("cortex.engine._x_insights_db_path", return_value=db_path):
            from cortex.engine import x_api_insights
            result = _run(x_api_insights(topic="smart_home"))
        assert result["count"] == 1
        assert result["insights"][0]["topic"] == "smart_home"

    def test_summary_non_generic_in_db(self, tmp_path):
        db_path = self._populated_insights_db(tmp_path)
        from unittest.mock import patch
        with patch("cortex.engine._x_insights_db_path", return_value=db_path):
            from cortex.engine import x_api_insights
            result = _run(x_api_insights())
        for insight in result["insights"]:
            summary = insight["summary"]
            assert len(summary) >= 30, f"Summary too short: {summary!r}"
            assert len(summary) <= 150, f"Summary too long: {summary!r}"
