# Auto-25: Apple Notes Indexer — Organize, Index, and Flag for Cleanup

## The Problem

104+ notes in Symphony SH, 21 in Previous Work, 11 in Work Cheats, plus Learning, My Stuff, and Incoming Tasks folders. Some are critical project references with photos and access codes. Some are stale drafts or duplicates. Nobody knows which is which without opening each one manually.

The notes_reader.py, notes_sync.py, and notes_watcher.py referenced in AGENTS.md were never actually built. Time to build them for real.

## Context Files to Read First
- AGENTS.md (Apple Notes Reader, Notes Sync, Notes Watcher sections)
- tools/imessage_watcher.py (similar pattern — watches a macOS resource)

## Prompt

Build the complete Apple Notes pipeline — read, index, categorize, flag for cleanup:

### 1. Notes Reader (`tools/notes_reader.py`)

Read the Apple Notes SQLite database directly on macOS:

```python
DB_PATH = "~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
```

The NoteStore.sqlite schema uses these key tables:
- `ZICCLOUDSYNCINGOBJECT` — main notes table (ZTITLE, ZSNIPPET, ZMODIFICATIONDATE1, ZFOLDER)
- `ZICNOTEDATA` — note body (ZDATA is gzipped protobuf, but ZSNIPPET in the main table has plain text preview)

Implement:
- `--list-folders` — show all folders with note count
- `--list <folder>` — list all notes in a folder (title, modified date, snippet preview)
- `--read <note_id>` — read full note content (extract text from protobuf or use snippet)
- `--search <query>` — full-text search across all notes
- `--export-all` — dump everything to `data/notes_export/` as individual markdown files
- `--stats` — total notes, notes per folder, oldest/newest, photos count

### 2. Notes Indexer (`tools/notes_indexer.py`)

Analyze every note and build a structured index:

For each note, determine:
- **Category**: project_reference, access_codes, configuration, photo_log, meeting_notes, idea, learning, stale_draft, duplicate, unknown
- **Project match**: does the title or content match a known project? (address patterns, client names)
- **Freshness**: last modified date, staleness score (>6 months = stale, >1 year = very stale)
- **Value score** (0-100): 
  - Has photos? +20
  - Has access codes/passwords/IPs? +30
  - References active project? +25
  - Modified in last 90 days? +15
  - Has actionable content? +10
  - Duplicate of another note? -50

Output: `data/notes_index.json`:
```json
{
  "notes": [
    {
      "id": 346,
      "title": "Topletz - 84 Aspen Meadow",
      "folder": "Symphony SH",
      "modified": "2026-03-28",
      "category": "project_reference",
      "project": "Topletz",
      "value_score": 85,
      "has_photos": true,
      "photo_count": 12,
      "has_codes": true,
      "action": "keep",
      "summary": "Site photos, WiFi password, alarm code, rack location notes"
    },
    {
      "id": 201,
      "title": "Speaker wire notes",
      "folder": "Symphony SH",
      "modified": "2025-06-15",
      "category": "stale_draft",
      "project": null,
      "value_score": 10,
      "has_photos": false,
      "has_codes": false,
      "action": "flag_for_deletion",
      "summary": "3 lines of incomplete notes about wire gauge"
    }
  ]
}
```

### 3. Cleanup Report (`tools/notes_cleanup.py`)

Generate an actionable cleanup report:

**Keep (high value):**
- Notes with access codes, passwords, IPs, WiFi info → these are critical
- Notes with project photos → feed into portfolio (Auto-24)
- Notes tied to active projects → keep and index
- Work Cheats → always keep

**Archive (medium value):**
- Previous Work notes → move to knowledge/projects/[name]/
- Completed project notes from Symphony SH → move to Previous Work folder
- Learning notes → index in knowledge/learning/

**Flag for Deletion (low value):**
- Empty or near-empty notes (<20 characters)
- Duplicate notes (same title + similar content)
- Stale drafts with no photos and no codes (>1 year old, <50 char)
- Test notes, scratch notes

**Needs Review (uncertain):**
- Notes that might have codes but we're not sure
- Notes with photos but no clear project match

Output as iMessage to Matt:
```
Notes Audit Complete:
✅ Keep: 67 notes (42 with photos, 18 with codes)
📦 Archive: 31 notes (move to Previous Work)
🗑️ Flag for Deletion: 24 notes (empty/stale/duplicate)
❓ Needs Review: 13 notes

Top action: 24 notes can be safely deleted. Reply YES to auto-delete, or I'll send you the full list.
```

### 4. Knowledge Extraction

For notes marked "keep":
- Extract all access codes, passwords, WiFi credentials, IP addresses → save to `knowledge/projects/[project]/access_codes.md` (encrypted or at least not in git)
- Extract all photos → save to `data/notes_photos/[project]/` for portfolio use
- Extract configuration notes → save to `knowledge/projects/[project]/config_notes.md`
- Extract meeting notes → save to `knowledge/projects/[project]/meeting_notes.md`

### 5. Notes Watcher (`tools/notes_watcher.py`)

Ongoing monitoring after initial cleanup:
- Check NoteStore.sqlite every 5 minutes for new or modified notes
- Auto-categorize new notes using the same rules
- If a new note matches an active project → add to the project's knowledge folder
- If a new note is in "Incoming Tasks" → parse as task, create Linear ticket
- Launchd service: `com.symphony.notes-watcher`

### 6. Notes Sync (`tools/notes_sync.py`)

Bidirectional awareness:
- `--sync-photos` — export all photos by project (for portfolio Auto-24)
- `--sync-learning` — index learning/certification notes
- `--sync-ideas` — extract ideas from My Stuff → create tasks or ideas.txt entries
- `--sync-all` — full sync
- Weekly scheduled run via launchd

### 7. CLI

```
python3 tools/notes_reader.py --list-folders
python3 tools/notes_reader.py --list "Symphony SH"
python3 tools/notes_reader.py --search "WiFi password"
python3 tools/notes_indexer.py --index --output data/notes_index.json
python3 tools/notes_cleanup.py --report
python3 tools/notes_cleanup.py --delete-flagged  (requires --confirm flag)
python3 tools/notes_sync.py --sync-all
python3 tools/notes_watcher.py --watch
```

All tools run on the HOST (not Docker) since they need filesystem access to NoteStore.sqlite. Use standard logging.
