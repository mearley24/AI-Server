"""Knowledge ingestion pipeline — processes raw intel into structured markdown files."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx

KNOWLEDGE_DIR = Path(__file__).parent
SOURCES_DIR = KNOWLEDGE_DIR / "sources"
LOG_DIR = KNOWLEDGE_DIR / "log"


class KnowledgeIngester:
    """Processes raw intel into structured knowledge files."""

    def __init__(self, anthropic_api_key: str = None):
        self.api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.knowledge_dir = KNOWLEDGE_DIR

    async def ingest_text(
        self,
        text: str,
        source_url: str = None,
        source_type: str = "manual",
    ) -> dict:
        """Ingest raw text into the knowledge graph.

        Returns the structured extraction dict with title, type, tags, etc.
        """
        extraction = await self._extract_knowledge(text, source_url)

        target_file = self._classify_target(extraction)

        self._store_knowledge(target_file, extraction)

        self._update_links(target_file, extraction)

        self._log_learning(extraction, source_url)

        return extraction

    async def ingest_url(self, url: str) -> dict:
        """Fetch content from a URL and ingest it."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            text = resp.text

        return await self.ingest_text(text, source_url=url, source_type="url")

    async def ingest_trade_result(self, trade: dict) -> dict:
        """Ingest a completed trade's results for strategy refinement."""
        strategy = trade.get("strategy", "unknown")
        platform = trade.get("platform", "unknown")
        pnl = trade.get("pnl", 0)
        market = trade.get("market_id", "unknown")

        text = (
            f"Trade completed on {platform}:\n"
            f"Strategy: {strategy}\n"
            f"Market: {market}\n"
            f"P&L: ${pnl:.2f}\n"
            f"Entry: {trade.get('entry_price')}, Exit: {trade.get('exit_price')}\n"
            f"Duration: {trade.get('duration_minutes', 'unknown')} minutes\n"
            f"Signal confidence: {trade.get('confidence', 'unknown')}\n"
            f"Debate result: {trade.get('debate_result', 'unknown')}\n"
        )

        return await self.ingest_text(text, source_type="trade_result")

    async def _extract_knowledge(self, text: str, source_url: str = None) -> dict:
        """Use Claude to extract structured knowledge from raw text."""
        prompt = f"""Analyze this trading/market intelligence and extract structured knowledge.

Source URL: {source_url or 'N/A'}
Raw text:
{text[:4000]}

Return a JSON object with:
{{
    "title": "short descriptive title",
    "type": "strategy|market|wallet|research|pattern",
    "tags": ["tag1", "tag2"],
    "confidence": "high|medium|low",
    "summary": "1-2 sentence summary",
    "key_facts": ["fact 1", "fact 2"],
    "numbers": {{"key": "value"}},
    "related_strategies": ["strategy names that could use this"],
    "action_items": ["things to implement or track"],
    "links_to": ["existing knowledge files this relates to"]
}}

Focus on actionable trading intelligence. Ignore fluff."""

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            data = resp.json()
            content = data["content"][0]["text"]
            # Extract JSON from response (may be wrapped in markdown code block)
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"title": "Unknown", "type": "research", "summary": content[:200]}

    def _classify_target(self, extraction: dict) -> Path:
        """Determine which knowledge file to update."""
        ktype = extraction.get("type", "research")
        title = extraction.get("title", "unknown").lower()
        slug = re.sub(r"[^a-z0-9]+", "_", title).strip("_")

        type_dirs = {
            "strategy": "strategies",
            "market": "markets",
            "wallet": "wallets",
            "research": "research",
            "pattern": "strategies",
        }

        subdir = type_dirs.get(ktype, "research")
        return self.knowledge_dir / subdir / f"{slug}.md"

    def _store_knowledge(self, target: Path, extraction: dict) -> None:
        """Write or append to a knowledge file."""
        target.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()

        if target.exists():
            existing = target.read_text()
            new_section = f"\n\n## Update {today}\n"
            new_section += f"**Summary:** {extraction.get('summary', '')}\n\n"
            for fact in extraction.get("key_facts", []):
                new_section += f"- {fact}\n"
            if extraction.get("action_items"):
                new_section += "\n**Action Items:**\n"
                for item in extraction["action_items"]:
                    new_section += f"- [ ] {item}\n"
            target.write_text(existing + new_section)
        else:
            content = f"""# {extraction.get('title', 'Unknown')}

> Type: {extraction.get('type', 'research')}
> Tags: {', '.join(extraction.get('tags', []))}
> Created: {today}
> Updated: {today}
> Confidence: {extraction.get('confidence', 'medium')}
> Status: active

## Summary
{extraction.get('summary', '')}

## Key Facts
"""
            for fact in extraction.get("key_facts", []):
                content += f"- {fact}\n"

            if extraction.get("numbers"):
                content += "\n## Numbers\n"
                for k, v in extraction["numbers"].items():
                    content += f"- **{k}**: {v}\n"

            if extraction.get("related_strategies"):
                content += "\n## Related Strategies\n"
                for s in extraction["related_strategies"]:
                    content += f"- [[strategies/{s}]]\n"

            if extraction.get("action_items"):
                content += "\n## Action Items\n"
                for item in extraction["action_items"]:
                    content += f"- [ ] {item}\n"

            target.write_text(content)

    def _update_links(self, target: Path, extraction: dict) -> None:
        """Add backlinks from related files."""
        for link in extraction.get("links_to", []):
            link_path = self.knowledge_dir / link
            if link_path.exists():
                existing = link_path.read_text()
                relative = os.path.relpath(target, link_path.parent)
                backlink = f"- [[{relative}]]"
                if backlink not in existing:
                    link_path.write_text(existing + f"\n{backlink}\n")

    def _log_learning(self, extraction: dict, source_url: str = None) -> None:
        """Append to today's learning log."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        log_file = LOG_DIR / f"{today}.md"

        entry = f"\n### {datetime.now().strftime('%H:%M')} — {extraction.get('title', 'Unknown')}\n"
        entry += f"- Type: {extraction.get('type', 'unknown')}\n"
        entry += f"- Summary: {extraction.get('summary', '')}\n"
        if source_url:
            entry += f"- Source: {source_url}\n"
        entry += f"- Confidence: {extraction.get('confidence', 'unknown')}\n"

        if log_file.exists():
            log_file.write_text(log_file.read_text() + entry)
        else:
            header = f"# Learning Log — {today}\n\nWhat Bob learned today.\n"
            log_file.write_text(header + entry)
