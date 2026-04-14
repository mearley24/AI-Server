"""Network dropout monitor — host-only (needs ping, traceroute, etc.)."""

import subprocess
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@router.get("/dropout/status")
async def dropout_status():
    """Check if network guard daemon is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "network_guard_daemon"],
            capture_output=True, text=True, timeout=5
        )
        running = result.returncode == 0
        pid = result.stdout.strip().split()[0] if running else None
        return {"running": running, "pid": pid}
    except Exception as exc:
        return {"running": False, "error": str(exc)}


@router.post("/dropout/start")
async def start_dropout_monitor():
    """Start the network dropout watcher."""
    try:
        subprocess.Popen(
            ["python3", "tools/network_guard_daemon.py"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"started": True}
    except Exception as exc:
        return {"started": False, "error": str(exc)}


@router.post("/dropout/stop")
async def stop_dropout_monitor():
    """Stop the network dropout watcher."""
    try:
        subprocess.run(["pkill", "-f", "network_guard_daemon"], timeout=5)
        return {"stopped": True}
    except Exception as exc:
        return {"stopped": False, "error": str(exc)}
