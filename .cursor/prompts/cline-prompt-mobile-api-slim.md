# Cline Prompt: Replace Mobile API Monolith with Slim Gateway

## Objective

Replace the 7,288-line `api/mobile_api.py` monolith with a small modular gateway that proxies to existing Docker services and only implements host-only functions directly. The current file reimplements half the stack — Cortex queries, proposal generation, AI chat, X intake, etc. — when those services already exist in Docker. Kill all that and make the Mobile API a thin gateway with ~5 focused modules.

---

## Architecture: Before vs After

### Before (7,288 lines, 120+ endpoints, one file)
```
iPhone → mobile_api.py (reimplements everything)
                ↓ duplicates
         cortex, proposals, openclaw, x-intake, email-monitor...
```

### After (~800 lines total across 5 files)
```
iPhone → mobile_gateway.py (thin proxy + host-only functions)
              ↓ proxies to
         Docker services (cortex:8102, proposals:8091, etc.)
              +
         host_modules/ (iMessage, network, Ollama health)
```

---

## File Structure

Delete `api/mobile_api.py` entirely. Replace with:

```
api/
  gateway.py              -- FastAPI app, ~200 lines: health, auth, service proxy
  host_modules/
    __init__.py
    imessage.py           -- iMessage watcher bridge (~150 lines)
    network.py            -- Network dropout monitor (~80 lines)
    ollama_health.py      -- Ollama/LM Studio health checks (~50 lines)
    host_tools.py         -- Launchd, subprocess helpers (~80 lines)
  requirements.txt
```

---

## Part 1: `api/gateway.py` — The Thin Gateway

This is the only FastAPI app. ~200 lines. It does three things:
1. Proxies requests to Docker services
2. Mounts host-only modules as sub-routers
3. Provides a unified `/health` and `/dashboard`

```python
#!/usr/bin/env python3
"""
Symphony Mobile Gateway — thin proxy to Docker services + host-only functions.

Runs on the Mac host (launchd), NOT in Docker.
Needs host access for: iMessage DB, iCloud, Ollama, launchd, network tools.

Everything else proxies to Docker services.
"""

import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import uvicorn

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from host_modules.imessage import router as imessage_router
from host_modules.network import router as network_router
from host_modules.ollama_health import router as ollama_router
from host_modules.host_tools import router as tools_router

app = FastAPI(title="Symphony Mobile Gateway", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PORT = int(os.environ.get("MOBILE_API_PORT", "8420"))
API_AUTH_TOKEN = os.environ.get("SYMPHONY_API_TOKEN", "").strip().strip("'\"")

SERVICES = {
    "cortex":       "http://localhost:8102",
    "proposals":    "http://localhost:8091",
    "email":        "http://localhost:8092",
    "voice":        "http://localhost:8093",
    "calendar":     "http://localhost:8094",
    "notifications":"http://localhost:8095",
    "portal":       "http://localhost:8096",
    "openclaw":     "http://localhost:8099",
    "x-intake":     "http://localhost:8101",
    "trading":      "http://localhost:8430",
}
```

**Auth middleware** — same as current, but simpler:
```python
AUTH_EXEMPT = {"/", "/health", "/docs", "/openapi.json"}

@app.middleware("http")
async def auth_check(request: Request, call_next):
    if not API_AUTH_TOKEN:
        return await call_next(request)
    if request.url.path in AUTH_EXEMPT:
        return await call_next(request)
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.query_params.get("token", "")
    if token != API_AUTH_TOKEN:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)
```

**Health + Dashboard** — aggregate from all services:
```python
@app.get("/")
async def root():
    return {"name": "Symphony Mobile Gateway", "version": "2.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok", "port": PORT, "services": list(SERVICES.keys())}

@app.get("/dashboard")
async def dashboard():
    """Aggregate health from all Docker services."""
    results = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in SERVICES.items():
            try:
                r = await client.get(f"{url}/health")
                results[name] = {"status": "healthy", "port": url.split(":")[-1]}
            except Exception:
                results[name] = {"status": "down", "port": url.split(":")[-1]}
    return {"services": results, "host": "ok"}
```

**Service proxy** — one generic proxy that forwards to any Docker service:
```python
@app.api_route("/proxy/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    """Forward requests to Docker services. 
    
    Example: GET /proxy/cortex/memories → GET http://localhost:8102/memories
    """
    base_url = SERVICES.get(service)
    if not base_url:
        raise HTTPException(404, f"Unknown service: {service}. Available: {list(SERVICES.keys())}")
    
    target = f"{base_url}/{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if request.method == "GET":
                r = await client.get(target, params=dict(request.query_params))
            else:
                body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else None
                r = await client.request(request.method, target, json=body)
            return JSONResponse(content=r.json(), status_code=r.status_code)
        except httpx.TimeoutException:
            return JSONResponse(content={"error": "timeout"}, status_code=504)
        except Exception as exc:
            return JSONResponse(content={"error": str(exc)}, status_code=502)
```

**Mount host-only routers:**
```python
app.include_router(imessage_router, prefix="/imessages", tags=["iMessage"])
app.include_router(network_router, prefix="/network", tags=["Network"])
app.include_router(ollama_router, prefix="/ai", tags=["AI"])
app.include_router(tools_router, prefix="/host", tags=["Host Tools"])

if __name__ == "__main__":
    uvicorn.run("gateway:app", host="127.0.0.1", port=PORT, log_level="info")
```

**Convenience shortcuts** — thin aliases so the iPhone app doesn't need to know the proxy path:
```python
@app.get("/cortex/stats")
async def cortex_stats():
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get(f"{SERVICES['cortex']}/health")
            return r.json()
        except Exception:
            return {"status": "offline"}

@app.get("/cortex/memories")
async def cortex_memories(category: str = None, limit: int = 20):
    params = {"limit": limit}
    if category:
        params["category"] = category
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get(f"{SERVICES['cortex']}/memories", params=params)
            return r.json()
        except Exception:
            return []

@app.get("/trading/status")
async def trading_status():
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get(f"{SERVICES['trading']}/health")
            return r.json()
        except Exception:
            return {"status": "offline"}
```

---

## Part 2: `api/host_modules/imessage.py` — iMessage Bridge

This replaces the 60+ iMessage references in the old mobile_api. It delegates to the existing `tools/imessage_watcher.py` module.

```python
"""iMessage host-only functions — reads chat.db, manages watchlist."""

import sys
from pathlib import Path
from fastapi import APIRouter

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "tools"))

from imessage_watcher import (
    get_status, process_once, process_backfill,
    set_watchlist, set_automation, set_monitor_all,
    load_state, save_state
)

router = APIRouter()

@router.get("/status")
async def status():
    """Current iMessage watcher state."""
    return get_status()

@router.post("/process_now")
async def process_now():
    """Process new messages immediately."""
    return process_once()

@router.post("/backfill")
async def backfill(weeks: int = 4, dry_run: bool = True):
    """Backfill messages from the past N weeks."""
    return process_backfill(weeks=weeks, dry_run=dry_run)

@router.get("/watchlist")
async def watchlist():
    """Get current watchlist."""
    state = load_state()
    return {
        "watchlist": state.get("watchlist", []),
        "monitor_all": state.get("monitor_all", False),
    }

@router.post("/watchlist")
async def update_watchlist(request: dict):
    """Update watchlist. Body: {numbers: [...], monitor_all: bool}"""
    numbers = request.get("numbers", [])
    monitor_all = request.get("monitor_all", False)
    return set_watchlist(numbers, monitor_all)

@router.post("/automation")
async def update_automation(request: dict):
    """Update automation settings. Body: {auto_invoice: bool, auto_appointment: bool, auto_task: bool}"""
    return set_automation(**{k: v for k, v in request.items() if k in ("auto_invoice", "auto_appointment", "auto_task")})
```

That's it. ~50 lines. All the actual iMessage logic lives in `tools/imessage_watcher.py` (870 lines, already tested).

---

## Part 3: `api/host_modules/network.py` — Network Monitor

```python
"""Network dropout monitor — host-only (needs ping, traceroute, etc.)."""

import subprocess
from fastapi import APIRouter

router = APIRouter()

@router.get("/dropout/status")
async def dropout_status():
    """Check if network guard daemon is running."""
    try:
        result = subprocess.run(["pgrep", "-f", "network_guard_daemon"], capture_output=True, text=True, timeout=5)
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
            cwd=str(Path(__file__).resolve().parent.parent.parent),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
```

---

## Part 4: `api/host_modules/ollama_health.py` — AI Health Checks

```python
"""Ollama and LM Studio health checks — host-only (local LAN access)."""

import os
import urllib.request
import json
from fastapi import APIRouter

router = APIRouter()

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://192.168.1.199:11434")

@router.get("/status")
async def ai_status():
    """Check local AI services availability."""
    ollama_ok = _check_url(f"{OLLAMA_URL}/api/tags")
    return {
        "ollama": {"url": OLLAMA_URL, "available": ollama_ok},
    }

@router.get("/verify/ollama")
async def verify_ollama():
    """Verify Ollama and list available models."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", headers={"User-Agent": "SymphonyGateway"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"available": True, "models": models}
    except Exception as exc:
        return {"available": False, "error": str(exc)}

def _check_url(url: str, timeout: int = 3) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SymphonyGateway"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False
```

---

## Part 5: `api/host_modules/host_tools.py` — Host Utilities

```python
"""Host-level tools — launchd management, disk space, process control."""

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
        "total_gb": round(total / (1024**3), 1),
        "used_gb": round(used / (1024**3), 1),
        "free_gb": round(free / (1024**3), 1),
        "pct_used": round(used / total * 100, 1),
    }

@router.get("/docker")
async def docker_status():
    """Check Docker container status."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"],
            capture_output=True, text=True, timeout=10
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
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{service}"], timeout=10)
            return {"restarted": service, "type": "launchd"}
        except Exception as exc:
            return {"error": str(exc)}
    else:
        return {"error": f"Unknown service: {service}"}

def _uid() -> str:
    import os
    return str(os.getuid())
```

---

## Part 6: `api/host_modules/__init__.py`

```python
"""Host-only modules for Symphony Mobile Gateway."""
```

---

## Part 7: `api/requirements.txt`

```
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.27.0
python-dotenv>=1.0.0
python-multipart>=0.0.6
```

---

## Part 8: Update launchd plist

The existing plist at `setup/launchd/com.symphony.mobile-api.plist` should point to the new gateway:

Update `ProgramArguments` to:
```xml
<array>
    <string>/usr/bin/python3</string>
    <string>api/gateway.py</string>
</array>
```

---

## Part 9: Update install script

Update `setup/install_mobile_api.sh` to reference the new gateway. The existing script at `setup/install_mobile_api.sh` should work — just verify it points to `api/gateway.py`.

If no install script exists yet, create `setup/install_mobile_api.sh`:

```zsh
#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_SERVER_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.symphony.mobile-api"
PLIST_SRC="$SCRIPT_DIR/launchd/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "Installing Mobile Gateway..."

pip3 install --break-system-packages -r "$AI_SERVER_DIR/api/requirements.txt" --quiet 2>/dev/null || pip3 install -r "$AI_SERVER_DIR/api/requirements.txt" --quiet

sed "s|/Users/bob/AI-Server|$AI_SERVER_DIR|g" "$PLIST_SRC" > "$PLIST_DST"

mkdir -p "$AI_SERVER_DIR/logs"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Mobile Gateway running on port 8420"
echo "Test: curl http://localhost:8420/health"
echo "Logs: tail -f $AI_SERVER_DIR/logs/mobile-api.log"
```

---

## Part 10: Migration Notes

### iPhone App Compatibility

If an iOS app or Shortcuts hit any of the old endpoints, they all still work through the proxy:
- Old: `GET http://bob:8420/cortex/stats` → New: still works (convenience alias)
- Old: `POST http://bob:8420/proposals/create` → New: `POST http://bob:8420/proxy/proposals/proposals/generate`
- Old: `GET http://bob:8420/imessages/status` → New: still works (host module)

The key shortcuts endpoints that the iPhone might use:
- `/health` → works
- `/dashboard` → works (aggregates all services)
- `/imessages/*` → works (host module)
- `/ai/status` → works (host module)
- `/cortex/stats` → works (convenience alias)
- `/trading/status` → works (convenience alias)
- Any other service → `/proxy/{service}/{path}`

### What Gets Deleted

The entire `api/mobile_api.py` (7,288 lines) is replaced by:
- `api/gateway.py` (~200 lines)
- `api/host_modules/imessage.py` (~50 lines)
- `api/host_modules/network.py` (~40 lines)
- `api/host_modules/ollama_health.py` (~40 lines)
- `api/host_modules/host_tools.py` (~70 lines)
- **Total: ~400 lines** (95% reduction)

Every reimplemented feature (cortex queries, proposal generation, AI chat, X intake, email, calendar, D-Tools, markup, leads, SEO, social) is deleted because the Docker services handle them. The gateway just proxies.

### What's Preserved

- iMessage watcher integration (delegates to `tools/imessage_watcher.py`)
- Network dropout monitor (host-only subprocess)
- Ollama/LM Studio health checks (host LAN access)
- Docker container management (host-only `docker` CLI)
- Auth middleware (same token-based approach)
- Launchd service deployment

---

## Implementation Order

1. Create `api/host_modules/` directory and `__init__.py`
2. Create `api/host_modules/imessage.py`
3. Create `api/host_modules/network.py`
4. Create `api/host_modules/ollama_health.py`
5. Create `api/host_modules/host_tools.py`
6. Create `api/gateway.py`
7. Update `api/requirements.txt` (add httpx)
8. Update launchd plist ProgramArguments to point to `api/gateway.py`
9. **Move** `api/mobile_api.py` to `api/mobile_api_legacy.py` (keep as reference for 1 week, then delete)
10. Update `setup/install_mobile_api.sh` if needed
11. Commit and push

---

## Verification

1. `python3 -c "from api.gateway import app; print('Gateway OK')"` — no import errors
2. `python3 api/gateway.py` starts on port 8420
3. `curl http://localhost:8420/health` returns ok
4. `curl http://localhost:8420/dashboard` returns service statuses
5. `curl http://localhost:8420/imessages/status` returns iMessage watcher state
6. `curl http://localhost:8420/proxy/cortex/memories` proxies to cortex
7. `curl http://localhost:8420/ai/status` returns Ollama availability
8. Total line count of `api/gateway.py` + `api/host_modules/*.py` is under 500

---

## Key Constraints

- **Runs on HOST, not Docker** — needs iMessage DB, iCloud, launchd, Ollama LAN access
- **No bare `git pull`** — use `bash scripts/pull.sh`
- **No `#` characters in bash/zsh scripts** — replace with alternatives
- **All Docker service calls use httpx with timeout** — a down service must never hang the gateway
- **Keep `mobile_api.py` as `mobile_api_legacy.py`** for one week reference, then delete
