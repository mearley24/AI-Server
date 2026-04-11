# Symphony File Watcher

Automates the full D-Tools → iCloud → Dropbox → client delivery pipeline.

```
D-Tools (M2)  →  Hazel copies PDF  →  iCloud/Projects/
                                              ↓  (auto-syncs to Bob)
Bob (Mac Mini)  ←  file-watcher detects new PDF
                        ↓
                  Match project (projects.json)
                        ↓
            Archive old version in Dropbox/[Project]/Archive/
                        ↓
            Copy as "Symphony Smart Homes - [Address] - [DocType].pdf"
                   to Dropbox/[Project]/Client/
                        ↓
              Publish Redis  files:new
                        ↓
          Generate Dropbox share link (API v2)
                        ↓
          Send iMessage to Matt for approval
                        ↓
          Queue Zoho email draft (notification-hub)
                        ↓
            (If Agreement) Create OpenClaw follow-up
```

---

## Quick Start — Native (Recommended)

Native mode is **preferred** because `brctl` (iCloud stub download) only works on macOS.

```bash
# 1. Install Python deps
pip3 install -r services/file-watcher/requirements.txt

# 2. Create iCloud Projects folder (if it doesn't exist)
mkdir -p "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects"

# 3. Install LaunchAgent
cp setup/launchd/com.symphony.file-watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.symphony.file-watcher.plist

# 4. Check it's running
launchctl list | grep file-watcher
curl http://127.0.0.1:8102/health

# 5. Watch the log
tail -f /tmp/file-watcher.log
```

## Quick Start — Docker (Optional)

Use Docker only when iCloud PDFs are always fully materialised (no .icloud stubs).

```bash
docker compose up -d --build file-watcher
docker compose logs -f file-watcher
```

---

## Required .env Keys

```bash
# Dropbox API v2 — create app at https://www.dropbox.com/developers/apps
DROPBOX_APP_KEY=your_app_key
DROPBOX_APP_SECRET=your_app_secret
DROPBOX_REFRESH_TOKEN=your_refresh_token   # see scripts/setup_dropbox.sh

# iMessage recipient for approval alerts
MATT_PHONE_NUMBER=+1XXXXXXXXXX
```

### Getting a Dropbox Refresh Token

1. Go to https://www.dropbox.com/developers/apps → Create App
2. Permissions: `files.content.write`, `files.content.read`, `sharing.write`
3. Generate an access token, then exchange for a refresh token:

```bash
curl https://api.dropboxapi.com/oauth2/token \
  -d grant_type=authorization_code \
  -d code=<auth_code> \
  -d client_id=$DROPBOX_APP_KEY \
  -d client_secret=$DROPBOX_APP_SECRET \
  -d redirect_uri=https://localhost
# → copy refresh_token from response
```

---

## M2 Hazel Setup

Run on your M2 MacBook Pro to see the full setup instructions:

```bash
bash scripts/generate-hazel-rules.sh
```

This outputs step-by-step Hazel rule configuration for:
- **Rule A**: Auto-copy D-Tools PDFs (`Q-*`) to iCloud/Projects/
- **Rule B**: Delete iCloud duplicate files (` (1)`, ` copy`)

---

## Adding New Projects

Edit `services/file-watcher/projects.json`:

```json
{
  "smith": {
    "address": "123 Main Street",
    "client": "John Smith",
    "client_email": "john@example.com",
    "dropbox_folder": "Smith",
    "keywords": ["smith", "123 main", "P-999"]
  }
}
```

Then restart the service — no rebuild needed:

```bash
# LaunchAgent:
launchctl stop com.symphony.file-watcher && launchctl start com.symphony.file-watcher

# Docker:
docker restart file-watcher
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Service health + config |
| `GET`  | `/projects` | Current project config |
| `POST` | `/process` | Manually process a file |

```bash
# Manual trigger (testing)
curl -X POST http://127.0.0.1:8102/process \
  -H 'Content-Type: application/json' \
  -d '{"path": "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects/test.pdf"}'
```

---

## Redis Events

| Channel | When | Payload |
|---------|------|---------|
| `files:new` | PDF copied to Dropbox/Client/ | project, doc_type, dropbox_path, client, client_email |
| `files:processed` | Share link generated + Matt notified | + share_url, notified_at |

---

## Testing

```bash
# 1. Drop a test PDF into the iCloud Projects folder
cp /tmp/test.pdf "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects/Steve-Topletz-Q-212.pdf"

# 2. Watch the log
tail -f /tmp/file-watcher.log

# 3. Check Dropbox
ls ~/Library/CloudStorage/Dropbox-Personal/Topletz/Client/

# 4. Verify Redis event fired
redis-cli -a d19c9b0faebeee9927555eb8d6b28ec9 subscribe files:new

# 5. Check idempotency DB
sqlite3 /tmp/file-watcher.db "SELECT filename, project_key, doc_type, share_url FROM processed_files"
```

---

## Troubleshooting

**File not processed?**
```bash
tail -100 /tmp/file-watcher.log
```

**iCloud stub not downloading?**
```bash
# Check if file is a stub
ls -la "/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects/"
# Force download manually
brctl download "/path/to/.filename.pdf.icloud"
```

**Dropbox path wrong?**
```bash
# Verify path exists
ls ~/Library/CloudStorage/Dropbox-Personal/
# If Dropbox uses a different folder name, set in .env:
# DROPBOX_PATH=/Users/bob/Library/CloudStorage/Dropbox-YourAccount
```

**Share link not generating?**
```bash
# Check Dropbox credentials in .env
grep DROPBOX_ /Users/bob/AI-Server/.env
# Check health endpoint
curl http://127.0.0.1:8102/health | python3 -m json.tool
```
