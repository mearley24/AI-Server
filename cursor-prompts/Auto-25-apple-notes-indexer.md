# Auto-25: Apple Notes Indexer — Organize, Index, and Extract

## The Problem

Matt uses Apple Notes for rapid field capture: photos of job sites, WiFi passwords, alarm codes, project ideas, learning notes. Over time this creates 100+ notes across folders like "Symphony SH", "Previous Work", "Work Cheats", "Incoming Tasks" — with no organization, no search, and no connection to the project system. Critical access codes sit buried next to empty scratch notes. Nobody can find anything without opening every note manually.

`notes_reader.py`, `notes_indexer.py`, and `notes_watcher.py` are referenced in AGENTS.md but were never built. This prompt builds them.

## Context Files to Read First

- `integrations/icloud_watch.py` — pattern for macOS host integrations: how to detect file changes, run subprocesses, interface with iCloud — mirror this pattern for Notes
- `openclaw/client_tracker.py` — how active projects are stored; used to match notes to projects by client name and address patterns
- `knowledge/topletz/project-config.yaml` — example project config shape; used to understand what project data looks like for matching

## Prompt

Build the complete Apple Notes pipeline: `integrations/apple_notes/notes_indexer.py` and `integrations/apple_notes/notes_parser.py`. These run on the macOS HOST (Bob, the Mac Mini) — not inside Docker — because they need access to the Notes database and `osascript`.

### 1. Notes Parser (`integrations/apple_notes/notes_parser.py`)

Access Apple Notes via AppleScript. macOS exposes Notes through the `Notes` application's scripting dictionary.

```python
import subprocess
import json

def run_applescript(script: str) -> str:
    """Execute an AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr}")
    return result.stdout.strip()

def get_all_notes() -> list[dict]:
    """Fetch all notes via AppleScript. Returns list of note dicts."""
    script = """
    tell application "Notes"
        set output to {}
        repeat with aNote in every note
            set noteData to {id: id of aNote as text, name: name of aNote, body: plaintext of aNote, creation date: creation date of aNote as text, modification date: modification date of aNote as text, folder: name of container of aNote}
            set end of output to noteData
        end repeat
        return output
    end tell
    """
```

Notes from AppleScript return `plaintext` — no need to decode protobuf. The `plaintext` property gives clean readable text. Images are referenced in the body text as attachments.

To get folders:
```applescript
tell application "Notes"
    set folderList to {}
    repeat with aFolder in every folder
        set end of folderList to {name of aFolder, count of notes of aFolder}
    end repeat
    return folderList
end tell
```

To get note attachments (images):
```applescript
tell application "Notes"
    set targetNote to first note whose id is "{note_id}"
    set attachList to every attachment of targetNote
    set output to {}
    repeat with att in attachList
        set end of output to {name: name of att, filename: filename of att}
    end repeat
    return output
end tell
```

Expose these as clean Python functions in `notes_parser.py`:
- `get_all_notes() -> list[NoteRecord]`
- `get_folders() -> list[FolderInfo]`
- `get_note_by_id(note_id: str) -> NoteRecord`
- `get_attachments(note_id: str) -> list[AttachmentRecord]`

```python
@dataclass
class NoteRecord:
    note_id: str
    title: str
    body: str            # plain text content
    created_at: str      # ISO date string
    modified_at: str
    folder: str
    has_attachments: bool
    attachment_count: int = 0
```

### 2. Notes Indexer (`integrations/apple_notes/notes_indexer.py`)

Main module. Reads all notes, categorizes each one, and writes `data/notes_index.json`.

#### Categorization

Classify each note into one of these categories using keyword matching first, Ollama LLM second (for ambiguous cases):

```python
CATEGORY_RULES = {
    "access_codes": [
        r"wifi|ssid|password|passcode|alarm code|gate code|lock code|pin:|code:",
        r"\b\d{4,6}\b",  # 4-6 digit codes
        r"\b192\.168\.\d+\.\d+\b",  # IP addresses
    ],
    "project_reference": [
        # matched via client_tracker project names and address patterns
    ],
    "photo_log": [
        r"photo|picture|image|site photo|job site|install photo",
    ],
    "meeting_notes": [
        r"meeting|call|discussed|action item|follow up|next steps",
    ],
    "learning": [
        r"certification|exam|study|cedia|c4|control4|training|notes on|how to",
    ],
    "idea": [
        r"idea:|concept:|what if|could we|potential|brainstorm",
    ],
    "stale_draft": [],   # fallback for old, short, unmatched notes
}
```

If keyword matching is inconclusive, call Ollama with a short prompt:
```python
async def classify_with_llm(note: NoteRecord) -> str:
    """Use local Ollama to classify ambiguous notes."""
    prompt = f"""Classify this Apple Note into exactly one category.
Title: {note.title}
Content (first 300 chars): {note.body[:300]}

Categories: access_codes, project_reference, photo_log, meeting_notes, learning, idea, stale_draft, unknown
Reply with only the category name."""
    
    # POST to Ollama at http://localhost:11434 (running on same Mac as this script)
    response = httpx.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3.1:8b", "prompt": prompt, "stream": False},
        timeout=10.0,
    )
    return response.json()["response"].strip().lower()
```

Note: On the Mac Mini (Bob), Ollama runs on Maestro at `192.168.1.199:11434` — use that if local Ollama is not installed on Bob.

#### Value Scoring

```python
def compute_value_score(note: NoteRecord, category: str, project_match: str | None) -> int:
    """0-100 score indicating how valuable this note is to keep."""
    score = 0
    if note.has_attachments:
        score += 20    # photos = high value
    if category == "access_codes":
        score += 30    # passwords/codes = critical
    if project_match:
        score += 25    # tied to active project
    if _days_since_modified(note) < 90:
        score += 15    # recently modified
    if len(note.body) > 100:
        score += 10    # has actual content
    if _is_duplicate(note):
        score -= 50    # duplicate = likely safe to delete
    return max(0, min(100, score))
```

#### Project Matching

Load active projects from `openclaw/client_tracker.py`'s data (or read the client JSON directly from the data directory). For each note, check if the title or body contains:
- A known client last name (e.g., "Topletz", "Gates", "Hernaiz", "Kelly")
- A known address pattern (e.g., "84 Aspen Meadow", "Starwood")
- A known project keyword from project configs

#### Output: `data/notes_index.json`

```json
{
  "generated_at": "2026-04-03T00:00:00Z",
  "summary": {
    "total_notes": 147,
    "by_category": {"access_codes": 18, "project_reference": 42, ...},
    "by_action": {"keep": 85, "archive": 31, "flag_for_deletion": 24, "needs_review": 7},
    "notes_with_photos": 34,
    "notes_with_codes": 18
  },
  "notes": [
    {
      "note_id": "x-coredata://...",
      "title": "Topletz - 84 Aspen Meadow",
      "folder": "Symphony SH",
      "modified_at": "2026-03-28",
      "category": "project_reference",
      "project": "Topletz",
      "value_score": 85,
      "has_attachments": true,
      "attachment_count": 12,
      "has_codes": true,
      "action": "keep",
      "extracted_codes": ["WiFi: NetworkName / P@ssword123", "Alarm: 4521"],
      "summary": "Site photos, WiFi password, alarm code, rack location notes"
    }
  ]
}
```

#### Duplicate Detection

```python
def _is_duplicate(note: NoteRecord, all_notes: list[NoteRecord]) -> bool:
    """Flag if another note has the same title or >80% body similarity."""
    for other in all_notes:
        if other.note_id == note.note_id:
            continue
        if other.title.strip().lower() == note.title.strip().lower():
            return True
        # Simple Jaccard similarity on word sets for short notes
        if len(note.body) < 200:
            words_a = set(note.body.lower().split())
            words_b = set(other.body.lower().split())
            if words_a and words_b:
                overlap = len(words_a & words_b) / len(words_a | words_b)
                if overlap > 0.8:
                    return True
    return False
```

### 3. Knowledge Extraction

For notes categorized as `access_codes`, extract structured data:

```python
ACCESS_CODE_PATTERNS = {
    "wifi_ssid":    r"(?:wifi|ssid|network)[:\s]+([^\n]+)",
    "wifi_password": r"(?:wifi password|wpa|password)[:\s]+([^\n]+)",
    "alarm_code":   r"(?:alarm|security|disarm)[:\s#]*(\d{4,6})",
    "gate_code":    r"(?:gate|entry)[:\s#]*(\d{4,6})",
    "ip_address":   r"\b(192\.168\.\d{1,3}\.\d{1,3})\b",
    "username":     r"(?:user|username|login)[:\s]+([^\n]+)",
}
```

Extracted codes for project-matched notes get saved to:
`knowledge/projects/[project_name]/access_codes.md`

Format:
```markdown
# Access Codes — Topletz Residence
## Last updated: 2026-04-03 (extracted from Apple Notes)

| System | Credential | Value | Notes |
|--------|-----------|-------|-------|
| WiFi | SSID | TopletzHome | Trusted network |
| WiFi | Password | [extracted] | |
| Alarm | Disarm code | [extracted] | Qolsys IQ4 |
```

**Safety**: Never commit `access_codes.md` files to git. Add `knowledge/projects/*/access_codes.md` to `.gitignore`.

### 4. Cleanup Report

After indexing, generate a cleanup report via iMessage to Matt. Use the same iMessage sending mechanism as other tools (subprocess `osascript` or the existing notification channel):

```
Apple Notes Audit Complete — 147 notes scanned

Keep (85 notes):
  • 34 with site photos
  • 18 with access codes/passwords
  • 33 project references (Gates, Topletz, Hernaiz...)

Archive (31 notes):
  • 24 completed project notes → move to Previous Work
  • 7 learning notes → indexed in knowledge/learning/

Flag for Deletion (24 notes):
  • 8 empty/near-empty (<20 chars)
  • 11 stale drafts (>1 year old, no photos, no codes)
  • 5 duplicates

Needs Review (7 notes):
  • Might have codes or project refs — needs human look

Extracted: 18 sets of access codes saved to project folders.
Full index: data/notes_index.json
```

### 5. Scheduled Execution

Run via `launchd` on Bob (Mac Mini) daily at midnight:

```xml
<!-- ~/Library/LaunchAgents/com.symphony.notes-indexer.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.notes-indexer</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/ai-server/integrations/apple_notes/notes_indexer.py</string>
        <string>--index</string>
        <string>--report</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>0</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/notes-indexer.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/notes-indexer-error.log</string>
</dict>
</plist>
```

Install: `launchctl load ~/Library/LaunchAgents/com.symphony.notes-indexer.plist`

Also expose via the OpenClaw API for on-demand runs:
```python
# In openclaw/main.py
@app.post("/api/notes/index")
async def trigger_notes_index():
    """Trigger a notes index run on the Mac Mini host."""
    # Publish to a host-agent channel that Bob watches
    redis.publish("host:commands", json.dumps({"cmd": "notes_index"}))
    return {"status": "triggered"}
```

### 6. CLI Interface

```bash
# Run from the Mac Mini host (not Docker):
python3 integrations/apple_notes/notes_indexer.py --index
python3 integrations/apple_notes/notes_indexer.py --index --output data/notes_index.json
python3 integrations/apple_notes/notes_indexer.py --report          # send iMessage report
python3 integrations/apple_notes/notes_indexer.py --extract-codes   # save codes to project folders
python3 integrations/apple_notes/notes_indexer.py --folders         # just list folders and counts
python3 integrations/apple_notes/notes_indexer.py --search "WiFi"   # full-text search
python3 integrations/apple_notes/notes_indexer.py --dry-run         # index without saving or notifying
```

### 7. Integration with Auto-26 (System Shells)

After `access_codes.md` files are written for each project, the system shell generator (`tools/system_shell.py`) can read them:

```python
# In system_shell.py
codes_path = Path(f"knowledge/projects/{project_name}/access_codes.md")
if codes_path.exists():
    # Parse and inject into the "Access Codes & Credentials" section of the shell
    shell["access_codes"] = parse_access_codes_md(codes_path)
```

This means an installer gets one document — the system shell — with network addresses AND extracted access codes from Matt's field notes, automatically combined.

### 8. Safety Rules

- **Read-only**: never delete or modify Apple Notes. Only flag notes in the JSON index.
- **No auto-delete**: even flagged notes require explicit human confirmation (`--delete-flagged --confirm`)
- **No git commit of codes**: `access_codes.md` files are extracted secrets; ensure `.gitignore` covers them
- **Graceful AppleScript failures**: if Notes is not running or the script times out, log the error and continue — don't crash the indexer for one bad note

Use standard Python logging (not structlog — this runs on the host, not in Docker).
