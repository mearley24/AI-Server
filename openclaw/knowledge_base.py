"""
Knowledge Base — iCloud Folder Scanner for Symphony Smart Homes.

Scans the /SymphonySH iCloud folder on Bob's Mac for PDFs, docs, and text files.
Catalogs filenames, paths, and metadata in SQLite. Does NOT parse file contents
(too expensive) — just indexes what's there for search and retrieval.

The scanner tries multiple possible iCloud paths and gracefully degrades
if the folder doesn't exist (Bob might not have it synced yet).
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("openclaw.knowledge_base")

# File types to index
INDEXABLE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".rtf", ".md",
    ".xls", ".xlsx", ".csv", ".ppt", ".pptx",
    ".pages", ".numbers", ".keynote",
}

# Candidate paths for iCloud SymphonySH folder (host-mounted into Docker)
CANDIDATE_PATHS = [
    "/data/symphony_docs",  # Docker volume mount (primary)
    "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/SymphonySH",
    "/Users/bob/SymphonySH",
    "/Users/bob/Documents/SymphonySH",
]

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeBase:
    """Indexes and searches the Symphony Smart Homes document folder."""

    def __init__(self, db_path: str = "/app/data/knowledge_base.db"):
        self._db_path = db_path
        self._local = threading.local()
        self._docs_path: Optional[Path] = None
        self._init_db()
        self._resolve_docs_path()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                file_type TEXT,
                size_bytes INTEGER,
                modified_at TEXT,
                indexed_at TEXT,
                summary TEXT DEFAULT '',
                tags TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_filename ON documents(filename)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_type ON documents(file_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents(tags)")
        conn.commit()
        conn.close()
        logger.info("Knowledge base DB initialized at %s", self._db_path)

    def _resolve_docs_path(self):
        """Find the SymphonySH docs folder from candidate paths."""
        # Check env var first
        env_path = os.getenv("SYMPHONY_DOCS_PATH", "")
        if env_path:
            CANDIDATE_PATHS.insert(0, env_path)

        for candidate in CANDIDATE_PATHS:
            p = Path(candidate)
            if p.exists() and p.is_dir():
                self._docs_path = p
                logger.info("Knowledge base docs folder: %s", p)
                return

        logger.warning(
            "SymphonySH docs folder not found. Tried: %s. "
            "Knowledge base will be empty until folder is available.",
            ", ".join(CANDIDATE_PATHS),
        )

    def scan(self) -> dict:
        """Scan the docs folder and update the index. Returns scan stats."""
        if not self._docs_path or not self._docs_path.exists():
            logger.info("Docs folder not available, skipping scan")
            return {"status": "skipped", "reason": "docs_folder_not_found"}

        now = datetime.utcnow().isoformat()
        added = 0
        updated = 0
        total = 0

        for file_path in self._docs_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                continue

            total += 1
            rel_path = str(file_path)
            stat = file_path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Check if already indexed
            existing = self._conn.execute(
                "SELECT id, modified_at FROM documents WHERE path = ?", (rel_path,)
            ).fetchone()

            if existing:
                if existing["modified_at"] != modified_at:
                    self._conn.execute(
                        "UPDATE documents SET size_bytes=?, modified_at=?, indexed_at=? WHERE id=?",
                        (stat.st_size, modified_at, now, existing["id"]),
                    )
                    updated += 1
            else:
                # Auto-tag based on subdirectory
                tags = self._auto_tag(file_path)
                self._conn.execute(
                    "INSERT INTO documents (filename, path, file_type, size_bytes, modified_at, indexed_at, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (file_path.name, rel_path, file_path.suffix.lower(),
                     stat.st_size, modified_at, now, tags),
                )
                added += 1

        self._conn.commit()
        result = {"status": "ok", "total_files": total, "added": added, "updated": updated}
        logger.info("Knowledge scan complete: %s", result)
        return result

    def _auto_tag(self, file_path: Path) -> str:
        """Generate tags based on file path and name."""
        tags = []
        path_lower = str(file_path).lower()

        if "proposal" in path_lower:
            tags.append("proposal")
        if "manual" in path_lower:
            tags.append("manual")
        if "contract" in path_lower:
            tags.append("contract")
        if "invoice" in path_lower:
            tags.append("invoice")
        if "template" in path_lower:
            tags.append("template")

        # Tag by product brand
        for brand in ["control4", "lutron", "crestron", "sonos", "pakedge", "triad"]:
            if brand in path_lower:
                tags.append(brand)

        return ",".join(tags)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Fuzzy search by filename and tags."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE filename LIKE ? OR tags LIKE ? OR summary LIKE ? "
            "ORDER BY modified_at DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_proposals(self, limit: int = 50) -> list[dict]:
        """Return all PDF files from proposals/ subdirectories."""
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE (path LIKE '%proposal%' OR tags LIKE '%proposal%') "
            "AND file_type = '.pdf' ORDER BY modified_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_manuals(self, limit: int = 50) -> list[dict]:
        """Return all files from manuals/ subdirectories."""
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE path LIKE '%manual%' OR tags LIKE '%manual%' "
            "ORDER BY modified_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_documents(self, limit: int = 100) -> list[dict]:
        """Return all indexed documents."""
        rows = self._conn.execute(
            "SELECT * FROM documents ORDER BY modified_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ---------------------------------------------------------------------------
# Module-level state (initialized from main.py)
# ---------------------------------------------------------------------------
_kb: Optional[KnowledgeBase] = None


def init(kb: KnowledgeBase):
    global _kb
    _kb = kb


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@router.get("/documents")
async def list_documents(limit: int = Query(default=100, ge=1, le=500)):
    if not _kb:
        return JSONResponse(status_code=503, content={"error": "Knowledge base not initialized"})
    return {"documents": _kb.get_all_documents(limit)}


@router.get("/search")
async def search_documents(q: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=100)):
    if not _kb:
        return JSONResponse(status_code=503, content={"error": "Knowledge base not initialized"})
    return {"results": _kb.search(q, limit)}


@router.get("/proposals")
async def list_proposals(limit: int = Query(default=50, ge=1, le=200)):
    if not _kb:
        return JSONResponse(status_code=503, content={"error": "Knowledge base not initialized"})
    return {"proposals": _kb.get_proposals(limit)}


@router.get("/manuals")
async def list_manuals(limit: int = Query(default=50, ge=1, le=200)):
    if not _kb:
        return JSONResponse(status_code=503, content={"error": "Knowledge base not initialized"})
    return {"manuals": _kb.get_manuals(limit)}
