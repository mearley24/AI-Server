"""CLI/import shim for RBI pipeline."""

from __future__ import annotations

import asyncio
import logging

from strategies.rbi_pipeline import RBIPipeline, evaluate_idea, _cli

__all__ = ["RBIPipeline", "evaluate_idea"]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(_cli())
