#!/usr/bin/env python3
"""
Symphony Mobile Gateway — thin proxy to Docker services + host-only functions.

Runs on the Mac host (launchd), NOT in Docker.
Needs host access for: iMessage DB, iCloud, Ollama, launchd, network tools.

Everything else proxies to Docker services.
"""

import os
import asyncio
import hashlib
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
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

AUTH_EXEMPT = {"/", "/health", "/docs", "/openapi.json", "/login", "/auth"}

SESSION_COOKIE = "symphony_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# In-memory session store (survives until process restarts, then re-login)
_sessions: dict[str, float] = {}  # token -> expiry timestamp


def _valid_session(cookie: str) -> bool:
    """Check if a session cookie is valid and not expired."""
    if not cookie:
        return False
    expiry = _sessions.get(cookie)
    if expiry is None:
        return False
    if time.time() > expiry:
        _sessions.pop(cookie, None)
        return False
    return True


def _create_session() -> str:
    """Create a new session token."""
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_MAX_AGE
    return token


@app.middleware("http")
async def auth_check(request: Request, call_next):
    """Auth: bearer token, query param, or session cookie. Skipped for public endpoints."""
    if not API_AUTH_TOKEN:
        return await call_next(request)
    if request.url.path in AUTH_EXEMPT:
        return await call_next(request)

    # 1. Session cookie
    cookie = request.cookies.get(SESSION_COOKIE, "")
    if _valid_session(cookie):
        return await call_next(request)

    # 2. Bearer header
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    # 3. Query param (also sets cookie so browser stays logged in)
    if not token:
        token = request.query_params.get("token", "")
        if token == API_AUTH_TOKEN:
            session = _create_session()
            response = await call_next(request)
            response.set_cookie(
                SESSION_COOKIE, session,
                max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
            )
            return response

    if token != API_AUTH_TOKEN:
        # Redirect browsers to login page, return 401 for API clients
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse("/login")
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


LOGIN_PAGE = """
<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Symphony Gateway</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background: #0a0a0a; color: #e0e0e0;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 2rem;
          max-width: 340px; width: 90%; text-align: center; }
  h1 { font-size: 1.4rem; margin: 0 0 0.5rem; }
  p { color: #888; font-size: 0.85rem; margin: 0 0 1.5rem; }
  input { width: 100%; padding: 0.75rem; border: 1px solid #333; border-radius: 8px;
          background: #111; color: #e0e0e0; font-size: 1rem; box-sizing: border-box;
          margin-bottom: 1rem; -webkit-appearance: none; }
  input:focus { outline: none; border-color: #5b8def; }
  button { width: 100%; padding: 0.75rem; border: none; border-radius: 8px;
           background: #5b8def; color: white; font-size: 1rem; cursor: pointer; }
  button:active { background: #4a7dde; }
  .err { color: #ef5b5b; font-size: 0.85rem; margin-top: 0.5rem; display: none; }
</style>
</head><body>
<div class="card">
  <h1>Symphony Gateway</h1>
  <p>Enter your access token</p>
  <form method="POST" action="/auth">
    <input type="password" name="token" placeholder="Token" autocomplete="current-password" required>
    <button type="submit">Sign In</button>
  </form>
  <div class="err" id="err">Invalid token</div>
</div>
<script>
  if (location.search.includes("error=1")) document.getElementById("err").style.display="block";
</script>
</body></html>
"""


@app.get("/login")
async def login_page():
    """Simple login form for browser access."""
    return HTMLResponse(LOGIN_PAGE)


@app.post("/auth")
async def auth_post(request: Request):
    """Handle login form submission — set session cookie on success."""
    form = await request.form()
    submitted = (form.get("token") or "").strip()
    if submitted != API_AUTH_TOKEN:
        return RedirectResponse("/login?error=1", status_code=303)
    session = _create_session()
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, session,
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
    )
    return response


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
