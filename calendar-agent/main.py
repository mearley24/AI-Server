"""Calendar Agent — FastAPI entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api import router as calendar_router
from calendar_client import ZohoCalendarClient
from reminders import reminder_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = ZohoCalendarClient()
    if client.configured:
        task = asyncio.create_task(reminder_loop(client))
        logger.info("Reminder background task started")
    else:
        task = None
        logger.warning("Zoho Calendar not configured — reminders disabled")
    yield
    if task:
        task.cancel()


app = FastAPI(title="Calendar Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    client = ZohoCalendarClient()
    return {
        "status": "healthy",
        "service": "calendar-agent",
        "configured": client.configured,
    }


app.include_router(calendar_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8094)
