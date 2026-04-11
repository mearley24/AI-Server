"""
Symphony Smart Homes — Client Portal
Port 8096 | SQLite at /data/portal.db

Endpoints:
  GET  /portal/{token}              — Client-facing project page (HTML)
  GET  /portal/{token}/sign         — E-signature page (HTML)
  POST /portal/{token}/sign         — Submit signed agreement
  GET  /portal/{token}/signed       — Thank-you page after signing
  GET  /portal/{token}/document     — Serve the agreement PDF
  GET  /api/portal/{token}/status   — JSON status
  POST /api/portal/generate/{job_id} — Generate a new portal token for a job
  POST /api/portal/{token}/attach-document — Attach agreement PDF to a portal
"""

import base64
import json
import logging
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import fitz  # pymupdf

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from jinja2 import Environment, BaseLoader
from pydantic import BaseModel

logger = logging.getLogger("client_portal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DB_PATH = os.getenv("PORTAL_DB_PATH", "/data/portal.db")
REDIS_URL = os.getenv("REDIS_URL", "")

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

    # Add new e-signature columns if they don't already exist
    _new_columns = [
        ("document_path",  "TEXT DEFAULT ''"),
        ("signed_at",      "TEXT DEFAULT ''"),
        ("signer_ip",      "TEXT DEFAULT ''"),
        ("signed_pdf_path","TEXT DEFAULT ''"),
        ("signature_data", "TEXT DEFAULT ''"),
    ]
    with _get_conn() as conn:
        for col_name, col_def in _new_columns:
            try:
                conn.execute(f"ALTER TABLE portals ADD COLUMN {col_name} {col_def}")
                conn.commit()
                logger.info("Added column portals.%s", col_name)
            except sqlite3.OperationalError:
                pass  # Column already exists


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
# PDF signature stamping
# ---------------------------------------------------------------------------

def stamp_signature(
    pdf_path: str,
    output_path: str,
    signer_name: str,
    signed_at: str,
    signer_ip: str,
    sig_image_b64: str = None,
) -> str:
    """Stamp the PDF with signature, metadata block, and footer on every page."""
    doc = fitz.open(pdf_path)

    # Add footer to every page
    for page in doc:
        footer_text = (
            f"Digitally executed {signed_at[:10]} — {signer_name} — "
            "Via Symphony Smart Homes Client Portal"
        )
        page.insert_text(
            fitz.Point(50, page.rect.height - 20),
            footer_text,
            fontsize=7,
            color=(0.5, 0.5, 0.5),
        )

    # Stamp signature on last page
    last_page = doc[-1]

    # Find approximate signature line location (bottom third of last page)
    sig_rect = fitz.Rect(
        72,
        last_page.rect.height * 0.65,
        350,
        last_page.rect.height * 0.75,
    )

    if sig_image_b64:
        # Insert drawn signature image
        sig_bytes = base64.b64decode(sig_image_b64.split(",")[-1])
        last_page.insert_image(sig_rect, stream=sig_bytes)
    else:
        # Insert typed signature text
        last_page.insert_text(
            fitz.Point(72, last_page.rect.height * 0.70),
            f"/{signer_name}/",
            fontsize=18,
            color=(0.05, 0.05, 0.3),
        )

    # Add signature metadata block below signature
    meta_y = last_page.rect.height * 0.76
    last_page.insert_text(
        fitz.Point(72, meta_y),
        f"Signed by: {signer_name}",
        fontsize=8,
        color=(0.3, 0.3, 0.3),
    )
    last_page.insert_text(
        fitz.Point(72, meta_y + 12),
        f"Date: {signed_at}",
        fontsize=8,
        color=(0.3, 0.3, 0.3),
    )
    last_page.insert_text(
        fitz.Point(72, meta_y + 24),
        f"IP Address: {signer_ip}",
        fontsize=8,
        color=(0.3, 0.3, 0.3),
    )
    last_page.insert_text(
        fitz.Point(72, meta_y + 36),
        "Legally binding under US ESIGN Act & UETA",
        fontsize=7,
        color=(0.5, 0.5, 0.5),
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    doc.close()
    return output_path


# ---------------------------------------------------------------------------
# Redis publish helper
# ---------------------------------------------------------------------------

def _redis_publish(channel: str, payload: dict) -> None:
    """Fire-and-forget Redis publish using redis-py (sync)."""
    if not REDIS_URL:
        return
    try:
        import redis as _redis  # type: ignore

        r = _redis.from_url(REDIS_URL, socket_connect_timeout=3)
        r.publish(channel, json.dumps(payload))
    except Exception as exc:
        logger.debug("redis_publish %s: %s", channel, exc)


# ---------------------------------------------------------------------------
# Jinja2 templates
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

    /* ── Sign Agreement CTA ─────────────────────────────────── */
    .sign-cta-wrap {
      margin-bottom: 1.5rem;
    }

    .btn-sign {
      display: inline-flex;
      align-items: center;
      gap: .5rem;
      background: var(--teal);
      color: var(--white);
      font-size: .95rem;
      font-weight: 600;
      padding: .85rem 2rem;
      border-radius: var(--radius);
      text-decoration: none;
      transition: background .15s, box-shadow .15s;
      box-shadow: 0 2px 6px rgba(32,128,141,.35);
    }

    .btn-sign:hover {
      background: var(--teal-light);
      box-shadow: 0 4px 12px rgba(32,128,141,.4);
    }

    .badge-signed {
      display: inline-flex;
      align-items: center;
      gap: .5rem;
      background: #DCFCE7;
      color: var(--green);
      font-size: .88rem;
      font-weight: 600;
      padding: .6rem 1.25rem;
      border-radius: 100px;
      border: 1px solid #86EFAC;
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

    {% if show_sign_btn %}
    <!-- Sign Agreement CTA -->
    <div class="sign-cta-wrap">
      <a class="btn-sign" href="/portal/{{ token }}/sign">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
        </svg>
        Sign Agreement
      </a>
    </div>
    {% elif signed_at %}
    <!-- Signed badge -->
    <div class="sign-cta-wrap">
      <span class="badge-signed">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        Agreement Signed &#10003; &nbsp; {{ signed_at[:10] }}
      </span>
    </div>
    {% endif %}

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

# ---------------------------------------------------------------------------
# Sign page template
# ---------------------------------------------------------------------------

SIGN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sign Agreement — Symphony Smart Homes</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Dancing+Script:wght@600&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --navy:  #0D1B2A;
      --teal:  #20808D;
      --teal-light: #2a9fab;
      --white: #FFFFFF;
      --gray:  #6B7280;
      --gray-light: #F3F4F6;
      --gray-mid:   #E5E7EB;
      --green: #16A34A;
      --radius: 8px;
      --shadow: 0 1px 3px rgba(0,0,0,.08);
      --shadow-md: 0 4px 6px rgba(0,0,0,.07);
    }

    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--gray-light);
      color: #111827;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    header {
      background: var(--navy);
      padding: 0 1.5rem;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .logo { display: flex; align-items: center; gap: .6rem; text-decoration: none; }
    .logo-mark { width: 36px; height: 36px; flex-shrink: 0; }
    .logo-text { line-height: 1.1; }
    .logo-text .name { font-size: .95rem; font-weight: 700; color: var(--white); letter-spacing: .02em; }
    .logo-text .tagline { font-size: .65rem; color: var(--teal); letter-spacing: .06em; text-transform: uppercase; }
    .header-badge { font-size: .7rem; font-weight: 600; color: var(--teal); border: 1px solid var(--teal); padding: .25rem .6rem; border-radius: 100px; letter-spacing: .04em; text-transform: uppercase; }

    main {
      flex: 1;
      max-width: 860px;
      width: 100%;
      margin: 2rem auto;
      padding: 0 1rem;
    }

    h1 {
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--navy);
      margin-bottom: .4rem;
    }

    .sub {
      font-size: .88rem;
      color: var(--gray);
      margin-bottom: 1.5rem;
    }

    .card {
      background: var(--white);
      border-radius: var(--radius);
      box-shadow: var(--shadow-md);
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }

    .section-label {
      font-size: .75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: var(--gray);
      margin-bottom: .75rem;
    }

    /* Document embed */
    .doc-embed {
      width: 100%;
      height: 480px;
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
    }

    .doc-missing {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 120px;
      border: 1px dashed var(--gray-mid);
      border-radius: var(--radius);
      color: var(--gray);
      font-size: .88rem;
    }

    /* Tabs */
    .tabs { display: flex; border-bottom: 2px solid var(--gray-mid); margin-bottom: 1rem; }
    .tab-btn {
      padding: .6rem 1.25rem;
      font-size: .88rem;
      font-weight: 500;
      cursor: pointer;
      background: none;
      border: none;
      color: var(--gray);
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
      transition: color .15s;
    }
    .tab-btn.active { color: var(--teal); border-bottom-color: var(--teal); font-weight: 600; }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* Canvas */
    .canvas-wrap {
      position: relative;
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
      background: #FAFAFA;
      overflow: hidden;
    }
    #sig-canvas { display: block; width: 100%; touch-action: none; cursor: crosshair; }
    .canvas-hint {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: none;
      color: var(--gray-mid);
      font-size: .88rem;
      font-style: italic;
      user-select: none;
    }
    .clear-btn {
      margin-top: .5rem;
      font-size: .8rem;
      color: var(--teal);
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      text-decoration: underline;
    }

    /* Typed sig */
    .typed-sig-input {
      width: 100%;
      font-family: 'Dancing Script', cursive;
      font-size: 2rem;
      color: var(--navy);
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
      padding: .75rem 1rem;
      outline: none;
      background: #FAFAFA;
      transition: border-color .15s;
    }
    .typed-sig-input:focus { border-color: var(--teal); background: var(--white); }
    .typed-sig-preview {
      min-height: 60px;
      display: flex;
      align-items: center;
      padding: .5rem 1rem;
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
      background: #FAFAFA;
      margin-top: .5rem;
      font-family: 'Dancing Script', cursive;
      font-size: 2rem;
      color: var(--navy);
    }

    /* Form fields */
    .form-row { margin-bottom: 1.1rem; }
    .form-label { font-size: .82rem; font-weight: 500; color: #374151; display: block; margin-bottom: .35rem; }
    .form-input {
      width: 100%;
      border: 1px solid var(--gray-mid);
      border-radius: var(--radius);
      padding: .6rem .85rem;
      font-size: .9rem;
      font-family: inherit;
      color: #111827;
      outline: none;
      transition: border-color .15s;
    }
    .form-input:focus { border-color: var(--teal); }
    .form-input[readonly] { background: var(--gray-light); color: var(--gray); cursor: default; }

    /* Checkbox */
    .checkbox-row {
      display: flex;
      align-items: flex-start;
      gap: .75rem;
      padding: 1rem;
      background: #F0FDF4;
      border: 1px solid #BBF7D0;
      border-radius: var(--radius);
      margin-bottom: 1.25rem;
    }
    .checkbox-row input[type="checkbox"] {
      width: 18px; height: 18px; flex-shrink: 0; accent-color: var(--teal); cursor: pointer; margin-top: 2px;
    }
    .checkbox-label { font-size: .85rem; color: #166534; line-height: 1.5; }

    /* Submit button */
    .btn-submit {
      width: 100%;
      background: var(--navy);
      color: var(--white);
      font-size: 1rem;
      font-weight: 600;
      padding: .9rem 2rem;
      border: none;
      border-radius: var(--radius);
      cursor: pointer;
      transition: background .15s, opacity .15s;
      letter-spacing: .01em;
    }
    .btn-submit:hover { background: #1a3149; }
    .btn-submit:disabled { opacity: .5; cursor: not-allowed; }

    /* Error msg */
    #error-msg {
      display: none;
      color: #DC2626;
      font-size: .85rem;
      margin-top: .75rem;
      padding: .65rem 1rem;
      background: #FEF2F2;
      border: 1px solid #FECACA;
      border-radius: var(--radius);
    }

    footer {
      background: var(--navy);
      color: rgba(255,255,255,.5);
      font-size: .75rem;
      text-align: center;
      padding: 1.25rem 1rem;
      margin-top: auto;
    }
    footer a { color: var(--teal); text-decoration: none; }
    footer a:hover { text-decoration: underline; }
    .footer-sep { margin: 0 .4rem; opacity: .4; }

    @media (max-width: 600px) {
      .card { padding: 1.25rem; }
      main  { margin: 1rem auto; }
    }
  </style>
</head>
<body>

  <header>
    <a class="logo" href="/portal/{{ token }}">
      <svg class="logo-mark" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="36" height="36" rx="8" fill="#20808D"/>
        <path d="M18 7L6 17H9V29H15V22H21V29H27V17H30L18 7Z" fill="white" opacity="0.95"/>
        <path d="M14 21 Q18 17 22 21" stroke="#0D1B2A" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.6"/>
        <path d="M16 24 Q18 22.5 20 24" stroke="#0D1B2A" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.6"/>
      </svg>
      <div class="logo-text">
        <div class="name">Symphony</div>
        <div class="tagline">Smart Homes</div>
      </div>
    </a>
    <span class="header-badge">E-Signature</span>
  </header>

  <main>
    <h1>Sign Your Agreement</h1>
    <p class="sub">{{ project_name }} &mdash; {{ client_name }}</p>

    <!-- Agreement Document -->
    <div class="card">
      <div class="section-label">Agreement Document</div>
      {% if has_document %}
        <embed class="doc-embed" src="/portal/{{ token }}/document" type="application/pdf" />
      {% else %}
        <div class="doc-missing">No agreement document attached yet. Please contact Symphony Smart Homes.</div>
      {% endif %}
    </div>

    <!-- Signature Form -->
    <div class="card">
      <div class="section-label">Your Signature</div>

      <!-- Tabs -->
      <div class="tabs">
        <button class="tab-btn active" data-tab="draw">Draw Signature</button>
        <button class="tab-btn" data-tab="type">Type Signature</button>
      </div>

      <!-- Draw tab -->
      <div id="tab-draw" class="tab-panel active">
        <div class="canvas-wrap">
          <canvas id="sig-canvas" height="160"></canvas>
          <div class="canvas-hint" id="canvas-hint">Sign here using your mouse or finger</div>
        </div>
        <button class="clear-btn" id="clear-btn" type="button">Clear</button>
      </div>

      <!-- Type tab -->
      <div id="tab-type" class="tab-panel">
        <input
          class="typed-sig-input"
          id="typed-name-sig"
          type="text"
          placeholder="Type your full name"
          autocomplete="off"
          spellcheck="false"
        />
        <div class="typed-sig-preview" id="typed-preview"></div>
      </div>

      <!-- Fields -->
      <div style="margin-top: 1.5rem;">
        <div class="form-row">
          <label class="form-label" for="full-name">Full Name <span style="color:#DC2626">*</span></label>
          <input class="form-input" id="full-name" type="text" placeholder="Enter your full legal name" required />
        </div>
        <div class="form-row">
          <label class="form-label" for="sign-date">Date</label>
          <input class="form-input" id="sign-date" type="text" readonly />
        </div>
      </div>

      <!-- Terms -->
      <div class="checkbox-row">
        <input type="checkbox" id="agree-chk" />
        <label class="checkbox-label" for="agree-chk">
          By signing below, I agree to the terms of the Smart Home Integration Agreement as presented.
          This signature is legally binding under the US ESIGN Act and UETA.
        </label>
      </div>

      <button class="btn-submit" id="submit-btn" type="button">Sign &amp; Submit</button>
      <div id="error-msg"></div>
    </div>
  </main>

  <footer>
    Powered by Symphony Smart Homes
    <span class="footer-sep">|</span>
    <a href="mailto:info@symphonysh.com">info@symphonysh.com</a>
    <span class="footer-sep">|</span>
    <a href="tel:+19705193013">(970) 519-3013</a>
    <span class="footer-sep">|</span>
    Edwards, Colorado
  </footer>

  <script>
    // ── Tabs ─────────────────────────────────────────────────
    const tabBtns = document.querySelectorAll('.tab-btn');
    let activeTab = 'draw';

    tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.tab;
        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.getElementById('tab-' + activeTab).classList.add('active');
      });
    });

    // ── Signature Pad (Draw) ─────────────────────────────────
    const canvas = document.getElementById('sig-canvas');
    const hint   = document.getElementById('canvas-hint');

    function resizeCanvas() {
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      canvas.width  = canvas.offsetWidth  * ratio;
      canvas.height = canvas.offsetHeight * ratio;
      canvas.getContext('2d').scale(ratio, ratio);
      sigPad.clear();
    }

    const sigPad = new SignaturePad(canvas, {
      backgroundColor: 'rgba(0,0,0,0)',
      penColor: '#0D1B2A',
      minWidth: 1.2,
      maxWidth: 2.8,
    });

    sigPad.addEventListener('beginStroke', () => { hint.style.display = 'none'; });

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    document.getElementById('clear-btn').addEventListener('click', () => {
      sigPad.clear();
      hint.style.display = 'flex';
    });

    // ── Typed Signature ───────────────────────────────────────
    const typedInput   = document.getElementById('typed-name-sig');
    const typedPreview = document.getElementById('typed-preview');
    typedInput.addEventListener('input', () => {
      typedPreview.textContent = typedInput.value;
    });

    // ── Auto-fill date ────────────────────────────────────────
    const dateField = document.getElementById('sign-date');
    const now = new Date();
    dateField.value = now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

    // ── Submit ────────────────────────────────────────────────
    const submitBtn  = document.getElementById('submit-btn');
    const errorMsg   = document.getElementById('error-msg');
    const fullName   = document.getElementById('full-name');
    const agreeChk   = document.getElementById('agree-chk');

    submitBtn.addEventListener('click', async () => {
      errorMsg.style.display = 'none';

      const name = fullName.value.trim();
      if (!name) { showError('Please enter your full name.'); return; }
      if (!agreeChk.checked) { showError('Please check the agreement checkbox.'); return; }

      let sigData = '';
      let sigType = '';

      if (activeTab === 'draw') {
        if (sigPad.isEmpty()) { showError('Please draw your signature.'); return; }
        sigData = sigPad.toDataURL('image/png');
        sigType = 'drawn';
      } else {
        const typed = typedInput.value.trim();
        if (!typed) { showError('Please type your signature.'); return; }
        sigData = typed;
        sigType = 'typed';
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Submitting…';

      try {
        const resp = await fetch('/portal/{{ token }}/sign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            signature_data_b64: sigData,
            signature_type: sigType,
            agreed: true,
          }),
        });
        const data = await resp.json();
        if (resp.ok) {
          window.location.href = '/portal/{{ token }}/signed';
        } else {
          showError(data.detail || 'An error occurred. Please try again.');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Sign & Submit';
        }
      } catch (err) {
        showError('Network error. Please check your connection and try again.');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign & Submit';
      }
    });

    function showError(msg) {
      errorMsg.textContent = msg;
      errorMsg.style.display = 'block';
    }
  </script>

</body>
</html>"""

# ---------------------------------------------------------------------------
# Thank-you page template
# ---------------------------------------------------------------------------

SIGNED_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Agreement Signed — Symphony Smart Homes</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --navy: #0D1B2A; --teal: #20808D; --white: #FFFFFF;
      --gray: #6B7280; --gray-light: #F3F4F6; --green: #16A34A;
      --radius: 8px; --shadow-md: 0 4px 6px rgba(0,0,0,.07);
    }
    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--gray-light);
      color: #111827;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--navy);
      padding: 0 1.5rem;
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .logo { display: flex; align-items: center; gap: .6rem; text-decoration: none; }
    .logo-mark { width: 36px; height: 36px; }
    .logo-text { line-height: 1.1; }
    .logo-text .name { font-size: .95rem; font-weight: 700; color: var(--white); }
    .logo-text .tagline { font-size: .65rem; color: var(--teal); letter-spacing: .06em; text-transform: uppercase; }
    .header-badge { font-size: .7rem; font-weight: 600; color: var(--teal); border: 1px solid var(--teal); padding: .25rem .6rem; border-radius: 100px; }

    main {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem 1rem;
    }
    .success-card {
      background: var(--white);
      border-radius: var(--radius);
      box-shadow: var(--shadow-md);
      padding: 3rem 2.5rem;
      text-align: center;
      max-width: 520px;
      width: 100%;
    }
    .check-circle {
      width: 72px;
      height: 72px;
      background: #DCFCE7;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 1.5rem;
    }
    .check-circle svg { width: 36px; height: 36px; color: var(--green); }
    h1 { font-size: 1.5rem; font-weight: 700; color: var(--navy); margin-bottom: .5rem; }
    .sub { font-size: .95rem; color: var(--gray); margin-bottom: 1.25rem; }
    .signed-at {
      display: inline-block;
      background: #DCFCE7;
      color: var(--green);
      font-size: .82rem;
      font-weight: 600;
      padding: .4rem 1rem;
      border-radius: 100px;
      border: 1px solid #86EFAC;
      margin-bottom: 1.5rem;
    }
    .next-steps {
      font-size: .88rem;
      color: var(--gray);
      line-height: 1.7;
      margin-bottom: 2rem;
      padding: 1rem;
      background: var(--gray-light);
      border-radius: var(--radius);
    }
    .btn-portal {
      display: inline-flex;
      align-items: center;
      gap: .5rem;
      background: var(--teal);
      color: var(--white);
      font-size: .9rem;
      font-weight: 600;
      padding: .75rem 1.75rem;
      border-radius: var(--radius);
      text-decoration: none;
      transition: background .15s;
    }
    .btn-portal:hover { background: #2a9fab; }

    footer {
      background: var(--navy);
      color: rgba(255,255,255,.5);
      font-size: .75rem;
      text-align: center;
      padding: 1.25rem 1rem;
    }
    footer a { color: var(--teal); text-decoration: none; }
    .footer-sep { margin: 0 .4rem; opacity: .4; }
  </style>
</head>
<body>
  <header>
    <a class="logo" href="/portal/{{ token }}">
      <svg class="logo-mark" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="36" height="36" rx="8" fill="#20808D"/>
        <path d="M18 7L6 17H9V29H15V22H21V29H27V17H30L18 7Z" fill="white" opacity="0.95"/>
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

  <main>
    <div class="success-card">
      <div class="check-circle">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <h1>Agreement Signed Successfully</h1>
      <p class="sub">{{ project_name }}</p>
      <div class="signed-at">Signed on {{ signed_at }}</div>
      <div class="next-steps">
        Symphony Smart Homes will be in touch shortly to discuss next steps.
        Our team will review your signed agreement and reach out within 1 business day.
      </div>
      <a class="btn-portal" href="/portal/{{ token }}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
          <polyline points="9 22 9 12 15 12 15 22"/>
        </svg>
        Return to Your Portal
      </a>
    </div>
  </main>

  <footer>
    Powered by Symphony Smart Homes
    <span class="footer-sep">|</span>
    <a href="mailto:info@symphonysh.com">info@symphonysh.com</a>
    <span class="footer-sep">|</span>
    Edwards, Colorado
  </footer>
</body>
</html>"""

# Jinja2 env using the inline templates
_jinja_env = Environment(loader=BaseLoader())
_jinja_env.globals["zip"] = zip
_portal_tmpl = _jinja_env.from_string(PORTAL_TEMPLATE)
_sign_tmpl = _jinja_env.from_string(SIGN_TEMPLATE)
_signed_tmpl = _jinja_env.from_string(SIGNED_TEMPLATE)

# Phase ordering
PHASES: list[str] = ["Lead", "Proposal", "Won", "Procurement", "Installation", "Complete"]


def _phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class SignRequest(BaseModel):
    name: str
    signature_data_b64: str
    signature_type: str  # "drawn" | "typed"
    agreed: bool


class AttachDocumentRequest(BaseModel):
    document_path: str


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
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "client-portal"}


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

    # Determine sign button visibility
    portal_dict = dict(portal)
    signed_at = portal_dict.get("signed_at", "") or ""
    document_path = portal_dict.get("document_path", "") or ""
    show_sign_btn = (not signed_at) and bool(document_path)

    html = _portal_tmpl.render(
        token=token,
        project_name=portal["project_name"],
        client_name=portal["client_name"],
        created_at=portal["created_at"],
        phases=phases,
        active_index=active_index,
        documents=[dict(d) for d in documents],
        milestones=[dict(m) for m in milestones],
        total_amount=total_amount,
        show_sign_btn=show_sign_btn,
        signed_at=signed_at,
    )
    return HTMLResponse(content=html)


@app.get("/portal/{token}/sign", response_class=HTMLResponse, include_in_schema=False)
async def sign_page(token: str) -> HTMLResponse:
    """E-signature page for the client to sign the agreement."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    portal_dict = dict(portal)
    signed_at = portal_dict.get("signed_at", "") or ""
    if signed_at:
        # Already signed — redirect to thank-you page
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/portal/{token}/signed")

    document_path = portal_dict.get("document_path", "") or ""
    has_document = bool(document_path) and os.path.isfile(document_path)

    html = _sign_tmpl.render(
        token=token,
        project_name=portal["project_name"],
        client_name=portal["client_name"],
        has_document=has_document,
    )
    return HTMLResponse(content=html)


@app.get("/portal/{token}/document", include_in_schema=False)
async def serve_document(token: str):
    """Serve the agreement PDF for embedding in the sign page."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    document_path = (dict(portal).get("document_path", "") or "").strip()
    if not document_path:
        raise HTTPException(status_code=404, detail="No agreement document has been attached to this portal.")
    if not os.path.isfile(document_path):
        raise HTTPException(
            status_code=404,
            detail=f"Agreement document not found on server. Please contact Symphony Smart Homes.",
        )
    return FileResponse(document_path, media_type="application/pdf")


@app.post("/portal/{token}/sign")
async def submit_signature(token: str, body: SignRequest, request: Request) -> JSONResponse:
    """Accept and process a signed agreement submission."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    portal_dict = dict(portal)
    signed_at_existing = portal_dict.get("signed_at", "") or ""
    if signed_at_existing:
        raise HTTPException(status_code=409, detail="This agreement has already been signed.")

    if not body.agreed:
        raise HTTPException(status_code=400, detail="You must agree to the terms to sign.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Signer name is required.")

    document_path = (portal_dict.get("document_path", "") or "").strip()
    if not document_path or not os.path.isfile(document_path):
        raise HTTPException(status_code=400, detail="No agreement document is attached. Cannot sign.")

    # Capture signing metadata
    signer_ip = request.client.host if request.client else "unknown"
    now_iso = datetime.now(timezone.utc).isoformat()
    signer_name = body.name.strip()

    # Build output PDF path
    output_path = f"/data/signed/{token}_signed.pdf"

    # Determine signature image (drawn) vs typed
    sig_image_b64: Optional[str] = None
    if body.signature_type == "drawn":
        sig_image_b64 = body.signature_data_b64

    # Stamp the PDF
    try:
        stamp_signature(
            pdf_path=document_path,
            output_path=output_path,
            signer_name=signer_name,
            signed_at=now_iso,
            signer_ip=signer_ip,
            sig_image_b64=sig_image_b64,
        )
    except Exception as exc:
        logger.error("stamp_signature failed for token=%s: %s", token, exc)
        raise HTTPException(status_code=500, detail="Failed to stamp the PDF signature. Please try again.")

    # Persist to DB
    sig_data_to_store = body.signature_data_b64 if body.signature_type == "drawn" else ""
    with _get_conn() as conn:
        conn.execute(
            """UPDATE portals
               SET signed_at = ?, signer_ip = ?, signed_pdf_path = ?, signature_data = ?
               WHERE token = ?""",
            (now_iso, signer_ip, output_path, sig_data_to_store, token),
        )
        conn.commit()

    # Publish Redis event
    job_id = portal_dict.get("job_id", "")
    client_name = portal_dict.get("client_name", "")
    _redis_publish(
        "events:agreement_signed",
        {
            "token": token,
            "client_name": client_name,
            "signer_name": signer_name,
            "signed_at": now_iso,
            "signer_ip": signer_ip,
            "signed_pdf_path": output_path,
            "job_id": job_id,
        },
    )

    logger.info(
        "Agreement signed: token=%s signer=%s ip=%s job_id=%s",
        token, signer_name, signer_ip, job_id,
    )
    return JSONResponse(
        {"status": "signed", "message": "Thank you! Your agreement has been signed. We'll be in touch shortly."}
    )


@app.get("/portal/{token}/signed", response_class=HTMLResponse, include_in_schema=False)
async def signed_page(token: str) -> HTMLResponse:
    """Thank-you page displayed after successful signing."""
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    portal_dict = dict(portal)
    signed_at = portal_dict.get("signed_at", "") or ""
    # Format the date nicely if present
    display_date = signed_at
    if signed_at:
        try:
            dt = datetime.fromisoformat(signed_at)
            display_date = dt.strftime("%B %d, %Y at %I:%M %p UTC")
        except Exception:
            display_date = signed_at

    html = _signed_tmpl.render(
        token=token,
        project_name=portal["project_name"],
        signed_at=display_date,
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
    portal_dict = dict(portal)

    return JSONResponse({
        "token": token,
        "job_id": portal_dict["job_id"],
        "client_name": portal_dict["client_name"],
        "project_name": portal_dict["project_name"],
        "current_phase": portal_dict["current_phase"],
        "created_at": portal_dict["created_at"],
        "document_path": portal_dict.get("document_path", "") or "",
        "signed_at": portal_dict.get("signed_at", "") or "",
        "signer_ip": portal_dict.get("signer_ip", "") or "",
        "signed_pdf_path": portal_dict.get("signed_pdf_path", "") or "",
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
        "current_phase": "Lead",
        "document_path": "/data/agreements/contract.pdf"   (optional)
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
    document_path = body.get("document_path", "")
    if current_phase not in PHASES:
        current_phase = "Lead"

    token = secrets.token_urlsafe(24)[:32]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO portals
                       (token, job_id, client_name, project_name, current_phase, created_at, document_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (token, job_id, client_name, project_name, current_phase, now, document_path),
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
            "document_path": document_path,
            "portal_url": f"/portal/{token}",
            "status_url": f"/api/portal/{token}/status",
            "sign_url": f"/portal/{token}/sign",
        },
        status_code=201,
    )


@app.post("/api/portal/{token}/attach-document")
async def attach_document(token: str, body: AttachDocumentRequest) -> JSONResponse:
    """
    Internal endpoint: attach an agreement PDF to a portal.
    Body: {"document_path": "/absolute/path/to/agreement.pdf"}
    """
    portal = _get_portal(token)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")

    document_path = body.document_path.strip()
    if not document_path:
        raise HTTPException(status_code=400, detail="document_path must not be empty")

    with _get_conn() as conn:
        conn.execute(
            "UPDATE portals SET document_path = ? WHERE token = ?",
            (document_path, token),
        )
        conn.commit()

    logger.info("Document attached: token=%s path=%s", token, document_path)
    return JSONResponse({"status": "ok", "token": token, "document_path": document_path})


# ---------------------------------------------------------------------------
# Dev entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8096, reload=True)
