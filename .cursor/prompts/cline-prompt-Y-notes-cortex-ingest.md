# Cline Prompt Y — Full Apple Notes Ingest to Cortex

## Objective
The current notes indexer (integrations/apple_notes/notes_indexer.py) has too-narrow category rules and misses the majority of valuable content. Notes about procedures, model numbers, wiring techniques, vendor info, proposal cheat sheets, client preferences, and troubleshooting steps all get dumped into "unknown" or "stale_draft" and flagged for deletion. Fix the indexer, then run a comprehensive ingest that feeds EVERYTHING useful into Cortex.

## Problem with Current Indexer
The CATEGORY_RULES dict only covers: access_codes, project_reference, photo_log, meeting_notes, learning, idea, stale_draft. That misses at LEAST:
- Work procedures / cheat sheets (step-by-step instructions for installs)
- Model numbers / product specs / part numbers
- Proposal language / scope templates / pricing notes
- Client preferences and decisions
- Troubleshooting notes (problem/solution pairs)
- Vendor/supplier contacts and account info
- Wiring diagrams / cable schedules / rack layouts
- System configuration notes (Control4, Lutron, networking)
- Business process notes (scheduling, inventory, truck stock)

## Steps

### 1. Expand CATEGORY_RULES in notes_indexer.py
Replace the existing CATEGORY_RULES dict with this expanded version:

```python
CATEGORY_RULES: dict[str, list[str]] = {
    "access_codes": [
        r"wifi|ssid|password|passcode|alarm code|gate code|lock code|pin:|code:",
        r"\b\d{4,6}\b",
        r"\b192\.168\.\d+\.\d+\b",
        r"username|login|credential",
    ],
    "project_reference": [],  # filled from project keywords
    "photo_log": [
        r"photo|picture|image|site photo|job site|install photo",
    ],
    "meeting_notes": [
        r"meeting|call|discussed|action item|follow up|next steps|walkthrough|site visit",
    ],
    "learning": [
        r"certification|exam|study|cedia|c4 certification|control4 training|training|notes on|how to",
    ],
    "idea": [
        r"idea:|concept:|what if|could we|potential|brainstorm",
    ],
    "work_procedure": [
        r"step\s*\d|step\s*one|step\s*two|how\s*to|procedure|instructions|cheat\s*sheet|process|checklist",
        r"first.*then.*next|install\s*steps|setup\s*guide|configuration\s*steps",
        r"rough[\s-]*in|trim[\s-]*out|commissioning|programming\s*steps",
        r"mount.*steps|wire.*steps|run\s*cat6|terminate|punch\s*down",
    ],
    "product_reference": [
        r"model\s*number|part\s*number|sku|specs|specification|compatibility",
        r"pricing|msrp|cost|wholesale|dealer\s*price|map\s*price",
        r"\b[A-Z]{2,4}[\-\.]\d{3,6}\b",
        r"araknis|triad|control4|lutron|sonos|luma|qolsys|episode|snap\s*one",
        r"an[\-]?\d{3}|ts[\-]?ams|ea[\-]?\d|c4[\-]",
    ],
    "proposal_template": [
        r"proposal|scope\s*of\s*work|agreement|quote|estimate|bid",
        r"scope\s*block|deliverable|exclusion|inclusion|payment\s*schedule",
        r"change\s*order|addendum|revision|terms|warranty",
    ],
    "client_preference": [
        r"client\s*wants|client\s*prefers|they\s*want|decided\s*on|chose|selected",
        r"homeowner|client\s*note|preference|approved|rejected|feedback",
        r"wife\s*wants|husband\s*wants|they\s*like|don.t\s*like",
    ],
    "install_notes": [
        r"installed|ran\s*wire|mounted|pulled\s*cable|terminated|field\s*note",
        r"rough\s*in|trim\s*out|punch\s*down|rack\s*build|cable\s*pull",
        r"on[\s-]*site|job\s*site|attic|crawl\s*space|basement|garage|rack",
        r"conduit|low[\s-]*voltage|junction\s*box|back\s*box|mud\s*ring",
    ],
    "troubleshooting": [
        r"fix|fixed|solved|issue\s*was|workaround|debug|troubleshoot",
        r"problem|error|not\s*working|failed|broken|reset|reboot",
        r"root\s*cause|solution|resolved|firmware|update|flash",
    ],
    "vendor_contact": [
        r"rep\b|supplier|vendor|distributor|account\s*number|dealer",
        r"sales\s*rep|territory|order\s*from|lead\s*time|eta",
    ],
    "system_config": [
        r"vlan|subnet|ip\s*address|switch\s*port|dhcp|dns",
        r"composer|programming|driver|zigbee|zwave|z-wave",
        r"scene|keypad|button|macro|event|trigger|agent",
        r"audio\s*matrix|amp|amplifier|receiver|avr",
        r"network\s*config|firewall|port\s*forward|nat",
    ],
    "wiring_reference": [
        r"cable\s*schedule|cable\s*label|wire\s*map|wire\s*run",
        r"cat6|cat5|coax|rg6|hdmi|fiber|speaker\s*wire|14[\-/]2|16[\-/]2",
        r"home\s*run|distribution|patch\s*panel|rack\s*layout",
    ],
    "business_operations": [
        r"schedule|calendar|inventory|truck\s*stock|order|purchase",
        r"invoice|payment|profit|margin|labor|cost\s*tracking",
        r"process\s*improvement|workflow|efficiency",
    ],
    "stale_draft": [],
}
```

### 2. Update Classification Priority
In the keyword_category() function, update the priority list to check in this order (most specific first):

```python
priority = [
    "access_codes",
    "system_config",
    "wiring_reference",
    "work_procedure",
    "product_reference",
    "proposal_template",
    "troubleshooting",
    "client_preference",
    "install_notes",
    "vendor_contact",
    "business_operations",
    "photo_log",
    "meeting_notes",
    "learning",
    "idea",
    "project_reference",
]
```

### 3. Fix the "stale_draft" Aggressive Deletion
In suggest_action(), change the logic so notes are NOT flagged for deletion just because they are short or old. Many valuable notes (like a quick "Araknis AN-520 default IP: 192.168.1.1") are under 40 chars but extremely useful. New rules:
- Only flag_for_deletion if: body is completely empty AND no attachments AND title is "New Note" or blank
- Everything else: at minimum "archive" or "needs_review", never auto-delete
- Notes with ANY category match other than "unknown" or "stale_draft": always "keep"

### 4. Expand Cortex Categories
Edit cortex/memory.py — add to the CATEGORIES set:
```python
"system_shell",
"access_codes",
"work_procedure",
"product_reference",
"proposal_template",
"client_preference",
"install_notes",
"troubleshooting",
"vendor_contact",
"training",
"business_operations",
"system_config",
"wiring_reference",
```

### 5. Write the Full Ingest Script
Create scripts/notes_to_cortex.py that:

a) Runs the updated indexer: subprocess call to notes_indexer.py --index --no-llm
b) Reads data/notes_index.json
c) For EVERY note where action is NOT "flag_for_deletion":
   - Map the indexer category to a Cortex category
   - POST to http://localhost:8102/remember with the full note body
   - Include metadata: note_id, folder, created_at, modified_at, attachment_count
   - Tag with: client names, brand names, service types, locations found in content
d) Track what was ingested and what was skipped

Tag extraction patterns:
```python
CLIENT_NAMES = ["topletz", "gates", "hernaiz", "kelly", "hukill", "timber ridge"]
BRAND_NAMES = ["control4", "lutron", "sonos", "triad", "araknis", "luma", "qolsys", 
               "samsung", "sony", "lg", "episode", "snap one", "wirepath", "binary",
               "strong", "middle atlantic", "panamax", "furman"]
SERVICE_TYPES = ["prewire", "networking", "audio", "lighting", "security", "shades", 
                 "theater", "tv mount", "surveillance", "automation", "climate"]
LOCATIONS = ["vail", "beaver creek", "edwards", "avon", "eagle", "singletree", 
             "cordillera", "minturn", "arrowhead", "bachelor gulch"]
```

### 6. Build Structured Knowledge Files
In addition to Cortex memory, also write organized files:

a) knowledge/procedures/ — one .md file per work_procedure note, cleaned up
b) knowledge/product_reference.md — aggregated table of all product_reference notes
c) knowledge/troubleshooting.md — aggregated problem/solution pairs
d) Update knowledge/projects/{client}/ with any new system_config or wiring_reference data

### 7. Run and Report
After the full ingest:

a) Print stats: total notes, ingested count, by category, skipped count
b) Write data/notes_ingest_report.md with full breakdown
c) Query Cortex: curl http://localhost:8102/health to verify memories grew

### 8. Important
- Do NOT skip notes just because they are short. A 30-char note with a model number is valuable.
- Do NOT skip notes just because they are old. Procedures and product specs don't expire.
- Do NOT skip notes in unfamiliar folders. Scan EVERY folder.
- The goal is to capture EVERYTHING that could possibly be useful for the smart home business, proposal generation, job execution, or training the future Symphony Smart Home Builders AI.

Commit and push when done.
