# Cline Prompt Y2 — Fix Apple Notes JXA Timeout (Folder-by-Folder Ingest)

## Problem
`integrations/apple_notes/notes_parser.py::get_all_notes()` dumps every Apple Note in one JXA call. With a large iCloud library this times out (180s), returning 0 notes. The entire Notes-to-Cortex pipeline then has nothing to ingest.

## Solution
Replace the monolithic JXA dump with a folder-by-folder approach that:
1. First lists all folders (fast, already works)
2. Then fetches notes per folder in batches
3. Falls back to the macOS Notes SQLite DB if JXA keeps failing

---

## Changes Required

### 1. Rewrite `notes_parser.py` — Add folder-by-folder export

Add a new JXA snippet that exports notes for a single folder:

```javascript
// _JXA_EXPORT_FOLDER — takes folder name as argv[0]
function run(argv) {
  if (!argv || argv.length < 1) return '[]';
  var targetFolder = argv[0];
  try {
    var Notes = Application('Notes');
    var folders = Notes.folders();
    var out = [];
    for (var fi = 0; fi < folders.length; fi++) {
      var f = folders[fi];
      if (String(f.name()) !== targetFolder) continue;
      var notes = f.notes();
      for (var i = 0; i < notes.length; i++) {
        var n = notes[i];
        var created = '';
        var modified = '';
        try { var cd = n.creationDate(); created = cd ? String(cd) : ''; } catch (e1) {}
        try { var md = n.modificationDate(); modified = md ? String(md) : ''; } catch (e2) {}
        var attCount = 0;
        try { var atts = n.attachments(); attCount = atts ? atts.length : 0; } catch (e3) {}
        out.push({
          note_id: String(n.id()),
          title: String(n.name() || ''),
          body: String(n.plaintext() || ''),
          created_at: created,
          modified_at: modified,
          folder: targetFolder,
          attachment_count: attCount
        });
      }
      break;
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({ "error": String(e) });
  }
}
```

Add a new function to notes_parser.py:

```python
def get_notes_by_folder(folder_name: str, timeout: float = 120.0) -> list[NoteRecord]:
    """Fetch all notes in a specific folder via JXA."""
    if platform.system() != "Darwin":
        return []
    try:
        raw = run_jxa_with_arg(_JXA_EXPORT_FOLDER, folder_name, timeout=timeout)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        if not isinstance(data, list):
            return []
        return [_parse_note_dict(x) for x in data if isinstance(x, dict)]
    except Exception as exc:
        logger.error("get_notes_by_folder(%s) failed: %s", folder_name, exc)
        return []
```

### 2. Add SQLite fallback to `notes_parser.py`

Apple Notes stores data at `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`. Add a direct SQLite reader as fallback when JXA fails:

```python
def _get_notes_sqlite_path() -> Path | None:
    """Find the Apple Notes SQLite database."""
    candidates = [
        Path.home() / "Library" / "Group Containers" / "group.com.apple.notes" / "NoteStore.sqlite",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def get_all_notes_sqlite() -> list[NoteRecord]:
    """Read notes directly from Apple Notes SQLite DB (fallback for JXA timeout)."""
    db_path = _get_notes_sqlite_path()
    if db_path is None:
        logger.warning("Notes SQLite DB not found")
        return []

    try:
        import sqlite3
        # Open read-only to avoid any corruption risk
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        query = """
        SELECT
            n.Z_PK as pk,
            n.ZTITLE1 as title,
            nb.ZTEXT as body_html,
            n.ZCREATIONDATE as created,
            n.ZMODIFICATIONDATE as modified,
            COALESCE(f.ZTITLE2, '') as folder,
            (SELECT COUNT(*) FROM ZICNOTEDATA WHERE ZNOTE = n.Z_PK) as att_count
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICCLOUDSYNCINGOBJECT f ON n.ZFOLDER = f.Z_PK
        LEFT JOIN ZICNOTEDATA nb ON nb.ZNOTE = n.Z_PK
        WHERE n.ZTITLE1 IS NOT NULL
          AND n.ZISPASSWORDPROTECTED != 1
          AND n.ZMARKEDFORDELETION != 1
        ORDER BY n.ZMODIFICATIONDATE DESC
        """

        rows = conn.execute(query).fetchall()
        conn.close()

        results = []
        for r in rows:
            # Apple Notes stores dates as seconds since 2001-01-01
            created_at = ""
            modified_at = ""
            try:
                if r["created"]:
                    from datetime import datetime, timezone, timedelta
                    epoch_2001 = datetime(2001, 1, 1, tzinfo=timezone.utc)
                    created_at = (epoch_2001 + timedelta(seconds=r["created"])).isoformat()
                if r["modified"]:
                    epoch_2001 = datetime(2001, 1, 1, tzinfo=timezone.utc)
                    modified_at = (epoch_2001 + timedelta(seconds=r["modified"])).isoformat()
            except Exception:
                pass

            # Strip HTML from body if present
            body = r["body_html"] or ""
            if "<" in body:
                import re
                body = re.sub(r"<[^>]+>", "", body)
                body = body.replace("&nbsp;", " ").replace("&amp;", "&")
                body = body.replace("&lt;", "<").replace("&gt;", ">")

            att_count = r["att_count"] or 0
            results.append(NoteRecord(
                note_id=f"sqlite_{r['pk']}",
                title=r["title"] or "",
                body=body.strip(),
                created_at=created_at,
                modified_at=modified_at,
                folder=r["folder"] or "",
                has_attachments=att_count > 0,
                attachment_count=att_count,
            ))

        logger.info("SQLite fallback: read %d notes from NoteStore.sqlite", len(results))
        return results

    except Exception as exc:
        logger.error("SQLite fallback failed: %s", exc)
        return []
```

**IMPORTANT SQLite schema note:** The actual column names in Apple Notes SQLite may vary by macOS version. The query above is for modern macOS (Ventura+). If the query fails, log the actual table columns:
```python
# Debug: list columns in ZICCLOUDSYNCINGOBJECT
cols = conn.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)").fetchall()
logger.info("Columns: %s", [c[1] for c in cols])
```
Adapt column names accordingly.

### 3. Update `get_all_notes()` to use the 3-tier strategy

Replace the current `get_all_notes()` with:

```python
def get_all_notes() -> list[NoteRecord]:
    """Fetch all notes. Strategy: folder-by-folder JXA -> monolithic JXA -> SQLite fallback."""
    if platform.system() != "Darwin":
        logger.warning("notes_parser: not macOS — skipping Notes export")
        return []

    # Strategy 1: Folder-by-folder JXA (most reliable for large libraries)
    folders = get_folders()
    if folders:
        all_notes = []
        failed_folders = []
        for f in folders:
            if f.note_count == 0:
                continue
            logger.info("Fetching folder '%s' (%d notes)...", f.name, f.note_count)
            # Scale timeout by note count: 2s per note, minimum 30s, max 120s
            timeout = max(30.0, min(120.0, f.note_count * 2.0))
            notes = get_notes_by_folder(f.name, timeout=timeout)
            if notes:
                all_notes.extend(notes)
                logger.info("  -> got %d notes from '%s'", len(notes), f.name)
            elif f.note_count > 0:
                failed_folders.append(f.name)
                logger.warning("  -> 0 notes from '%s' (expected %d)", f.name, f.note_count)

        if all_notes:
            if failed_folders:
                logger.warning("Failed folders (will retry with SQLite): %s", failed_folders)
            logger.info("Folder-by-folder JXA: %d notes total", len(all_notes))
            return all_notes

    # Strategy 2: Original monolithic JXA (works for small libraries)
    logger.info("Trying monolithic JXA export...")
    try:
        raw = run_jxa(_JXA_EXPORT_ALL, timeout=180.0)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        if isinstance(data, list) and data:
            logger.info("Monolithic JXA: %d notes", len(data))
            return [_parse_note_dict(x) for x in data if isinstance(x, dict)]
    except Exception as exc:
        logger.warning("Monolithic JXA failed: %s", exc)

    # Strategy 3: SQLite direct read (last resort)
    logger.info("Falling back to SQLite direct read...")
    return get_all_notes_sqlite()
```

### 4. Update `notes_indexer.py` — Add note body to index JSON

The current indexer does NOT include `body` in the index output (line 531-547 of notes_indexer.py). The `notes_to_cortex.py` script reads `note.get("body")` from the index JSON. Without the body field, every note gets classified as empty and skipped.

**This is the second critical bug.** In `notes_indexer.py::run_index()`, the `indexed.append(...)` block (around line 531) must include the body:

```python
indexed.append(
    {
        "note_id": note.note_id,
        "title": note.title,
        "body": note.body,              # <-- ADD THIS LINE
        "folder": note.folder,
        "created_at": note.created_at,  # <-- ADD full timestamps
        "modified_at": note.modified_at[:10] if note.modified_at else "",
        "category": cat,
        "project": proj,
        "value_score": score,
        "has_attachments": note.has_attachments,
        "attachment_count": note.attachment_count,
        "has_codes": hc,
        "action": action,
        "extracted_codes": codes,
        "summary": one_line_summary(note, cat),
    }
)
```

**Without the `body` field in the index JSON, `notes_to_cortex.py` gets empty strings for every note and skips them all as "empty."**

### 5. Add `notes_parser.py` imports

Make sure these imports are at the top of `notes_parser.py`:

```python
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
```

---

## Testing

After making the changes, run on Bob:

```zsh
# Step 1: List folders to verify JXA connectivity
python3 integrations/apple_notes/notes_indexer.py --folders

# Step 2: Build index (no LLM, just keyword classification)
python3 integrations/apple_notes/notes_indexer.py --index --no-llm

# Step 3: Check how many notes were indexed
python3 -c "import json; d=json.load(open('data/notes_index.json')); print(f'Notes: {len(d.get(\"notes\",[]))}'); print(f'Cats: {d.get(\"summary\",{}).get(\"by_category\",{})}')"

# Step 4: Ingest into Cortex
python3 scripts/notes_to_cortex.py

# Step 5: Verify Cortex memories grew
curl -s http://localhost:8102/health | python3 -m json.tool
```

## Expected Outcome
- Folders list should show all iCloud Notes folders
- Index should contain the full body text of every note
- `notes_to_cortex.py` should match notes to categories and POST them to Cortex
- Cortex `/health` memory total should grow significantly

Commit message: `fix(notes): folder-by-folder JXA + SQLite fallback + body in index JSON`
