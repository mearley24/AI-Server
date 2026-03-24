"""
CVD (Cumulative Volume Delta) Strategy

Measures buying vs selling pressure by tracking trade volume on each side.
When CVD diverges from price, it signals a potential reversal:
- Price up + CVD down = bearish divergence (selling pressure building despite rising price)
- Price down + CVD up = bullish divergence (buying pressure building despite falling price)

Uses CCXT's fetch_trades() to get recent trades and classify as buy/sell based on
whether the trade was at ask (buy) or bid (sell) price.
"""

import os
import time
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

class CVDStrategy:
    """Cumulative Volume Delta strategy for crypto spot trading."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.name = "cvd"
        self.platform = "crypto"
        self.symbols = self.config.get("symbols", ["XRP/USD", "HBAR/USD", "XCN/USD"])
        self.lookback_trades = self.config.get("lookback_trades", 500)  # last 500 trades
        self.divergence_threshold = self.config.get("divergence_threshold", 0.02)  # 2% price vs CVD divergence
        self.poll_interval = self.config.get("poll_interval", 120)  # seconds
        self.trade_amount_usd = float(self.config.get("trade_amount_usd", 50))
        self._running = False
        self._cvd_history = {}  # symbol -> list of (timestamp, cumulative_delta, price)

    async def start(self, exchange):
        """Start CVD monitoring loop."""
        self._running = True
        self._exchange = exchange
        log.info("CVD strategy started for %s", self.symbols)

        while self._running:
            for symbol in self.symbols:
                try:
                    signal = await self._analyze(symbol)
                    if signal:
                        log.info("CVD signal: %s %s (divergence: %.4f)", signal["action"], symbol, signal["divergence"])
                        yield signal
                except Exception as e:
                    log.error("CVD error on %s: %s", symbol, e)
            await asyncio.sleep(self.poll_interval)

    async def stop(self):
        self._running = False

    async def _analyze(self, symbol: str) -> Optional[dict]:
        """Analyze CVD for a single symbol."""
        # Fetch recent trades
        trades = self._exchange.fetch_trades(symbol, limit=self.lookback_trades)
        if len(trades) < 50:
            return None

        # Calculate CVD
        buy_volume = 0.0
        sell_volume = 0.0
        for trade in trades:
            vol = trade["amount"] * trade["price"]  # volume in USD
            if trade["side"] == "buy":
                buy_volume += vol
            else:
                sell_volume += vol

        delta = buy_volume - sell_volume
        total_volume = buy_volume + sell_volume
        if total_volume == 0:
            return None

        # Normalized delta (-1 to +1)
        normalized_delta = delta / total_volume

        # Get price change over same period
        first_price = trades[0]["price"]
        last_price = trades[-1]["price"]
        price_change = (last_price - first_price) / first_price if first_price > 0 else 0

        # Track history
        if symbol not in self._cvd_history:
            self._cvd_history[symbol] = []
        self._cvd_history[symbol].append({
            "timestamp": time.time(),
            "delta": normalized_delta,
            "price": last_price,
            "price_change": price_change,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
        })
        # Keep last 100 readings
        self._cvd_history[symbol] = self._cvd_history[symbol][-100:]

        # Detect divergence
        divergence = price_change - normalized_delta

        if abs(divergence) < self.divergence_threshold:
            return None  # No significant divergence

        # Bearish divergence: price going up but selling pressure dominates
        if price_change > 0 and normalized_delta < -0.1:
            return {
                "strategy": self.name,
                "platform": self.platform,
                "symbol": symbol,
                "action": "sell",
                "divergence": divergence,
                "confidence": min(abs(divergence) / 0.05, 1.0),
                "price": last_price,
                "buy_volume": buy_volume,
                "sell_volume": sell_volume,
                "normalized_delta": normalized_delta,
                "price_change": price_change,
                "reason": f"Bearish CVD divergence: price +{price_change:.2%} but delta {normalized_delta:+.2f}",
            }

        # Bullish divergence: price going down but buying pressure dominates
        if price_change < 0 and normalized_delta > 0.1:
            return {
                "strategy": self.name,
                "platform": self.platform,
                "symbol": symbol,
                "action": "buy",
                "divergence": divergence,
                "confidence": min(abs(divergence) / 0.05, 1.0),
                "price": last_price,
                "buy_volume": buy_volume,
                "sell_volume": sell_volume,
                "normalized_delta": normalized_delta,
                "price_change": price_change,
                "reason": f"Bullish CVD divergence: price {price_change:.2%} but delta {normalized_delta:+.2f}",
            }

        return None

    def get_status(self) -> dict:
        """Return current CVD state for all symbols."""
        return {
            "name": self.name,
            "running": self._running,
            "symbols": self.symbols,
            "history": {
                symbol: entries[-1] if entries else None
                for symbol, entries in self._cvd_history.items()
            },
        }
