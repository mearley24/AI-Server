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
    "cortex":        "http://localhost:8102",
    "proposals":     "http://localhost:8091",
    "email":         "http://localhost:8092",
    "voice":         "http://localhost:8093",
    "calendar":      "http://localhost:8094",
    "notifications": "http://localhost:8095",
    "portal":        "http://localhost:8096",
    "openclaw":      "http://localhost:8099",
    "x-intake":      "http://localhost:8101",
    "trading":       "http://localhost:8430",
}

AUTH_EXEMPT = {"/", "/health", "/docs", "/openapi.json"}


@app.middleware("http")
async def auth_check(request: Request, call_next):
    """Bearer token auth — skipped for public endpoints and when no token is configured."""
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


@app.api_route("/proxy/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    """Forward requests to Docker services.

    Example: GET /proxy/cortex/memories  ->  GET http://localhost:8102/memories
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
                body = None
                ct = request.headers.get("content-type", "")
                if ct.startswith("application/json"):
                    body = await request.json()
                r = await client.request(request.method, target, json=body)
            return JSONResponse(content=r.json(), status_code=r.status_code)
        except httpx.TimeoutException:
            return JSONResponse(content={"error": "timeout"}, status_code=504)
        except Exception as exc:
            return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/cortex/stats")
async def cortex_stats():
    """Cortex health shortcut."""
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get(f"{SERVICES['cortex']}/health")
            return r.json()
        except Exception:
            return {"status": "offline"}


@app.get("/cortex/memories")
async def cortex_memories(category: str = None, limit: int = 20):
    """Cortex memories shortcut."""
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
    """Trading bot health shortcut."""
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            r = await c.get(f"{SERVICES['trading']}/health")
            return r.json()
        except Exception:
            return {"status": "offline"}


app.include_router(imessage_router, prefix="/imessages", tags=["iMessage"])
app.include_router(network_router, prefix="/network", tags=["Network"])
app.include_router(ollama_router, prefix="/ai", tags=["AI"])
app.include_router(tools_router, prefix="/host", tags=["Host Tools"])

if __name__ == "__main__":
    bind_host = os.environ.get("MOBILE_API_BIND_HOST", "127.0.0.1")
    uvicorn.run("gateway:app", host=bind_host, port=PORT, log_level="info")
