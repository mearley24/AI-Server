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


async def _run_with_restart(coro_fn, name: str) -> None:
    """Run an async function, restarting on failure to avoid crashing the service."""
    while True:
        try:
            await coro_fn()
            break  # Normal exit
        except Exception as e:
            logger.error("%s crashed: %s — restarting in 10s", name, e)
            await asyncio.sleep(10)


async def main() -> None:
    from monitor import EmailMonitor, init_db
    from notifier import run_subscriber

    init_db()

    email_addr = os.getenv("SYMPHONY_EMAIL", "")
    if not email_addr:
        logger.warning("Email monitoring disabled — no credentials configured")

    monitor = EmailMonitor()

    # Run FastAPI in a background thread
    config = uvicorn.Config(
        "api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8092")),
        log_level="info",
    )
    server = uvicorn.Server(config)

    # Run all three concurrently — monitor and notifier are wrapped
    # so that a crash in either does not take down the API server
    await asyncio.gather(
        _run_with_restart(monitor.run, "EmailMonitor"),
        _run_with_restart(run_subscriber, "Notifier"),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
