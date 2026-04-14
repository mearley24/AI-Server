"""Host-level tools — launchd management, disk space, process control."""

import os
import subprocess
import shutil
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent


@router.get("/disk")
async def disk_usage():
    """Check disk space."""
    total, used, free = shutil.disk_usage("/")
    return {
        "total_gb": round(total / (1024 ** 3), 1),
        "used_gb": round(used / (1024 ** 3), 1),
        "free_gb": round(free / (1024 ** 3), 1),
        "pct_used": round(used / total * 100, 1),
    }


@router.get("/docker")
async def docker_status():
    """Check Docker container status."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            containers.append({
                "name": parts[0] if len(parts) > 0 else "",
                "status": parts[1] if len(parts) > 1 else "",
                "ports": parts[2] if len(parts) > 2 else "",
            })
        return {"containers": containers}
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/restart/{service}")
async def restart_service(service: str):
    """Restart a Docker service or launchd agent."""
    allowed_docker = {
        "cortex", "polymarket-bot", "openclaw", "email-monitor",
        "calendar-agent", "notification-hub", "proposals",
        "x-intake", "x-alpha-collector", "client-portal",
    }
    allowed_launchd = {
        "com.symphony.mobile-api",
        "com.symphony.imessage-watcher",
    }

    if service in allowed_docker:
        try:
            subprocess.run(["docker", "restart", service], timeout=30, check=True)
            return {"restarted": service, "type": "docker"}
        except Exception as exc:
            return {"error": str(exc)}
    elif service in allowed_launchd:
        try:
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{_uid()}/{service}"],
                timeout=10,
            )
            return {"restarted": service, "type": "launchd"}
        except Exception as exc:
            return {"error": str(exc)}
    else:
        return {"error": f"Unknown service: {service}"}


def _uid() -> str:
    """Return current user's UID as string."""
    return str(os.getuid())
