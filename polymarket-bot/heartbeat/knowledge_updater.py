"""Feed strategy review results back into the knowledge graph."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class KnowledgeUpdater:
    """Updates the knowledge graph with strategy performance data from heartbeat reviews."""

    async def update_from_review(self, strategy_reviews: list[dict]) -> None:
        """Update knowledge files based on strategy performance.

        For each strategy with trades > 0, formats performance data as text
        and feeds it into the knowledge graph via KnowledgeIngester.
        Flags underperforming strategies and highlights strong ones.
        """
        try:
            from knowledge.ingest import KnowledgeIngester
        except ImportError:
            logger.warning("knowledge_ingester_not_available", msg="Skipping knowledge update")
            return

        ingester = KnowledgeIngester()

        for review in strategy_reviews:
            if review["trades"] == 0:
                continue

            text = (
                f"Strategy performance review for {review['name']} "
                f"on {review['platform']}:\n"
                f"- Signals generated: {review['signals']}\n"
                f"- Trades executed: {review['trades']}\n"
                f"- Win rate: {review['win_rate']}\n"
                f"- P&L: ${review['pnl']:.2f}\n"
                f"- Average trade size: ${review['avg_trade_size']:.2f}\n"
                f"- Average hold time: {review['avg_hold_time_min']:.0f} minutes\n"
                f"- Status: {review['status']}\n"
            )

            if review["status"] == "underperforming":
                text += (
                    "\nATTENTION: This strategy is underperforming. "
                    "Consider parameter adjustments or temporary pause.\n"
                )
            elif review["status"] == "strong":
                text += (
                    "\nThis strategy is performing well. "
                    "Consider increasing position size or adding similar setups.\n"
                )

            try:
                await ingester.ingest_text(
                    text,
                    source_url=None,
                    source_type="heartbeat_review",
                )
                logger.info(
                    "knowledge_updated",
                    strategy=review["name"],
                    status=review["status"],
                )
            except Exception as e:
                logger.error(
                    "knowledge_update_failed",
                    strategy=review["name"],
                    error=str(e),
                )
