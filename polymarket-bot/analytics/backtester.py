"""CLI backtester stub — Auto-20."""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest Polymarket strategies")
    p.add_argument("--strategy", default="mean_reversion")
    p.add_argument("--days", type=int, default=7)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    logger.info("backtester_stub strategy=%s days=%s (implement Gamma snapshots)", args.strategy, args.days)


if __name__ == "__main__":
    main()
