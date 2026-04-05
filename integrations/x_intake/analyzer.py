"""
analyzer.py
-----------
Analyzes a fetched X/Twitter post for trading intelligence.

v1 uses keyword matching and pattern detection — no LLM required.
Designed to be upgraded with LLM calls in a future version.

Analysis covers:
  - Trading signals (price targets, predictions, breakout calls)
  - Market sentiment (bullish/bearish on specific assets)
  - Whale activity mentions
  - Polymarket-relevant events
  - Strategy ideas
  - Cross-reference against current open positions
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

try:
    from .post_fetcher import PostData
except ImportError:
    from post_fetcher import PostData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

# Asset / ticker detection — broad coverage
CRYPTO_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ALGO", "ICP", "FIL", "VET",
    "HBAR", "ETC", "MANA", "SAND", "APE", "ARB", "OP", "SUI", "SEI", "TIA",
    "INJ", "PEPE", "WIF", "BONK", "JTO", "PYTH", "JUP", "W", "ZK", "STRK",
    "ENA", "ETHFI", "REZ", "OMNI", "SAGA", "BB", "IO", "ZRO", "BLAST", "BOME",
    "RENDER", "WLD", "NEAR", "FTM", "CRV", "AAVE", "COMP", "MKR", "SNX",
    "BITCOIN", "ETHEREUM", "SOLANA", "RIPPLE", "CARDANO", "DOGECOIN",
}

STOCK_TICKERS = {
    "AAPL", "MSFT", "TSLA", "NVDA", "AMZN", "GOOGL", "META", "NFLX", "SPY",
    "QQQ", "GME", "AMC", "PLTR", "COIN", "MSTR", "MARA", "RIOT", "HOOD",
    "SPX", "NDX", "VIX", "DXY",
}

PREDICTION_MARKET_KEYWORDS = {
    "polymarket", "kalshi", "manifold", "prediction market",
    "will trump", "will biden", "will the fed", "will btc", "will eth",
    "probability", "odds", "chance", "likelihood", "bet", "resolve",
}

BULLISH_SIGNALS = {
    "bullish", "buy", "long", "moon", "pump", "breakout", "rip", "run",
    "accumulate", "dip buy", "support", "bounce", "golden cross", "uptrend",
    "all time high", "ath", "new high", "target", "upside", "rally",
    "reversal", "bottom", "oversold", "undervalued", "cheap",
    "load up", "loading", "stacking", "adding", "conviction", "strong",
}

BEARISH_SIGNALS = {
    "bearish", "sell", "short", "dump", "crash", "drop", "fall", "down",
    "resistance", "overbought", "overvalued", "expensive", "top",
    "distribution", "death cross", "downtrend", "breakdown",
    "lower", "correction", "capitulation", "bear market",
}

WHALE_SIGNALS = {
    "whale", "large order", "block trade", "institutional", "smart money",
    "big buy", "big sell", "massive", "huge", "$1m", "$10m", "$100m",
    "million", "billion", "accumulation", "distribution",
    "on-chain", "exchange outflow", "exchange inflow", "wallet",
}

STRATEGY_SIGNALS = {
    "strategy", "edge", "alpha", "setup", "trade idea", "trade plan",
    "risk/reward", "risk reward", "r/r", "entry", "exit", "stop loss",
    "take profit", "tp", "sl", "dca", "dollar cost", "hedge",
    "options", "calls", "puts", "futures", "perps", "leverage",
    "scalp", "swing trade", "position trade", "spot", "arbitrage",
}

# Common Polymarket event categories
POLYMARKET_CATEGORIES = {
    "election": ["election", "vote", "president", "congress", "senate", "governor", "ballot"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "defi", "nft"],
    "fed": ["fed", "fomc", "interest rate", "rate hike", "rate cut", "powell", "inflation", "cpi"],
    "sports": ["super bowl", "world cup", "nba", "nfl", "mlb", "championship", "playoff"],
    "ai": ["chatgpt", "gpt", "openai", "anthropic", "gemini", "llm", "ai model"],
    "geo": ["war", "ceasefire", "invasion", "conflict", "nato", "ukraine", "russia", "china"],
    "finance": ["ipo", "earnings", "merger", "acquisition", "bankruptcy", "s&p", "recession"],
}

# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    """Structured analysis output for a fetched post."""

    relevance_score: float = 0.0          # 0.0–1.0
    sentiment: str = "neutral"            # bullish | bearish | neutral | mixed
    assets_mentioned: list = field(default_factory=list)
    markets_mentioned: list = field(default_factory=list)   # Polymarket categories
    signals: list = field(default_factory=list)             # list of signal strings
    actionable_items: list = field(default_factory=list)    # concrete things to do
    strategy_suggestions: list = field(default_factory=list)
    whale_activity: bool = False
    prediction_market_relevant: bool = False
    position_hits: list = field(default_factory=list)       # matching open positions
    summary: str = ""
    full_text: str = ""

    def to_dict(self) -> dict:
        return {
            "relevance_score": self.relevance_score,
            "sentiment": self.sentiment,
            "assets_mentioned": self.assets_mentioned,
            "markets_mentioned": self.markets_mentioned,
            "signals": self.signals,
            "actionable_items": self.actionable_items,
            "strategy_suggestions": self.strategy_suggestions,
            "whale_activity": self.whale_activity,
            "prediction_market_relevant": self.prediction_market_relevant,
            "position_hits": self.position_hits,
            "summary": self.summary,
        }

    def is_actionable(self) -> bool:
        return (
            self.relevance_score >= 0.3
            or bool(self.actionable_items)
            or bool(self.position_hits)
        )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class PostAnalyzer:
    """
    Analyzes a PostData object for trading intelligence.

    Usage:
        analyzer = PostAnalyzer(open_positions=["BTC", "ETH"])
        result = analyzer.analyze(post)
    """

    def __init__(
        self,
        open_positions: Optional[list] = None,
        watched_markets: Optional[list] = None,
    ):
        """
        Args:
            open_positions: List of asset tickers/names Bob currently holds positions in.
                            Used to flag direct position relevance.
            watched_markets: List of Polymarket market titles/keywords to watch for.
        """
        self.open_positions = [p.upper() for p in (open_positions or [])]
        self.watched_markets = watched_markets or []

    def analyze(self, post: PostData) -> AnalysisResult:
        """Run full analysis on a PostData object."""
        # Combine main text with thread context for broader signal detection
        full_text = post.text
        if post.thread_context:
            full_text = f"{post.thread_context.text}\n\n{full_text}"

        text_lower = full_text.lower()
        words = set(re.findall(r"\b\w+\b", full_text.upper()))

        result = AnalysisResult(full_text=full_text)

        # ---- Asset detection -------------------------------------------
        crypto_hits = words & CRYPTO_TICKERS
        stock_hits = words & STOCK_TICKERS
        all_assets = sorted(crypto_hits | stock_hits)
        result.assets_mentioned = all_assets

        # ---- Sentiment -------------------------------------------------
        bull_count = sum(1 for kw in BULLISH_SIGNALS if kw in text_lower)
        bear_count = sum(1 for kw in BEARISH_SIGNALS if kw in text_lower)

        if bull_count > bear_count:
            result.sentiment = "bullish"
        elif bear_count > bull_count:
            result.sentiment = "bearish"
        elif bull_count > 0 and bear_count > 0:
            result.sentiment = "mixed"
        else:
            result.sentiment = "neutral"

        # ---- Signals ---------------------------------------------------
        signals = []
        if bull_count:
            signals.append(f"bullish_indicators({bull_count})")
        if bear_count:
            signals.append(f"bearish_indicators({bear_count})")

        # Price targets — patterns like "$50k", "100k", "$0.05", "1000x"
        price_patterns = re.findall(
            r"\$[\d,]+(?:\.\d+)?[kmbt]?|\b\d+[kmbt]\b|\b\d+(?:\.\d+)?x\b",
            text_lower,
        )
        if price_patterns:
            signals.append(f"price_targets: {', '.join(set(price_patterns[:5]))}")

        # Date/timeframe mentions
        time_patterns = re.findall(
            r"\b(?:today|tomorrow|this week|next week|eow|eom|q[1-4]|h[12]|"
            r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
            r"\d{4})\b",
            text_lower,
        )
        if time_patterns:
            signals.append(f"timeframes: {', '.join(set(time_patterns[:5]))}")

        result.signals = signals

        # ---- Whale activity --------------------------------------------
        whale_hits = sum(1 for kw in WHALE_SIGNALS if kw in text_lower)
        result.whale_activity = whale_hits >= 1

        # ---- Prediction market relevance ------------------------------
        pm_hits = sum(1 for kw in PREDICTION_MARKET_KEYWORDS if kw in text_lower)
        result.prediction_market_relevant = pm_hits >= 1

        # ---- Polymarket category matching -----------------------------
        markets_found = []
        for category, keywords in POLYMARKET_CATEGORIES.items():
            if any(kw in text_lower for kw in keywords):
                markets_found.append(category)
        result.markets_mentioned = markets_found

        # Also check watched market list
        for mkt in self.watched_markets:
            if mkt.lower() in text_lower and mkt not in result.markets_mentioned:
                result.markets_mentioned.append(mkt)

        # ---- Open position cross-reference ----------------------------
        position_hits = []
        for pos in self.open_positions:
            if pos in words or pos.lower() in text_lower:
                direction = result.sentiment
                position_hits.append({"position": pos, "sentiment": direction})
        result.position_hits = position_hits

        # ---- Strategy suggestions ------------------------------------
        strat_hits = sum(1 for kw in STRATEGY_SIGNALS if kw in text_lower)
        if strat_hits:
            result.strategy_suggestions = self._extract_strategy_suggestions(text_lower, full_text)

        # ---- Actionable items ----------------------------------------
        result.actionable_items = self._build_actionable_items(result, text_lower)

        # ---- Relevance score -----------------------------------------
        result.relevance_score = self._score_relevance(result)

        # ---- Human-readable summary ----------------------------------
        result.summary = self._build_summary(post, result)

        return result

    def _extract_strategy_suggestions(self, text_lower: str, full_text: str) -> list:
        """Extract strategy-relevant sentences from the post."""
        suggestions = []
        sentences = re.split(r"[.!?\n]+", full_text)
        for sentence in sentences:
            s = sentence.strip()
            if not s or len(s) < 10:
                continue
            s_lower = s.lower()
            if any(kw in s_lower for kw in STRATEGY_SIGNALS):
                suggestions.append(s[:200])
                if len(suggestions) >= 3:
                    break
        return suggestions

    def _build_actionable_items(self, result: AnalysisResult, text_lower: str) -> list:
        """Build a list of concrete actionable items from the analysis."""
        items = []

        if result.position_hits:
            for hit in result.position_hits:
                pos = hit["position"]
                sentiment = hit["sentiment"]
                if sentiment == "bullish":
                    items.append(f"Consider adding to {pos} position — post is bullish on {pos}")
                elif sentiment == "bearish":
                    items.append(f"Review {pos} position — post is bearish on {pos}")
                else:
                    items.append(f"Monitor {pos} — mentioned in post")

        if result.whale_activity:
            items.append("Whale activity detected — check on-chain data for confirmation")

        if result.prediction_market_relevant:
            items.append("Check Polymarket for related markets to this prediction/event")

        for market in result.markets_mentioned:
            items.append(f"Search Polymarket for open '{market}' markets")

        if result.sentiment == "bullish" and result.assets_mentioned:
            assets_str = ", ".join(result.assets_mentioned[:3])
            items.append(f"Bullish signal on {assets_str} — evaluate entry opportunity")
        elif result.sentiment == "bearish" and result.assets_mentioned:
            assets_str = ", ".join(result.assets_mentioned[:3])
            items.append(f"Bearish signal on {assets_str} — evaluate risk / consider hedge")

        # Dedup while preserving order
        seen = set()
        deduped = []
        for item in items:
            if item not in seen:
                seen.add(item)
                deduped.append(item)

        return deduped

    def _score_relevance(self, result: AnalysisResult) -> float:
        """
        Compute a 0.0–1.0 relevance score.
        Higher = more actionable and trading-relevant.
        """
        score = 0.0

        if result.assets_mentioned:
            score += min(0.2, len(result.assets_mentioned) * 0.05)

        if result.sentiment in ("bullish", "bearish"):
            score += 0.15
        elif result.sentiment == "mixed":
            score += 0.08

        if result.signals:
            score += min(0.15, len(result.signals) * 0.05)

        if result.whale_activity:
            score += 0.15

        if result.prediction_market_relevant:
            score += 0.1

        if result.markets_mentioned:
            score += min(0.1, len(result.markets_mentioned) * 0.03)

        if result.position_hits:
            score += min(0.25, len(result.position_hits) * 0.1)

        if result.strategy_suggestions:
            score += min(0.1, len(result.strategy_suggestions) * 0.05)

        return round(min(1.0, score), 2)

    def _build_summary(self, post: PostData, result: AnalysisResult) -> str:
        """Build a concise human-readable summary of the analysis."""
        lines = []

        # Post basics
        lines.append(f"@{post.author} posted:")
        # Truncate text for summary
        display_text = post.text[:280]
        if len(post.text) > 280:
            display_text += "..."
        lines.append(f'"{display_text}"')

        if post.thread_context:
            lines.append(
                f"[In reply to @{post.thread_context.author}: "
                f'"{post.thread_context.text[:120]}..."]'
            )

        lines.append("")

        # Stats line
        stats = []
        if post.like_count is not None:
            stats.append(f"{post.like_count:,} likes")
        if post.retweet_count is not None:
            stats.append(f"{post.retweet_count:,} RTs")
        if stats:
            lines.append("Stats: " + " | ".join(stats))

        # Analysis
        if result.assets_mentioned:
            lines.append(f"Assets: {', '.join(result.assets_mentioned)}")

        if result.sentiment != "neutral":
            lines.append(f"Sentiment: {result.sentiment.upper()}")

        if result.whale_activity:
            lines.append("⚠️  Whale activity mentioned")

        if result.markets_mentioned:
            lines.append(f"Polymarket categories: {', '.join(result.markets_mentioned)}")

        if result.position_hits:
            hits = [h["position"] for h in result.position_hits]
            lines.append(f"Hits open positions: {', '.join(hits)}")

        lines.append(f"Relevance: {int(result.relevance_score * 100)}%")

        if result.actionable_items:
            lines.append("")
            lines.append("What to do:")
            for item in result.actionable_items[:4]:
                lines.append(f"  • {item}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze_post(
    post: PostData,
    open_positions: Optional[list] = None,
    watched_markets: Optional[list] = None,
) -> AnalysisResult:
    """
    Convenience wrapper — create a one-shot PostAnalyzer and run it.

    Args:
        post: PostData from PostFetcher
        open_positions: Current position tickers (e.g. ["BTC", "ETH"])
        watched_markets: Polymarket keywords to watch for
    """
    analyzer = PostAnalyzer(
        open_positions=open_positions,
        watched_markets=watched_markets,
    )
    return analyzer.analyze(post)


# ---------------------------------------------------------------------------
# CLI test helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json
    from .post_fetcher import PostFetcher, FetchError
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m integrations.x_intake.analyzer <tweet_url> [position1,position2,...]")
        sys.exit(1)

    url = sys.argv[1]
    positions = sys.argv[2].split(",") if len(sys.argv) > 2 else []

    fetcher = PostFetcher()
    try:
        post = fetcher.fetch(url)
    except FetchError as e:
        print(f"Fetch error: {e}")
        sys.exit(1)

    result = analyze_post(post, open_positions=positions)
    print(result.summary)
    print("\n--- JSON ---")
    print(json.dumps(result.to_dict(), indent=2))
