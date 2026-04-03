# Auto-18: Dropbox + iCloud Sync — File Pipeline

## Context Files to Read First
- integrations/icloud_watch.py
- openclaw/dropbox_integration.py
- tools/icloud_sync.py
- tools/notes_sync.py
- CONTEXT.md (iCloud SymphonySH folder status)

## Prompt

Fix the file sync pipeline so project files flow automatically:

1. **iCloud SymphonySH folder** — currently empty on Bob, needs fixing:
   - Diagnose why `~/Library/Mobile Documents/com~apple~CloudDocs/SymphonySH/` is empty
   - Check if iCloud Drive is signed in and syncing on Bob
   - If the folder structure exists but files aren't downloading, force sync
   - If iCloud isn't configured, document the manual setup steps in `setup/nodes/BOB_ICLOUD_SETUP.md`

2. **iCloud watcher** (`integrations/icloud_watch.py` — fix and deploy):
   - Watch the SymphonySH folder for new files (photos, PDFs, docs)
   - Auto-categorize by filename/folder: proposals → `knowledge/proposals/`, photos → `knowledge/photos/`, agreements → project folder
   - On new file detected: send iMessage notification with filename and destination
   - Run as launchd service (not Docker — needs host filesystem access)

3. **Dropbox integration** (`openclaw/dropbox_integration.py` — wire up):
   - Symphony uses Dropbox for client-shared files
   - Watch configured Dropbox folders for new uploads from clients (signed agreements, photos, reference docs)
   - Auto-download and route to correct project folder in `knowledge/projects/`
   - Send iMessage when a client uploads something: "Steve Topletz uploaded 'Signed_Agreement.pdf' to Dropbox"

4. **Notes sync** (`tools/notes_sync.py` — verify and schedule):
   - The Apple Notes sync pipeline is built — verify it still works
   - Schedule weekly sync via launchd: photos export, learning notes index, ideas extraction
   - Project photo export: categorize 785+ photos by project for portfolio use

5. **Unified file index**:
   - Maintain a master file index at `knowledge/file_index.json`
   - Track: filename, source (iCloud/Dropbox/email attachment), project, date added, path on disk
   - Bob can answer "where is the Topletz signed agreement?" by querying this index

Use standard logging.
