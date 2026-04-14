"""iMessage host-only functions — reads chat.db, manages watchlist."""

import sys
from pathlib import Path
from fastapi import APIRouter

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "tools"))

try:
    from imessage_watcher import (
        get_status, process_once, process_backfill,
        set_watchlist, set_automation, set_monitor_all,
        load_state, save_state
    )
    _WATCHER_AVAILABLE = True
except ImportError:
    _WATCHER_AVAILABLE = False

router = APIRouter()


@router.get("/status")
async def status():
    """Current iMessage watcher state."""
    if not _WATCHER_AVAILABLE:
        return {"error": "imessage_watcher not available", "available": False}
    return get_status()


@router.post("/process_now")
async def process_now():
    """Process new messages immediately."""
    if not _WATCHER_AVAILABLE:
        return {"error": "imessage_watcher not available"}
    return process_once()


@router.post("/backfill")
async def backfill(weeks: int = 4, dry_run: bool = True):
    """Backfill messages from the past N weeks."""
    if not _WATCHER_AVAILABLE:
        return {"error": "imessage_watcher not available"}
    return process_backfill(weeks=weeks, dry_run=dry_run)


@router.get("/watchlist")
async def watchlist():
    """Get current watchlist."""
    if not _WATCHER_AVAILABLE:
        return {"watchlist": [], "monitor_all": False, "available": False}
    state = load_state()
    return {
        "watchlist": state.get("watchlist", []),
        "monitor_all": state.get("monitor_all", False),
    }


@router.post("/watchlist")
async def update_watchlist(request: dict):
    """Update watchlist. Body: {numbers: [...], monitor_all: bool}"""
    if not _WATCHER_AVAILABLE:
        return {"error": "imessage_watcher not available"}
    numbers = request.get("numbers", [])
    monitor_all = request.get("monitor_all", False)
    return set_watchlist(numbers, monitor_all)


@router.post("/automation")
async def update_automation(request: dict):
    """Update automation settings. Body: {auto_invoice: bool, auto_appointment: bool, auto_task: bool}"""
    if not _WATCHER_AVAILABLE:
        return {"error": "imessage_watcher not available"}
    allowed = {"auto_invoice", "auto_appointment", "auto_task"}
    return set_automation(**{k: v for k, v in request.items() if k in allowed})
