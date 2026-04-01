"""
Intel Feeds — Trading Intelligence Gathering Layer
===================================================
Always-on monitoring of public sources that feeds signals into the bot's decision making.

Monitors:
  - Reddit (r/Polymarket, r/sportsbetting, r/predictit)
  - RSS news feeds (AP, NOAA, ESPN, CoinDesk, FRED)
  - Polymarket platform (volume spikes, odds movements)

All signals flow through the signal_aggregator, which scores and routes them to:
  - Redis pub/sub channels for real-time consumption
  - SQLite for persistence and daily briefings
  - notifications:trading channel for critical alerts (iMessage)

Entry point:  python -m integrations.intel_feeds.runner
"""

__version__ = "1.0.0"
__all__ = [
    "reddit_monitor",
    "news_monitor",
    "polymarket_monitor",
    "signal_aggregator",
    "runner",
]

# Signal schema reference — every signal dict must conform to this shape
SIGNAL_SCHEMA = {
    "source": str,           # e.g. "reddit", "rss:ap_news", "polymarket"
    "timestamp": str,        # ISO-8601 UTC
    "relevance_score": int,  # 0-100
    "urgency": str,          # "low" | "medium" | "high" | "critical"
    "category": str,         # "weather" | "sports" | "crypto" | "politics" | "economics" | "general"
    "markets_affected": list, # list of market slugs / condition IDs
    "summary": str,          # human-readable one-liner
    "raw": dict,             # original payload from the source
}
