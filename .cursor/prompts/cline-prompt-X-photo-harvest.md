# Cline Prompt X — Notes Photo Harvest + Dedupe

## Objective
Scan all Apple Notes folders, extract photos from project/install notes, dedupe against existing repo photos, convert HEIC to JPG, and update projects.ts with new unique images.

## Steps

### 1. Scan Apple Notes
Run the existing notes indexer:
```
python3 integrations/apple_notes/notes_indexer.py --index
```
This exports all notes to data/notes_index.json with titles, bodies, folders, and attachment counts.

### 2. Extract Photo Notes
Write a script at scripts/photo_harvest.py that:
- Reads data/notes_index.json
- Filters notes where category is "photo_log" OR attachment_count > 0 OR folder name contains "photo", "install", "project", "job", "symphony"
- For each matching note, use osascript JXA to export image attachments (.jpg, .jpeg, .png, .heic) to a staging directory: /tmp/notes_photos/{folder_name}/{note_title}/
- Use the JXA from integrations/apple_notes/notes_parser.py get_attachments() to list them, then use AppleScript to save the actual files:

```applescript
tell application "Notes"
  set theNote to first note whose id is "{note_id}"
  repeat with att in attachments of theNote
    save att in POSIX file "/tmp/notes_photos/{folder}/{filename}"
  end repeat
end tell
```

- Log each extracted photo with source note title and folder

### 3. Scan Existing Repo Photos
Build a hash index of every photo already in public/lovable-uploads/ using:
- File size + first 8KB hash (fast approximate dedupe)
- Generate: /tmp/photo_harvest_existing_hashes.json

### 4. Dedupe
Compare extracted notes photos against existing hashes.
- Exact dupes: skip
- Unique photos: copy to public/lovable-uploads/ organized by project folder
- Near-dupes (same size within 5 percent): flag for manual review
- Write report: data/photo_harvest_report.md listing:
  - Total notes scanned
  - Photos found
  - Dupes removed
  - New unique photos added (with paths)
  - Near-dupes flagged for review

### 5. HEIC Conversion
Convert ALL .heic files to .jpg using sips:
```
sips -s format jpeg input.heic --out output.jpg
```
The site cannot serve HEIC files. This includes existing unconverted files:
- public/lovable-uploads/wiring/Wire Relocation/IMG_2841.HEIC
- public/lovable-uploads/wiring/Wire Relocation/IMG_2840.HEIC
- public/lovable-uploads/wiring/IMG_2330.HEIC
- public/lovable-uploads/wiring/IMG_0444.HEIC
- public/lovable-uploads/wiring/IMG_0443.HEIC
- public/lovable-uploads/mounted tvs/Misc/IMG_0012.HEIC

After conversion, delete the original .heic files and update any references in source code (src/utils/photos/*.ts, src/data/projects.ts) to point to the new .jpg versions.

### 6. Update Projects Data
- For the "full-home-install" project (slug: full-home-install in src/data/projects.ts), add all new unique photos from the Home-related notes
- For any other projects that gained new photos, update their entries too
- For the wiring project (slug: structured-wiring-showcase), add the newly converted JPGs from the wiring HEIC files
- Make sure every photo path in projects.ts actually exists on disk

### 7. Validation
- Run: find public/lovable-uploads -name "*.heic" -o -name "*.HEIC" (should return nothing)
- Run: grep -r "\.heic\|\.HEIC" src/ (should return nothing)
- Verify the dev server builds without errors

Commit and push when done.
