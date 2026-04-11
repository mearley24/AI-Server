-- Cline prompt: Hazel + Dropbox auto-sync for M2 and Bob --

CONTEXT:
Matt uses D-Tools Cloud to generate proposals on his M2 MacBook Pro. Proposals export as PDFs to a local folder. The SymphonySH iCloud folder is shared between M2 and Bob (Mac Mini M4 at 192.168.1.189). Bob has Dropbox installed and syncing. The Dropbox folder structure for every project is:
[ProjectName]/Client/ (shared with client, always current docs)
[ProjectName]/Internal/ (background work, never shared)
[ProjectName]/Archive/ (old versions with date stamp, never shared)

Client-facing files use this naming: "Symphony Smart Homes - [Project Address] - [Document Type].pdf"
No version numbers, no quote numbers, no internal codes on client-facing files.
Bob's iCloud path: /Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/
Bob's Dropbox path: ~/Library/CloudStorage/Dropbox-Personal/ (NOT ~/Dropbox)

WHAT TO BUILD:

HAZEL RULE GENERATOR (for M2)
Create a script at scripts/generate-hazel-rules.sh that outputs instructions for Matt to create Hazel rules on his M2: Rule A - D-Tools Export Watcher:

Watch folder: ~/Documents/ (or wherever D-Tools exports -- Matt may need to adjust)

Condition: File is PDF AND filename contains "Q-" (D-Tools quote prefix)

Action: Copy file to ~/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects/

This gets the file into iCloud, which syncs to Bob automatically

Rule B - Duplicate Cleanup:

Watch folder: ~/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/

Condition: File has " (1)" or " copy" in name

Action: Delete (Hazel on M2 handles dedup so Bob doesn't see duplicates)

BOB FILE WATCHER SERVICE (new Docker container or LaunchAgent)
Create services/file-watcher/main.py that: a) Watches the iCloud SymphonySH folder for new/changed PDFs:
/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects/ b) When a new proposal PDF is detected:

Parse project name from filename (e.g. "Topletz" from "Steve-Toplets-84-Aspen-Meadow...")

Map to Dropbox project folder (use a config file or fuzzy match)

Archive the existing file in [Project]/Archive/ with date stamp:
"Symphony Smart Homes - [Address] - Proposal-YYYYMMDD.pdf"

Rename the new file to client-facing format:
"Symphony Smart Homes - [Address] - [DocType].pdf"

Copy to [Project]/Client/ in Dropbox

Publish a Redis event on channel "files:new" with project name, file type, and path

c) When a Redis "files:new" event fires:

Generate a fresh Dropbox share link via API (tokens in .env: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN)

Queue a Zoho email draft via notification-hub Hermes channel with the share link

Send Matt an iMessage for approval before sending

d) Also watch ~/Library/CloudStorage/Dropbox-Personal/ root for files that land there by accident:

If a project-related PDF lands in Dropbox root, move it to the correct [Project]/Client/ folder

Archive any previous version first

PROJECT MAPPING CONFIG
Create services/file-watcher/projects.json:
{
"topletz": {
"address": "84 Aspen Meadow",
"client": "Steve Topletz",
"client_email": "stopletz1@gmail.com",
"dropbox_folder": "Topletz",
"keywords": ["topletz", "toplets", "aspen meadow", "P-119"]
},
"timber-ridge": {
"address": "Timber Ridge",
"client": "Austin Hukill",
"dropbox_folder": "Timber Ridge",
"keywords": ["timber", "shaw", "hukill"]
}
}
New projects get added here. Bob should also be able to create new project folders automatically when he sees an unknown project name.

INTEGRATION POINTS

Redis channel: "files:new" (publish when new file detected)

Redis channel: "files:processed" (publish when file moved to Client/)

Cortex: Log every file operation as an observation (POST /api/observations)

notification-hub: Use Hermes channel for email draft creation

follow-up-tracker: If document type is "Agreement" and it gets moved to Client/, create a follow-up for signature

REQUIREMENTS

Use Python watchdog library for filesystem monitoring

Use Dropbox API v2 for share link generation (refresh token flow)

Handle iCloud .icloud stub files (run brctl download to force-download before processing)

Idempotent: if the same file lands twice, don't archive and re-copy

Log everything to /tmp/file-watcher.log

Graceful handling of Dropbox API rate limits

DOCKER OPTION (preferred if possible)
If this can run as a Docker container, add to docker-compose.yml. Volume mount both:

/Users/bob/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/:/data/icloud:ro

/Users/bob/Library/CloudStorage/Dropbox-Personal/:/data/dropbox

If Docker volume mounting iCloud causes issues with .icloud stubs, fall back to a LaunchAgent running natively on Bob.

TESTING:

Drop a test PDF into the iCloud SymphonySH/Projects/ folder

Verify it gets renamed, archived (if previous version exists), and copied to Dropbox Client/

Verify Redis event fires

Verify Dropbox share link is generated

Verify notification-hub queues a draft email

Verify Cortex logs the observation
