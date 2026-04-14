"""X Bookmark Folder Organizer — categorize and ingest X bookmarks into Cortex."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import httpx

sys.path.insert(0, "/app")

logger = logging.getLogger(__name__)

VALID_CATEGORIES = [
    "trading_alpha",
    "prediction_markets",
    "crypto",
    "ai_agents",
    "smart_home",
    "business",
    "macro",
    "sports",
    "weather",
    "general",
]

CATEGORIZE_PROMPT = """Categorize this X/Twitter post into exactly ONE of these categories:
- trading_alpha: trading strategies, market analysis, price targets
- prediction_markets: Polymarket, Kalshi, prediction market news
- crypto: cryptocurrency news, DeFi, on-chain analysis
- ai_agents: AI, MCP, autonomous agents, LLM tools
- smart_home: Control4, Lutron, home automation, AV
- business: entrepreneurship, SaaS, client acquisition
- macro: Fed, inflation, economic policy, geopolitics
- sports: NBA, NFL, MLB, UFC betting/analysis
- weather: weather events, hurricane tracking
- general: everything else

Post by @{author}: "{text}"

Reply with ONLY the category name, nothing else."""

HIGH_VALUE_CATEGORIES = {"trading_alpha", "prediction_markets"}


class BookmarkOrganizer:
    """Categorize X bookmarks and ingest them into Cortex as structured memories."""

    def __init__(self, cortex_url: str, bookmarks_path: str) -> None:
        self.cortex_url = cortex_url.rstrip("/")
        self.bookmarks_path = bookmarks_path
        self._bookmarks: list[dict] = []

    def _load_bookmarks(self) -> list[dict]:
        """Load bookmarks from JSON file."""
        if self._bookmarks:
            return self._bookmarks
        try:
            with open(self.bookmarks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._bookmarks = data
            elif isinstance(data, dict):
                self._bookmarks = data.get("bookmarks", data.get("items", []))
            else:
                self._bookmarks = []
            logger.info("bookmarks_loaded count=%d", len(self._bookmarks))
        except FileNotFoundError:
            logger.warning("bookmarks_file_not_found path=%s", self.bookmarks_path)
            self._bookmarks = []
        except Exception as exc:
            logger.error("bookmarks_load_error path=%s error=%s", self.bookmarks_path, str(exc)[:200])
            self._bookmarks = []
        return self._bookmarks

    async def _categorize_batch(self, batch: list[dict]) -> list[str]:
        """Categorize a batch of bookmarks using LLM Router."""
        from openclaw.llm_router import completion

        categories = []
        for bookmark in batch:
            author = bookmark.get("author", "unknown")
            text = (bookmark.get("text") or bookmark.get("content") or "")[:300]
            if not text:
                categories.append("general")
                continue

            prompt = CATEGORIZE_PROMPT.format(author=author, text=text)
            try:
                result = await completion(
                    prompt=prompt,
                    complexity="simple",
                    cache_ttl=86400,
                    service="bookmark_organizer",
                    max_tokens=20,
                    temperature=0.1,
                )
                raw_cat = (result.get("content") or "general").strip().lower()
                raw_cat = raw_cat.split()[0] if raw_cat.split() else "general"
                raw_cat = raw_cat.rstrip(".,;:")
                if raw_cat in VALID_CATEGORIES:
                    categories.append(raw_cat)
                else:
                    categories.append("general")
            except Exception as exc:
                logger.warning("categorize_failed author=%s error=%s", author, str(exc)[:100])
                categories.append("general")

        return categories

    async def categorize_all(self) -> dict[str, list[dict]]:
        """Categorize every bookmark and group by category."""
        bookmarks = self._load_bookmarks()
        if not bookmarks:
            return {}

        categorized: dict[str, list[dict]] = {cat: [] for cat in VALID_CATEGORIES}

        batch_size = 10
        for i in range(0, len(bookmarks), batch_size):
            batch = bookmarks[i : i + batch_size]
            batch_cats = await self._categorize_batch(batch)
            for bookmark, cat in zip(batch, batch_cats):
                bookmark["_category"] = cat
                categorized[cat].append(bookmark)
            logger.info(
                "categorize_progress batch=%d/%d",
                min(i + batch_size, len(bookmarks)),
                len(bookmarks),
            )

        non_empty = {k: v for k, v in categorized.items() if v}
        logger.info(
            "categorize_done total=%d categories=%d",
            len(bookmarks),
            len(non_empty),
        )
        return non_empty

    def _format_category_summary(self, category: str, items: list[dict]) -> str:
        """Format a list of bookmarks into a readable Cortex memory."""
        lines = [f"X Bookmarks category: {category}", f"Total posts: {len(items)}", ""]
        for i, bm in enumerate(items[:50], 1):
            author = bm.get("author", "unknown")
            text = (bm.get("text") or bm.get("content") or "")[:280]
            url = bm.get("url", "")
            has_video = bm.get("has_video", False)
            video_flag = " [VIDEO]" if has_video else ""
            lines.append(f"{i}. @{author}{video_flag}: {text}")
            if url:
                lines.append(f"   {url}")
            lines.append("")
        return "\n".join(lines).strip()

    async def ingest_to_cortex(self, categorized: dict[str, list[dict]]) -> dict:
        """POST each category group to Cortex /remember."""
        results = {
            "total_bookmarks": sum(len(v) for v in categorized.values()),
            "categories_ingested": 0,
            "high_value_triggered": 0,
            "errors": 0,
            "details": {},
        }

        for category, items in categorized.items():
            if not items:
                continue

            summary = self._format_category_summary(category, items)
            payload = {
                "category": "x_bookmarks",
                "title": f"X Bookmarks: {category} ({len(items)} posts)",
                "content": summary,
                "source": "bookmark_organizer",
                "importance": 6,
                "tags": ["x_bookmarks", category, "batch_import"],
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(f"{self.cortex_url}/remember", json=payload)
                    if r.status_code in (200, 201):
                        results["categories_ingested"] += 1
                        results["details"][category] = {"stored": True, "count": len(items)}
                        logger.info("cortex_ingested category=%s count=%d", category, len(items))
                    else:
                        results["errors"] += 1
                        results["details"][category] = {"stored": False, "status": r.status_code}
                        logger.warning("cortex_ingest_failed category=%s status=%d", category, r.status_code)
            except Exception as exc:
                results["errors"] += 1
                results["details"][category] = {"stored": False, "error": str(exc)[:100]}
                logger.error("cortex_ingest_error category=%s error=%s", category, str(exc)[:200])

            if category in HIGH_VALUE_CATEGORIES:
                triggered = await self._trigger_video_pipeline(items)
                results["high_value_triggered"] += triggered

        return results

    async def _trigger_video_pipeline(self, items: list[dict]) -> int:
        """Trigger video transcription for high-value bookmarks that have video."""
        triggered = 0
        video_items = [bm for bm in items if bm.get("has_video") or bm.get("has_images")]
        if not video_items:
            return 0

        for bm in video_items[:10]:
            url = bm.get("url")
            if not url:
                continue
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        "http://localhost:8101/analyze",
                        json={"url": url, "source": "bookmark_organizer"},
                    )
                triggered += 1
                logger.info("video_pipeline_triggered url=%s", url[:80])
            except Exception as exc:
                logger.warning("video_trigger_failed url=%s error=%s", url[:60], str(exc)[:80])

        return triggered
