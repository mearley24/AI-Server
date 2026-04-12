#!/usr/bin/env python3
"""Export Apple Notes directly from NoteStore.sqlite — no JXA, no Notes.app needed.

Reads the local SQLite database, decompresses gzip+protobuf note bodies,
and writes data/notes_index.json in the format notes_to_cortex.py expects.

Usage (run on the Mac where Notes live — your M2):
  python3 export_notes.py

Output: data/notes_index.json  (same format the ingest pipeline reads)
"""

import gzip
import json
import os
import re
import sqlite3
import struct
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

DB_CANDIDATES = [
    Path.home() / "Library" / "Group Containers" / "group.com.apple.notes" / "NoteStore.sqlite",
]

OUTPUT_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "notes_index.json"


def find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.is_file():
            return p
    print("ERROR: NoteStore.sqlite not found. Expected at:")
    for p in DB_CANDIDATES:
        print(f"  {p}")
    sys.exit(1)


def apple_ts_to_iso(ts) -> str:
    """Convert Apple Core Data timestamp (seconds since 2001-01-01) to ISO string."""
    if ts is None:
        return ""
    try:
        dt = APPLE_EPOCH + timedelta(seconds=float(ts))
        return dt.isoformat()
    except Exception:
        return ""


def extract_text_from_blob(blob: bytes) -> str:
    """Extract readable text from a Notes ZDATA blob (gzip + protobuf)."""
    if not blob:
        return ""

    # Try gzip decompression first
    raw = blob
    try:
        raw = gzip.decompress(blob)
    except Exception:
        pass

    # Strategy 1: extract UTF-8 text runs from protobuf
    text = _extract_proto_text(raw)
    if text and len(text) > 20:
        return text

    # Strategy 2: brute-force printable ASCII/UTF-8 extraction
    text = _extract_printable(raw)
    return text


def _extract_proto_text(data: bytes) -> str:
    """Extract text from protobuf wire format (field type 2 = length-delimited)."""
    results = []
    i = 0
    while i < len(data) - 2:
        try:
            # Read varint (field tag)
            tag_byte = data[i]
            wire_type = tag_byte & 0x07
            i += 1

            if wire_type == 2:  # length-delimited
                # Read varint length
                length = 0
                shift = 0
                while i < len(data):
                    b = data[i]
                    i += 1
                    length |= (b & 0x7F) << shift
                    if not (b & 0x80):
                        break
                    shift += 7

                if 0 < length < 100000 and i + length <= len(data):
                    chunk = data[i:i + length]
                    i += length
                    try:
                        text = chunk.decode("utf-8", errors="strict")
                        # Only keep chunks that are mostly printable
                        printable_ratio = sum(1 for c in text if c.isprintable() or c in "\n\t\r") / max(len(text), 1)
                        if printable_ratio > 0.8 and len(text.strip()) > 1:
                            results.append(text)
                    except UnicodeDecodeError:
                        pass
                else:
                    # Skip bad length
                    if length > 0 and i + length <= len(data):
                        i += length
            elif wire_type == 0:  # varint
                while i < len(data) and data[i] & 0x80:
                    i += 1
                i += 1
            elif wire_type == 1:  # 64-bit
                i += 8
            elif wire_type == 5:  # 32-bit
                i += 4
            else:
                i += 1
        except (IndexError, struct.error):
            i += 1

    return "\n".join(results)


def _extract_printable(data: bytes) -> str:
    """Fallback: extract runs of printable text from raw bytes."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = data.decode("latin-1", errors="replace")

    # Keep only printable runs of 3+ characters
    runs = re.findall(r"[\x20-\x7E\n\t]{3,}", text)
    combined = " ".join(runs)

    # Quality gate: if less than 50% of original length, it is mostly binary
    if len(combined) < len(data) * 0.1:
        return ""
    return combined.strip()


def read_notes_from_sqlite(db_path: Path) -> list:
    """Read all notes from NoteStore.sqlite with full body text."""
    # Copy DB to avoid locking issues (Apple Notes may have it open)
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "NoteStore.sqlite"
    shutil.copy2(db_path, tmp)
    # Also copy WAL and SHM if they exist
    for ext in ("-wal", "-shm"):
        src = db_path.parent / (db_path.name + ext)
        if src.is_file():
            shutil.copy2(src, tmp.parent / (tmp.name + ext))

    conn = sqlite3.connect(str(tmp))
    conn.row_factory = sqlite3.Row

    # Discover schema — column names vary across macOS versions
    obj_cols = [r[1] for r in conn.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)").fetchall()]
    data_cols = [r[1] for r in conn.execute("PRAGMA table_info(ZICNOTEDATA)").fetchall()]

    print(f"ZICCLOUDSYNCINGOBJECT columns: {len(obj_cols)}")
    print(f"ZICNOTEDATA columns: {len(data_cols)}")

    # Pick the right title column
    title_col = "ZTITLE1" if "ZTITLE1" in obj_cols else "ZTITLE"

    # Pick the right folder title column
    folder_title_col = "ZTITLE2" if "ZTITLE2" in obj_cols else "ZTITLE"

    # Pick the right note link column
    note_fk = "ZNOTE" if "ZNOTE" in data_cols else "Z_PK"

    # Pick the right created/modified columns
    created_col = "ZCREATIONDATE3" if "ZCREATIONDATE3" in obj_cols else (
        "ZCREATIONDATE2" if "ZCREATIONDATE2" in obj_cols else (
            "ZCREATIONDATE1" if "ZCREATIONDATE1" in obj_cols else "ZCREATIONDATE"
        )
    )
    modified_col = "ZMODIFICATIONDATE1" if "ZMODIFICATIONDATE1" in obj_cols else "ZMODIFICATIONDATE"

    # Check for deletion / password columns
    has_deleted = "ZMARKEDFORDELETION" in obj_cols
    has_trash = "ZISINTRASHEDFOLDER" in obj_cols  
    has_password = "ZISPASSWORDPROTECTED" in obj_cols

    # Build WHERE clause to skip deleted / password-protected notes
    conditions = [f"note.{title_col} IS NOT NULL"]
    if has_deleted:
        conditions.append("note.ZMARKEDFORDELETION != 1")
    if has_password:
        conditions.append("note.ZISPASSWORDPROTECTED != 1")
    where = " AND ".join(conditions)

    # Check for folder FK column
    folder_fk = "ZFOLDER" if "ZFOLDER" in obj_cols else None

    query = f"""
    SELECT
        note.Z_PK as note_pk,
        note.{title_col} as title,
        nd.ZDATA as body_blob,
        note.{created_col} as created,
        note.{modified_col} as modified,
        {'folder.' + folder_title_col if folder_fk else "''"} as folder_name
    FROM ZICCLOUDSYNCINGOBJECT note
    LEFT JOIN ZICNOTEDATA nd ON nd.{note_fk} = note.Z_PK
    {'LEFT JOIN ZICCLOUDSYNCINGOBJECT folder ON note.' + folder_fk + ' = folder.Z_PK' if folder_fk else ''}
    WHERE {where}
    ORDER BY note.{modified_col} DESC
    """

    print(f"Running query...")
    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        print(f"Query failed: {e}")
        print("Trying simpler query...")
        # Fallback: simplest possible query
        rows = conn.execute(f"""
            SELECT
                nd.Z_PK as note_pk,
                '' as title,
                nd.ZDATA as body_blob,
                NULL as created,
                NULL as modified,
                '' as folder_name
            FROM ZICNOTEDATA nd
            WHERE nd.ZDATA IS NOT NULL
        """).fetchall()

    conn.close()

    notes = []
    empty_count = 0
    for row in rows:
        body_blob = row["body_blob"]
        body = extract_text_from_blob(body_blob) if body_blob else ""

        title = row["title"] or ""
        if not title and body:
            # Use first line as title
            title = body.split("\n")[0][:80].strip()

        if not body and not title:
            empty_count += 1
            continue

        # Count attachments for this note (approximate)
        att_count = 0

        notes.append({
            "note_id": f"sqlite_{row['note_pk']}",
            "title": title,
            "body": body[:3000],
            "created_at": apple_ts_to_iso(row["created"]),
            "modified_at": apple_ts_to_iso(row["modified"]),
            "folder": row["folder_name"] or "",
            "attachment_count": att_count,
            "has_attachments": False,
            "value_score": 50,
            "action": "keep",
            "category": "unknown",
            "summary": body[:200].replace("\n", " ") if body else title,
        })

    print(f"Extracted {len(notes)} notes ({empty_count} empty/deleted skipped)")

    # Clean up temp files
    try:
        import shutil as sh2
        sh2.rmtree(tmp.parent, ignore_errors=True)
    except Exception:
        pass

    return notes


def main():
    db_path = find_db()
    print(f"Reading: {db_path}")
    print(f"DB size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")

    notes = read_notes_from_sqlite(db_path)

    if not notes:
        print("WARNING: No notes extracted. Check Full Disk Access for Terminal:")
        print("  System Settings > Privacy & Security > Full Disk Access > Terminal")
        return 1

    # Categorize by folder
    by_folder = defaultdict(int)
    for n in notes:
        by_folder[n.get("folder", "") or "(no folder)"] += 1

    print(f"\nFolders:")
    for folder, count in sorted(by_folder.items(), key=lambda x: -x[1]):
        print(f"  {folder}: {count} notes")

    # Build output in the same format notes_indexer.py produces
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "export_notes.py (SQLite direct read)",
        "summary": {
            "total_notes": len(notes),
            "by_category": {},
            "by_action": {"keep": len(notes)},
            "notes_with_photos": 0,
            "notes_with_codes": 0,
        },
        "notes": notes,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE} ({len(notes)} notes, {OUTPUT_FILE.stat().st_size / 1024:.0f} KB)")
    print(f"\nNext: push to repo and run notes_to_cortex.py on Bob")
    return 0


if __name__ == "__main__":
    sys.exit(main())
