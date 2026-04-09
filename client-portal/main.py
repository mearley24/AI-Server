"""
Symphony Smart Homes — Client Portal
Port 8096 | SQLite at /data/portal.db

Endpoints:
  GET  /portal/{token}              — Client-facing project page (HTML)
  GET  /api/portal/{token}/status   — JSON status
  POST /api/portal/generate/{job_id} — Generate a new portal token for a job
"""

import logging
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, BaseLoader

logger = logging.getLogger("client_portal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DB_PATH = os.getenv("PORTAL_DB_PATH", "/data/portal.db")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portals (
                token        TEXT PRIMARY KEY,
                job_id       INT  NOT NULL,
                client_name  TEXT NOT NULL,
                project_name TEXT NOT NULL,
                current_phase TEXT NOT NULL DEFAULT 'Lead',
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portal_documents (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                token    TEXT    NOT NULL,
                name     TEXT    NOT NULL,
                url      TEXT    NOT NULL,
                added_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portal_milestones (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                token    TEXT    NOT NULL,
                name     TEXT    NOT NULL,
                amount   REAL    NOT NULL,
                status   TEXT    NOT NULL DEFAULT 'pending',
                due_date TEXT,
                paid_at  TEXT
            );
        """)
        conn.commit()


def _get_portal(token: str) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM portals WHERE token = ?", (token,)
        ).fetchone()


def _get_documents(token: str) -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM portal_documents WHERE token = ? ORDER BY added_at",
            (token,),
        ).fetchall()


def _get_milestones(token: str) -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM portal_milestones WHERE token = ? ORDER BY id",
            (token,),
        ).fetchall()


# ---------------------------------------------------------------------------
# Jinja2 template
# ---------------------------------------------------------------------------

PORTAL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ project_name }} — Symphony Smart Homes</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --navy:   #0D1B2A;
      --teal:   #20808D;
      --teal-light: #2a9fab;
      --white:  #FFFFFF;
      --gray:   #6B7280;
      --gray-light: #F3F4F6;
      --gray-mid:   #E5E7EB;
      --green:  #16A34A;
      --radius: 8px;
      --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
      --shadow-md: 0 4px 6px rgba(0,0,0,.07), 0 2px 4px rgba(0,0,0,.06);
    }

    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--gray-light);
      color: #111827;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* ── Header ────────────────────────────────────────────── */
    header {
      background: var(--navy);
      padding: 0 1.5rem;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .logo {
      display: flex;
      align-items: center;
      gap: .6rem;
      text-decoration: none;
    }

    .logo-mark {
      width: 36px;
      height: 36px;
      flex-shrink: 0;
    }

    .logo-text {
      line-height: 1.1;
    }

    .logo-text .name {
      font-size: .95rem;
      font-weight: 700;
      color: var(--white);
      letter-spacing: .02em;
    }

    .logo-text .tagline {
      font-size: .65rem;
      color: var(--teal);
      letter-spacing: .06em;
      text-transform: uppercase;
    }

    .header-badge {
      font-size: .7rem;
      font-weight: 600;
      color: var(--teal);
      border: 1px solid var(--teal);
      padding: .25rem .6rem;
      border-radius: 100px;
      letter-spacing: .04em;
      text-transform: uppercase;
    }

    /* ── Main container ─────────────────────────────────────── */
    main {
      flex: 1;
      max-width: 860px;
      width: 100%;
      margin: 2rem auto;
      padding: 0 1rem;
    }

    /* ── Hero card ───────────────────────────────────────────── */
    .hero-card {
      background: var(--white);
      border-radius: var(--radius);
      box-shadow: var(--shadow-md);
      padding: 2rem 2rem 1.5rem;
      margin-bottom: 1.5rem;
      border-top: 4px solid var(--teal);
    }

    .hero-card .project-name {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--navy);
      margin-bottom: .25rem;
    }

    .hero-card .client-name {
      font-size: .9rem;
      color: var(--gray);
      margin-bottom: 1.25rem;
    }

    .hero-card .meta {
      font-size: .75rem;
      color: var(--gray);
    }

    /* ── Section card ────────────────────────────────────────── */
    .card {
      background: var(--white);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }

    .card-title {
      font-size: .8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: var(--gray);
      margin-bottom: 1.25rem;
    }

    /* ── Progress bar ────────────────────────────────────────── */
    .progress-wrapper {
      position: relative;
      padding: .5rem 0 2.2rem;
      overflow-x: auto;
    }

    .progress-track {
      display: flex;
      align-items: center;
      min-width: 480px;
    }

    .progress-line {
      flex: 1;
      height: 2px;
      background: var(--gray-mid);
    }

    .progress-line.done {
      background: var(--teal);
    }

    .phase-dot {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--gray-mid);
      border: 2px solid var(--gray-mid);
      flex-shrink: 0;
      position: relative;
      z-index: 1;
      transition: background .2s;
    }

    .phase-dot.done {
      background: var(--teal);
      border-color: var(--teal);
    }

    .phase-dot.active {
      background: var(--white);
      border-color: var(--teal);
      box-shadow: 0 0 0 4px rgba(32,128,141,.15);
    }

    .phase-dot.active::after {
      content: '';
      position: absolute;
      inset: 4px;
      border-radius: 50%;
      background: var(--teal);
    }

    .phase-labels {
      display: flex;
      min-width: 480px;
      margin-top: .5rem;
    }

    .phase-label {
      flex: 1;
      text-align: center;
      font-size: .68rem;
      color: var(--gray);
      font-weight: 400;
    }

    .phase-label.active {
      color: var(--teal);
      font-weight: 600;
    }

    .phase-label:first-child { text-align: left; }
    .phase-label:last-child  { text-align: right; }

    /* ── Documents ───────────────────────────────────────────── */
    .doc-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: .75rem;
    }

    .doc-card {
      display: flex;
      align-items: center;
      gap: .75rem;
      padding: .85rem 1rem;
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
      text-decoration: none;
      color: var(--navy);
      transition: border-color .15s, box-shadow .15s;
    }

    .doc-card:hover {
      border-color: var(--teal);
      box-shadow: 0 0 0 2px rgba(32,128,141,.12);
    }

    .doc-icon {
      width: 32px;
      height: 32px;
      background: rgba(32,128,141,.1);
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .doc-icon svg {
      width: 16px;
      height: 16px;
      color: var(--teal);
    }

    .doc-name {
      font-size: .82rem;
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .empty-state {
      font-size: .85rem;
      color: var(--gray);
      padding: .5rem 0;
    }

    /* ── Milestones table ────────────────────────────────────── */
    .milestones-table {
      width: 100%;
      border-collapse: collapse;
      font-size: .85rem;
    }

    .milestones-table th {
      text-align: left;
      font-size: .72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .05em;
      color: var(--gray);
      padding: .5rem .75rem;
      border-bottom: 1px solid var(--gray-mid);
    }

    .milestones-table td {
      padding: .75rem .75rem;
      border-bottom: 1px solid var(--gray-mid);
      vertical-align: middle;
    }

    .milestones-table tr:last-child td {
      border-bottom: none;
    }

    .milestones-table tr:nth-child(even) td {
      background: #FAFAFA;
    }

    .amount-cell {
      font-weight: 600;
      color: var(--navy);
      white-space: nowrap;
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: .35rem;
      font-size: .75rem;
      font-weight: 600;
      padding: .25rem .65rem;
      border-radius: 100px;
    }

    .status-badge.paid {
      background: #DCFCE7;
      color: var(--green);
    }

    .status-badge.pending {
      background: #F3F4F6;
      color: var(--gray);
    }

    .status-badge svg {
      width: 12px;
      height: 12px;
      flex-shrink: 0;
    }

    .total-row td {
      font-weight: 700;
      font-size: .88rem;
      color: var(--navy);
      border-top: 2px solid var(--gray-mid);
      padding-top: 1rem;
    }

    /* ── Footer ──────────────────────────────────────────────── */
    footer {
      background: var(--navy);
      color: rgba(255,255,255,.5);
      font-size: .75rem;
      text-align: center;
      padding: 1.25rem 1rem;
      margin-top: auto;
    }

    footer a {
      color: var(--teal);
      text-decoration: none;
    }

    footer a:hover { text-decoration: underline; }

    .footer-sep { margin: 0 .4rem; opacity: .4; }

    /* ── Responsive ──────────────────────────────────────────── */
    @media (max-width: 600px) {
      .hero-card { padding: 1.5rem 1.25rem 1.25rem; }
      .card       { padding: 1.25rem; }
      main        { margin: 1rem auto; }
      .milestones-table td, .milestones-table th { padding: .6rem .5rem; }
    }
  </style>
</head>
<body>

  <!-- ── Header ─────────────────────────────────────────────── -->
  <header>
    <a class="logo" href="#">
      <!-- Inline SVG logo mark -->
      <svg class="logo-mark" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Symphony Smart Homes logo mark">
        <rect width="36" height="36" rx="8" fill="#20808D"/>
        <!-- House silhouette -->
        <path d="M18 7L6 17H9V29H15V22H21V29H27V17H30L18 7Z" fill="white" opacity="0.95"/>
        <!-- Wifi arcs -->
        <path d="M14 21 Q18 17 22 21" stroke="#0D1B2A" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.6"/>
        <path d="M16 24 Q18 22.5 20 24" stroke="#0D1B2A" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.6"/>
      </svg>
      <div class="logo-text">
        <div class="name">Symphony</div>
        <div class="tagline">Smart Homes</div>
      </div>
    </a>
    <span class="header-badge">Client Portal</span>
  </header>

  <!-- ── Main ───────────────────────────────────────────────── -->
  <main>

    <!-- Hero card -->
    <div class="hero-card">
      <div class="project-name">{{ project_name }}</div>
      <div class="client-name">{{ client_name }}</div>
      <div class="meta">Last updated {{ created_at }}</div>
    </div>

    <!-- Progress -->
    <div class="card">
      <div class="card-title">Project Phase</div>
      <div class="progress-wrapper">
        <div class="progress-track">
          {% for i, phase in phases %}
            {% if not loop.first %}
              <div class="progress-line{% if loop.index0 <= active_index %} done{% endif %}"></div>
            {% endif %}
            <div class="phase-dot{% if loop.index0 < active_index %} done{% elif loop.index0 == active_index %} active{% endif %}"></div>
          {% endfor %}
        </div>
        <div class="phase-labels">
          {% for i, phase in phases %}
            <div class="phase-label{% if loop.index0 == active_index %} active{% endif %}">{{ phase }}</div>
          {% endfor %}
        </div>
      </div>
    </div>

    <!-- Documents -->
    <div class="card">
      <div class="card-title">Documents</div>
      {% if documents %}
        <div class="doc-grid">
          {% for doc in documents %}
            <a class="doc-card" href="{{ doc.url }}" target="_blank" rel="noopener noreferrer">
              <div class="doc-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </div>
              <span class="doc-name">{{ doc.name }}</span>
            </a>
          {% endfor %}
        </div>
      {% else %}
        <p class="empty-state">No documents have been added yet.</p>
      {% endif %}
    </div>

    <!-- Payment Milestones -->
    <div class="card">
      <div class="card-title">Payment Milestones</div>
      {% if milestones %}
        <table class="milestones-table">
          <thead>
            <tr>
              <th>Milestone</th>
              <th>Amount</th>
              <th>Due</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {% for m in milestones %}
              <tr>
                <td>{{ m.name }}</td>
                <td class="amount-cell">${{ "%.2f"|format(m.amount) }}</td>
                <td style="color:var(--gray); font-size:.8rem;">{{ m.due_date or "—" }}</td>
                <td>
                  {% if m.status == "paid" %}
                    <span class="status-badge paid">
                      <!-- Checkmark -->
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12"/>
                      </svg>
                      Paid
                    </span>
                  {% else %}
                    <span class="status-badge pending">
                      <!-- Clock -->
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"/>
                        <polyline points="12 6 12 12 16 14"/>
                      </svg>
                      Pending
                    </span>
                  {% endif %}
                </td>
              </tr>
            {% endfor %}
            <tr class="total-row">
              <td>Total</td>
              <td class="amount-cell">${{ "%.2f"|format(total_amount) }}</td>
              <td></td>
              <td></td>
            </tr>
          </tbody>
        </table>
      {% else %}
        <p class="empty-state">No payment milestones have been set up yet.</p>
      {% endif %}
    </div>

  </main>

  <!-- ── Footer ─────────────────────────────────────────────── -->
  <footer>
    Powered by Symphony Smart Homes
    <span class="footer-sep">|</span>
    <a href="mailto:info@symphonysh.com">info@symphonysh.com</a>
    <span class="footer-sep">|</span>
    <a href="tel:+19705193013">(970) 519-3013</a>
    <span class="footer-sep">|</span>
    Edwards, Colorado
  </footer>

</body>
</html>"""

# Jinja2 env using the inline template
_jinja_env = Environment(loader=BaseLoader())
_jinja_env.globals["zip"] = zip
_portal_tmpl = _jinja_env.from_string(PORTAL_TEMPLATE)

# Phase ordering
PHASES: list[str] = ["Lead", "Proposal", "Won", "Procurement", "Installation", "Complete"]


def _phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    logger.info("Portal DB initialised at %s", DB_PATH)
    yield


app = FastAPI(
    title="Symphony Smart Homes — Client Portal",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/portal/{token}", response_class=HTMLResponse, include_in_schema=False)
async def portal_page(token: str) -> HTMLResponse:
    """Client-facing project status page."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    documents = _get_documents(token)
    milestones = _get_milestones(token)

    total_amount = sum(float(m["amount"]) for m in milestones)
    active_index = _phase_index(portal["current_phase"])
    phases = list(enumerate(PHASES))

    html = _portal_tmpl.render(
        project_name=portal["project_name"],
        client_name=portal["client_name"],
        created_at=portal["created_at"],
        phases=phases,
        active_index=active_index,
        documents=[dict(d) for d in documents],
        milestones=[dict(m) for m in milestones],
        total_amount=total_amount,
    )
    return HTMLResponse(content=html)


@app.get("/api/portal/{token}/status")
async def portal_status(token: str) -> JSONResponse:
    """JSON status endpoint for the given portal token."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    documents = _get_documents(token)
    milestones = _get_milestones(token)

    return JSONResponse({
        "token": token,
        "job_id": portal["job_id"],
        "client_name": portal["client_name"],
        "project_name": portal["project_name"],
        "current_phase": portal["current_phase"],
        "created_at": portal["created_at"],
        "documents": [dict(d) for d in documents],
        "milestones": [dict(m) for m in milestones],
        "total_amount": sum(float(m["amount"]) for m in milestones),
    })


@app.post("/api/portal/generate/{job_id}", status_code=201)
async def generate_portal(job_id: int, request: Request) -> JSONResponse:
    """
    Internal endpoint: generate a portal token for a job.

    JSON body (all optional except client_name / project_name):
    {
        "client_name":   "Jane Smith",
        "project_name":  "Telluride Residence",
        "current_phase": "Lead"
    }
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    client_name = body.get("client_name", "Client")
    project_name = body.get("project_name", f"Project {job_id}")
    current_phase = body.get("current_phase", "Lead")
    if current_phase not in PHASES:
        current_phase = "Lead"

    token = secrets.token_urlsafe(24)[:32]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO portals (token, job_id, client_name, project_name, current_phase, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (token, job_id, client_name, project_name, current_phase, now),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info("Portal generated: token=%s job_id=%d", token, job_id)
    return JSONResponse(
        {
            "token": token,
            "job_id": job_id,
            "client_name": client_name,
            "project_name": project_name,
            "current_phase": current_phase,
            "portal_url": f"/portal/{token}",
            "status_url": f"/api/portal/{token}/status",
        },
        status_code=201,
    )


# ---------------------------------------------------------------------------
# Dev entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8096, reload=True)
