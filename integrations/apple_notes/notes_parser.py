"""Read Apple Notes via JXA/osascript (macOS host only)."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# JXA: export all notes as JSON (plaintext, folder, ids).
_JXA_EXPORT_ALL = r"""
function run() {
  try {
    var Notes = Application('Notes');
    var out = [];
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      var folderName = '';
      try {
        folderName = String(n.container().name() || '');
      } catch (e0) {}
      var created = '';
      var modified = '';
      try {
        var cd = n.creationDate();
        created = cd ? String(cd) : '';
      } catch (e1) {}
      try {
        var md = n.modificationDate();
        modified = md ? String(md) : '';
      } catch (e2) {}
      var attCount = 0;
      try {
        var atts = n.attachments();
        attCount = atts ? atts.length : 0;
      } catch (e3) {}
      out.push({
        note_id: String(n.id()),
        title: String(n.name() || ''),
        body: String(n.plaintext() || ''),
        created_at: created,
        modified_at: modified,
        folder: folderName,
        attachment_count: attCount
      });
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ "error": String(e) });
  }
}
"""

_JXA_FOLDERS = r"""
function run() {
  try {
    var Notes = Application('Notes');
    var out = [];
    var folders = Notes.folders();
    for (var i = 0; i < folders.length; i++) {
      var f = folders[i];
      var cnt = 0;
      try {
        var ns = f.notes();
        cnt = ns ? ns.length : 0;
      } catch (e) {}
      out.push({ name: String(f.name() || ''), note_count: cnt });
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ "error": String(e) });
  }
}
"""

_JXA_NOTE_BY_ID = r"""
function run(argv) {
  if (!argv || argv.length < 1) return 'null';
  var want = argv[0];
  try {
    var Notes = Application('Notes');
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      if (String(n.id()) !== String(want)) continue;
      var folderName = '';
      try { folderName = String(n.container().name() || ''); } catch (e0) {}
      var created = '', modified = '';
      try { var cd = n.creationDate(); created = cd ? String(cd) : ''; } catch (e1) {}
      try { var md = n.modificationDate(); modified = md ? String(md) : ''; } catch (e2) {}
      var attCount = 0;
      try { var atts = n.attachments(); attCount = atts ? atts.length : 0; } catch (e3) {}
      return JSON.stringify({
        note_id: String(n.id()),
        title: String(n.name() || ''),
        body: String(n.plaintext() || ''),
        created_at: created,
        modified_at: modified,
        folder: folderName,
        attachment_count: attCount
      });
    }
  } catch (e) { return 'null'; }
  return 'null';
}
"""

_JXA_ATTACHMENTS = r"""
function run(argv) {
  if (!argv || argv.length < 1) return '[]';
  var want = argv[0];
  try {
    var Notes = Application('Notes');
    var notes = Notes.notes();
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      if (String(n.id()) !== String(want)) continue;
      var out = [];
      try {
        var atts = n.attachments();
        for (var j = 0; j < atts.length; j++) {
          var a = atts[j];
          out.push({ name: String(a.name()||''), filename: String(a.filename()||'') });
        }
      } catch (e) {}
      return JSON.stringify(out);
    }
  } catch (e) {}
  return '[]';
}
"""


def run_jxa(source: str, timeout: float = 120.0) -> str:
    """Run a JavaScript-for-Automation snippet; return stdout."""
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", source],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"JXA failed (rc={result.returncode}): {result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def run_jxa_with_arg(source: str, arg: str, timeout: float = 90.0) -> str:
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", source, "--", arg],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"JXA failed (rc={result.returncode}): {result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def run_applescript(script: str, timeout: float = 60.0) -> str:
    """Execute AppleScript and return stdout (fallback / attachments)."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr}")
    return result.stdout.strip()


@dataclass
class NoteRecord:
    note_id: str
    title: str
    body: str
    created_at: str
    modified_at: str
    folder: str
    has_attachments: bool
    attachment_count: int = 0


@dataclass
class FolderInfo:
    name: str
    note_count: int


@dataclass
class AttachmentRecord:
    name: str
    filename: str


def _parse_note_dict(d: dict[str, Any]) -> NoteRecord:
    ac = int(d.get("attachment_count") or 0)
    return NoteRecord(
        note_id=str(d.get("note_id") or ""),
        title=str(d.get("title") or ""),
        body=str(d.get("body") or ""),
        created_at=str(d.get("created_at") or ""),
        modified_at=str(d.get("modified_at") or ""),
        folder=str(d.get("folder") or ""),
        has_attachments=ac > 0,
        attachment_count=ac,
    )


# ── Batched per-folder JXA (fixes the 2-min AppleEvent timeout) ───────────────

# Batch size: 50 notes per JXA call — well under the 2-min AppleEvent timeout.
_BATCH_SIZE = 50

_JXA_FOLDER_NAMES_ONLY = r"""
function run() {
  try {
    var app = Application('Notes');
    var folders = app.folders();
    var out = [];
    for (var i = 0; i < folders.length; i++) {
      try { out.push(String(folders[i].name())); } catch(e) {}
    }
    return JSON.stringify(out);
  } catch(e) { return JSON.stringify({error: String(e)}); }
}
"""

_JXA_FOLDER_NOTE_BATCH = r"""
function run(argv) {
  // argv = [folderName, offset, limit]
  var folderName = argv[0];
  var offset = parseInt(argv[1]) || 0;
  var limit  = parseInt(argv[2]) || 50;
  try {
    var app = Application('Notes');
    var folder = null;
    var folders = app.folders();
    for (var i = 0; i < folders.length; i++) {
      try {
        if (String(folders[i].name()) === folderName) { folder = folders[i]; break; }
      } catch(e) {}
    }
    if (!folder) return JSON.stringify({error: 'folder_not_found', name: folderName});
    var notes = folder.notes();
    var total = notes.length;
    var end   = Math.min(offset + limit, total);
    var out   = [];
    for (var j = offset; j < end; j++) {
      try {
        var n   = notes[j];
        var ac  = 0;
        try { ac = n.attachments().length; } catch(e) {}
        out.push({
          note_id:          String(n.id()),
          title:            String(n.name()           || ''),
          body:             String(n.plaintext()       || ''),
          created_at:       String(n.creationDate()   || ''),
          modified_at:      String(n.modificationDate() || ''),
          folder:           folderName,
          attachment_count: ac
        });
      } catch(e) {}
    }
    return JSON.stringify({notes: out, total: total, offset: offset, folder: folderName});
  } catch(e) {
    return JSON.stringify({error: String(e), folder: folderName});
  }
}
"""

_JXA_FOLDER_NOTE_COUNT = r"""
function run(argv) {
  var folderName = argv[0];
  try {
    var app = Application('Notes');
    var folders = app.folders();
    for (var i = 0; i < folders.length; i++) {
      try {
        if (String(folders[i].name()) === folderName) {
          return JSON.stringify({count: folders[i].notes().length, folder: folderName});
        }
      } catch(e) {}
    }
    return JSON.stringify({error: 'folder_not_found', folder: folderName});
  } catch(e) {
    return JSON.stringify({error: String(e), folder: folderName});
  }
}
"""


def _run_jxa_args(source: str, *args: str, timeout: float = 90.0) -> str:
    """Run JXA with multiple argv arguments."""
    cmd = ["osascript", "-l", "JavaScript", "-e", source, "--"] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "JXA error")
        return (result.stdout or "").strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"JXA timed out after {timeout}s")


def _get_folder_names(timeout: float = 90.0) -> list[str]:
    """Return a list of Notes folder names. Raises on failure."""
    raw = run_jxa(_JXA_FOLDER_NAMES_ONLY, timeout=timeout)
    data = json.loads(raw)
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(data["error"])
    return [str(n) for n in data if n]


def _get_notes_batch(
    folder_name: str,
    offset: int,
    limit: int = _BATCH_SIZE,
    timeout: float = 90.0,
) -> dict:
    """Fetch one batch of notes from a folder. Returns the parsed JSON dict."""
    raw = _run_jxa_args(
        _JXA_FOLDER_NOTE_BATCH,
        folder_name,
        str(offset),
        str(limit),
        timeout=timeout,
    )
    return json.loads(raw)


# ── SQLite fallback reader ─────────────────────────────────────────────────────

_NOTES_DB = (
    os.path.expanduser("~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite")
)


def _read_local_cache() -> list[NoteRecord]:
    """Read notes that are locally cached in the Notes SQLite database.

    Only notes that have been fully synced to this Mac appear here. With a
    large iCloud library that is still syncing this will be a small subset,
    but it works immediately without JXA.

    The ZICNOTEDATA.ZDATA blob is an Apple-proprietary format; we use a
    heuristic text extractor rather than a full protobuf decoder.
    """
    import sqlite3 as _sqlite3

    if not os.path.exists(_NOTES_DB):
        return []

    notes: list[NoteRecord] = []
    try:
        # Open read-only (immutable=1 avoids locking the live DB)
        uri = f"file:{_NOTES_DB}?immutable=1"
        conn = _sqlite3.connect(uri, uri=True)
        conn.row_factory = _sqlite3.Row

        # Z_ENT = 12 is ICNote in the entity table
        rows = conn.execute(
            """
            SELECT
                n.Z_PK,
                n.ZIDENTIFIER,
                n.ZTITLE,
                n.ZSNIPPET,
                n.ZSUMMARY,
                n.ZCREATIONDATE1,
                n.ZMODIFICATIONDATE1,
                n.ZNOTEDATA,
                f.ZNAME AS ZFOLDERNAME
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON f.Z_PK = n.ZFOLDER
            WHERE n.Z_ENT = 12
              AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION = 0)
            """
        ).fetchall()

        # For each note, try to grab body from ZICNOTEDATA
        note_pks_with_data = {}
        try:
            data_rows = conn.execute("SELECT ZNOTE, ZDATA FROM ZICNOTEDATA").fetchall()
            for dr in data_rows:
                note_pks_with_data[dr["ZNOTE"]] = dr["ZDATA"]
        except Exception:
            pass

        conn.close()

        for row in rows:
            note_id = str(row["ZIDENTIFIER"] or row["Z_PK"] or "")
            title = str(row["ZTITLE"] or "").strip()
            snippet = str(row["ZSNIPPET"] or row["ZSUMMARY"] or "").strip()

            # Use ZSNIPPET/ZSUMMARY as body; try ZDATA only as supplement
            body = snippet
            blob = note_pks_with_data.get(row["Z_PK"])
            if blob:
                extracted = _extract_text_from_blob(bytes(blob))
                # Only use ZDATA extraction if it looks like real text
                # (ratio of printable ASCII > 85%)
                if extracted:
                    printable = sum(1 for c in extracted if 32 <= ord(c) <= 126 or c in "\n\t")
                    if len(extracted) > 0 and printable / len(extracted) > 0.85:
                        body = extracted or snippet
                    # else: keep snippet — ZDATA extraction was mostly binary garbage

            # Convert Apple CFAbsoluteTime (seconds since 2001-01-01) → ISO string
            created_at = _apple_time_to_iso(row["ZCREATIONDATE1"])
            modified_at = _apple_time_to_iso(row["ZMODIFICATIONDATE1"])
            folder = str(row["ZFOLDERNAME"] or "Notes")

            if len(body) < 5 and not title:
                continue

            notes.append(NoteRecord(
                note_id=note_id,
                title=title or snippet[:60] or "(untitled)",
                body=body,
                created_at=created_at,
                modified_at=modified_at,
                folder=folder,
                has_attachments=False,
                attachment_count=0,
            ))

    except Exception as exc:
        logger.warning("sqlite_cache_reader failed: %s", exc)

    return notes


def _apple_time_to_iso(t) -> str:
    """Convert Apple CFAbsoluteTime (float secs since 2001-01-01) to ISO string."""
    if not t:
        return ""
    try:
        import datetime as _dt
        epoch_offset = 978307200  # seconds between Unix epoch and Apple epoch
        unix_ts = float(t) + epoch_offset
        return _dt.datetime.utcfromtimestamp(unix_ts).isoformat() + "Z"
    except Exception:
        return ""


def _extract_text_from_blob(data: bytes) -> str:
    """Extract readable text from an Apple Notes ZDATA blob.

    Apple Notes stores ZDATA as gzip-compressed protobuf. After decompression
    we scan for UTF-8 text segments of at least 8 printable characters —
    sufficient to recover note body text without a full protobuf decoder.
    """
    import gzip as _gzip

    # Step 1: try gzip decompression (most Notes blobs are gzipped)
    raw = data
    try:
        raw = _gzip.decompress(data)
    except Exception:
        pass  # not gzipped, work with raw bytes

    # Step 2: extract text runs of ≥8 printable ASCII chars
    MIN_RUN = 8
    text_parts: list[str] = []
    current: list[int] = []

    for b in raw:
        if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D):
            current.append(b)
        else:
            if len(current) >= MIN_RUN:
                fragment = bytes(current).decode("ascii", errors="ignore").strip()
                if len(fragment) >= MIN_RUN:
                    text_parts.append(fragment)
            current = []

    if len(current) >= MIN_RUN:
        fragment = bytes(current).decode("ascii", errors="ignore").strip()
        if fragment:
            text_parts.append(fragment)

    # Step 3: deduplicate, join, quality check
    seen: set[str] = set()
    unique: list[str] = []
    for p in text_parts:
        key = p[:40]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    result = "\n".join(unique)[:4000]

    # Quality gate: require ≥85% printable in final output
    if not result:
        return ""
    printable = sum(1 for c in result if 32 <= ord(c) <= 126 or c in "\n\t")
    if printable / len(result) < 0.85:
        return ""
    return result


# ── Public API ─────────────────────────────────────────────────────────────────


def get_all_notes() -> list[NoteRecord]:
    """Fetch all Notes via batched per-folder JXA, falling back to SQLite cache.

    Strategy:
    1. Try to get folder names (fast — no note bodies loaded).
    2. For each folder, fetch notes in BATCH_SIZE=50 batches.
    3. Each batch is a separate 90s osascript call — safe under the 2-min
       AppleEvent limit even for large folders.
    4. If JXA fails entirely (iCloud sync not complete), fall back to reading
       the local SQLite cache for whatever has been downloaded so far.
    """
    if platform.system() != "Darwin":
        logger.warning("notes_parser: not macOS — skipping Notes export")
        return []

    # ── Try JXA batched approach ──────────────────────────────────────────────
    # Use a short initial timeout — if Notes is still syncing from iCloud,
    # the folder list call blocks for 2+ minutes. Fail fast and fall to SQLite.
    try:
        logger.info("notes_parser: fetching folder list (15s timeout)…")
        folder_names = _get_folder_names(timeout=15.0)
        if not folder_names:
            raise RuntimeError("no folders returned")
        logger.info("notes_parser: %d folders found", len(folder_names))

        all_notes: list[NoteRecord] = []
        for fi, folder_name in enumerate(folder_names, 1):
            try:
                offset = 0
                folder_total: int | None = None
                while True:
                    logger.info(
                        "notes_parser: folder %d/%d '%s' — batch offset=%d",
                        fi, len(folder_names), folder_name, offset,
                    )
                    result = _get_notes_batch(folder_name, offset, _BATCH_SIZE)
                    if "error" in result:
                        logger.warning(
                            "notes_parser: folder '%s' batch error: %s",
                            folder_name, result["error"],
                        )
                        break
                    batch = result.get("notes", [])
                    total = int(result.get("total", 0))
                    folder_total = total
                    for d in batch:
                        if isinstance(d, dict):
                            all_notes.append(_parse_note_dict(d))
                    offset += len(batch)
                    if offset >= total or not batch:
                        break
                logger.info(
                    "notes_parser: folder '%s' — %d/%s notes fetched",
                    folder_name, offset, folder_total,
                )
            except Exception as exc:
                logger.warning("notes_parser: folder '%s' failed: %s", folder_name, exc)
                continue  # skip to next folder, don't abort

        if all_notes:
            logger.info("notes_parser: JXA batched — %d notes total", len(all_notes))
            return all_notes

        # JXA returned no notes — try cache
        raise RuntimeError("JXA returned 0 notes")

    except Exception as exc:
        logger.warning(
            "notes_parser: JXA batched approach failed (%s) — "
            "falling back to local SQLite cache",
            exc,
        )

    # ── SQLite fallback ───────────────────────────────────────────────────────
    cache_notes = _read_local_cache()
    if cache_notes:
        logger.info(
            "notes_parser: SQLite cache returned %d locally synced notes "
            "(full library available once iCloud sync completes)",
            len(cache_notes),
        )
    else:
        logger.warning(
            "notes_parser: SQLite cache also empty — "
            "Notes iCloud library not yet synced to this Mac. "
            "Re-run after Notes.app finishes syncing."
        )
    return cache_notes


def get_folders() -> list[FolderInfo]:
    """List Notes folders with note counts."""
    if platform.system() != "Darwin":
        return []
    try:
        raw = run_jxa(_JXA_FOLDERS, timeout=90.0)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        if not isinstance(data, list):
            return []
        return [
            FolderInfo(name=str(x.get("name") or ""), note_count=int(x.get("note_count") or 0))
            for x in data
            if isinstance(x, dict)
        ]
    except Exception as exc:
        logger.error("get_folders failed: %s", exc)
        # Fallback: derive folder list from SQLite cache
        try:
            import sqlite3 as _sqlite3
            uri = f"file:{_NOTES_DB}?immutable=1"
            conn = _sqlite3.connect(uri, uri=True)
            rows = conn.execute(
                "SELECT ZNAME, COUNT(*) as cnt FROM ZICCLOUDSYNCINGOBJECT "
                "WHERE Z_ENT = 15 GROUP BY ZNAME"
            ).fetchall()
            conn.close()
            return [FolderInfo(name=str(r[0] or ""), note_count=int(r[1])) for r in rows if r[0]]
        except Exception:
            return []


def get_note_by_id(note_id: str) -> NoteRecord | None:
    """Fetch a single note by id (JXA)."""
    if platform.system() != "Darwin" or not note_id:
        return None
    try:
        raw = run_jxa_with_arg(_JXA_NOTE_BY_ID, note_id, timeout=90.0)
        if raw == "null" or not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return _parse_note_dict(data)
    except Exception as exc:
        logger.warning("get_note_by_id failed for %s: %s", note_id[:40], exc)
        return None


def get_attachments(note_id: str) -> list[AttachmentRecord]:
    """List attachment metadata for a note (read-only, JXA)."""
    if platform.system() != "Darwin" or not note_id:
        return []
    try:
        raw = run_jxa_with_arg(_JXA_ATTACHMENTS, note_id, timeout=90.0)
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return [
            AttachmentRecord(name=str(x.get("name") or ""), filename=str(x.get("filename") or ""))
            for x in data
            if isinstance(x, dict)
        ]
    except Exception as exc:
        logger.warning("get_attachments failed: %s", exc)
        return []
