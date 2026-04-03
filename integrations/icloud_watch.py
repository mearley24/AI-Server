"""iCloud File Watcher — monitors SymphonySH folder for new/changed files.

When a new file appears or an existing file changes in an active project folder,
publishes an event to Redis so Bob can update deliverables, sync to Dropbox, etc.

Runs as a standalone process on the Mac Mini (not in Docker — needs local filesystem access).

Usage:
    python integrations/icloud_watch.py

Requires:
    pip install watchdog redis
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import redis
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Config
WATCH_DIR = os.environ.get(
    "ICLOUD_WATCH_DIR",
    os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/SymphonySH")
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_CHANNEL = "events:file_change"
NOTIFICATION_CHANNEL = "notifications:trading"
DROPBOX_PROJECTS_DIR = os.environ.get(
    "DROPBOX_PROJECTS_DIR",
    os.path.expanduser("~/Dropbox/Projects"),
)

logger = logging.getLogger(__name__)

# Ignore patterns
IGNORE_EXTENSIONS = {".tmp", ".ds_store", ".icloud", ".partial"}
IGNORE_PREFIXES = {".", "~", "#"}


class ProjectFileHandler(FileSystemEventHandler):
    """Handles file system events in the SymphonySH directory."""

    def __init__(self):
        self._redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        self._last_events: dict[str, float] = {}  # debounce
        self._repo_root = Path(__file__).resolve().parents[1]

    def _should_ignore(self, path: str) -> bool:
        """Ignore temp files, hidden files, etc."""
        name = os.path.basename(path).lower()
        ext = os.path.splitext(name)[1]
        if ext in IGNORE_EXTENSIONS:
            return True
        if any(name.startswith(p) for p in IGNORE_PREFIXES):
            return True
        return False

    def _debounce(self, path: str, seconds: float = 5.0) -> bool:
        """Debounce rapid events for the same file."""
        now = time.time()
        last = self._last_events.get(path, 0)
        if now - last < seconds:
            return True
        self._last_events[path] = now
        return False

    def _extract_project(self, path: str) -> str | None:
        """Extract project name from path."""
        rel = os.path.relpath(path, WATCH_DIR)
        parts = rel.split(os.sep)
        if len(parts) >= 1:
            return parts[0]  # First directory is the project
        return None

    def _publish(self, event_type: str, path: str) -> None:
        """Publish file event to Redis."""
        project = self._extract_project(path)
        filename = os.path.basename(path)
        rel_path = os.path.relpath(path, WATCH_DIR)

        event = {
            "type": event_type,
            "path": rel_path,
            "filename": filename,
            "project": project,
            "timestamp": time.time(),
            "full_path": path,
        }

        try:
            self._redis.publish(REDIS_CHANNEL, json.dumps(event))

            # Also send iMessage notification for important files
            ext = os.path.splitext(filename)[1].lower()
            if ext in {".pdf", ".docx", ".xlsx", ".dwg", ".rvt"}:
                self._redis.publish(NOTIFICATION_CHANNEL, json.dumps({
                    "title": f"[FILE] {project or 'SymphonySH'}",
                    "body": f"New/updated: {filename}\n\nPath: {rel_path}",
                }))
        except Exception as e:
            logger.error("Redis publish error: %s", e)

    def _is_proposal_pdf(self, path: str) -> bool:
        """Detect proposal PDFs by extension/name."""
        p = Path(path)
        if p.suffix.lower() != ".pdf":
            return False
        name = p.name.lower()
        return "proposal" in name

    def _normalize_address(self, raw: str) -> str:
        """Create a readable address/token for naming."""
        cleaned = re.sub(r"\s+", " ", raw).strip(" -_")
        cleaned = re.sub(r"[^\w\s\-&,]", "", cleaned).strip()
        return cleaned or "Unknown Address"

    def _infer_address(self, path: str, project: str | None) -> str:
        """Infer address from project folder or PDF filename."""
        if project:
            base = project.split(" - ")[0].strip()
            return self._normalize_address(base)
        stem = Path(path).stem
        stem = re.sub(r"(?i)\bproposal\b", "", stem).strip(" -_")
        return self._normalize_address(stem)

    def _copy_proposal_to_dropbox(self, src_path: str, project: str | None) -> Path | None:
        """Copy proposal PDF into Dropbox Projects/[project]/Client/ with canonical naming."""
        project_name = (project or "Unsorted Project").strip() or "Unsorted Project"
        address = self._infer_address(src_path, project_name)
        dest_dir = Path(DROPBOX_PROJECTS_DIR) / project_name / "Client"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"Symphony Smart Homes — {address} — Proposal.pdf"
        dest_path = dest_dir / dest_name
        shutil.copy2(src_path, dest_path)
        logger.info("Copied proposal to Dropbox: %s", dest_path)
        return dest_path

    def _run_proposal_checker(self, pdf_path: str, project: str | None) -> None:
        """Run openclaw proposal_checker.py for proposal PDFs."""
        openclaw_paths = [
            self._repo_root / "openclaw",
            Path("/app/openclaw"),
        ]
        for openclaw_path in openclaw_paths:
            resolved = str(openclaw_path.resolve()) if openclaw_path.exists() else str(openclaw_path)
            if os.path.isdir(resolved) and resolved not in sys.path:
                sys.path.insert(0, resolved)

        try:
            from proposal_checker import check_proposal  # type: ignore
        except Exception as exc:
            logger.error("Could not import proposal_checker: %s", exc)
            return

        project_key = (project or "").strip().lower()
        if not project_key:
            project_key = "topletz"
        try:
            results = check_proposal(pdf_path, project=project_key)
            if results.get("error"):
                logger.info("Proposal checker project '%s' not found, falling back to default", project_key)
                results = check_proposal(pdf_path, project="topletz")
            logger.info("Proposal checker summary: %s", results.get("summary", "")[:300])
        except Exception as exc:
            logger.error("Proposal checker failed for %s: %s", pdf_path, exc)

    def _notify_new_proposal(self, filename: str) -> None:
        """Send iMessage notification via Redis trading channel."""
        body = f"[FILE] New proposal detected: {filename}"
        try:
            self._redis.publish(
                NOTIFICATION_CHANNEL,
                json.dumps({"title": "[FILE]", "body": body}),
            )
            logger.info("Published proposal notification: %s", body)
        except Exception as exc:
            logger.error("Failed to publish proposal notification: %s", exc)

    def _handle_new_pdf(self, path: str) -> None:
        """Run proposal workflow for new proposal PDFs."""
        if not self._is_proposal_pdf(path):
            return
        project = self._extract_project(path)
        filename = os.path.basename(path)
        logger.info("New proposal PDF detected: %s (project=%s)", filename, project or "unknown")
        self._run_proposal_checker(path, project)
        try:
            self._copy_proposal_to_dropbox(path, project)
        except Exception as exc:
            logger.error("Failed to copy proposal to Dropbox: %s", exc)
        self._notify_new_proposal(filename)

    def on_created(self, event):
        if event.is_directory or self._should_ignore(event.src_path):
            return
        if self._debounce(event.src_path):
            return
        logger.info("[NEW] %s", os.path.relpath(event.src_path, WATCH_DIR))
        self._publish("created", event.src_path)
        self._handle_new_pdf(event.src_path)

    def on_modified(self, event):
        if event.is_directory or self._should_ignore(event.src_path):
            return
        if self._debounce(event.src_path):
            return
        logger.info("[MOD] %s", os.path.relpath(event.src_path, WATCH_DIR))
        self._publish("modified", event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        if self._should_ignore(event.dest_path):
            return
        logger.info(
            "[MOV] %s -> %s",
            os.path.relpath(event.src_path, WATCH_DIR),
            os.path.relpath(event.dest_path, WATCH_DIR),
        )
        self._publish("moved", event.dest_path)
        self._handle_new_pdf(event.dest_path)


def _count_files(path: str) -> int:
    """Count files in a directory recursively."""
    root = Path(path)
    return sum(1 for p in root.rglob("*") if p.is_file())


def _run_sync_command(command: list[str]) -> None:
    """Run a sync command and log result."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        logger.info(
            "Sync command '%s' exit=%s stdout='%s' stderr='%s'",
            " ".join(command),
            result.returncode,
            (result.stdout or "").strip()[:300],
            (result.stderr or "").strip()[:300],
        )
    except FileNotFoundError:
        logger.warning("Sync command not found: %s", command[0])
    except Exception as exc:
        logger.warning("Sync command failed (%s): %s", " ".join(command), exc)


def _ensure_icloud_synced() -> None:
    """Startup check: if watch dir appears empty, force iCloud sync."""
    file_count = _count_files(WATCH_DIR)
    logger.info("Startup iCloud content check: %s file(s) found", file_count)
    if file_count > 0:
        return

    logger.warning("iCloud watch folder is empty, forcing sync for %s", WATCH_DIR)
    _run_sync_command(["brctl", "download", WATCH_DIR])
    _run_sync_command(["bird", "-c", "com.apple.cloudd"])
    time.sleep(5)
    post_count = _count_files(WATCH_DIR)
    logger.info("Post-sync iCloud content check: %s file(s) found", post_count)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if not os.path.isdir(WATCH_DIR):
        logger.error("Watch directory not found: %s", WATCH_DIR)
        logger.error("Set ICLOUD_WATCH_DIR environment variable to the correct path.")
        return

    _ensure_icloud_synced()
    logger.info("Watching: %s", WATCH_DIR)
    logger.info("Redis: %s", REDIS_URL)
    logger.info("Press Ctrl+C to stop.")

    handler = ProjectFileHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
