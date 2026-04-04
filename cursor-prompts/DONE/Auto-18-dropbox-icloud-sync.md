# Auto-18: Dropbox + iCloud Sync — File Pipeline

## Context Files to Read First
- integrations/icloud_watch.py
- openclaw/dropbox_integration.py
- tools/icloud_sync.py
- tools/notes_sync.py
- knowledge/client_registry.json  ← used to route files to the correct project folder
- CONTEXT.md (iCloud SymphonySH folder status)

## Prompt

Fix and extend the file sync pipeline so project files flow automatically from iCloud and Dropbox into the right places, with zero manual intervention.

---

### 1. iCloud SymphonySH Folder — Diagnose and Fix

**Watch path:** `/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/SymphonySH/`

Current issue: folder is empty on Bob. Fix before wiring up the watcher.

- Diagnose why the folder is empty: check if iCloud Drive is signed in and syncing on Bob (`brctl status`, `brctl log --wait --shorten`)
- If iCloud Drive is signed in but files aren't downloading → force sync: `brctl download ~/Library/Mobile\ Documents/`
- If iCloud isn't configured → document the manual setup steps in `setup/nodes/BOB_ICLOUD_SETUP.md` (sign in, enable iCloud Drive, enable Desktop & Documents if needed)
- Verify SymphonySH folder appears and syncs before deploying the watcher

---

### 2. Standardized Dropbox Folder Structure

**This is the canonical folder layout for all Symphony projects.** All file operations — uploads, version replacements, archiving — follow this structure.

```
Symphony Smart Homes/
└── Projects/
    └── [Client Name] — [Address]/
        ├── Client/          ← shared with client via stable Dropbox share link
        │   ├── Proposals/   ← current proposal PDF(s)
        │   ├── Agreements/  ← signed agreements
        │   └── Documents/   ← anything else for the client
        ├── Internal/        ← Symphony-only, never shared with client
        │   ├── Photos/      ← site photos, install photos
        │   ├── Drawings/    ← CAD, wire diagrams, rack layouts
        │   └── Notes/       ← internal project notes
        └── Archive/         ← old proposal versions, superseded files
```

**Share link rule:** The `Client/` folder is shared with the client once, at project creation. The share link is stored in the project record in `knowledge/client_registry.json`. It never changes — the client bookmarks it and always has access to the latest files.

**Dropbox API credentials** are in `.env`:
```
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
DROPBOX_REFRESH_TOKEN=...
```

Use `dropbox` Python SDK with the refresh token for offline access (no user interaction required):
```python
import dropbox
from dropbox.oauth import DropboxOAuth2FlowNoRedirect

dbx = dropbox.Dropbox(
    oauth2_refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN"),
    app_key=os.getenv("DROPBOX_APP_KEY"),
    app_secret=os.getenv("DROPBOX_APP_SECRET")
)
```

---

### 3. Proposal Version Management (Dropbox)

When the proposal engine (proposals/proposal_engine.py) exports a new PDF — or when D-Tools exports a new PDF — auto-upload it to the correct `Client/Proposals/` folder and archive the previous version.

**Trigger:** D-Tools export path watch OR direct call from proposal engine.

**Upload + archive flow:**
```python
def upload_proposal(project_id: str, new_pdf_path: str):
    project = client_registry.get(project_id)
    dropbox_base = f"/Symphony Smart Homes/Projects/{project['folder_name']}"
    proposals_folder = f"{dropbox_base}/Client/Proposals"
    archive_folder = f"{dropbox_base}/Archive"
    
    # List existing proposals in Client/Proposals/
    existing = dbx.files_list_folder(proposals_folder).entries
    for file in existing:
        if file.name.endswith(".pdf"):
            # Move old version to Archive/
            dbx.files_move_v2(
                file.path_display,
                f"{archive_folder}/{file.name}"
            )
    
    # Upload new version
    with open(new_pdf_path, "rb") as f:
        dbx.files_upload(f.read(), f"{proposals_folder}/{os.path.basename(new_pdf_path)}")
    
    # Notify via event bus
    event_bus.publish("dropbox-sync", "proposal_uploaded", {
        "project_id": project_id,
        "filename": os.path.basename(new_pdf_path),
        "client": project["client_name"]
    })
    
    # Send iMessage to Matt
    notify(f"Proposal uploaded to Dropbox for {project['client_name']}: {os.path.basename(new_pdf_path)}")
```

**Note:** The client share link for `Client/` does not change — the client will see the new proposal automatically.

---

### 4. iCloud Watcher (`integrations/icloud_watch.py` — fix and deploy)

Watch `/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/SymphonySH/` for new files.

**Run as launchd service** (not Docker — needs host filesystem access). LaunchAgent plist at `~/Library/LaunchAgents/com.symphonysh.icloud-watch.plist`.

**On new file detected → auto-categorize using filename + path analysis:**

```python
def categorize_file(filepath: str) -> tuple[str, str]:
    """Returns (category, destination_description)"""
    filename = os.path.basename(filepath).lower()
    
    if any(kw in filename for kw in ["proposal", "quote", "estimate", "bid"]):
        return "proposal", "Client/Proposals/"
    
    if any(kw in filename for kw in ["agreement", "contract", "signed", "signature"]):
        return "agreement", "Client/Agreements/"
    
    if any(ext in filename for ext in [".jpg", ".jpeg", ".png", ".heic", ".mov"]):
        return "photo", "Internal/Photos/"
    
    if any(kw in filename for kw in ["drawing", "cad", "dwg", "rack", "wire"]):
        return "drawing", "Internal/Drawings/"
    
    return "document", "Client/Documents/"
```

**Client registry lookup:** After categorizing, look up which project the file belongs to using `knowledge/client_registry.json`. Match on:
1. Subfolder name (if file is in `SymphonySH/Topletz/` → Topletz project)
2. Filename keywords (if filename contains "Topletz" → Topletz project)
3. If no match → quarantine to `knowledge/unrouted/` and notify Matt via iMessage

**Routing flow:**
```python
def handle_new_file(filepath: str):
    category, destination = categorize_file(filepath)
    project = client_registry.find_by_file(filepath)
    
    if project is None:
        # Can't route — notify Matt
        shutil.copy(filepath, f"knowledge/unrouted/{os.path.basename(filepath)}")
        notify(f"New file can't be routed: {os.path.basename(filepath)} — check knowledge/unrouted/")
        return
    
    # Copy to local knowledge store
    local_dest = f"knowledge/projects/{project['id']}/{destination}"
    os.makedirs(local_dest, exist_ok=True)
    shutil.copy(filepath, local_dest)
    
    # Upload to Dropbox in the right subfolder
    if category == "proposal":
        upload_proposal(project['id'], filepath)
    else:
        upload_to_project_folder(project['id'], filepath, destination)
    
    # Update file index
    file_index.add(filepath, source="icloud", project_id=project['id'], category=category)
    
    # Notify Matt
    notify(f"iCloud: {os.path.basename(filepath)} → {project['client_name']}/{destination}")
    
    # Publish event
    event_bus.publish("icloud-watch", "file_synced", {
        "filename": os.path.basename(filepath),
        "project_id": project['id'],
        "category": category,
        "destination": destination
    })
```

**Auto-categorization rules:**
- Proposals → `Client/Proposals/` (also triggers proposal version management from Section 3)
- Photos/HEIC/MOV → `Internal/Photos/`
- Agreements/signed docs → `Client/Agreements/` (also triggers acceptance workflow in API-13)
- Drawings/CAD → `Internal/Drawings/`
- Everything else → `Client/Documents/`

---

### 5. Dropbox Integration (`openclaw/dropbox_integration.py` — wire up)

Symphony uses Dropbox for client-shared files. Watch for client uploads.

- Poll Dropbox for new files in configured project folders every 5 minutes (use Dropbox longpoll API for efficiency: `files_list_folder_longpoll`)
- When a client uploads something → auto-download to `knowledge/projects/{project_id}/Client/`
- Route based on file type (same categorization logic as above)
- If signed agreement detected → trigger acceptance workflow (emit `file_synced` event with category `agreement`)
- Send iMessage: `"Steve Topletz uploaded 'Signed_Agreement.pdf' to Dropbox"`
- Log in client communication tracker

**Dropbox longpoll watcher:**
```python
def watch_project_folders():
    for project in client_registry.get_active_projects():
        folder = f"/Symphony Smart Homes/Projects/{project['folder_name']}/Client"
        result = dbx.files_list_folder(folder)
        cursor = result.cursor
        
        while True:
            poll = dbx.files_list_folder_longpoll(cursor, timeout=30)
            if poll.changes:
                result = dbx.files_list_folder_continue(cursor)
                for entry in result.entries:
                    handle_dropbox_upload(project, entry)
                cursor = result.cursor
```

---

### 6. Notes Sync (`tools/notes_sync.py` — verify and schedule)

- The Apple Notes sync pipeline is built — verify it still works
- Schedule weekly sync via launchd: photos export, learning notes index, ideas extraction
- Project photo export: categorize 785+ photos by project for portfolio use

---

### 7. Unified File Index

Maintain a master file index at `knowledge/file_index.json`:

```python
# Entry format
{
    "id": "uuid",
    "filename": "Topletz_Proposal_v3.pdf",
    "source": "icloud",              # icloud | dropbox | email_attachment
    "project_id": "topletz_2026",
    "project_name": "Topletz",
    "category": "proposal",          # proposal | agreement | photo | drawing | document
    "local_path": "knowledge/projects/topletz_2026/Client/Proposals/Topletz_Proposal_v3.pdf",
    "dropbox_path": "/Symphony Smart Homes/Projects/Topletz — 123 Main St/Client/Proposals/Topletz_Proposal_v3.pdf",
    "date_added": "2026-04-03T16:24:35Z",
    "date_modified": "2026-04-03T16:24:35Z"
}
```

- Bob can answer "where is the Topletz signed agreement?" by querying this index
- Index is queryable via Bob's Brain (API-11): `GET /context/files?project=topletz&category=agreement`
- Index is updated by icloud_watch.py, dropbox_integration.py, and email attachment handler

---

### 8. Client Registry (`knowledge/client_registry.json`)

The client registry is the lookup table that routes files to the right project. It must be kept current.

```json
{
  "projects": [
    {
      "id": "topletz_2026",
      "client_name": "Steve Topletz",
      "address": "123 Main St, Dallas TX",
      "folder_name": "Topletz — 123 Main St",
      "dropbox_share_link": "https://www.dropbox.com/sh/...",
      "status": "proposal_sent",
      "keywords": ["topletz", "steve", "123 main"],
      "linear_project_id": "PRJ-001"
    }
  ]
}
```

- `keywords` is used for filename-based routing (case-insensitive match)
- Updated by API-13 (Client Lifecycle) when a new project is created
- Read by icloud_watch.py, dropbox_integration.py, and file_index

Use standard logging.
