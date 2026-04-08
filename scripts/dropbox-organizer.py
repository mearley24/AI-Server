#!/usr/bin/env python3
"""
dropbox-organizer.py — Watches Dropbox root for new project files and routes them.

Rules:
  1. Detect project name from filename by matching against existing project folders.
  2. Move PDF to [Project]/Client/ with standardized name.
  3. Archive any existing file at that destination with a datestamp suffix.
  4. Clean up known junk/duplicate files in root.

Run via launchd — see com.symphonysh.dropbox-organizer.plist
"""

import os
import re
import shutil
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dropbox-organizer] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DROPBOX_ROOT = Path(
    os.environ.get(
        "DROPBOX_ROOT",
        os.path.expanduser("~/Library/CloudStorage/Dropbox-Personal"),
    )
)
if not DROPBOX_ROOT.exists():
    DROPBOX_ROOT = Path(os.path.expanduser("~/Dropbox"))

POLL_INTERVAL = 15  # seconds

# Files to silently delete from root (duplicates, temp exports)
JUNK_PATTERNS = [
    r".*\(\d+\)\.pdf$",             # e.g. "file (1).pdf", "file (2).pdf"
    r".*— Updated Proposal\.pdf$",  # old "Updated Proposal" naming
]

# Canonical client-facing name templates per document type
DOC_TYPE_NAMES = {
    "proposal":    "Symphony Smart Homes - {project} - Proposal.pdf",
    "agreement":   "Symphony Smart Homes - {project} - Agreement.pdf",
    "deliverables":"Symphony Smart Homes - {project} - Deliverables.pdf",
    "sow":         "Symphony Smart Homes - {project} - SOW.pdf",
    "invoice":     "Symphony Smart Homes - {project} - Invoice.pdf",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_project_folders() -> list[str]:
    """Return list of project folder names in Dropbox root."""
    return [
        d.name for d in DROPBOX_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]


def detect_project(filename: str, project_folders: list[str]) -> str | None:
    """Try to match a filename to a project folder name."""
    name_lower = filename.lower()
    for folder in project_folders:
        # Match any word from the folder name that's 4+ chars (avoids noise)
        words = [w for w in re.split(r"[\s\-_]+", folder) if len(w) >= 4]
        if any(w.lower() in name_lower for w in words):
            return folder
    return None


def detect_doc_type(filename: str) -> str:
    """Detect document type from filename keywords."""
    name_lower = filename.lower()
    if any(w in name_lower for w in ["proposal", "quote", "q-", " q"]):
        return "proposal"
    if any(w in name_lower for w in ["agreement", "contract", "sow"]):
        return "agreement"
    if any(w in name_lower for w in ["deliverable"]):
        return "deliverables"
    if any(w in name_lower for w in ["invoice", "billing"]):
        return "invoice"
    return "proposal"  # default


def archive_existing(dest: Path) -> None:
    """Move an existing file to Archive/ with a datestamp."""
    if not dest.exists():
        return
    archive_dir = dest.parent.parent / "Archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    stem = dest.stem
    suffix = dest.suffix
    archived = archive_dir / f"{stem}-{stamp}{suffix}"
    # Avoid overwriting if multiple archives on same day
    counter = 1
    while archived.exists():
        archived = archive_dir / f"{stem}-{stamp}-{counter}{suffix}"
        counter += 1
    shutil.move(str(dest), str(archived))
    log.info("Archived: %s → %s", dest.name, archived.name)


def ensure_client_dir(project: str) -> Path:
    client_dir = DROPBOX_ROOT / project / "Client"
    client_dir.mkdir(parents=True, exist_ok=True)
    return client_dir


def is_junk(filename: str) -> bool:
    return any(re.match(p, filename, re.IGNORECASE) for p in JUNK_PATTERNS)


def route_file(src: Path, project_folders: list[str]) -> bool:
    """
    Attempt to route a file to the correct project folder.
    Returns True if handled, False if not matched.
    """
    filename = src.name

    # Delete junk files silently
    if is_junk(filename):
        src.unlink(missing_ok=True)
        log.info("Deleted junk: %s", filename)
        return True

    # Only route PDFs
    if src.suffix.lower() != ".pdf":
        return False

    project = detect_project(filename, project_folders)
    if not project:
        log.warning("No project match for: %s — leaving in place", filename)
        return False

    doc_type = detect_doc_type(filename)

    # Derive project display name for canonical filename
    # e.g. "Topletz" → "84 Aspen Meadow" — use folder name if no mapping
    project_display = project  # can be overridden via PROJECT_DISPLAY_NAMES env

    canonical_name = DOC_TYPE_NAMES.get(doc_type, "{project} - Document.pdf").format(
        project=project_display
    )

    client_dir = ensure_client_dir(project)
    dest = client_dir / canonical_name

    archive_existing(dest)
    shutil.move(str(src), str(dest))
    log.info("Routed: %s → %s/Client/%s", filename, project, canonical_name)

    # Notify Bob via Redis so he can auto-draft the client email
    notify_redis("file_routed", {
        "project": project,
        "doc_type": doc_type,
        "filename": canonical_name,
        "path": str(dest),
    })
    return True


# ── Main loop ─────────────────────────────────────────────────────────────────

def watch_root() -> None:
    log.info("Watching Dropbox root: %s (poll every %ds)", DROPBOX_ROOT, POLL_INTERVAL)

    # Track files we've already seen to avoid re-processing
    seen: set[str] = set()

    # Seed seen with files already in root on startup (don't route pre-existing)
    for f in DROPBOX_ROOT.iterdir():
        if f.is_file():
            seen.add(f.name)

    while True:
        try:
            project_folders = get_project_folders()
            current = {f.name for f in DROPBOX_ROOT.iterdir() if f.is_file()}
            new_files = current - seen

            for filename in new_files:
                src = DROPBOX_ROOT / filename
                if not src.exists():
                    continue
                # Small delay — let Dropbox finish writing the file
                time.sleep(2)
                routed = route_file(src, project_folders)
                if routed:
                    seen.discard(filename)
                else:
                    seen.add(filename)

            # Refresh seen with whatever remains
            seen = {f.name for f in DROPBOX_ROOT.iterdir() if f.is_file()}

        except Exception as exc:
            log.error("Watcher error: %s", exc)

        time.sleep(POLL_INTERVAL)


def cleanup_root() -> None:
    """Remove known junk/duplicate files from Dropbox root on startup."""
    patterns_to_delete = [
        r".*\(\d+\)\.pdf$",                          # file (1).pdf, (2).pdf
        r".*\u2014.*Updated Proposal\.pdf$",          # — Updated Proposal
        r".*-Q-\d+-V[1-9]\.pdf$",                    # old D-Tools versioned exports
        r"^topletz-.*-v\d+\.pdf$",                    # old lowercase versioned files
        r".*C4NoSecurity.*\.pdf$",                    # old scope exports
        r".*C4RA3.*\.pdf$",                           # old D-Tools raw exports
    ]
    for f in DROPBOX_ROOT.iterdir():
        if not f.is_file():
            continue
        for pat in patterns_to_delete:
            if re.match(pat, f.name, re.IGNORECASE):
                try:
                    f.unlink()
                    log.info("Startup cleanup deleted: %s", f.name)
                except Exception as e:
                    log.warning("Could not delete %s: %s", f.name, e)
                break


def notify_redis(event: str, payload: dict) -> None:
    """Publish a Redis event so Bob can react (e.g. auto-draft client email)."""
    try:
        import json
        import redis
        r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"),
            decode_responses=True, socket_timeout=2
        )
        r.publish("events:dropbox", json.dumps({"event": event, **payload}))
    except Exception as exc:
        log.debug("Redis notify skipped: %s", exc)


if __name__ == "__main__":
    cleanup_root()
    watch_root()
