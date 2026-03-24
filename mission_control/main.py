"""Mission Control — entrypoint that wraps event_server with health monitoring and dashboard."""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8098"))
STATIC_DIR = Path(__file__).parent / "static"

# Service map: name -> (container_hostname, internal_port, external_port)
SERVICES = [
    {"name": "OpenWebUI", "host": "openwebui", "port": 8080, "ext_port": 3000},
    {"name": "Uptime Kuma", "host": "uptime-kuma", "port": 3001, "ext_port": 3001},
    {"name": "Remediator", "host": "remediator", "port": 8090, "ext_port": 8090},
    {"name": "Proposals", "host": "proposals", "port": 8091, "ext_port": 8091},
    {"name": "Email Monitor", "host": "email-monitor", "port": 8092, "ext_port": 8092},
    {"name": "Voice Receptionist", "host": "voice-receptionist", "port": 3000, "ext_port": 8093},
    {"name": "Calendar Agent", "host": "calendar-agent", "port": 8094, "ext_port": 8094},
    {"name": "Notification Hub", "host": "notification-hub", "port": 8095, "ext_port": 8095},
    {"name": "D-Tools Bridge", "host": "dtools-bridge", "port": 5050, "ext_port": 8096},
    {"name": "ClawWork", "host": "clawwork", "port": 8097, "ext_port": 8097},
    {"name": "Polymarket Bot", "host": "polymarket-bot", "port": 8430, "ext_port": 8430},
    {"name": "OpenClaw", "host": "openclaw", "port": 3000, "ext_port": 8099},
    {"name": "Knowledge Scanner", "host": "knowledge-scanner", "port": 8100, "ext_port": 8100},
]


async def check_service_health(service: dict) -> dict:
    """Check a single service's health endpoint."""
    url = f"http://{service['host']}:{service['port']}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                details = resp.json() if "json" in ct else {}
                return {"name": service["name"], "status": "healthy", "port": service["ext_port"], "details": details}
            else:
                return {"name": service["name"], "status": "degraded", "port": service["ext_port"], "details": {"http_status": resp.status_code}}
    except Exception:
        return {"name": service["name"], "status": "down", "port": service["ext_port"], "details": {}}


# Import the existing event_server — but override DB path before init
import event_server
data_dir = Path(os.getenv("DATA_DIR", "/data"))
data_dir.mkdir(parents=True, exist_ok=True)
event_server.DB_PATH = data_dir / "events.db"
event_server.STATIC_DIR = STATIC_DIR

# Re-use the existing app from event_server (has WebSocket, events, status, digest)
app = event_server.app

# ── Add new routes ──

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mission-control"}


@app.get("/api/services")
async def api_services():
    """Check health of all services."""
    results = await asyncio.gather(*[check_service_health(s) for s in SERVICES])
    now = datetime.now().isoformat()
    for r in results:
        r["checked_at"] = now
    return {
        "services": results,
        "total": len(results),
        "healthy": sum(1 for r in results if r["status"] == "healthy"),
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the ops dashboard."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Dashboard not found</h1>")


if __name__ == "__main__":
    event_server.init_db()
    logger.info("Mission Control starting on port %d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
