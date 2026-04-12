# Cline Prompt Y — Full Apple Notes Ingest to Cortex

## Objective
Scan every Apple Notes folder. Extract ALL useful content — not just photos. Categorize, dedupe, and feed everything into Cortex memory via the remember() API. This includes system shells, access codes, work procedures, model numbers, proposal cheat sheets, troubleshooting steps, client preferences, and installation notes.

## Context
- Cortex runs on port 8102 with a POST /remember endpoint
- Cortex memory.py accepts: category, title, content, source, confidence, importance, tags, metadata, subcategory
- Valid categories: trading_rule, strategy_idea, strategy_performance, market_pattern, whale_intel, x_intel, infrastructure, edge, meta_learning, external_research
- We need to ADD new categories for smart home business content (see Step 2)
- The notes indexer at integrations/apple_notes/notes_indexer.py already has category detection rules
- Notes are accessed via JXA/osascript (macOS only, runs on Bob)

## Steps

### 1. Run Full Notes Export
Run the notes indexer first to get a complete inventory:
```
python3 integrations/apple_notes/notes_indexer.py --index
```
This creates data/notes_index.json. Read the output to understand what folders exist and how many notes are in each.

### 2. Expand Cortex Categories
Edit cortex/memory.py and add these categories to the CATEGORIES set:
```python
CATEGORIES = {
    # existing
    "trading_rule",
    "strategy_idea",
    "strategy_performance",
    "market_pattern",
    "whale_intel",
    "x_intel",
    "infrastructure",
    "edge",
    "meta_learning",
    "external_research",
    # new — smart home business
    "system_shell",        # VLAN configs, device registries, cable schedules per client
    "access_codes",        # WiFi, alarm, gate codes, IP addresses per client
    "work_procedure",      # Step-by-step install/config procedures, cheat sheets
    "product_reference",   # Model numbers, specs, compatibility notes, pricing
    "proposal_template",   # Proposal language, scope blocks, pricing formulas
    "client_preference",   # Client-specific preferences, decisions, communication style
    "install_notes",       # Job site notes, photos, field conditions, gotchas
    "troubleshooting",     # Problem/solution pairs, debug steps, known issues
    "vendor_contact",      # Supplier contacts, rep info, account numbers
    "training",            # Certifications, study notes, Control4/Lutron/CEDIA material
    "business_operations", # Scheduling, inventory, truck stock, process improvements
}
```

### 3. Write the Ingest Script
Create scripts/notes_to_cortex.py that:

a) Reads data/notes_index.json (from Step 1)

b) For each note, categorizes it using these rules (in priority order):

| If note contains... | Category | Subcategory | Importance |
|---|---|---|---|
| VLAN, subnet, 10.x.x.x, device registry, switch port | system_shell | {client_name} | 9 |
| wifi, password, alarm code, gate code, pin, ssid | access_codes | {client_name} | 10 |
| step 1, step 2, how to, procedure, instructions, process | work_procedure | {topic} | 8 |
| model, part number, SKU, specs, compatibility, pricing | product_reference | {brand} | 7 |
| proposal, scope, agreement, quote, pricing template | proposal_template | {type} | 8 |
| client preference, likes, dislikes, decided on, chose | client_preference | {client_name} | 7 |
| job site, installed, ran wire, mounted, field note | install_notes | {project} | 6 |
| fix, solved, issue was, workaround, debug, troubleshoot | troubleshooting | {system} | 8 |
| rep, supplier, vendor, account number, distributor | vendor_contact | {vendor} | 6 |
| certification, exam, training, study, CEDIA, C4 | training | {topic} | 5 |
| schedule, inventory, truck, process, business | business_operations | {topic} | 5 |

c) Extracts the client name or project name from the note title or folder when possible

d) Skips notes that are:
  - Empty or under 20 characters
  - Purely photo attachments with no text (those are handled by Prompt X)
  - Default "New Note" titles with no content
  - Duplicate content (hash the content, skip if already ingested)

e) For each valid note, POSTs to Cortex:
```python
import httpx

CORTEX_URL = "http://localhost:8102"

def ingest_note(note):
    category, subcategory, importance = categorize(note)
    
    payload = {
        "category": category,
        "subcategory": subcategory,
        "title": note["title"],
        "content": note["body"],
        "source": f"apple_notes/{note['folder']}",
        "confidence": 0.8,  # human-written notes are high confidence
        "importance": importance,
        "tags": extract_tags(note),
        "metadata": {
            "note_id": note["note_id"],
            "folder": note["folder"],
            "created_at": note["created_at"],
            "modified_at": note["modified_at"],
            "attachment_count": note.get("attachment_count", 0),
            "ingested_from": "notes_to_cortex.py"
        }
    }
    
    resp = httpx.post(f"{CORTEX_URL}/remember", json=payload, timeout=5.0)
    return resp.status_code == 200
```

f) Tag extraction — pull tags from content:
  - Client names (Topletz, Gates, Hernaiz, Kelly, etc.)
  - Brand names (Control4, Lutron, Sonos, Triad, Araknis, Luma, Qolsys, Samsung)
  - Service types (prewire, networking, audio, lighting, security, shades, theater)
  - Location markers (Vail, Beaver Creek, Edwards, Avon, Eagle, Singletree, Cordillera)

### 4. Build System Shells from Notes
For any notes that contain network configs, device lists, or cable schedules that do NOT already have a system shell in knowledge/projects/:

a) Extract the structured data into the standard system shell format (matching the existing format in knowledge/projects/topletz/system_shell.md)

b) Create a new directory: knowledge/projects/{client_slug}/

c) Write system_shell.md and system_shell_data.json

d) Also POST to Cortex as category "system_shell"

### 5. Build Procedure Library
For notes that contain step-by-step procedures, cheat sheets, or how-to content:

a) Clean up the formatting (Notes exports can be messy)

b) Save to knowledge/procedures/{slug}.md in a standard format:
```markdown
# {Procedure Title}
## When to Use
{context}
## Steps
1. ...
2. ...
## Notes
{gotchas, tips}
## Related
{links to other procedures}
```

c) POST each to Cortex as category "work_procedure"

### 6. Build Product Reference
For notes with model numbers, specs, or pricing:

a) Extract into a structured format

b) Append to knowledge/product_reference.md (create if not exists):
```markdown
# Product Reference Library

## Control4
| Model | Description | Use Case | Notes |
|---|---|---|---|

## Araknis Networking
| Model | Description | Use Case | Notes |
|---|---|---|---|

## Triad Audio
...
```

c) POST each product entry to Cortex as category "product_reference"

### 7. Validation and Report
After all ingestion:

a) Query Cortex to verify: curl http://localhost:8102/api/stats (or whatever the stats endpoint is)

b) Write data/notes_ingest_report.md:
```markdown
# Notes Ingest Report — {date}

## Summary
- Total notes scanned: X
- Notes ingested to Cortex: X
- Skipped (empty/duplicate): X
- Categories breakdown:
  - system_shell: X
  - access_codes: X
  - work_procedure: X
  - product_reference: X
  - ...

## New System Shells Created
- {client}: knowledge/projects/{slug}/

## Procedures Extracted
- {procedure title}: knowledge/procedures/{slug}.md

## Product References Added
- X entries added to knowledge/product_reference.md

## Notes Flagged for Manual Review
- {note title}: {reason} (e.g., "contains potential PII", "unclear categorization")
```

### 8. Security Note
- Access codes and passwords should be ingested with importance=10 and tagged with "sensitive"
- Do NOT log password values to stdout or the report
- System shells with IP addresses are fine to log (internal network only)

Commit and push when done.
