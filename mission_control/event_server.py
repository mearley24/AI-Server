#!/usr/bin/env python3
"""
Symphony Mission Control — Event Server

Real-time event streaming via WebSocket + SQLite archive.
All employees emit events here; dashboard and menu bar connect to watch.

Usage:
    python3 event_server.py                    # Start server on port 8765
    python3 event_server.py --port 9000        # Custom port
"""

import asyncio
import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

# ============================================================
# CONFIG
# ============================================================

AI_SERVER = Path(__file__).parent.parent
DB_PATH = AI_SERVER / "mission_control" / "events.db"
STATIC_DIR = Path(__file__).parent / "static"

# ============================================================
# DATABASE
# ============================================================

def init_db():
    """Initialize SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            employee TEXT NOT NULL,
            event_type TEXT NOT NULL,
            category TEXT,
            title TEXT NOT NULL,
            details TEXT,
            metadata TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_employee ON events(employee)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)
    """)
    
    # Daily digest table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            stats TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")


def store_event(event: dict) -> int:
    """Store an event in the database. Returns event ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO events (timestamp, employee, event_type, category, title, details, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("timestamp", datetime.now().isoformat()),
        event.get("employee", "unknown"),
        event.get("event_type", "unknown"),
        event.get("category"),
        event.get("title", ""),
        event.get("details"),
        json.dumps(event.get("metadata")) if event.get("metadata") else None
    ))
    
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return event_id


def get_recent_events(
    limit: int = 100,
    employee: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None
) -> list:
    """Get recent events from database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    if employee:
        query += " AND employee = ?"
        params.append(employee)
    
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    
    if since:
        query += " AND timestamp > ?"
        params.append(since)
    
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_employee_stats(hours: int = 24) -> dict:
    """Get stats per employee for the last N hours."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    since = datetime.now().isoformat()[:10]  # Today's date
    
    cursor.execute("""
        SELECT 
            employee,
            COUNT(*) as event_count,
            COUNT(DISTINCT event_type) as event_types,
            MAX(timestamp) as last_active
        FROM events
        WHERE timestamp > datetime('now', '-' || ? || ' hours')
        GROUP BY employee
    """, (hours,))
    
    rows = cursor.fetchall()
    conn.close()
    
    stats = {}
    for row in rows:
        stats[row[0]] = {
            "event_count": row[1],
            "event_types": row[2],
            "last_active": row[3]
        }
    
    return stats


# ============================================================
# WEBSOCKET MANAGER
# ============================================================

class ConnectionManager:
    """Manage WebSocket connections."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.employee_status: dict[str, dict] = {
            "bob": {"status": "idle", "current_task": None, "last_seen": None},
            "betty": {"status": "idle", "current_task": None, "last_seen": None},
            "beatrice": {"status": "idle", "current_task": None, "last_seen": None},
            "bill": {"status": "idle", "current_task": None, "last_seen": None},
        }
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current status to new connection
        await websocket.send_json({
            "type": "status_update",
            "employees": self.employee_status,
            "timestamp": datetime.now().isoformat()
        })
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, event: dict):
        """Broadcast event to all connected clients."""
        # Update employee status
        employee = event.get("employee")
        if employee and employee in self.employee_status:
            self.employee_status[employee]["last_seen"] = datetime.now().isoformat()
            
            event_type = event.get("event_type", "")
            if "task.claimed" in event_type:
                self.employee_status[employee]["status"] = "working"
                self.employee_status[employee]["current_task"] = event.get("title")
            elif "task.completed" in event_type or "task.passed" in event_type:
                self.employee_status[employee]["status"] = "idle"
                self.employee_status[employee]["current_task"] = None
            elif "message" in event_type:
                self.employee_status[employee]["status"] = "active"
        
        # Broadcast to all clients
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except:
                disconnected.append(connection)
        
        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()

# ============================================================
# FASTAPI APP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize on startup."""
    init_db()
    yield

app = FastAPI(
    title="Symphony Mission Control",
    description="Real-time AI employee monitoring",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard (prefer Mission Control index.html, else legacy dashboard)."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    html_path = STATIC_DIR / "dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Symphony Mission Control</h1><p>Dashboard loading...</p>")


@app.get("/neural", response_class=HTMLResponse)
async def neural_view():
    """Serve the neural decision map."""
    html_path = STATIC_DIR / "neural_view.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Neural Map</h1><p>Loading...</p>")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and receive any client messages
            data = await websocket.receive_text()
            # Could handle client commands here
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/event")
async def receive_event(event: dict):
    """Receive and broadcast an event from an employee."""
    # Add timestamp if missing
    if "timestamp" not in event:
        event["timestamp"] = datetime.now().isoformat()
    
    # Store in database
    event_id = store_event(event)
    event["id"] = event_id
    
    # Broadcast to all connected clients
    await manager.broadcast(event)
    
    return {"status": "ok", "event_id": event_id}


@app.get("/events")
async def get_events(
    limit: int = Query(100, le=1000),
    employee: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None
):
    """Get recent events."""
    events = get_recent_events(limit, employee, event_type, since)
    return {"events": events, "count": len(events)}


@app.get("/status")
async def get_status():
    """Get current employee status."""
    stats = get_employee_stats(24)
    return {
        "employees": manager.employee_status,
        "stats_24h": stats,
        "connections": len(manager.active_connections)
    }


@app.get("/digest")
async def get_digest(date: Optional[str] = None):
    """Get or generate daily digest."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Check if digest exists
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_digests WHERE date = ?", (date,))
    row = cursor.fetchone()
    
    if row:
        conn.close()
        return dict(row)
    
    # Generate digest
    cursor.execute("""
        SELECT 
            employee,
            event_type,
            COUNT(*) as count
        FROM events
        WHERE date(timestamp) = ?
        GROUP BY employee, event_type
        ORDER BY employee, count DESC
    """, (date,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Format digest
    by_employee = {}
    for row in rows:
        emp = row["employee"]
        if emp not in by_employee:
            by_employee[emp] = []
        by_employee[emp].append(f"{row['event_type']}: {row['count']}")
    
    digest_lines = [f"# Symphony Daily Digest — {date}\n"]
    for emp, actions in by_employee.items():
        digest_lines.append(f"\n## {emp.title()}")
        for action in actions:
            digest_lines.append(f"- {action}")
    
    digest_content = "\n".join(digest_lines)
    
    return {
        "date": date,
        "content": digest_content,
        "stats": by_employee
    }


# ============================================================
# MAIN
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Symphony Mission Control Server")
    parser.add_argument("--port", type=int, default=8765, help="Port to run on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: localhost)")
    
    args = parser.parse_args()
    
    print(f"🎼 Symphony Mission Control starting on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
