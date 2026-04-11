"""Cortex migration — seeds brain.db from existing knowledge sources.

Run once on first startup (engine.py checks if DB is empty).
Sources:
  - AGENT_LEARNINGS.md   → trading_rule memories
  - ideas.txt            → strategy_idea memories
  - polymarket-bot/knowledge/ → strategy_performance, whale_intel, market_pattern, external_research
  - cortex/seed_data.json → meta_learning
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from cortex.config import (
    AGENT_LEARNINGS_PATH,
    IDEAS_PATH,
    KNOWLEDGE_DIR,
)
from cortex.memory import MemoryStore

logger = structlog.get_logger(__name__)


# ── AGENT_LEARNINGS.md → trading_rule ─────────────────────────────────────────

_TRADING_RULES: list[dict] = [
    {
        "title": "Avoid entries below 40 cents",
        "content": (
            "Only 35% WR on entries <40c vs 47% for >40c entries (206 markets tracked). "
            "Longshot bets lose 2 out of 3 times and winners don't pay enough to cover losses. "
            "Exception: crypto dip-to markets with METAR-style data."
        ),
        "confidence": 0.85,
        "importance": 9,
        "tags": ["entry_price", "win_rate", "critical"],
    },
    {
        "title": "High conviction entries >80c have 83% win rate",
        "content": (
            "Entries above 80c have 83% WR (best tier). "
            "When the market already agrees something will happen, the remaining 17c is usually free money. "
            "Actively seek and size up these opportunities."
        ),
        "confidence": 0.90,
        "importance": 10,
        "tags": ["entry_price", "win_rate", "high_conviction"],
    },
    {
        "title": "Keep position size below $5 default",
        "content": (
            "Positions <$5 have 78% WR and +$63 net. "
            "Medium positions $5-10 have 43% WR and lose money. "
            "Large positions >$20 have 33% WR — never use. "
            "Default = $3. Scale to $5 for >80% WR wallets. Scale to $10 for >90% WR wallets with >30 resolved."
        ),
        "confidence": 0.92,
        "importance": 10,
        "tags": ["position_size", "win_rate", "critical"],
    },
    {
        "title": "Stop trading at midnight MDT",
        "content": (
            "0:00 MDT has 29% WR — worst time slot. "
            "Late-night copies come from overseas wallets trading thin markets. "
            "Suppress new buys between 11pm-5am MDT. Let existing positions ride."
        ),
        "confidence": 0.88,
        "importance": 9,
        "tags": ["time_of_day", "win_rate", "schedule"],
    },
    {
        "title": "1am-4am MDT is the best trading window",
        "content": (
            "1-4am MDT has 88% WR — best time slot. "
            "Fewer markets, higher quality signals. "
            "Priority window for automated entries."
        ),
        "confidence": 0.80,
        "importance": 8,
        "tags": ["time_of_day", "win_rate", "schedule"],
    },
    {
        "title": "Avoid US sports and international soccer",
        "content": (
            "US sports: 40% WR, -$15 net. Soccer_intl: 40% WR, -$8 net. "
            "Close matchups (NBA spreads, NHL games, soccer friendlies) are coin flips. "
            "Set us_sports multiplier to 0.3x, soccer_intl to 0.2x. "
            "Only enter if wallet WR >85% in that specific category."
        ),
        "confidence": 0.88,
        "importance": 9,
        "tags": ["category", "avoidance", "sports"],
    },
    {
        "title": "Never buy both sides of the same event",
        "content": (
            "Both-sides buying destroyed ~$50+ on day 1. "
            "Block at event slug level, not just condition ID. "
            "20 events had multiple outcome buys (Up AND Down, both CS teams, etc)."
        ),
        "confidence": 0.99,
        "importance": 10,
        "tags": ["both_sides", "risk_management", "critical"],
    },
    {
        "title": "Crypto up/down is the best category post-fix",
        "content": (
            "Crypto_updown: 75% WR, +$57 net (45W, 15L). "
            "Best earner but ONLY after both-sides fix. "
            "Keep the both-sides guard, keep position sizing small."
        ),
        "confidence": 0.85,
        "importance": 9,
        "tags": ["category", "crypto", "win_rate"],
    },
    {
        "title": "Esports (CS2/Valorant) has genuine edge via copied wallets",
        "content": (
            "Esports: 71% WR, +$28 net (5W, 2L). Big swings — winners are huge. "
            "The copied wallets genuinely know matchups. Keep but watch liquidity."
        ),
        "confidence": 0.78,
        "importance": 8,
        "tags": ["category", "esports", "copytrade"],
    },
    {
        "title": "Tennis copytrade works — specific wallets have real edge",
        "content": (
            "Tennis: 75% WR, +$18 net (6W, 2L). "
            "@tradecraft (0xde9f...) is a tennis specialist with 2139% ROI. "
            "Consistent edge from copied wallets. Trust them."
        ),
        "confidence": 0.82,
        "importance": 8,
        "tags": ["category", "tennis", "copytrade", "wallet"],
    },
    {
        "title": "Priority wallets: @tradecraft and @coldmath",
        "content": (
            "@tradecraft 0xde9f... — Tennis specialist, 2139% ROI. "
            "@coldmath 0x594e... — Weather via aviation data, $89K+. "
            "Any wallet with >85% WR on >30 resolved in a SPECIFIC category is trustworthy."
        ),
        "confidence": 0.90,
        "importance": 9,
        "tags": ["wallet", "copytrade", "priority"],
    },
    {
        "title": "Weather with METAR aviation data has edge",
        "content": (
            "Weather: 43% WR overall (barely positive). "
            "BUT Dallas and Shanghai wins proved METAR aviation data provides real edge. "
            "Avoid large positions on exact temperatures (43% WR). "
            "Use aviation data for entry decisions."
        ),
        "confidence": 0.75,
        "importance": 7,
        "tags": ["category", "weather", "metar", "aviation"],
    },
    {
        "title": "Kraken P/L must be tracked separately from Polymarket",
        "content": (
            "Kraken losses contaminated overall P/L accounting. "
            "Always track Kraken P/L independently. "
            "Do not include Kraken in Polymarket performance reports."
        ),
        "confidence": 0.95,
        "importance": 8,
        "tags": ["kraken", "accounting", "infrastructure"],
        "category": "infrastructure",
    },
    {
        "title": "Code pushed but not deployed needs explicit restart",
        "content": (
            "Multiple incidents where code was pushed to git but container was not rebuilt. "
            "Always run docker compose up -d --build <service> after code changes. "
            "Use symphony-ship.sh for standard deploys."
        ),
        "confidence": 0.95,
        "importance": 8,
        "tags": ["deployment", "docker", "infrastructure"],
        "category": "infrastructure",
    },
]


async def _migrate_agent_learnings(memory: MemoryStore) -> int:
    """Parse AGENT_LEARNINGS.md and create trading_rule memories."""
    count = 0

    # First, load the hardcoded rules extracted from the file
    for rule in _TRADING_RULES:
        cat = rule.pop("category", "trading_rule")
        memory.remember(
            category=cat,
            title=rule["title"],
            content=rule["content"],
            source="AGENT_LEARNINGS.md",
            confidence=rule.get("confidence", 0.8),
            importance=rule.get("importance", 8),
            tags=rule.get("tags", []),
        )
        count += 1

    # Then try to parse the file for any additional context
    if AGENT_LEARNINGS_PATH.exists():
        try:
            text = AGENT_LEARNINGS_PATH.read_text()
            # Extract any 2026-dated learning sections
            sections = re.findall(
                r"## (20\d{2}-\d{2}-\d{2} .+?)\n(.*?)(?=\n## |$)",
                text,
                re.DOTALL,
            )
            for title, body in sections:
                body = body.strip()
                if len(body) > 50:
                    memory.remember(
                        category="infrastructure",
                        title=f"Lesson: {title.strip()[:80]}",
                        content=body[:1000],
                        source="AGENT_LEARNINGS.md",
                        confidence=0.85,
                        importance=7,
                        tags=["lesson", "infrastructure"],
                    )
                    count += 1
        except Exception as exc:
            logger.warning("agent_learnings_parse_error", error=str(exc))

    logger.info("migrated_agent_learnings", count=count)
    return count


# ── ideas.txt → strategy_idea ──────────────────────────────────────────────────


async def _migrate_ideas(memory: MemoryStore) -> int:
    """Parse ideas.txt and create strategy_idea memories."""
    if not IDEAS_PATH.exists():
        logger.warning("ideas_txt_not_found", path=str(IDEAS_PATH))
        return 0

    count = 0
    text = IDEAS_PATH.read_text()
    blocks = [b.strip() for b in text.split("---") if b.strip()]

    for block in blocks:
        idea: dict[str, str] = {}
        for line in block.split("\n"):
            if ": " in line:
                key, _, value = line.partition(": ")
                idea[key.strip()] = value.strip()

        if "IDEA" not in idea:
            continue

        status = idea.get("STATUS", "pending").lower()
        if status == "implementing":
            importance = 8
            tags = ["active", "implementing"]
        elif status == "pending":
            importance = 6
            tags = ["pending"]
        elif status == "rejected":
            importance = 2
            tags = ["rejected"]
        else:
            importance = 5
            tags = [status]

        content = idea.get("HYPOTHESIS", idea.get("DESCRIPTION", ""))
        notes = idea.get("NOTES", "")
        if notes:
            content = f"{content}\n\nNotes: {notes}"

        memory.remember(
            category="strategy_idea",
            title=idea["IDEA"],
            content=content,
            source="ideas.txt",
            confidence=0.5,
            importance=importance,
            tags=tags,
            metadata={"date": idea.get("DATE", ""), "status": status},
        )
        count += 1

    logger.info("migrated_ideas", count=count)
    return count


# ── polymarket-bot/knowledge/ → various categories ─────────────────────────────


_KNOWLEDGE_CATEGORY_MAP: dict[str, str] = {
    "strategies": "strategy_performance",
    "wallets": "whale_intel",
    "markets": "market_pattern",
    "research": "external_research",
}


async def _migrate_knowledge_dir(memory: MemoryStore) -> int:
    """Walk knowledge/ and ingest markdown files into appropriate categories."""
    if not KNOWLEDGE_DIR.exists():
        logger.warning("knowledge_dir_not_found", path=str(KNOWLEDGE_DIR))
        return 0

    count = 0
    for subdir_name, category in _KNOWLEDGE_CATEGORY_MAP.items():
        subdir = KNOWLEDGE_DIR / subdir_name
        if not subdir.exists():
            continue
        for md_file in subdir.glob("*.md"):
            try:
                content = md_file.read_text()
                if len(content) < 20:
                    continue
                title = md_file.stem.replace("_", " ").replace("-", " ").title()
                memory.remember(
                    category=category,
                    title=f"{title} ({subdir_name})",
                    content=content[:2000],  # cap at 2000 chars
                    source=str(md_file),
                    confidence=0.7,
                    importance=6,
                    tags=[subdir_name, "knowledge_dir"],
                )
                count += 1
            except Exception as exc:
                logger.warning("knowledge_file_error", file=str(md_file), error=str(exc))

    logger.info("migrated_knowledge_dir", count=count)
    return count


# ── cortex/seed_data.json → meta_learning ─────────────────────────────────────


async def _migrate_seed_data(memory: MemoryStore) -> int:
    """Parse cortex/seed_data.json timeline → meta_learning memories."""
    seed_path = Path(__file__).parent / "seed_data.json"
    if not seed_path.exists():
        return 0

    count = 0
    try:
        data = json.loads(seed_path.read_text())
        timeline = data if isinstance(data, list) else data.get("timeline", [])
        for entry in timeline:
            if isinstance(entry, dict):
                title = entry.get("title", entry.get("event", ""))
                content = entry.get("description", entry.get("content", str(entry)))
                date = entry.get("date", "")
                if title and content:
                    memory.remember(
                        category="meta_learning",
                        title=f"History: {title[:80]}",
                        content=f"{content}\n\nDate: {date}" if date else content,
                        source="cortex/seed_data.json",
                        confidence=0.75,
                        importance=5,
                        tags=["history", "timeline"],
                    )
                    count += 1
    except Exception as exc:
        logger.warning("seed_data_parse_error", error=str(exc))

    logger.info("migrated_seed_data", count=count)
    return count


# ── Main migration entrypoint ──────────────────────────────────────────────────


async def run_migration(memory: MemoryStore) -> dict[str, int]:
    """Run all migrations. Returns counts per source."""
    logger.info("cortex_migration_started")

    results = {
        "trading_rules": await _migrate_agent_learnings(memory),
        "ideas": await _migrate_ideas(memory),
        "knowledge_dir": await _migrate_knowledge_dir(memory),
        "seed_data": await _migrate_seed_data(memory),
    }

    total = sum(results.values())
    logger.info("cortex_migration_complete", total=total, breakdown=results)
    return results
