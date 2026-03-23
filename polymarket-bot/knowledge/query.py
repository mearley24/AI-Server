"""Query interface — strategies ask the markdown knowledge graph questions."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

KNOWLEDGE_DIR = Path(__file__).parent


class KnowledgeQuery:
    """Query interface for the markdown knowledge graph."""

    def __init__(self):
        self.knowledge_dir = KNOWLEDGE_DIR

    def search(
        self,
        query: str,
        ktype: str = None,
        tags: list[str] = None,
    ) -> list[dict]:
        """Full-text search across knowledge files.

        Args:
            query: Search term (case-insensitive).
            ktype: Filter by knowledge type (strategy, market, wallet, research).
            tags: Filter to files containing at least one of these tags.

        Returns:
            List of dicts with file, title, summary, confidence, relevance.
        """
        results = []

        for md_file in self.knowledge_dir.rglob("*.md"):
            if md_file.name.startswith(".") or "/sources/" in str(md_file):
                continue

            content = md_file.read_text()

            # Filter by type if specified
            if ktype:
                type_match = re.search(r"> Type:\s*(.+)", content)
                if type_match and ktype not in type_match.group(1):
                    continue

            # Filter by tags if specified
            if tags:
                tags_match = re.search(r"> Tags:\s*(.+)", content)
                if tags_match:
                    file_tags = [t.strip() for t in tags_match.group(1).split(",")]
                    if not any(t in file_tags for t in tags):
                        continue
                else:
                    continue  # no tags in file, skip

            # Full-text search
            if query.lower() in content.lower():
                title_match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
                summary_match = re.search(
                    r"## Summary\n(.+?)(?:\n#|\Z)", content, re.DOTALL
                )
                confidence_match = re.search(r"> Confidence:\s*(.+)", content)

                results.append(
                    {
                        "file": str(md_file.relative_to(self.knowledge_dir)),
                        "title": title_match.group(1) if title_match else md_file.stem,
                        "summary": (
                            summary_match.group(1).strip()[:200]
                            if summary_match
                            else ""
                        ),
                        "confidence": (
                            confidence_match.group(1).strip()
                            if confidence_match
                            else "unknown"
                        ),
                        "relevance": content.lower().count(query.lower()),
                    }
                )

        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results

    def get_strategy_knowledge(self, strategy_name: str) -> str:
        """Get all knowledge relevant to a specific strategy."""
        strategy_file = self.knowledge_dir / "strategies" / f"{strategy_name}.md"
        if strategy_file.exists():
            return strategy_file.read_text()

        # Search for mentions across all files
        results = self.search(strategy_name)
        if results:
            combined = ""
            for r in results[:5]:
                f = self.knowledge_dir / r["file"]
                combined += f"\n---\n## {r['title']}\n{f.read_text()}\n"
            return combined

        return ""

    def get_market_intel(self, platform: str) -> str:
        """Get current market intelligence for a platform."""
        market_file = self.knowledge_dir / "markets" / f"{platform}_markets.md"
        if market_file.exists():
            return market_file.read_text()
        return ""

    def get_wallet_patterns(self, wallet_name: str = None) -> str:
        """Get tracked wallet patterns.

        Args:
            wallet_name: Optional wallet identifier. If None, returns the index.
        """
        if wallet_name:
            for f in (self.knowledge_dir / "wallets").glob("*.md"):
                if wallet_name.lower() in f.stem.lower():
                    return f.read_text()

        # Return all wallet intel
        index = self.knowledge_dir / "wallets" / "_index.md"
        if index.exists():
            return index.read_text()
        return ""

    def get_recent_learnings(self, days: int = 7) -> str:
        """Get what Bob has learned recently.

        Args:
            days: Number of days to look back (default 7).
        """
        log_dir = self.knowledge_dir / "log"
        combined = ""
        for i in range(days):
            d = date.today() - timedelta(days=i)
            log_file = log_dir / f"{d.isoformat()}.md"
            if log_file.exists():
                combined += log_file.read_text() + "\n"
        return combined
