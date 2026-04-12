# Cline Prompt Y2 — Fix Apple Notes JXA Timeout

## Problem
The notes_parser.py `get_all_notes()` function uses `app.notes()` which forces
Notes.app to load ALL notes from iCloud before returning. With a large library
this exceeds the 2-minute AppleEvent timeout. The SQLite database at
~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite has
encrypted data — cannot be read directly.

## Root Cause
`_JXA_EXPORT_ALL` iterates `Notes.notes()` (flat list of ALL notes) in a
single osascript call with a 120s timeout. Notes with a large iCloud library
pre-fetches all notes before the iterator can start, hitting the AppleEvent
system timeout.

## Fix: Batched Per-Folder JXA

Replace the single monolithic JXA call with a two-pass approach:

**Pass 1:** Get folder list with note counts (fast — folder metadata only, no body fetch).

**Pass 2:** For each folder, fetch notes in index-based batches of 50. Each
batch is a separate osascript call so no single call exceeds the system timeout.

## Implementation

Rewrite `integrations/apple_notes/notes_parser.py`:

1. Add `get_folders_fast()` — gets folder names and note counts without reading
   note bodies (just `folder.notes.length`).

2. Add `get_notes_batch(folder_name, offset, limit)` — fetches `limit` notes
   starting at `offset` from the named folder, reading only:
   `note_id`, `title`, `plaintext()` (body), `creationDate`, `modificationDate`,
   `attachments().length`

3. Replace `get_all_notes()` with a loop:
   - For each folder, fetch in batches of 50 until all notes retrieved
   - Skip folders with 0 notes
   - Collect into a flat `list[NoteRecord]`
   - Continue past per-folder errors (don't abort the whole scan)

4. Add a per-batch timeout of 90s (safe under the 2-min AppleEvent limit).

5. Add progress logging: "Folder X/N: {name} — {count} notes (batch Y/Z)"

## JXA for per-folder batch fetch:

```javascript
function run(argv) {
  // argv[0] = folder name, argv[1] = offset, argv[2] = limit
  var folderName = argv[0];
  var offset = parseInt(argv[1]) || 0;
  var limit = parseInt(argv[2]) || 50;
  try {
    var app = Application('Notes');
    var folder = null;
    var folders = app.folders();
    for (var i = 0; i < folders.length; i++) {
      if (String(folders[i].name()) === folderName) {
        folder = folders[i];
        break;
      }
    }
    if (!folder) return JSON.stringify({error: 'folder not found: ' + folderName});
    var notes = folder.notes();
    var end = Math.min(offset + limit, notes.length);
    var out = [];
    for (var j = offset; j < end; j++) {
      var n = notes[j];
      try {
        var attCount = 0;
        try { attCount = n.attachments().length; } catch(e) {}
        out.push({
          note_id: String(n.id()),
          title: String(n.name() || ''),
          body: String(n.plaintext() || ''),
          created_at: String(n.creationDate() || ''),
          modified_at: String(n.modificationDate() || ''),
          folder: folderName,
          attachment_count: attCount
        });
      } catch(e) {}
    }
    return JSON.stringify({notes: out, total: notes.length, offset: offset});
  } catch(e) {
    return JSON.stringify({error: String(e)});
  }
}
```

## Also fix notes_indexer.py

After fixing notes_parser.py, re-run the indexer:
```
python3 integrations/apple_notes/notes_indexer.py --index --no-llm
```

Verify data/notes_index.json has actual notes (not 0).

## Then re-run the ingest:
```
python3 scripts/notes_to_cortex.py
```

## Validation
```
cat data/notes_index.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('notes:', d['summary']['total_notes'])"
curl -s http://localhost:8102/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('memories:', d['memories']['total'])"
```

Commit and push when done.
