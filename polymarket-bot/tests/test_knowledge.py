"""Tests for the knowledge ingestion pipeline."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge.ingest import KnowledgeIngester
from knowledge.query import KnowledgeQuery


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def knowledge_dir(tmp_path):
    """Create a temporary knowledge directory with seed data."""
    kdir = tmp_path / "knowledge"
    for subdir in ("strategies", "markets", "wallets", "research", "log", "sources"):
        (kdir / subdir).mkdir(parents=True)

    # Seed a strategy file
    (kdir / "strategies" / "latency_patterns.md").write_text(
        "# Latency Patterns\n\n"
        "> Type: strategy\n"
        "> Tags: latency, BTC, momentum\n"
        "> Created: 2026-03-23\n"
        "> Updated: 2026-03-23\n"
        "> Confidence: high\n"
        "> Status: active\n\n"
        "## Summary\n"
        "9-16 second window after BTC >0.11% move on Binance.\n\n"
        "## Key Facts\n"
        "- $1.67M wallet exploits this pattern\n"
        "- Entry after 9s, exit by 16s\n"
    )

    # Seed a market file
    (kdir / "markets" / "kalshi_markets.md").write_text(
        "# Kalshi Markets\n\n"
        "> Type: market\n"
        "> Tags: Kalshi, CFTC, regulated\n"
        "> Created: 2026-03-23\n"
        "> Updated: 2026-03-23\n"
        "> Confidence: high\n"
        "> Status: active\n\n"
        "## Summary\n"
        "CFTC-regulated prediction market with binary contracts.\n\n"
        "## Key Facts\n"
        "- Maker fees ~4x lower than taker\n"
    )

    # Seed a wallet file
    (kdir / "wallets" / "_index.md").write_text(
        "# Tracked Wallets\n\n"
        "> Type: wallet\n"
        "> Tags: wallets, tracking\n"
        "> Created: 2026-03-23\n"
        "> Updated: 2026-03-23\n"
        "> Confidence: high\n"
        "> Status: active\n\n"
        "## Summary\n"
        "Master index of tracked wallets.\n"
    )

    (kdir / "wallets" / "latency_167m.md").write_text(
        "# Latency Whale\n\n"
        "> Type: wallet\n"
        "> Tags: whale, latency, BTC\n"
        "> Created: 2026-03-23\n"
        "> Updated: 2026-03-23\n"
        "> Confidence: high\n"
        "> Status: active\n\n"
        "## Summary\n"
        "$1.67M wallet trading BTC momentum.\n"
    )

    return kdir


@pytest.fixture
def query(knowledge_dir):
    """KnowledgeQuery pointed at the temp knowledge dir."""
    q = KnowledgeQuery()
    q.knowledge_dir = knowledge_dir
    return q


@pytest.fixture
def ingester(knowledge_dir):
    """KnowledgeIngester pointed at the temp knowledge dir."""
    ing = KnowledgeIngester(anthropic_api_key="test-key")
    ing.knowledge_dir = knowledge_dir
    return ing


# ── Query Tests ───────────────────────────────────────────────────────────

class TestKnowledgeQuery:

    def test_search_finds_matching_files(self, query):
        results = query.search("BTC")
        assert len(results) >= 2  # latency_patterns.md + latency_167m.md
        # Results sorted by relevance (count of matches)
        assert all("file" in r for r in results)

    def test_search_with_type_filter(self, query):
        results = query.search("BTC", ktype="strategy")
        assert len(results) >= 1
        for r in results:
            assert "strategies/" in r["file"]

    def test_search_with_tag_filter(self, query):
        results = query.search("", ktype=None, tags=["CFTC"])
        assert len(results) >= 1
        assert any("kalshi" in r["file"] for r in results)

    def test_search_no_results(self, query):
        results = query.search("nonexistent_term_xyz123")
        assert results == []

    def test_get_strategy_knowledge_direct(self, query):
        content = query.get_strategy_knowledge("latency_patterns")
        assert "Latency Patterns" in content
        assert "9-16 second" in content

    def test_get_strategy_knowledge_by_search(self, query):
        # No file named "btc_momentum.md" but search should find mentions
        content = query.get_strategy_knowledge("BTC")
        assert content  # should find via search fallback

    def test_get_strategy_knowledge_not_found(self, query):
        content = query.get_strategy_knowledge("totally_nonexistent_strategy")
        assert content == ""

    def test_get_market_intel(self, query):
        content = query.get_market_intel("kalshi")
        assert "Kalshi Markets" in content
        assert "CFTC" in content

    def test_get_market_intel_not_found(self, query):
        content = query.get_market_intel("binance")
        assert content == ""

    def test_get_wallet_patterns_index(self, query):
        content = query.get_wallet_patterns()
        assert "Tracked Wallets" in content

    def test_get_wallet_patterns_by_name(self, query):
        content = query.get_wallet_patterns("latency")
        assert "$1.67M" in content

    def test_get_recent_learnings_empty(self, query):
        content = query.get_recent_learnings(days=1)
        assert content == ""  # no log files in seed data

    def test_get_recent_learnings_with_data(self, query, knowledge_dir):
        today = date.today().isoformat()
        log_file = knowledge_dir / "log" / f"{today}.md"
        log_file.write_text("# Learning Log\n\n### 10:00 — Test entry\n- Learned something\n")

        content = query.get_recent_learnings(days=1)
        assert "Test entry" in content
        assert "Learned something" in content


# ── Ingester Tests ────────────────────────────────────────────────────────

class TestKnowledgeIngester:

    def test_classify_target_strategy(self, ingester):
        extraction = {"type": "strategy", "title": "New Weather Pattern"}
        target = ingester._classify_target(extraction)
        assert "strategies" in str(target)
        assert target.name == "new_weather_pattern.md"

    def test_classify_target_market(self, ingester):
        extraction = {"type": "market", "title": "Binance Updates"}
        target = ingester._classify_target(extraction)
        assert "markets" in str(target)

    def test_classify_target_wallet(self, ingester):
        extraction = {"type": "wallet", "title": "New Whale"}
        target = ingester._classify_target(extraction)
        assert "wallets" in str(target)

    def test_classify_target_pattern_goes_to_strategies(self, ingester):
        extraction = {"type": "pattern", "title": "Flash Pattern"}
        target = ingester._classify_target(extraction)
        assert "strategies" in str(target)

    def test_classify_target_unknown_goes_to_research(self, ingester):
        extraction = {"type": "unknown_type", "title": "Some Info"}
        target = ingester._classify_target(extraction)
        assert "research" in str(target)

    def test_store_knowledge_creates_new_file(self, ingester, knowledge_dir):
        extraction = {
            "title": "Test Knowledge",
            "type": "research",
            "tags": ["test", "unit"],
            "confidence": "low",
            "summary": "This is a test.",
            "key_facts": ["Fact one", "Fact two"],
            "numbers": {"threshold": "0.05"},
            "related_strategies": ["stink_bid"],
            "action_items": ["Track this"],
        }
        target = knowledge_dir / "research" / "test_knowledge.md"
        ingester._store_knowledge(target, extraction)

        assert target.exists()
        content = target.read_text()
        assert "# Test Knowledge" in content
        assert "> Type: research" in content
        assert "> Tags: test, unit" in content
        assert "> Confidence: low" in content
        assert "This is a test." in content
        assert "- Fact one" in content
        assert "- Fact two" in content
        assert "- **threshold**: 0.05" in content
        assert "[[strategies/stink_bid]]" in content
        assert "- [ ] Track this" in content

    def test_store_knowledge_appends_to_existing(self, ingester, knowledge_dir):
        target = knowledge_dir / "strategies" / "latency_patterns.md"
        original = target.read_text()

        extraction = {
            "summary": "New finding about latency.",
            "key_facts": ["Window may be narrowing"],
            "action_items": ["Re-validate timing"],
        }
        ingester._store_knowledge(target, extraction)

        updated = target.read_text()
        assert original in updated  # original content preserved
        assert "New finding about latency." in updated
        assert "Window may be narrowing" in updated
        assert "- [ ] Re-validate timing" in updated

    def test_log_learning_creates_log_file(self, ingester, knowledge_dir):
        # Point log dir to temp
        import knowledge.ingest as ingest_mod
        original_log_dir = ingest_mod.LOG_DIR
        ingest_mod.LOG_DIR = knowledge_dir / "log"

        extraction = {
            "title": "Test Log Entry",
            "type": "strategy",
            "summary": "Learned something new.",
            "confidence": "medium",
        }
        ingester._log_learning(extraction, source_url="https://example.com")

        today = date.today().isoformat()
        log_file = knowledge_dir / "log" / f"{today}.md"
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test Log Entry" in content
        assert "Learned something new." in content
        assert "https://example.com" in content

        # Restore
        ingest_mod.LOG_DIR = original_log_dir

    def test_log_learning_appends_to_existing_log(self, ingester, knowledge_dir):
        import knowledge.ingest as ingest_mod
        original_log_dir = ingest_mod.LOG_DIR
        ingest_mod.LOG_DIR = knowledge_dir / "log"

        today = date.today().isoformat()
        log_file = knowledge_dir / "log" / f"{today}.md"
        log_file.write_text("# Learning Log\n\nExisting content.\n")

        extraction = {"title": "Second Entry", "type": "market", "summary": "More info.", "confidence": "high"}
        ingester._log_learning(extraction)

        content = log_file.read_text()
        assert "Existing content." in content
        assert "Second Entry" in content
        assert "More info." in content

        ingest_mod.LOG_DIR = original_log_dir

    def test_update_links_adds_backlink(self, ingester, knowledge_dir):
        target = knowledge_dir / "strategies" / "new_strategy.md"
        target.write_text("# New Strategy\n\nSome content.\n")

        extraction = {"links_to": ["strategies/latency_patterns.md"]}
        ingester._update_links(target, extraction)

        linked = knowledge_dir / "strategies" / "latency_patterns.md"
        content = linked.read_text()
        assert "[[new_strategy.md]]" in content

    def test_update_links_skips_nonexistent(self, ingester, knowledge_dir):
        target = knowledge_dir / "strategies" / "new_strategy.md"
        target.write_text("# New Strategy\n")

        # Should not raise even if linked file doesn't exist
        extraction = {"links_to": ["strategies/nonexistent.md"]}
        ingester._update_links(target, extraction)

    @pytest.mark.asyncio
    async def test_ingest_text_full_pipeline(self, ingester, knowledge_dir):
        """Test the full ingest pipeline with a mocked Claude response."""
        import knowledge.ingest as ingest_mod
        original_log_dir = ingest_mod.LOG_DIR
        ingest_mod.LOG_DIR = knowledge_dir / "log"

        mock_extraction = {
            "title": "BTC Flash Pattern",
            "type": "strategy",
            "tags": ["BTC", "flash"],
            "confidence": "medium",
            "summary": "BTC flash crashes create buying opportunities.",
            "key_facts": ["Drop >5% in 1 minute triggers", "Recovery within 15 minutes"],
            "numbers": {"drop_threshold": "5%"},
            "related_strategies": ["flash_crash"],
            "action_items": ["Backtest with historical data"],
            "links_to": [],
        }

        with patch.object(ingester, "_extract_knowledge", new_callable=AsyncMock, return_value=mock_extraction):
            result = await ingester.ingest_text("BTC dropped 5% and recovered quickly")

        assert result["title"] == "BTC Flash Pattern"
        assert result["type"] == "strategy"

        # Verify file was created
        expected_file = knowledge_dir / "strategies" / "btc_flash_pattern.md"
        assert expected_file.exists()
        content = expected_file.read_text()
        assert "BTC flash crashes" in content
        assert "Drop >5% in 1 minute" in content

        # Verify log entry was created
        today = date.today().isoformat()
        log_file = knowledge_dir / "log" / f"{today}.md"
        assert log_file.exists()
        assert "BTC Flash Pattern" in log_file.read_text()

        ingest_mod.LOG_DIR = original_log_dir

    @pytest.mark.asyncio
    async def test_ingest_trade_result(self, ingester, knowledge_dir):
        """Test trade result ingestion with mocked extraction."""
        import knowledge.ingest as ingest_mod
        original_log_dir = ingest_mod.LOG_DIR
        ingest_mod.LOG_DIR = knowledge_dir / "log"

        mock_extraction = {
            "title": "Latency Detector Win",
            "type": "strategy",
            "tags": ["trade-result", "latency"],
            "confidence": "high",
            "summary": "Profitable latency trade on Polymarket.",
            "key_facts": ["$12.50 profit on BTC 5m up"],
            "numbers": {"pnl": "$12.50"},
            "related_strategies": ["latency_detector"],
            "action_items": [],
            "links_to": [],
        }

        with patch.object(ingester, "_extract_knowledge", new_callable=AsyncMock, return_value=mock_extraction):
            result = await ingester.ingest_trade_result({
                "strategy": "latency_detector",
                "platform": "polymarket",
                "market_id": "BTC-5min-up",
                "pnl": 12.50,
                "entry_price": 0.45,
                "exit_price": 0.58,
                "duration_minutes": 3,
                "confidence": 0.82,
                "debate_result": "bull_wins",
            })

        assert result["title"] == "Latency Detector Win"

        ingest_mod.LOG_DIR = original_log_dir


# ── Seed Data Validation Tests ────────────────────────────────────────────

class TestSeedData:
    """Verify the pre-populated knowledge files exist and are well-formed."""

    KNOWLEDGE_ROOT = Path(__file__).parent.parent / "knowledge"

    @pytest.fixture(autouse=True)
    def skip_if_no_knowledge(self):
        if not self.KNOWLEDGE_ROOT.exists():
            pytest.skip("Knowledge directory not found")

    @pytest.mark.parametrize("filepath", [
        "strategies/latency_patterns.md",
        "strategies/weather_edges.md",
        "strategies/fed_calendar.md",
        "strategies/sports_patterns.md",
        "strategies/crypto_correlations.md",
        "strategies/mean_reversion_params.md",
        "markets/kalshi_markets.md",
        "markets/polymarket_markets.md",
        "markets/crypto_tokens.md",
        "wallets/_index.md",
        "wallets/latency_167m.md",
        "wallets/sports_619k.md",
        "wallets/coldmath_80k.md",
        "research/moon_dev_rbi.md",
        "research/marginal_polytope.md",
    ])
    def test_seed_file_exists(self, filepath):
        full_path = self.KNOWLEDGE_ROOT / filepath
        assert full_path.exists(), f"Seed file missing: {filepath}"

    @pytest.mark.parametrize("filepath", [
        "strategies/latency_patterns.md",
        "strategies/weather_edges.md",
        "markets/kalshi_markets.md",
        "wallets/latency_167m.md",
        "research/moon_dev_rbi.md",
    ])
    def test_seed_file_has_required_headers(self, filepath):
        full_path = self.KNOWLEDGE_ROOT / filepath
        content = full_path.read_text()

        # Must have a title
        assert content.startswith("# "), f"{filepath} missing title"
        # Must have metadata headers
        assert "> Type:" in content, f"{filepath} missing Type header"
        assert "> Tags:" in content, f"{filepath} missing Tags header"
        assert "> Created:" in content, f"{filepath} missing Created header"
        assert "> Updated:" in content, f"{filepath} missing Updated header"
        assert "> Confidence:" in content, f"{filepath} missing Confidence header"
        assert "> Status:" in content, f"{filepath} missing Status header"
        # Must have Summary section
        assert "## Summary" in content, f"{filepath} missing Summary section"
        # Must have Key Facts section
        assert "## Key Facts" in content, f"{filepath} missing Key Facts section"

    def test_search_seed_data(self):
        """Verify search works against actual seed data."""
        query = KnowledgeQuery()
        results = query.search("BTC")
        assert len(results) > 0, "Search for 'BTC' should find seed data"

    def test_get_strategy_knowledge_seed(self):
        query = KnowledgeQuery()
        content = query.get_strategy_knowledge("latency_patterns")
        assert "9-16" in content

    def test_get_market_intel_seed(self):
        query = KnowledgeQuery()
        content = query.get_market_intel("kalshi")
        assert "CFTC" in content

    def test_get_wallet_patterns_seed(self):
        query = KnowledgeQuery()
        content = query.get_wallet_patterns()
        assert "Tracked" in content
