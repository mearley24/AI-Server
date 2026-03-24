#!/usr/bin/env python3
"""
main.py — Entry point for the Email Monitor service.

Runs the IMAP monitor loop, Redis notification subscriber,
and FastAPI HTTP API concurrently.
"""

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("email-monitor")


async def main() -> None:
    from monitor import EmailMonitor, init_db
    from notifier import run_subscriber

    init_db()

    monitor = EmailMonitor()

    # Run FastAPI in a background thread
    config = uvicorn.Config(
        "api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8092")),
        log_level="info",
    )
    server = uvicorn.Server(config)

    # Run all three concurrently
    await asyncio.gather(
        monitor.run(),
        run_subscriber(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
