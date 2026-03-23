"""Paper trade ledger — records hypothetical trades in observer/dry-run mode
and retroactively scores them against resolved markets via the Gamma API."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PaperTrade:
    """A single paper (hypothetical) trade entry."""

    timestamp: float
    strategy: str
    market_id: str
    market_question: str
    side: str  # "BUY" or "SELL"
    size: float
    price: float
    signals: dict[str, Any] = field(default_factory=dict)
    debate_confidence: float | None = None
    debate_recommendation: str | None = None
    latency_window_ms: float | None = None
    would_have_profited: bool | None = None
    resolved_price: float | None = None
    scored_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperTrade:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class PaperLedger:
    """Append-only JSONL ledger for paper trades with retroactive scoring."""

    def __init__(
        self,
        ledger_path: str | Path = "/data/paper_trades.jsonl",
        gamma_api_url: str = "https://gamma-api.polymarket.com",
    ) -> None:
        self._path = Path(ledger_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._gamma_url = gamma_api_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ── Write ────────────────────────────────────────────────────────────

    def record(self, trade: PaperTrade) -> None:
        """Append a paper trade to the JSONL ledger."""
        with self._path.open("a") as f:
            f.write(json.dumps(trade.to_dict(), default=str) + "\n")

        logger.info(
            "paper_trade_recorded",
            strategy=trade.strategy,
            market=trade.market_question,
            side=trade.side,
            size=trade.size,
            price=trade.price,
        )

    # ── Read ─────────────────────────────────────────────────────────────

    def read_all(self) -> list[PaperTrade]:
        """Read all paper trades from the ledger."""
        if not self._path.exists():
            return []
        trades: list[PaperTrade] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(PaperTrade.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("paper_ledger_parse_error", error=str(exc))
        return trades

    def read_recent(self, limit: int = 100) -> list[PaperTrade]:
        """Read the most recent N paper trades."""
        all_trades = self.read_all()
        return all_trades[-limit:]

    # ── Scoring ──────────────────────────────────────────────────────────

    async def score_resolved_markets(self) -> dict[str, Any]:
        """Check each unscored paper trade against the Gamma API to see
        if the market resolved in our favor.

        Returns a summary of scoring results.
        """
        trades = self.read_all()
        if not trades:
            return {"scored": 0, "total": 0, "errors": 0}

        http = await self._get_http()
        scored_count = 0
        error_count = 0
        updated = False

        for trade in trades:
            if trade.would_have_profited is not None:
                continue  # already scored

            try:
                resp = await http.get(
                    f"{self._gamma_url}/markets/{trade.market_id}",
                )
                if resp.status_code != 200:
                    continue

                market_data = resp.json()

                # Check if market has resolved
                if not market_data.get("closed", False):
                    continue

                # Get resolution price — resolved YES = 1.0, NO = 0.0
                resolution_price: float | None = None
                tokens = market_data.get("tokens", [])
                for token in tokens:
                    # Match the token the paper trade targeted
                    outcome = token.get("outcome", "").upper()
                    winner = token.get("winner", False)
                    if winner:
                        resolution_price = 1.0 if outcome == "YES" else 0.0
                        break

                if resolution_price is None:
                    # Try the top-level resolved_price / outcome fields
                    outcome_str = market_data.get("outcome", "")
                    if outcome_str:
                        resolution_price = 1.0 if outcome_str.upper() == "YES" else 0.0

                if resolution_price is None:
                    continue  # not yet resolvable

                # Determine if our paper trade would have profited
                # BUY side: profit if market resolved to 1.0 (we bought at < 1.0)
                # SELL side: profit if market resolved to 0.0 (we sold at > 0.0)
                if trade.side == "BUY":
                    trade.would_have_profited = resolution_price > trade.price
                else:
                    trade.would_have_profited = resolution_price < trade.price

                trade.resolved_price = resolution_price
                trade.scored_at = time.time()
                scored_count += 1
                updated = True

                logger.info(
                    "paper_trade_scored",
                    strategy=trade.strategy,
                    market=trade.market_question,
                    side=trade.side,
                    price=trade.price,
                    resolved=resolution_price,
                    profitable=trade.would_have_profited,
                )

            except Exception as exc:
                error_count += 1
                logger.warning(
                    "paper_trade_scoring_error",
                    market_id=trade.market_id,
                    error=str(exc),
                )

        # Rewrite the entire ledger with updated scores
        if updated:
            self._rewrite(trades)

        return {
            "scored": scored_count,
            "total": len(trades),
            "already_scored": sum(1 for t in trades if t.would_have_profited is not None),
            "errors": error_count,
        }

    def _rewrite(self, trades: list[PaperTrade]) -> None:
        """Atomically rewrite the ledger file with updated trade data."""
        tmp_path = self._path.with_suffix(".jsonl.tmp")
        with tmp_path.open("w") as f:
            for trade in trades:
                f.write(json.dumps(trade.to_dict(), default=str) + "\n")
        tmp_path.replace(self._path)

    # ── P&L calculation ──────────────────────────────────────────────────

    def get_paper_pnl(self) -> dict[str, Any]:
        """Calculate hypothetical P&L from scored paper trades.

        For each scored trade:
        - BUY: pnl = (resolved_price - entry_price) × size
        - SELL: pnl = (entry_price - resolved_price) × size
        Unscored trades contribute 0 to realized P&L but are counted
        as unrealized (open) positions.
        """
        trades = self.read_all()
        if not trades:
            return {
                "total_paper_trades": 0,
                "scored_trades": 0,
                "unscored_trades": 0,
                "total_pnl": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "by_strategy": {},
                "trades": [],
            }

        scored = [t for t in trades if t.would_have_profited is not None]
        unscored = [t for t in trades if t.would_have_profited is None]

        total_pnl = 0.0
        winning = 0
        losing = 0
        by_strategy: dict[str, dict[str, Any]] = {}

        for trade in scored:
            if trade.resolved_price is None:
                continue

            if trade.side == "BUY":
                pnl = (trade.resolved_price - trade.price) * trade.size
            else:
                pnl = (trade.price - trade.resolved_price) * trade.size

            total_pnl += pnl

            if pnl > 0:
                winning += 1
            elif pnl < 0:
                losing += 1

            # Aggregate by strategy
            if trade.strategy not in by_strategy:
                by_strategy[trade.strategy] = {
                    "pnl": 0.0,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                }
            by_strategy[trade.strategy]["pnl"] += pnl
            by_strategy[trade.strategy]["trades"] += 1
            if pnl > 0:
                by_strategy[trade.strategy]["wins"] += 1
            elif pnl < 0:
                by_strategy[trade.strategy]["losses"] += 1

        total_scored = winning + losing
        win_rate = winning / total_scored if total_scored > 0 else 0.0

        # Build trade summaries for the response
        trade_summaries = []
        for t in trades[-100:]:  # last 100
            summary: dict[str, Any] = {
                "timestamp": t.timestamp,
                "strategy": t.strategy,
                "market_question": t.market_question,
                "side": t.side,
                "size": t.size,
                "price": t.price,
                "would_have_profited": t.would_have_profited,
            }
            if t.resolved_price is not None:
                if t.side == "BUY":
                    summary["pnl"] = (t.resolved_price - t.price) * t.size
                else:
                    summary["pnl"] = (t.price - t.resolved_price) * t.size
            trade_summaries.append(summary)

        return {
            "total_paper_trades": len(trades),
            "scored_trades": len(scored),
            "unscored_trades": len(unscored),
            "total_pnl": round(total_pnl, 4),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": round(win_rate, 4),
            "by_strategy": by_strategy,
            "trades": trade_summaries,
        }
