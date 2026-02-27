#!/usr/bin/env python3
"""
concierge_server.py
Symphony Smart Homes — Local Concierge AI Server

The core runtime for the Symphony Concierge appliance. Runs on a Mac Mini or
similar hardware at the client's home. Provides:

  - RAG pipeline: query → ChromaDB embed → augment prompt → Ollama generate
  - REST API endpoints: /chat, /troubleshoot, /scene, /status
  - WebSocket support for real-time streaming chat
  - Static web UI served at /
  - All inference stays local — no data leaves the appliance

Usage:
    python concierge_server.py
    python concierge_server.py --host 0.0.0.0 --port 8080
    python concierge_server.py --config /opt/symphony/concierge/config.json

Environment variables:
    SYMPHONY_CLIENT_ID, SYMPHONY_AI_NAME, SYMPHONY_MODEL_TAG,
    SYMPHONY_BASE_MODEL, OLLAMA_HOST, CHROMA_PATH, CONCIERGE_HOME

Dependencies:
    pip install fastapi uvicorn[standard] httpx chromadb sentence-transformers
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

try:
    import fastapi
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    print("ERROR: FastAPI/uvicorn not installed. Run:")
    print("  pip install fastapi uvicorn[standard] httpx")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

CONCIERGE_HOME = Path(os.environ.get("CONCIERGE_HOME", "/opt/symphony/concierge"))
LOG_DIR = CONCIERGE_HOME / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "concierge_server.log", mode="a"),
    ],
)
logger = logging.getLogger("symphony.concierge")

SERVER_VERSION = "2.0.0"

DEFAULT_CONFIG = {
    "client_id": os.environ.get("SYMPHONY_CLIENT_ID", "DEMO"),
    "ai_name": os.environ.get("SYMPHONY_AI_NAME", "Aria"),
    "model_tag": os.environ.get("SYMPHONY_MODEL_TAG", os.environ.get("SYMPHONY_BASE_MODEL", "llama3.1:8b")),
    "base_model": os.environ.get("SYMPHONY_BASE_MODEL", "llama3.1:8b"),
    "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    "chroma_path": os.environ.get("CHROMA_PATH", str(CONCIERGE_HOME / "vectorstore")),
    "chroma_collection": "symphony_home_knowledge",
    "host": os.environ.get("CONCIERGE_HOST", "0.0.0.0"),
    "port": int(os.environ.get("CONCIERGE_PORT", "8080")),
    "web_ui_path": str(CONCIERGE_HOME / "ui"),
    "max_history_turns": 10,
    "rag_n_results": 5,
    "rag_max_context_chars": 3000,
    "stream_response": True,
    "temperature": 0.4,
    "num_predict": 1024,
    "num_ctx": 8192,
}


def load_config(config_path: Optional[str] = None) -> dict:
    """Load config from file, merging with defaults and env vars."""
    config = DEFAULT_CONFIG.copy()
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            config.update(json.load(f))
    home_config = CONCIERGE_HOME / "config.json"
    if home_config.exists():
        with open(home_config) as f:
            config.update(json.load(f))
    manifest = CONCIERGE_HOME / "MANIFEST.json"
    if manifest.exists():
        with open(manifest) as f:
            m = json.load(f)
        config.setdefault("client_id", m.get("client_id", config["client_id"]))
        config.setdefault("ai_name", m.get("ai_name", config["ai_name"]))
        if m.get("model_tag"):
            config["model_tag"] = m["model_tag"]
    return config


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    session_id: str = Field(default="default")
    stream: bool = Field(default=True)
    context_override: Optional[str] = Field(default=None)


class TroubleshootRequest(BaseModel):
    device: str = Field(...)
    issue: str = Field(...)
    session_id: str = Field(default="default")


class SceneRequest(BaseModel):
    scene_name: str = Field(...)
    room: Optional[str] = Field(default=None)


class StatusResponse(BaseModel):
    status: str
    ai_name: str
    client_id: str
    model: str
    ollama_online: bool
    chroma_ready: bool
    chroma_chunks: int
    version: str
    uptime_seconds: float
    timestamp: str


class AppState:
    def __init__(self):
        self.config: dict = {}
        self.ollama_client: Optional[httpx.AsyncClient] = None
        self.chroma_collection = None
        self.embed_fn = None
        self.start_time: float = time.time()
        self.conversations: dict[str, list[dict]] = {}

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize services on startup, clean up on shutdown."""
    logger.info(f"Symphony Concierge Server v{SERVER_VERSION} starting up...")
    state.config = load_config()
    logger.info(f"Client: {state.config['client_id']} | AI: {state.config['ai_name']}")
    logger.info(f"Model: {state.config['model_tag']}")

    state.ollama_client = httpx.AsyncClient(
        base_url=state.config["ollama_host"],
        timeout=httpx.Timeout(300.0, connect=10.0),
        limits=httpx.Limits(max_connections=10),
    )

    await _wait_for_ollama(state.ollama_client, max_retries=30, retry_delay=2.0)
    await _ensure_model_available(state.ollama_client, state.config)
    state.chroma_collection, state.embed_fn = _init_chroma(state.config)

    logger.info("Concierge server ready.")
    yield

    logger.info("Concierge server shutting down...")
    if state.ollama_client:
        await state.ollama_client.aclose()
    logger.info("Shutdown complete.")


async def _wait_for_ollama(client: httpx.AsyncClient, max_retries: int, retry_delay: float):
    for attempt in range(max_retries):
        try:
            r = await client.get("/api/tags", timeout=5.0)
            if r.status_code == 200:
                logger.info("Ollama is online")
                return
        except Exception:
            pass
        logger.warning(f"Waiting for Ollama... ({attempt + 1}/{max_retries})")
        await asyncio.sleep(retry_delay)
    logger.error("Ollama not available after waiting. Proceeding anyway.")


async def _ensure_model_available(client: httpx.AsyncClient, config: dict):
    try:
        r = await client.get("/api/tags")
        models = [m["name"] for m in r.json().get("models", [])]
        model_tag = config["model_tag"]
        base_model = config["base_model"]

        if any(model_tag in m for m in models):
            logger.info(f"Custom model '{model_tag}' is available")
            return

        if any(base_model in m for m in models):
            logger.info(f"Using base model '{base_model}'")
            config["model_tag"] = base_model
            return

        logger.warning(f"Model '{model_tag}' not found. Pulling '{base_model}'...")
        async with client.stream("POST", "/api/pull", json={"name": base_model}) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "status" in data:
                            logger.info(f"Pull: {data['status']}")
                    except json.JSONDecodeError:
                        pass
        config["model_tag"] = base_model
        logger.info(f"Base model pulled: {base_model}")
    except Exception as e:
        logger.error(f"Model check failed: {e}")


def _init_chroma(config: dict):
    try:
        from knowledge_ingestion import get_chroma_client, get_or_create_collection, LocalEmbeddingFunction
        embed_fn = LocalEmbeddingFunction()
        chroma_client = get_chroma_client(config["chroma_path"])
        collection = get_or_create_collection(chroma_client, config["chroma_collection"], embed_fn)
        count = collection.count()
        logger.info(f"ChromaDB ready: {count} chunks in '{config['chroma_collection']}'")
        return collection, embed_fn
    except ImportError:
        logger.warning("knowledge_ingestion.py not found - RAG disabled.")
        return None, None
    except Exception as e:
        logger.error(f"ChromaDB init failed: {e} - RAG disabled")
        return None, None


app = FastAPI(
    title="Symphony Concierge",
    description="Local smart home AI assistant by Symphony Smart Homes",
    version=SERVER_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1", "http://192.168.*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def build_rag_context(query: str) -> str:
    if state.chroma_collection is None:
        return ""
    try:
        from knowledge_ingestion import build_rag_context as _build_rag_context
        loop = asyncio.get_event_loop()
        context = await loop.run_in_executor(
            None, _build_rag_context, query, state.chroma_collection,
            state.config.get("rag_n_results", 5),
            state.config.get("rag_max_context_chars", 3000),
        )
        return context
    except Exception as e:
        logger.warning(f"RAG context failed: {e}")
        return ""


def build_ollama_messages(session_id: str, user_message: str, rag_context: str, system_prompt_override: Optional[str] = None) -> list[dict]:
    config = state.config
    system_content = (
        f"You are {config['ai_name']}, a smart home assistant for Symphony Smart Homes. "
        f"You have deep knowledge of this client's specific system. "
        f"Be helpful, warm, concise, and accurate. "
        f"If you don't know something, say so clearly."
    )
    if system_prompt_override:
        system_content = system_prompt_override
    elif rag_context:
        system_content += f"\n\n{rag_context}"

    messages = [{"role": "system", "content": system_content}]
    history = state.conversations.get(session_id, [])
    max_turns = config.get("max_history_turns", 10)
    messages.extend(history[-max_turns * 2:])
    messages.append({"role": "user", "content": user_message})
    return messages


def update_conversation_history(session_id: str, user_message: str, assistant_response: str):
    if session_id not in state.conversations:
        state.conversations[session_id] = []
    history = state.conversations[session_id]
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_response})
    max_items = state.config.get("max_history_turns", 10) * 2
    if len(history) > max_items:
        state.conversations[session_id] = history[-max_items:]


async def ollama_chat_stream(messages: list[dict]) -> AsyncIterator[str]:
    config = state.config
    payload = {
        "model": config["model_tag"],
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": config.get("temperature", 0.4),
            "num_predict": config.get("num_predict", 1024),
            "num_ctx": config.get("num_ctx", 8192),
            "repeat_penalty": 1.1,
        },
    }
    try:
        async with state.ollama_client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise HTTPException(status_code=502, detail=f"Ollama error {response.status_code}")
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    except httpx.TimeoutException:
        yield "\n\n[Response timed out. Please try again.]"
    except httpx.ConnectError:
        yield "\n\n[Cannot reach local AI engine. Check that Ollama is running.]"


async def ollama_chat_complete(messages: list[dict]) -> str:
    config = state.config
    payload = {
        "model": config["model_tag"],
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.get("temperature", 0.4),
            "num_predict": config.get("num_predict", 1024),
            "num_ctx": config.get("num_ctx", 8192),
        },
    }
    try:
        response = await state.ollama_client.post("/api/chat", json=payload)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except httpx.TimeoutException:
        return "I'm taking longer than expected. Please try again."
    except Exception as e:
        logger.error(f"Ollama completion error: {e}")
        return "I encountered an error. Please try again."


@app.get("/")
async def serve_ui():
    ui_path = Path(state.config.get("web_ui_path", str(CONCIERGE_HOME / "ui")))
    index = ui_path / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse(_fallback_ui_html(), status_code=200)


@app.get("/status")
async def get_status() -> StatusResponse:
    config = state.config
    ollama_ok = False
    try:
        r = await state.ollama_client.get("/api/tags", timeout=3.0)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    chroma_ready = state.chroma_collection is not None
    chroma_chunks = 0
    if chroma_ready:
        try:
            chroma_chunks = state.chroma_collection.count()
        except Exception:
            chroma_ready = False

    return StatusResponse(
        status="ok" if ollama_ok else "degraded",
        ai_name=config.get("ai_name", "Aria"),
        client_id=config.get("client_id", "UNKNOWN"),
        model=config.get("model_tag", "unknown"),
        ollama_online=ollama_ok,
        chroma_ready=chroma_ready,
        chroma_chunks=chroma_chunks,
        version=SERVER_VERSION,
        uptime_seconds=round(state.uptime, 1),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/chat")
async def chat(request: ChatRequest):
    user_message = request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    logger.info(f"Chat [{request.session_id[:8]}]: '{user_message[:80]}'")
    rag_context = request.context_override or await build_rag_context(user_message)
    messages = build_ollama_messages(request.session_id, user_message, rag_context)

    if request.stream:
        full_response = []

        async def generate() -> AsyncIterator[str]:
            async for token in ollama_chat_stream(messages):
                full_response.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            complete = "".join(full_response)
            update_conversation_history(request.session_id, user_message, complete)
            yield f"data: {json.dumps({'done': True, 'full': complete})}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        response_text = await ollama_chat_complete(messages)
        update_conversation_history(request.session_id, user_message, response_text)
        return JSONResponse({
            "response": response_text,
            "session_id": request.session_id,
            "model": state.config["model_tag"],
            "rag_used": bool(rag_context),
        })


@app.post("/troubleshoot")
async def troubleshoot(request: TroubleshootRequest):
    focused_query = f"troubleshoot {request.device} {request.issue}"
    rag_context = await build_rag_context(focused_query)
    troubleshoot_prompt = (
        f"The user has an issue with: {request.device}\n"
        f"Problem description: {request.issue}\n\n"
        f"Provide a clear, numbered troubleshooting guide for their equipment. "
        f"Start with simplest checks. End with when to call Symphony."
    )
    messages = build_ollama_messages(request.session_id, troubleshoot_prompt, rag_context)
    response_text = await ollama_chat_complete(messages)
    update_conversation_history(request.session_id, request.issue, response_text)
    return JSONResponse({"device": request.device, "issue": request.issue, "response": response_text, "rag_used": bool(rag_context)})


@app.post("/scene")
async def get_scene_info(request: SceneRequest):
    query = f"scene {request.scene_name} how to activate what does it do"
    if request.room:
        query += f" {request.room}"
    rag_context = await build_rag_context(query)
    prompt = (
        f"The user wants to know about the '{request.scene_name}' scene"
        f"{f' in the {request.room}' if request.room else ''}. "
        f"Explain what it does and how to activate it using their Control4 system."
    )
    messages = build_ollama_messages("scene_queries", prompt, rag_context)
    response_text = await ollama_chat_complete(messages)
    return JSONResponse({"scene": request.scene_name, "response": response_text})


@app.delete("/chat/history/{session_id}")
async def clear_history(session_id: str):
    if session_id in state.conversations:
        del state.conversations[session_id]
    return JSONResponse({"cleared": True, "session_id": session_id})


@app.get("/config")
async def get_public_config():
    return JSONResponse({
        "ai_name": state.config.get("ai_name", "Aria"),
        "client_id": state.config.get("client_id", ""),
        "model": state.config.get("model_tag", ""),
        "version": SERVER_VERSION,
        "rag_enabled": state.chroma_collection is not None,
    })


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket connected: {session_id}")

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)
        logger.info(f"WebSocket disconnected: {session_id}")

    async def send_json(self, session_id: str, data: dict):
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(data)


ws_manager = ConnectionManager()


@app.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    await ws_manager.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            user_message = data.get("message", "").strip()
            if not user_message:
                await websocket.send_json({"type": "error", "message": "Empty message"})
                continue

            logger.info(f"WS [{session_id[:8]}]: '{user_message[:60]}'")
            await websocket.send_json({"type": "start"})

            rag_context = await build_rag_context(user_message)
            messages = build_ollama_messages(session_id, user_message, rag_context)

            full_response = []
            try:
                async for token in ollama_chat_stream(messages):
                    full_response.append(token)
                    await websocket.send_json({"type": "token", "token": token})
                complete = "".join(full_response)
                update_conversation_history(session_id, user_message, complete)
                await websocket.send_json({"type": "done", "full": complete})
            except Exception as e:
                logger.error(f"WS stream error: {e}")
                await websocket.send_json({"type": "error", "message": "Error generating response."})

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error [{session_id}]: {e}")
        ws_manager.disconnect(session_id)


ui_path = CONCIERGE_HOME / "ui"
if ui_path.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_path)), name="ui")


def _fallback_ui_html() -> str:
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Symphony Concierge</title>
<style>
  body{font-family:sans-serif;max-width:600px;margin:80px auto;text-align:center;color:#333}
  h1{color:#1a1a2e}.status{color:#c9a84c}
  input{width:80%;padding:10px;font-size:1em;border:1px solid #ddd;border-radius:4px}
  button{padding:10px 20px;background:#1a1a2e;color:#c9a84c;border:none;border-radius:4px;cursor:pointer}
  #response{text-align:left;margin-top:20px;padding:20px;background:#f9f9f9;border-radius:8px;min-height:60px}
</style></head>
<body>
<h1>Symphony Concierge</h1>
<p class="status">Fallback UI</p>
<div>
  <input id="q" placeholder="Ask anything about your home..." onkeydown="if(event.key==='Enter')ask()">
  <button onclick="ask()">Ask</button>
</div>
<div id="response">Ready.</div>
<script>
async function ask(){
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  document.getElementById('response').textContent='Thinking...';
  const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:q,stream:false})});
  const d=await r.json();
  document.getElementById('response').textContent=d.response||'No response';
}
</script>
</body></html>"""


@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Symphony Concierge Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    def _shutdown(sig, frame):
        logger.info("Received shutdown signal")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info(f"Starting Symphony Concierge on {args.host}:{args.port}")
    uvicorn.run(
        "concierge_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        access_log=True,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
