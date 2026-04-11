"""Operations service runner — starts the Linear ops listener."""

import asyncio
import logging

from linear_ops import listen_and_create

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    asyncio.run(listen_and_create())
