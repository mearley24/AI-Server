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
import os
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

# Ignore patterns
IGNORE_EXTENSIONS = {".tmp", ".ds_store", ".icloud", ".partial"}
IGNORE_PREFIXES = {".", "~", "#"}


class ProjectFileHandler(FileSystemEventHandler):
    """Handles file system events in the SymphonySH directory."""

    def __init__(self):
        self._redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        self._last_events: dict[str, float] = {}  # debounce

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
            print(f"Redis publish error: {e}")

    def on_created(self, event):
        if event.is_directory or self._should_ignore(event.src_path):
            return
        if self._debounce(event.src_path):
            return
        print(f"[NEW] {os.path.relpath(event.src_path, WATCH_DIR)}")
        self._publish("created", event.src_path)

    def on_modified(self, event):
        if event.is_directory or self._should_ignore(event.src_path):
            return
        if self._debounce(event.src_path):
            return
        print(f"[MOD] {os.path.relpath(event.src_path, WATCH_DIR)}")
        self._publish("modified", event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        if self._should_ignore(event.dest_path):
            return
        print(f"[MOV] {os.path.relpath(event.src_path, WATCH_DIR)} -> {os.path.relpath(event.dest_path, WATCH_DIR)}")
        self._publish("moved", event.dest_path)


def main():
    if not os.path.isdir(WATCH_DIR):
        print(f"Watch directory not found: {WATCH_DIR}")
        print("Set ICLOUD_WATCH_DIR environment variable to the correct path.")
        return

    print(f"Watching: {WATCH_DIR}")
    print(f"Redis: {REDIS_URL}")
    print("Press Ctrl+C to stop.\n")

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
