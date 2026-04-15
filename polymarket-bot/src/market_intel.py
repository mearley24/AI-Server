"""Market intelligence module — gathers live data for debate engine context.

Pulls real-time data from Perplexity (news research), CoinGecko (crypto prices),
Financial Datasets API (fundamentals, SEC filings), and the existing Polymarket
client before each bull/bear debate round.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
FINANCIAL_DATASETS_BASE_URL = "https://api.financialdatasets.ai"

# Rate limiting: max 10 Perplexity queries per hour
_MAX_PERPLEXITY_PER_HOUR = 10
# Cache TTL: 5 minutes
_CACHE_TTL_SECONDS = 300

# Heuristic patterns indicating a market involves stocks or economic events
_STOCK_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
_FINANCIAL_KEYWORDS = frozenset({
    "stock", "share", "earnings", "gdp", "fed", "interest rate", "inflation",
    "recession", "s&p", "nasdaq", "dow", "treasury", "cpi", "jobs", "unemployment",
    "revenue", "ipo", "sec", "10-k", "10-q", "market cap", "dividend",
})


@dataclass
class MarketContext:
    """Structured market context for debate injection."""

    market_question: str
    gathered_at: str
    polymarket_price: str | None = None
    crypto_prices: dict[str, Any] = field(default_factory=dict)
    perplexity_research: str | None = None
    order_book_summary: str | None = None
    financial_data: dict[str, Any] = field(default_factory=dict)

    def format(self) -> str:
        """Format as a [MARKET CONTEXT] block for prompt injection."""
        lines = [
            f"[MARKET CONTEXT — gathered at {self.gathered_at}]",
            f"Market: \"{self.market_question}\"",
        ]
        if self.polymarket_price:
            lines.append(f"Polymarket data: {self.polymarket_price}")
        if self.crypto_prices:
            for coin, data in self.crypto_prices.items():
                price = data.get("usd", "N/A")
                change = data.get("usd_24h_change")
                change_str = f" (24h: {change:+.1f}%)" if change is not None else ""
                lines.append(f"{coin.upper()} spot: ${price:,.2f}{change_str}" if isinstance(price, (int, float)) else f"{coin.upper()}: ${price}")
        if self.financial_data:
            lines.append("[FINANCIAL DATA]")
            for ticker, fdata in self.financial_data.items():
                lines.append(f"  {ticker}:")
                snapshot = fdata.get("snapshot")
                if snapshot:
                    lines.append(f"    Price: ${snapshot.get('price', 'N/A')}")
                    lines.append(f"    Market Cap: {snapshot.get('market_cap', 'N/A')}")
                    lines.append(f"    P/E: {snapshot.get('pe_ratio', 'N/A')}")
                statements = fdata.get("financials")
                if statements:
                    latest = statements[0] if isinstance(statements, list) and statements else statements
                    lines.append(f"    Revenue: {latest.get('revenue', 'N/A')}")
                    lines.append(f"    Net Income: {latest.get('net_income', 'N/A')}")
                filings = fdata.get("filings")
                if filings:
                    lines.append(f"    Recent filings: {len(filings)}")
        if self.perplexity_research:
            lines.append(f"Research: {self.perplexity_research}")
        if self.order_book_summary:
            lines.append(f"Order book: {self.order_book_summary}")
        return "\n".join(lines)


class MarketIntel:
    """Gathers live market data for debate context injection."""

    def __init__(self) -> None:
        self._perplexity_key = os.environ.get("PERPLEXITY_API_KEY", "")
        self._financial_api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=15)
        # Rate limiting state
        self._perplexity_timestamps: list[float] = []
        # Cache: market_question -> (timestamp, MarketContext)
        self._cache: dict[str, tuple[float, MarketContext]] = {}

    @property
    def enabled(self) -> bool:
        return True  # Always enabled; degrades gracefully without API keys

    async def gather(
        self,
        market: str,
        context: dict[str, Any] | None = None,
    ) -> MarketContext:
        """Gather all available market intelligence for a given market.

        Returns a MarketContext even if some sources fail — never raises.
        """
        now = time.time()

        # Check cache
        cached = self._cache.get(market)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            logger.debug("market_intel_cache_hit", market=market)
            return cached[1]

        gathered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ctx = MarketContext(market_question=market, gathered_at=gathered_at)

        # Run all data fetches concurrently
        tasks: list[asyncio.Task] = [
            asyncio.ensure_future(self._fetch_crypto_prices()),
            asyncio.ensure_future(self._fetch_perplexity_research(market)),
        ]

        # If market involves stocks/economics, also fetch financial data
        tickers = self._extract_tickers(market)
        financial_task = None
        if tickers:
            financial_task = asyncio.ensure_future(self._fetch_financial_data(tickers))
            tasks.append(financial_task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        crypto_result = results[0]
        perplexity_result = results[1]

        if isinstance(crypto_result, dict):
            ctx.crypto_prices = crypto_result
        elif isinstance(crypto_result, Exception):
            logger.debug("market_intel_crypto_error", error=str(crypto_result))

        if isinstance(perplexity_result, str) and perplexity_result:
            ctx.perplexity_research = perplexity_result
        elif isinstance(perplexity_result, Exception):
            logger.debug("market_intel_perplexity_error", error=str(perplexity_result))

        if financial_task is not None and len(results) > 2:
            financial_result = results[2]
            if isinstance(financial_result, dict) and financial_result:
                ctx.financial_data = financial_result
            elif isinstance(financial_result, Exception):
                logger.debug("market_intel_financial_error", error=str(financial_result))

        # Extract Polymarket-specific context from caller-provided dict
        if context:
            price_info = context.get("current_price") or context.get("price")
            if price_info is not None:
                ctx.polymarket_price = str(price_info)
            ob = context.get("order_book")
            if ob:
                ctx.order_book_summary = str(ob)

        # Cache result
        self._cache[market] = (now, ctx)

        logger.info(
            "market_intel_gathered",
            market=market,
            has_crypto=bool(ctx.crypto_prices),
            has_research=bool(ctx.perplexity_research),
            has_financial=bool(ctx.financial_data),
        )
        return ctx

    def _extract_tickers(self, market: str) -> list[str]:
        """Heuristic: extract stock tickers from a market question.

        Returns tickers only when the market clearly involves stocks or economics.
        """
        lower = market.lower()
        # Only look for tickers if market mentions financial keywords
        if not any(kw in lower for kw in _FINANCIAL_KEYWORDS):
            return []
        # Find uppercase words that look like tickers (1-5 chars)
        candidates = _STOCK_TICKER_RE.findall(market)
        # Filter out common English words that aren't tickers
        _NOISE = {"THE", "AND", "FOR", "NOT", "BUT", "ARE", "THIS", "THAT", "WITH",
                   "FROM", "WILL", "HAS", "BEEN", "WAS", "WERE", "YES", "NO", "OR",
                   "BY", "AT", "TO", "OF", "IN", "ON", "IF", "SO", "DO", "UP", "AN",
                   "IS", "IT", "BE", "AS", "GDP", "CPI", "FED", "SEC", "IPO", "USA"}
        tickers = [t for t in candidates if t not in _NOISE and len(t) >= 2]
        return tickers[:3]  # Cap at 3 tickers per query

    async def _fetch_crypto_prices(self) -> dict[str, Any]:
        """Fetch crypto prices from CoinGecko free API."""
        try:
            resp = await self._http.get(
                COINGECKO_PRICE_URL,
                params={
                    "ids": "bitcoin,ripple,hedera",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("coingecko_fetch_error", error=str(exc))
            return {}

    async def _fetch_perplexity_research(self, market: str) -> str:
        """Query Perplexity API for real-time market research."""
        if not self._perplexity_key:
            return ""

        # Rate limiting: max 10 per hour
        now = time.time()
        cutoff = now - 3600
        self._perplexity_timestamps = [t for t in self._perplexity_timestamps if t > cutoff]
        if len(self._perplexity_timestamps) >= _MAX_PERPLEXITY_PER_HOUR:
            logger.warning("perplexity_rate_limited")
            return ""

        try:
            resp = await self._http.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._perplexity_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a concise market research assistant. Provide a 2-3 sentence summary of the latest relevant news and data. Focus on facts, numbers, and recent developments.",
                        },
                        {
                            "role": "user",
                            "content": f"What is the latest news and current market sentiment for: {market}",
                        },
                    ],
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._perplexity_timestamps.append(now)

            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

        except Exception as exc:
            logger.debug("perplexity_fetch_error", error=str(exc))
            return ""

    async def _fetch_financial_data(self, tickers: list[str]) -> dict[str, Any]:
        """Fetch financial data for detected tickers concurrently."""
        if not tickers:
            return {}
        results: dict[str, Any] = {}
        for ticker in tickers:
            ticker_data: dict[str, Any] = {}
            tasks = {
                "snapshot": self._get_stock_snapshot(ticker),
                "financials": self._get_financial_statements(ticker),
            }
            fetched = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), fetched):
                if isinstance(result, Exception):
                    logger.debug("financial_fetch_error", ticker=ticker, source=key, error=str(result))
                elif result:
                    ticker_data[key] = result
            if ticker_data:
                results[ticker] = ticker_data
        return results

    async def _get_stock_snapshot(self, ticker: str) -> dict[str, Any] | None:
        """Get current price + key metrics from Financial Datasets API."""
        if not self._financial_api_key:
            return None
        try:
            resp = await self._http.get(
                f"{FINANCIAL_DATASETS_BASE_URL}/prices/snapshot",
                params={"ticker": ticker},
                headers={"X-API-Key": self._financial_api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("snapshot", data)
        except Exception as exc:
            logger.debug("stock_snapshot_error", ticker=ticker, error=str(exc))
        return None

    async def _get_financial_statements(self, ticker: str) -> list[dict] | None:
        """Get income statement / balance sheet from Financial Datasets API."""
        if not self._financial_api_key:
            return None
        try:
            resp = await self._http.get(
                f"{FINANCIAL_DATASETS_BASE_URL}/financials/income-statements",
                params={"ticker": ticker, "period": "annual", "limit": 1},
                headers={"X-API-Key": self._financial_api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("income_statements", data.get("financials", []))
        except Exception as exc:
            logger.debug("financial_statements_error", ticker=ticker, error=str(exc))
        return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Standalone financial data functions for direct use
# ---------------------------------------------------------------------------
async def get_financial_statements(
    ticker: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch income statement and balance sheet for a ticker.

    Uses the Financial Datasets API (https://api.financialdatasets.ai).
    Returns empty dict if API key is not set (backward-compatible).
    """
    key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    if not key:
        return {}
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=15) as http:
        for endpoint, result_key in [
            ("income-statements", "income_statements"),
            ("balance-sheets", "balance_sheets"),
        ]:
            try:
                resp = await http.get(
                    f"{FINANCIAL_DATASETS_BASE_URL}/financials/{endpoint}",
                    params={"ticker": ticker, "period": "annual", "limit": 4},
                    headers={"X-API-Key": key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result[result_key] = data.get(result_key, [])
            except Exception as exc:
                logger.debug("financial_statements_error", ticker=ticker, endpoint=endpoint, error=str(exc))
    return result


async def get_stock_snapshot(
    ticker: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch current price + key metrics for a ticker.

    Uses the Financial Datasets API. Returns empty dict without API key.
    """
    key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    if not key:
        return {}
    async with httpx.AsyncClient(timeout=15) as http:
        try:
            resp = await http.get(
                f"{FINANCIAL_DATASETS_BASE_URL}/prices/snapshot",
                params={"ticker": ticker},
                headers={"X-API-Key": key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("snapshot", data)
        except Exception as exc:
            logger.debug("stock_snapshot_error", ticker=ticker, error=str(exc))
    return {}


async def get_sec_filings(
    ticker: str,
    filing_type: str = "10-K",
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch SEC filings for a ticker.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL").
        filing_type: Filing type — "10-K", "10-Q", "8-K", etc.
        api_key: Optional API key override.

    Uses the Financial Datasets API. Returns empty list without API key.
    """
    key = api_key or os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    if not key:
        return []
    async with httpx.AsyncClient(timeout=15) as http:
        try:
            resp = await http.get(
                f"{FINANCIAL_DATASETS_BASE_URL}/sec/filings",
                params={"ticker": ticker, "filing_type": filing_type, "limit": 5},
                headers={"X-API-Key": key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("filings", [])
        except Exception as exc:
            logger.debug("sec_filings_error", ticker=ticker, error=str(exc))
    return []
