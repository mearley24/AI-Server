#!/usr/bin/env python3
"""
services/file-watcher/main.py

Symphony Smart Homes — File Watcher
====================================
Watches the iCloud SymphonySH/Projects/ folder for new proposal PDFs, then:
  1. Matches the file to a project (via projects.json keywords)
  2. Archives any existing version of the file in [Project]/Archive/
  3. Renames to client-facing format: "Symphony Smart Homes - [Address] - [DocType].pdf"
  4. Copies to [Project]/Client/ in Dropbox
  5. Publishes a Redis "files:new" event

When a "files:new" Redis event fires (subscribed in a background thread):
  6. Generates a Dropbox share link via API v2
  7. Sends Matt an iMessage for approval (via notification-hub)
  8. Queues a Zoho email draft (via notification-hub Hermes channel)
  9. Creates a follow-up in OpenClaw if doc type is Agreement
  10. Logs an observation to Cortex
  11. Publishes "files:processed"

Also watches the Dropbox root for PDFs that land there by accident and moves
them to the correct [Project]/Client/ folder.

Channels:
  Publishes:  files:new, files:processed
  Subscribes: files:new

Run modes:
  • LaunchAgent (recommended) — runs natively on Bob, brctl works, best iCloud compatibility
  • Docker — set IS_DOCKER=true; brctl is skipped, iCloud/Dropbox are bind-mounted

Log: /tmp/file-watcher.log
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import dropbox
import dropbox.sharing
import redis
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH = os.getenv("LOG_PATH", "/tmp/file-watcher.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("file-watcher")

# ── Config ────────────────────────────────────────────────────────────────────
IS_DOCKER = os.getenv("IS_DOCKER", "false").lower() == "true"

# Native paths (LaunchAgent mode)
_ICLOUD_NATIVE = Path(
    os.getenv(
        "ICLOUD_WATCH_PATH",
        "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects",
    )
)
_DROPBOX_NATIVE = Path(
    os.getenv(
        "DROPBOX_PATH",
        "/Users/bob/Library/CloudStorage/Dropbox-Personal",
    )
)

# Docker mount paths
_ICLOUD_DOCKER = Path(os.getenv("ICLOUD_MOUNT_PATH", "/data/icloud/Projects"))
_DROPBOX_DOCKER = Path(os.getenv("DROPBOX_MOUNT_PATH", "/data/dropbox"))

WATCH_PATH: Path = _ICLOUD_DOCKER if IS_DOCKER else _ICLOUD_NATIVE
DEST_DROPBOX: Path = _DROPBOX_DOCKER if IS_DOCKER else _DROPBOX_NATIVE

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
NOTIFICATION_HUB_URL = os.getenv("NOTIFICATION_HUB_URL", "http://notification-hub:8095")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw:3000")
CORTEX_URL = os.getenv("CORTEX_URL", "http://openclaw:3000")
MATT_PHONE = os.getenv("MATT_PHONE_NUMBER", os.getenv("OWNER_PHONE_NUMBER", ""))

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")

PROJECTS_CONFIG = Path(__file__).parent / "projects.json"
DB_PATH = Path(os.getenv("DB_PATH", "/tmp/file-watcher.db"))
PORT = int(os.getenv("PORT", "8103"))

# ── Database (idempotency) ────────────────────────────────────────────────────

def init_db() -> None:
    """Create the SQLite idempotency table if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            filename      TEXT NOT NULL,
            project_key   TEXT,
            doc_type      TEXT,
            dropbox_path  TEXT,
            share_url     TEXT DEFAULT '',
            processed_at  TEXT NOT NULL,
            UNIQUE(filename)
        )
    """)
    conn.commit()
    conn.close()


def is_processed(filename: str) -> bool:
    """Return True if this filename has already been processed."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id FROM processed_files WHERE filename = ?", (filename,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_processed(
    filename: str,
    project_key: str,
    doc_type: str,
    dropbox_path: str,
    share_url: str = "",
) -> None:
    """Record a successfully processed file."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO processed_files
           (filename, project_key, doc_type, dropbox_path, share_url, processed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (filename, project_key, doc_type, dropbox_path, share_url, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def update_share_url(filename: str, share_url: str) -> None:
    """Update the share_url for an already-processed file."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE processed_files SET share_url = ? WHERE filename = ?",
        (share_url, filename),
    )
    conn.commit()
    conn.close()


# ── Project config ────────────────────────────────────────────────────────────

def load_projects() -> dict:
    """Load projects.json. Returns empty dict if missing."""
    if PROJECTS_CONFIG.exists():
        with open(PROJECTS_CONFIG) as f:
            data = json.load(f)
        # Strip internal _comment key
        return {k: v for k, v in data.items() if not k.startswith("_")}
    logger.warning("projects.json not found at %s", PROJECTS_CONFIG)
    return {}


def match_project(filename: str, projects: dict) -> Optional[tuple]:
    """
    Fuzzy-match a filename against project keywords.
    Returns (project_key, project_config) or None.
    """
    lower = filename.lower()
    for key, cfg in projects.items():
        for kw in cfg.get("keywords", []):
            if kw.lower() in lower:
                return key, cfg
    return None


def detect_doc_type(filename: str) -> str:
    """Infer document type from filename. Defaults to 'Proposal'."""
    lower = filename.lower()
    if any(x in lower for x in ["agreement", "contract", "sign", "esign"]):
        return "Agreement"
    if any(x in lower for x in ["invoice", "inv-"]):
        return "Invoice"
    if any(x in lower for x in ["change order", "change-order", " co-"]):
        return "Change Order"
    if any(x in lower for x in ["scope", "sow", "scope-of-work"]):
        return "Scope of Work"
    # Default covers "proposal", "quote", "Q-NNN", etc.
    return "Proposal"


def client_facing_name(address: str, doc_type: str) -> str:
    """Build the canonical client-facing filename."""
    return f"Symphony Smart Homes - {address} - {doc_type}.pdf"


# ── iCloud stub handling ──────────────────────────────────────────────────────

def ensure_downloaded(path: Path) -> bool:
    """
    Force-download an iCloud placeholder stub (.icloud file).
    No-op and returns True in Docker (brctl is not available).
    Returns True when the real file is ready, False on timeout/error.
    """
    if IS_DOCKER:
        # brctl is a macOS binary — not available in Docker.
        # If the file is a stub, log and return False.
        if str(path).endswith(".icloud"):
            logger.warning(
                "iCloud stub detected in Docker (cannot force-download): %s", path.name
            )
            return False
        return path.exists()

    # Resolve .icloud stub → real filename
    src = path
    if str(path).endswith(".icloud"):
        real_name = re.sub(r"^\.(.+)\.icloud$", r"\1", path.name)
        src = path.parent / real_name
        logger.info("iCloud stub → triggering download: %s", real_name)
        try:
            subprocess.run(
                ["brctl", "download", str(path)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as e:
            logger.error("brctl download failed: %s", e.stderr)
            return False
        except Exception as e:
            logger.error("brctl error: %s", e)
            return False
        # Wait up to 30 s for the real file to materialise
        for _ in range(30):
            if src.exists() and src.stat().st_size > 0:
                return True
            time.sleep(1)
        logger.warning("Timeout waiting for iCloud download: %s", real_name)
        return False

    # Not a stub — but file might still be evicted
    if not src.exists():
        logger.info("Attempting brctl download for evicted file: %s", src.name)
        try:
            subprocess.run(
                ["brctl", "download", str(src)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            time.sleep(2)
        except Exception:
            pass
    return src.exists() and src.stat().st_size > 0


# ── Dropbox API ───────────────────────────────────────────────────────────────

_dbx: Optional[dropbox.Dropbox] = None


def get_dropbox() -> Optional[dropbox.Dropbox]:
    """Return a (cached) Dropbox client, or None if creds are missing."""
    global _dbx
    if not all([DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN]):
        logger.warning("Dropbox credentials not configured — share link generation disabled")
        return None
    if _dbx is None:
        _dbx = dropbox.Dropbox(
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
        )
    return _dbx


def get_dropbox_api_path(local_path: Path) -> str:
    """Convert a local Dropbox path to the Dropbox API path (e.g. /Topletz/Client/...)."""
    try:
        rel = local_path.relative_to(DEST_DROPBOX)
        return "/" + str(rel).replace("\\", "/")
    except ValueError:
        return "/" + local_path.name


def generate_share_link(dropbox_api_path: str) -> str:
    """
    Generate a public Dropbox share link for the given API path.
    Returns URL string, or '' on error.
    Gracefully handles rate limits and already-existing links.
    """
    dbx = get_dropbox()
    if not dbx:
        return ""
    try:
        settings = dropbox.sharing.SharedLinkSettings(
            requested_visibility=dropbox.sharing.RequestedVisibility.public
        )
        result = dbx.sharing_create_shared_link_with_settings(dropbox_api_path, settings)
        url = result.url.replace("?dl=0", "?dl=1")
        logger.info("Dropbox share link created: %s", url)
        return url
    except dropbox.exceptions.ApiError as e:
        err = str(e)
        if "shared_link_already_exists" in err:
            # Retrieve existing link
            try:
                links = dbx.sharing_list_shared_links(path=dropbox_api_path, direct_only=True)
                if links.links:
                    url = links.links[0].url.replace("?dl=0", "?dl=1")
                    logger.info("Dropbox share link (existing): %s", url)
                    return url
            except Exception as e2:
                logger.error("Could not retrieve existing share link: %s", e2)
        elif "too_many_requests" in err or "rate_limit" in err.lower():
            logger.warning("Dropbox rate limit hit — retrying in 60s")
            time.sleep(60)
            return generate_share_link(dropbox_api_path)
        else:
            logger.error("Dropbox API error: %s", e)
    return ""


# ── Redis ─────────────────────────────────────────────────────────────────────

def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)


def publish_event(channel: str, data: dict) -> None:
    """Publish a JSON event to a Redis channel. Swallows errors gracefully."""
    try:
        r = get_redis()
        r.publish(channel, json.dumps(data))
        logger.info("Redis → %s: project=%s", channel, data.get("project", "?"))
    except Exception as e:
        logger.error("Redis publish failed (%s): %s", channel, e)


# ── Notification Hub ──────────────────────────────────────────────────────────

def send_approval_imessage(
    project_name: str,
    doc_type: str,
    share_url: str,
    client_name: str,
    client_email: str,
) -> None:
    """Ask Matt for approval before the document is emailed to the client."""
    share_text = share_url if share_url else "(share link pending)"
    msg = (
        f"📄 {doc_type} ready — {project_name}\n"
        f"Client: {client_name}"
        + (f" <{client_email}>" if client_email else "")
        + f"\nDropbox: {share_text}\n\n"
        "Reply with a Bob command to send, e.g.:\n"
        f"  draft to {client_name.split()[0].lower()}, client {project_name.lower()}"
    )
    payload = {
        "message": msg,
        "subject": f"📄 {doc_type} ready — {project_name}",
        "channel": "imessage",
        "priority": "high",
        "recipient": MATT_PHONE,
    }
    try:
        resp = requests.post(
            f"{NOTIFICATION_HUB_URL}/api/send",
            json=payload,
            timeout=10,
        )
        logger.info("iMessage approval sent (HTTP %s)", resp.status_code)
    except Exception as e:
        logger.error("Notification hub error: %s", e)


def queue_email_draft(
    project_name: str,
    doc_type: str,
    share_url: str,
    client_name: str,
    client_email: str,
) -> None:
    """Queue a Zoho email draft via notification-hub Hermes channel."""
    if not client_email:
        logger.info("No client email configured for %s — skipping draft", project_name)
        return

    first_name = client_name.split()[0]
    body = (
        f"Hi {first_name},\n\n"
        f"Please find your updated {doc_type} for your Symphony Smart Homes project "
        f"at the link below.\n\n"
        f"{share_url}\n\n"
        "Let me know if you have any questions.\n\n"
        "Matt Earley\n"
        "Symphony Smart Homes\n"
        "Vail Valley, CO"
    )
    payload = {
        "message": body,
        "subject": f"Symphony Smart Homes — {doc_type} for {project_name}",
        "channel": "email",
        "recipient": client_email,
        "priority": "normal",
        "thread_id": f"file-watcher:{project_name}",
    }
    try:
        resp = requests.post(
            f"{NOTIFICATION_HUB_URL}/api/send",
            json=payload,
            timeout=10,
        )
        logger.info("Email draft queued for %s (HTTP %s)", client_email, resp.status_code)
    except Exception as e:
        logger.error("Email draft error: %s", e)


# ── Cortex observations ───────────────────────────────────────────────────────

def log_observation(summary: str, metadata: dict) -> None:
    """Log a file operation observation to OpenClaw/Cortex. Best-effort."""
    try:
        requests.post(
            f"{CORTEX_URL}/api/observations",
            json={"summary": summary, "source": "file-watcher", "metadata": metadata},
            timeout=5,
        )
    except Exception:
        pass  # Non-critical — never block file processing on this


# ── Follow-up tracker ─────────────────────────────────────────────────────────

def create_follow_up(
    project_name: str,
    client_name: str,
    client_email: str,
    doc_type: str,
    share_url: str,
) -> None:
    """Create a signature follow-up in OpenClaw when an Agreement is sent."""
    if doc_type != "Agreement":
        return
    payload = {
        "contact": client_name,
        "email": client_email,
        "type": "signature",
        "notes": f"Agreement sent to {client_name}. Dropbox: {share_url}",
        "project": project_name,
        "due_days": 7,
    }
    try:
        resp = requests.post(
            f"{OPENCLAW_URL}/api/follow-ups",
            json=payload,
            timeout=5,
        )
        logger.info("Follow-up created for %s Agreement (HTTP %s)", client_name, resp.status_code)
    except Exception as e:
        logger.warning("Follow-up creation failed: %s", e)


# ── Core file processing ──────────────────────────────────────────────────────

def process_new_pdf(src_path: Path) -> None:
    """
    Full pipeline for a newly detected PDF:
      1. Validate (skip stubs, temp files, already-processed)
      2. Force-download iCloud stub if needed
      3. Match project from filename
      4. Archive existing version in Dropbox/[Project]/Archive/
      5. Copy to Dropbox/[Project]/Client/ with client-facing name
      6. Mark as processed (idempotency)
      7. Publish files:new Redis event
    """
    filename = src_path.name

    # ── Guards ──────────────────────────────────────────────────────────────
    if not filename.lower().endswith(".pdf"):
        return
    if filename.startswith(".") or filename.startswith("~") or filename.startswith("._"):
        return
    if is_processed(filename):
        logger.debug("Already processed — skipping: %s", filename)
        return

    logger.info("New PDF detected: %s", filename)

    # ── iCloud stub resolution ───────────────────────────────────────────────
    if not ensure_downloaded(src_path):
        logger.warning("File not available (stub or missing): %s", filename)
        return

    # Brief pause to let any concurrent write finish
    time.sleep(1)

    if not src_path.exists() or src_path.stat().st_size == 0:
        logger.warning("File empty or disappeared: %s", filename)
        return

    # ── Project matching ─────────────────────────────────────────────────────
    projects = load_projects()
    match = match_project(filename, projects)
    if match:
        project_key, project_cfg = match
    else:
        logger.warning("No project match for '%s' — filing under 'unknown'", filename)
        project_key = "unknown"
        # Auto-create a minimal unknown-project record
        safe_stem = re.sub(r"[^a-zA-Z0-9 \-]", "", src_path.stem)[:40].strip()
        project_cfg = {
            "address": safe_stem or "Unknown Project",
            "client": "Unknown Client",
            "client_email": "",
            "dropbox_folder": "Unknown",
            "keywords": [],
        }

    doc_type = detect_doc_type(filename)
    address = project_cfg.get("address", project_key.title())
    client_name = project_cfg.get("client", "Client")
    client_email = project_cfg.get("client_email", "")
    dropbox_folder = project_cfg.get("dropbox_folder", project_key.title())

    # ── Destination paths ────────────────────────────────────────────────────
    client_dir = DEST_DROPBOX / dropbox_folder / "Client"
    archive_dir = DEST_DROPBOX / dropbox_folder / "Archive"
    client_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    new_filename = client_facing_name(address, doc_type)
    dest_path = client_dir / new_filename

    # ── Archive existing version ─────────────────────────────────────────────
    if dest_path.exists():
        date_stamp = datetime.now().strftime("%Y%m%d")
        archive_name = f"Symphony Smart Homes - {address} - {doc_type}-{date_stamp}.pdf"
        archive_path = archive_dir / archive_name
        try:
            shutil.copy2(dest_path, archive_path)
            logger.info("Archived previous version → %s", archive_path.name)
        except Exception as e:
            logger.error("Archive failed: %s", e)

    # ── Copy to Dropbox/Client/ ──────────────────────────────────────────────
    try:
        shutil.copy2(src_path, dest_path)
        logger.info("Copied to Dropbox: %s/%s", dropbox_folder, new_filename)
    except Exception as e:
        logger.error("Copy to Dropbox failed: %s", e)
        return

    # ── Idempotency record ───────────────────────────────────────────────────
    mark_processed(filename, project_key, doc_type, str(dest_path))

    # ── Publish Redis event ──────────────────────────────────────────────────
    event_data = {
        "project": project_key,
        "project_name": dropbox_folder,
        "address": address,
        "client": client_name,
        "client_email": client_email,
        "doc_type": doc_type,
        "dropbox_path": str(dest_path),
        "dropbox_api_path": get_dropbox_api_path(dest_path),
        "source_file": filename,
        "timestamp": datetime.now().isoformat(),
    }
    publish_event("files:new", event_data)

    # ── Cortex observation ───────────────────────────────────────────────────
    log_observation(
        f"New {doc_type} for {client_name} copied to Dropbox",
        event_data,
    )

    logger.info(
        "✅ %s → %s/%s (%s)", filename, dropbox_folder, new_filename, doc_type
    )


def handle_files_new_event(event_data: dict) -> None:
    """
    Handle a files:new Redis event:
      1. Generate Dropbox share link
      2. Send Matt an iMessage for approval
      3. Queue Zoho email draft via notification-hub
      4. Create follow-up if Agreement
      5. Publish files:processed
    """
    project_name = event_data.get("project_name", event_data.get("project", ""))
    doc_type = event_data.get("doc_type", "Proposal")
    dropbox_api_path = event_data.get("dropbox_api_path", "")
    client_name = event_data.get("client", "Client")
    client_email = event_data.get("client_email", "")
    source_file = event_data.get("source_file", "")

    logger.info("Handling files:new for %s (%s)", project_name, doc_type)

    # ── Generate Dropbox share link ──────────────────────────────────────────
    share_url = ""
    if dropbox_api_path:
        share_url = generate_share_link(dropbox_api_path)
        if share_url and source_file:
            update_share_url(source_file, share_url)

    # ── iMessage approval ────────────────────────────────────────────────────
    send_approval_imessage(project_name, doc_type, share_url, client_name, client_email)

    # ── Queue email draft ────────────────────────────────────────────────────
    if share_url:
        queue_email_draft(project_name, doc_type, share_url, client_name, client_email)

    # ── Agreement follow-up ──────────────────────────────────────────────────
    create_follow_up(project_name, client_name, client_email, doc_type, share_url)

    # ── Cortex observation ───────────────────────────────────────────────────
    log_observation(
        f"{doc_type} share link generated for {client_name}",
        {**event_data, "share_url": share_url},
    )

    # ── Publish files:processed ──────────────────────────────────────────────
    publish_event(
        "files:processed",
        {
            **event_data,
            "share_url": share_url,
            "notified_at": datetime.now().isoformat(),
        },
    )

    logger.info("✅ files:new fully handled — share: %s", share_url or "N/A")


def move_misplaced_pdf(src_path: Path) -> None:
    """
    Handle a PDF that landed in the Dropbox root.
    Match it to a project, archive any existing version, move to Client/.
    """
    filename = src_path.name
    if not filename.lower().endswith(".pdf") or filename.startswith("."):
        return

    projects = load_projects()
    match = match_project(filename, projects)
    if not match:
        logger.debug("Dropbox root PDF doesn't match any project — leaving: %s", filename)
        return

    project_key, project_cfg = match
    doc_type = detect_doc_type(filename)
    address = project_cfg.get("address", project_key.title())
    client_name = project_cfg.get("client", "Client")
    client_email = project_cfg.get("client_email", "")
    dropbox_folder = project_cfg.get("dropbox_folder", project_key.title())

    client_dir = DEST_DROPBOX / dropbox_folder / "Client"
    archive_dir = DEST_DROPBOX / dropbox_folder / "Archive"
    client_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    new_filename = client_facing_name(address, doc_type)
    dest_path = client_dir / new_filename

    # Archive existing version
    if dest_path.exists():
        date_stamp = datetime.now().strftime("%Y%m%d")
        archive_name = f"Symphony Smart Homes - {address} - {doc_type}-{date_stamp}.pdf"
        shutil.copy2(dest_path, archive_dir / archive_name)
        logger.info("Archived existing version: %s", archive_name)

    # Brief pause — let Dropbox finish uploading the root file
    time.sleep(2)

    try:
        shutil.move(str(src_path), str(dest_path))
        logger.info(
            "Rescued misplaced PDF: %s → %s/%s", filename, dropbox_folder, new_filename
        )
    except Exception as e:
        logger.error("Failed to move misplaced PDF: %s", e)
        return

    event_data = {
        "project": project_key,
        "project_name": dropbox_folder,
        "address": address,
        "client": client_name,
        "client_email": client_email,
        "doc_type": doc_type,
        "dropbox_path": str(dest_path),
        "dropbox_api_path": get_dropbox_api_path(dest_path),
        "source_file": filename,
        "source": "dropbox_root_rescue",
        "timestamp": datetime.now().isoformat(),
    }
    publish_event("files:new", event_data)
    log_observation(
        f"Rescued misplaced {doc_type} for {client_name} from Dropbox root",
        event_data,
    )


# ── Watchdog event handlers ───────────────────────────────────────────────────

class ICloudHandler(FileSystemEventHandler):
    """Watches the iCloud Projects/ folder for new or updated PDFs."""

    def _is_pdf_or_stub(self, path: str) -> bool:
        p = Path(path).name
        return p.lower().endswith(".pdf") or p.endswith(".icloud")

    def on_created(self, event):
        if event.is_directory:
            return
        if self._is_pdf_or_stub(event.src_path):
            path = Path(event.src_path)
            # Resolve .icloud stub → actual filename for idempotency check
            if path.name.endswith(".icloud"):
                real_name = re.sub(r"^\.(.+)\.icloud$", r"\1", path.name)
                path = path.parent / real_name
            threading.Thread(
                target=process_new_pdf, args=(path,), daemon=True
            ).start()

    def on_modified(self, event):
        if event.is_directory:
            return
        if self._is_pdf_or_stub(event.src_path):
            path = Path(event.src_path)
            if path.name.endswith(".icloud"):
                return  # Stub modification — real file event will follow
            if not is_processed(path.name):
                threading.Thread(
                    target=process_new_pdf, args=(path,), daemon=True
                ).start()


class DropboxRootHandler(FileSystemEventHandler):
    """Watches the Dropbox root for accidental PDF drops."""

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        # Only handle files directly in the root, not sub-folders
        if path.suffix.lower() == ".pdf" and path.parent.resolve() == DEST_DROPBOX.resolve():
            logger.info("Dropbox root: unexpected PDF — %s", path.name)
            threading.Thread(
                target=move_misplaced_pdf, args=(path,), daemon=True
            ).start()


# ── Redis subscriber (background thread) ─────────────────────────────────────

def redis_subscriber_thread() -> None:
    """
    Subscribe to files:new and call handle_files_new_event().
    Runs forever in a daemon thread; reconnects on error.
    """
    while True:
        try:
            r = get_redis()
            pubsub = r.pubsub()
            pubsub.subscribe("files:new")
            logger.info("Redis subscriber: listening on files:new")

            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    # Skip events that already have a share_url (already handled)
                    # and events from the dropbox_root_rescue path that also skip
                    # duplicate handling
                    if "share_url" in data:
                        continue
                    threading.Thread(
                        target=handle_files_new_event, args=(data,), daemon=True
                    ).start()
                except Exception as e:
                    logger.error("files:new handler error: %s", e)

        except Exception as e:
            logger.warning("Redis subscriber disconnected: %s — reconnecting in 10s", e)
            time.sleep(10)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("═══ File Watcher ready ═══  watch=%s  dropbox=%s", WATCH_PATH, DEST_DROPBOX)
    yield


app = FastAPI(title="Symphony File Watcher", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "file-watcher",
        "watch_path": str(WATCH_PATH),
        "dropbox_path": str(DEST_DROPBOX),
        "is_docker": IS_DOCKER,
        "dropbox_configured": bool(DROPBOX_APP_KEY),
    }


@app.post("/process")
def process_manual(body: dict):
    """Manually trigger processing of a specific file (useful for testing)."""
    path = Path(body.get("path", ""))
    if not path.exists():
        return {"error": f"File not found: {path}"}
    threading.Thread(target=process_new_pdf, args=(path,), daemon=True).start()
    return {"status": "queued", "file": str(path)}


@app.get("/projects")
def list_projects():
    """Return the loaded project config."""
    return load_projects()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("═══ Symphony File Watcher starting ═══")
    logger.info("  Mode:         %s", "Docker" if IS_DOCKER else "Native (LaunchAgent)")
    logger.info("  Watch path:   %s", WATCH_PATH)
    logger.info("  Dropbox path: %s", DEST_DROPBOX)
    logger.info("  Redis URL:    %s", REDIS_URL.replace(REDIS_URL.split("@")[0].split("//")[1], "***") if "@" in REDIS_URL else REDIS_URL)
    logger.info("  Dropbox API:  %s", "configured ✅" if DROPBOX_APP_KEY else "NOT configured ⚠️")

    init_db()

    # Ensure watch directory exists
    if not WATCH_PATH.exists():
        logger.warning("Watch path missing — creating: %s", WATCH_PATH)
        WATCH_PATH.mkdir(parents=True, exist_ok=True)

    # Start filesystem observers
    observer = Observer()
    observer.schedule(ICloudHandler(), str(WATCH_PATH), recursive=False)
    if DEST_DROPBOX.exists():
        observer.schedule(DropboxRootHandler(), str(DEST_DROPBOX), recursive=False)
    else:
        logger.warning("Dropbox path not found — root rescue watcher not started: %s", DEST_DROPBOX)
    observer.start()
    logger.info("Filesystem observers started")

    # Start Redis subscriber thread
    sub_thread = threading.Thread(target=redis_subscriber_thread, daemon=True)
    sub_thread.start()
    logger.info("Redis subscriber thread started")

    # Process any PDFs already sitting in the watch folder on startup
    if WATCH_PATH.exists():
        startup_files = list(WATCH_PATH.glob("*.pdf"))
        for f in startup_files:
            if not is_processed(f.name):
                logger.info("Startup scan: unprocessed file found — queuing: %s", f.name)
                threading.Thread(target=process_new_pdf, args=(f,), daemon=True).start()
        if startup_files:
            logger.info("Startup scan complete (%d files checked)", len(startup_files))

    # Run FastAPI health server (blocks)
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        observer.stop()
        observer.join()
        logger.info("File Watcher stopped")


if __name__ == "__main__":
    main()
