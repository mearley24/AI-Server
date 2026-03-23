"""Bridge between FrondEnt/PolymarketBTC15mAssistant and Redis signal bus.

Launches the Node.js assistant as a subprocess, parses TA indicator output
from its stdout, and publishes structured JSON signals to the Redis channel
``polymarket:ta_signals`` for the main bot to consume.

Expected assistant stdout lines (one JSON object per line):
    {"rsi": 45.2, "macd": 0.003, "heikin_ashi": "bullish", "vwap": 63210.5,
     "delta": 120.3, "prediction": "up", "confidence": 0.72, "timestamp": ...}

If a line isn't valid JSON, the bridge silently skips it.

The bridge is resilient to assistant crashes — it will restart the subprocess
with exponential backoff and never exit itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_CHANNEL = "polymarket:ta_signals"
ASSISTANT_DIR = "/app/assistant"
ASSISTANT_CMD = ["node", "index.js"]

# Retry configuration
INITIAL_BACKOFF_SECS = 30
MAX_BACKOFF_SECS = 300  # 5 minutes
RAPID_CRASH_THRESHOLD_SECS = 5  # If process dies within this, it's a config issue
BACKOFF_ESCALATION_FAILURES = 5  # After this many consecutive failures, use max backoff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bridge")


async def publish_signal(redis_client: aioredis.Redis, raw_line: str) -> None:
    """Parse a TA output line and publish to Redis."""
    try:
        data = json.loads(raw_line)
    except json.JSONDecodeError:
        return  # Not a JSON line — skip (startup logs, etc.)

    # Ensure required fields are present
    required = {"prediction"}
    if not required.issubset(data.keys()):
        return

    signal_payload = {
        "source": "btc_15m_assistant",
        "timestamp": data.get("timestamp", time.time()),
        "rsi": data.get("rsi"),
        "macd": data.get("macd"),
        "heikin_ashi": data.get("heikin_ashi"),
        "vwap": data.get("vwap"),
        "delta": data.get("delta"),
        "prediction": data.get("prediction"),
        "confidence": data.get("confidence"),
    }

    await redis_client.publish(REDIS_CHANNEL, json.dumps(signal_payload))
    log.info("Published TA signal: prediction=%s confidence=%s rsi=%s",
             signal_payload["prediction"],
             signal_payload.get("confidence"),
             signal_payload.get("rsi"))


async def run_assistant(redis_client: aioredis.Redis, env: dict) -> int:
    """Run the assistant subprocess once. Returns exit code."""
    log.info("Starting BTC 15m Assistant from %s", ASSISTANT_DIR)

    proc = await asyncio.create_subprocess_exec(
        *ASSISTANT_CMD,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=ASSISTANT_DIR,
        env=env,
    )

    log.info("Assistant process started (pid=%d)", proc.pid)

    async def read_stdout() -> None:
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            log.debug("assistant stdout: %s", line[:200])
            try:
                await publish_signal(redis_client, line)
            except Exception as exc:
                log.error("Publish error: %s", exc)

    async def read_stderr() -> None:
        assert proc.stderr is not None
        async for raw_line in proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                log.warning("assistant stderr: %s", line[:500])

    try:
        await asyncio.gather(read_stdout(), read_stderr())
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()

    return proc.returncode if proc.returncode is not None else -1


async def run_bridge() -> None:
    """Main bridge loop: start assistant subprocess with retry on crash."""
    log.info("Connecting to Redis at %s", REDIS_URL)
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    try:
        await redis_client.ping()
        log.info("Redis connection OK")
    except Exception as exc:
        log.error("Redis connection failed: %s — will retry on each publish", exc)

    env = {**os.environ}
    env.setdefault("POLYMARKET_AUTO_SELECT_LATEST", "true")

    consecutive_failures = 0
    backoff_secs = INITIAL_BACKOFF_SECS

    while True:
        start_time = time.monotonic()

        try:
            exit_code = await run_assistant(redis_client, env)
        except asyncio.CancelledError:
            log.info("Bridge received cancellation, shutting down")
            break
        except Exception as exc:
            exit_code = -1
            log.error("Unexpected error running assistant: %s", exc)

        elapsed = time.monotonic() - start_time
        consecutive_failures += 1

        if elapsed < RAPID_CRASH_THRESHOLD_SECS:
            log.error(
                "Assistant exited in %.1fs (exit code %s) — likely a config or dependency issue",
                elapsed, exit_code,
            )
        else:
            log.warning(
                "Assistant crashed after %.0fs (exit code %s)",
                elapsed, exit_code,
            )

        # Calculate backoff
        if consecutive_failures >= BACKOFF_ESCALATION_FAILURES:
            backoff_secs = MAX_BACKOFF_SECS
            log.error(
                "%d consecutive failures — backing off to %ds between restarts",
                consecutive_failures, backoff_secs,
            )
        else:
            # Exponential backoff: 30, 60, 120, 240, then cap at 300
            backoff_secs = min(INITIAL_BACKOFF_SECS * (2 ** (consecutive_failures - 1)), MAX_BACKOFF_SECS)

        log.info(
            "Restarting assistant in %ds (attempt %d)...",
            backoff_secs, consecutive_failures + 1,
        )

        try:
            await asyncio.sleep(backoff_secs)
        except asyncio.CancelledError:
            log.info("Bridge received cancellation during backoff, shutting down")
            break

    await redis_client.aclose()
    log.info("Bridge shut down cleanly")


def main() -> None:
    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: object) -> None:
        log.info("Received signal %d, shutting down", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(run_bridge())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
