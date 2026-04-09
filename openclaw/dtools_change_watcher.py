"""
D-Tools Change Watcher — detects new proposal versions exported from D-Tools
and triggers the document regeneration pipeline.

On each orchestrator tick this module:
  1. Scans the D-Tools proposals directory for PDF files whose filename
     contains a version stamp (V1, V2, V3, …).
  2. Also listens on the Redis channel ``events:dropbox`` for
     ``file_routed`` events with ``doc_type == "proposal"``.
  3. When a new (higher) version is detected for a job:
       a. Extracts financial data from the PDF using pdfplumber.
       b. Persists the new version number in jobs.db ``scan_state`` table.
       c. Publishes an ``events:dtools_change`` event to Redis with a rich
          payload so the dropbox-organizer and doc-generator can react.

State is stored in the ``scan_state`` table of jobs.db using the key
``dtools_version_{job_id}`` (or ``dtools_version_path_{path_hash}`` when no
job can be matched).

Environment variables
---------------------
DTOOLS_PROPOSALS_DIR   Directory to scan   (default /data/proposals)
JOBS_DB_PATH           jobs.db path        (default /data/jobs.db)
REDIS_URL              Redis URL           (default redis://localhost:6379)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.dtools_change_watcher")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_PROPOSALS_DIR = os.environ.get("DTOOLS_PROPOSALS_DIR", "/data/proposals")
DEFAULT_JOBS_DB = os.environ.get("JOBS_DB_PATH", "/data/jobs.db")
REDIS_CHANNEL_IN = "events:dropbox"
REDIS_CHANNEL_OUT = "events:dtools_change"

# Regex that captures the version number from filenames like:
#   Proposal_ClientName_V3.pdf
#   SymphonyProposal-TopletzV4_2024.pdf
#   some_proposal_v12_final.pdf
_VERSION_RE = re.compile(r"[Vv](\d+)", re.IGNORECASE)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_conn(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and row_factory."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_scan_state(conn: sqlite3.Connection) -> None:
    """Create the scan_state table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """Retrieve a value from scan_state by key. Returns None if absent."""
    row = conn.execute(
        "SELECT value FROM scan_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert a key/value pair in scan_state."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO scan_state (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
    conn.commit()


# ── Pdfplumber helper ──────────────────────────────────────────────────────────

def _extract_financials(pdf_path: str) -> dict:
    """
    Extract financial summary from a D-Tools proposal PDF.

    Uses pdfplumber to read the first few pages and attempt to locate:
    - Total price / project total
    - Line-item subtotals
    - Any currency-formatted values

    Returns a dict with at minimum ``raw_text_snippet`` and ``amounts``.
    Gracefully returns an empty dict if pdfplumber is unavailable or the
    file cannot be parsed.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        logger.debug("pdfplumber not installed — skipping financial extraction")
        return {}

    financials: dict = {"amounts": [], "raw_text_snippet": ""}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_scan = pdf.pages[:5]  # Limit to first 5 pages for speed
            full_text = ""
            for page in pages_to_scan:
                text = page.extract_text() or ""
                full_text += text + "\n"

            # Grab a snippet for reference
            financials["raw_text_snippet"] = full_text[:1000]

            # Extract all dollar amounts: $1,234.56 or $1234 patterns
            amounts_raw = re.findall(
                r"\$\s?[\d,]+(?:\.\d{2})?", full_text
            )
            # Parse to floats
            parsed_amounts = []
            for amt in amounts_raw:
                try:
                    cleaned = re.sub(r"[^\d.]", "", amt)
                    if cleaned:
                        parsed_amounts.append(float(cleaned))
                except ValueError:
                    pass
            financials["amounts"] = parsed_amounts

            # Try to identify a project total (look for "Total" label + amount)
            total_match = re.search(
                r"(?:project\s+)?total[:\s]+\$?\s*([\d,]+(?:\.\d{2})?)",
                full_text,
                re.IGNORECASE,
            )
            if total_match:
                try:
                    financials["project_total"] = float(
                        total_match.group(1).replace(",", "")
                    )
                except ValueError:
                    pass

    except Exception as exc:
        logger.warning("_extract_financials failed for %s: %s", pdf_path, exc)

    return financials


# ── Main class ─────────────────────────────────────────────────────────────────

class DToolsChangeWatcher:
    """
    Watches for new D-Tools proposal versions and publishes change events.

    Parameters
    ----------
    proposals_dir:
        Filesystem path to the directory containing exported proposal PDFs.
    redis_client:
        An async Redis client (``redis.asyncio``).
    jobs_db:
        Path to the jobs.db SQLite database.
    """

    def __init__(
        self,
        proposals_dir: str = DEFAULT_PROPOSALS_DIR,
        redis_client=None,
        jobs_db: str = DEFAULT_JOBS_DB,
    ) -> None:
        self._proposals_dir = proposals_dir
        self._redis = redis_client
        self._jobs_db = jobs_db

        # Ensure state table exists
        try:
            conn = _get_conn(self._jobs_db)
            _ensure_scan_state(conn)
            conn.close()
        except Exception as exc:
            logger.warning("scan_state init error: %s", exc)

        logger.info(
            "dtools_change_watcher_init dir=%s jobs_db=%s",
            proposals_dir,
            jobs_db,
        )

    # ── Public interface ───────────────────────────────────────────────────────

    async def tick(self) -> int:
        """
        Run one watcher cycle.

        Scans the proposals directory *and* drains any pending Dropbox
        ``file_routed`` events from Redis.

        Returns
        -------
        int
            Number of change events detected and published.
        """
        changes = 0

        # 1. Scan filesystem
        try:
            proposals = await self._scan_proposals_dir()
            for proposal in proposals:
                if await self._process_proposal(proposal):
                    changes += 1
        except Exception as exc:
            logger.warning("dtools_watcher filesystem scan error: %s", exc)

        # 2. Drain Redis dropbox events
        try:
            redis_changes = await self._drain_dropbox_events()
            changes += redis_changes
        except Exception as exc:
            logger.warning("dtools_watcher redis drain error: %s", exc)

        if changes:
            logger.info("dtools_change_watcher.tick: %d changes detected", changes)
        return changes

    async def _scan_proposals_dir(self) -> list[dict]:
        """
        Scan the proposals directory for PDF files.

        Returns
        -------
        list[dict]
            Each entry has keys: ``path``, ``version``, ``project_name``,
            ``filename``, ``mtime``.
        """
        proposals_path = Path(self._proposals_dir)
        if not proposals_path.exists():
            logger.debug("proposals dir does not exist: %s", self._proposals_dir)
            return []

        results = []
        for pdf_file in proposals_path.rglob("*.pdf"):
            try:
                filename = pdf_file.name
                version = await self._extract_version(filename)
                project_name = self._extract_project_name(filename)
                mtime = pdf_file.stat().st_mtime
                results.append(
                    {
                        "path": str(pdf_file),
                        "filename": filename,
                        "version": version,
                        "project_name": project_name,
                        "mtime": mtime,
                    }
                )
            except Exception as exc:
                logger.debug("skipping %s: %s", pdf_file, exc)

        logger.debug(
            "_scan_proposals_dir: found %d PDFs in %s",
            len(results),
            self._proposals_dir,
        )
        return results

    async def _extract_version(self, filename: str) -> int:
        """
        Extract the version number from a proposal filename.

        Looks for patterns like V3, v4, V12 anywhere in the filename.
        Returns 0 if no version marker is found.

        Examples
        --------
        >>> await watcher._extract_version("Proposal_Topletz_V3.pdf")
        3
        >>> await watcher._extract_version("proposal_final.pdf")
        0
        """
        match = _VERSION_RE.search(filename)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return 0

    async def _publish_change_event(self, payload: dict) -> None:
        """
        Publish a change event to the ``events:dtools_change`` Redis channel.

        Parameters
        ----------
        payload:
            Arbitrary dict; will be JSON-serialised.
        """
        if not self._redis:
            logger.debug("_publish_change_event: no redis client, skipping")
            return

        message = json.dumps(payload, default=str)
        try:
            await self._redis.publish(REDIS_CHANNEL_OUT, message)
            logger.info(
                "dtools_change_published path=%s version=%s",
                payload.get("path", ""),
                payload.get("version", ""),
            )
        except Exception as exc:
            logger.warning("_publish_change_event error: %s", exc)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _process_proposal(self, proposal: dict) -> bool:
        """
        Check if a scanned proposal represents a new version and, if so,
        extract financials, update state, and publish a change event.

        Returns True if a new version was detected and published.
        """
        path = proposal["path"]
        version = proposal["version"]
        project_name = proposal["project_name"]
        mtime = proposal.get("mtime", 0.0)

        # Derive a stable state key
        job_id = self._match_job_id(project_name)
        state_key = (
            f"dtools_version_{job_id}"
            if job_id
            else f"dtools_version_path_{_path_hash(path)}"
        )

        # Also track mtime for version-0 files (no version in filename)
        mtime_key = f"{state_key}__mtime"

        try:
            conn = _get_conn(self._jobs_db)
            stored_version_str = _get_state(conn, state_key)
            stored_version = int(stored_version_str) if stored_version_str else 0
            stored_mtime_str = _get_state(conn, mtime_key)
            stored_mtime = float(stored_mtime_str) if stored_mtime_str else 0.0
            conn.close()
        except Exception as exc:
            logger.warning("_process_proposal state read error: %s", exc)
            return False

        # Determine if this represents a change
        is_new_version = version > 0 and version > stored_version
        is_mtime_change = version == 0 and mtime > stored_mtime + 1.0  # 1s tolerance

        if not (is_new_version or is_mtime_change):
            return False

        logger.info(
            "dtools_new_version detected path=%s version=%d->%d",
            path,
            stored_version,
            version,
        )

        # Extract financials from PDF
        financials = _extract_financials(path)

        # Build event payload
        event_payload: dict = {
            "event_type": "dtools_change",
            "path": path,
            "filename": proposal["filename"],
            "version": version,
            "previous_version": stored_version,
            "project_name": project_name,
            "job_id": job_id,
            "financials": financials,
            "mtime": mtime,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist updated state
        try:
            conn = _get_conn(self._jobs_db)
            _set_state(conn, state_key, str(version))
            _set_state(conn, mtime_key, str(mtime))
            conn.close()
        except Exception as exc:
            logger.warning("_process_proposal state write error: %s", exc)

        # Publish to Redis
        await self._publish_change_event(event_payload)
        return True

    async def _drain_dropbox_events(self) -> int:
        """
        Read pending messages from the ``events:dropbox`` Redis list/channel.

        Expects messages to be JSON objects with at least:
        - ``event_type`` == ``"file_routed"``
        - ``doc_type``   == ``"proposal"``
        - ``path``       : filesystem path to the routed PDF

        Returns the number of new change events published.
        """
        if not self._redis:
            return 0

        changes = 0
        try:
            # Attempt to read up to 50 queued messages from a list key
            # (dropbox-organizer may use LPUSH / RPUSH)
            for _ in range(50):
                raw = await self._redis.rpop(REDIS_CHANNEL_IN)
                if raw is None:
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if (
                    msg.get("event_type") != "file_routed"
                    or msg.get("doc_type") != "proposal"
                ):
                    continue

                path = msg.get("path", "")
                if not path or not Path(path).exists():
                    logger.debug("dropbox file_routed: path not found: %s", path)
                    continue

                filename = Path(path).name
                version = await self._extract_version(filename)
                project_name = self._extract_project_name(filename)
                mtime = Path(path).stat().st_mtime

                proposal = {
                    "path": path,
                    "filename": filename,
                    "version": version,
                    "project_name": project_name,
                    "mtime": mtime,
                }
                if await self._process_proposal(proposal):
                    changes += 1

        except Exception as exc:
            logger.warning("_drain_dropbox_events error: %s", exc)

        return changes

    @staticmethod
    def _extract_project_name(filename: str) -> str:
        """
        Derive a human-readable project name from a proposal filename.

        Strips the extension, removes version stamps, normalises separators,
        and strips common prefixes like "Proposal_" or "Symphony".

        Examples
        --------
        "Proposal_Topletz_V3.pdf"          → "Topletz"
        "SymphonySmartHomes_Johnson_V2.pdf" → "Johnson"
        "proposal_final.pdf"               → "proposal final"
        """
        stem = Path(filename).stem  # strip .pdf
        # Remove version stamps
        stem = _VERSION_RE.sub("", stem)
        # Replace separators with spaces
        stem = re.sub(r"[_\-]+", " ", stem).strip()
        # Strip common boring prefixes (case-insensitive)
        stem = re.sub(
            r"^(Proposal|Symphony\s*Smart\s*Homes?|Symphony|SmartHomes?)\s*",
            "",
            stem,
            flags=re.IGNORECASE,
        ).strip()
        return stem or Path(filename).stem

    def _match_job_id(self, project_name: str) -> Optional[int]:
        """
        Try to match the project_name to a job in jobs.db.

        Returns the job_id if a reasonable match is found, else None.
        Matching is done by comparing tokens (≥4 chars) from the project name
        against job client_name and project_name fields.
        """
        if not project_name:
            return None

        try:
            conn = _get_conn(self._jobs_db)
            rows = conn.execute(
                """
                SELECT job_id, client_name, project_name FROM jobs
                WHERE phase NOT IN ('COMPLETED', 'WARRANTY')
                ORDER BY updated_at DESC
                """
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.debug("_match_job_id db error: %s", exc)
            return None

        search_lower = project_name.lower()
        tokens = [t for t in re.split(r"\W+", search_lower) if len(t) >= 4]

        best_id: Optional[int] = None
        best_score = 0

        for row in rows:
            combined = (
                (row["client_name"] or "") + " " + (row["project_name"] or "")
            ).lower()
            score = sum(1 for t in tokens if t in combined)
            if score > best_score:
                best_score = score
                best_id = row["job_id"]

        return best_id if best_score > 0 else None


# ── Utility ────────────────────────────────────────────────────────────────────

def _path_hash(path: str) -> str:
    """Return a short stable hash of a file path for use as a state key."""
    return hashlib.sha1(path.encode()).hexdigest()[:12]
