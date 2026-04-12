# Notes Ingest Report — 2026-04-12

## Summary

**Total ingested to Cortex this run: 67** (0 failed)

| Source | Files | Ingested | Skipped (dup/empty) | Failed |
|---|---|---|---|---|
| Apple Notes | 0 | 0 | 0 | 0 |
| Products (knowledge/products/) | 20 | 0 | 20 | 0 |
| System shells (knowledge/projects/) | 4 | 0 | 4 | 0 |
| Procedures (knowledge/procedures/) | 3 | 3 | 0 | 0 |
| Operations Runbook | 1 | 1 | 0 | 0 |
| Hardware playbooks (knowledge/hardware/) | 3 | 3 | 0 | 0 |
| Network docs (knowledge/network/) | 2 | 2 | 0 | 0 |
| SOW blocks (knowledge/sow-blocks/) | 22 | 22 | 0 | 0 |
| Proposal library (knowledge/proposal_library/) | 26 | 26 | 0 | 0 |
| Incidents (knowledge/incidents/) | 1 | 1 | 0 | 0 |
| Reports (knowledge/reports/) | 3 | 3 | 0 | 0 |
| Cortex learnings | 1 | 1 | 0 | 0 |
| Agent runbooks (knowledge/agents/) | 2 | 2 | 0 | 0 |
| Equipment rollups (knowledge/proposals/) | 3 | 3 | 0 | 0 |

## Procedures Extracted

- Symphony IP Addressing Standard
- Mount Clearance Validation
- TV & Mount Recommendations Workflow

Procedure library: `knowledge/procedures/`

## Product Reference

- `20` entries in `knowledge/product_reference.md`
- `0` new product records ingested to Cortex

## Knowledge Base Entries Ingested

**Procedures (knowledge/procedures/)** — 3 entries:
  - Symphony IP Addressing Standard
  - Mount Clearance Validation
  - TV & Mount Recommendations Workflow
**Operations Runbook** — 1 entries:
  - Symphony Smart Homes — Operations Runbook
**Hardware playbooks (knowledge/hardware/)** — 3 entries:
  - Control4 TV Driver Compatibility Reference
  - Mount Clearance Validation Checklist
  - TV & Mount Recommendations — Operations Playbook
**Network docs (knowledge/network/)** — 2 entries:
  - Device Count Analysis — Proposal Rollups
  - Symphony Standard IP Addressing
**SOW blocks (knowledge/sow-blocks/)** — 22 entries:
  - Client Responsibilities
  - Commissioning
  - Control4 Automation
  - Control4 Lighting
  - Design Intent
  - *(+17 more)*
**Proposal library (knowledge/proposal_library/)** — 26 entries:
  - Assumptions & Exclusions Library
  - Symphony Smart Homes — Proposal Master Template
  - Room Config: Bathroom
  - Room Config: Bedroom (Secondary / Guest)
  - Room Config: Dining Room
  - *(+21 more)*
**Incidents (knowledge/incidents/)** — 1 entries:
  - Incident Report: Docker Crash Cascade
**Reports (knowledge/reports/)** — 3 entries:
  - Proposal Intelligence: Kelly
  - Room Archetype Packages
  - SKU Frequency Report
**Cortex learnings** — 1 entries:
  - Symphony Cortex — Learnings
**Agent runbooks (knowledge/agents/)** — 2 entries:
  - Learner roadmap — Symphony AI Server
  - Ultra Runbook — Session Protocol
**Equipment rollups (knowledge/proposals/)** — 3 entries:
  - Gates Equipment Roll-Up
  - Hernaiz Equipment Roll-Up
  - Hernaiz vs Gates Roll-Up Comparison

## Apple Notes JXA Status

The Apple Notes JXA interface (`osascript`) timed out during this run.
This is expected when Notes.app has a large iCloud library syncing.

**To re-run when Notes is accessible:**
```zsh
python3 integrations/apple_notes/notes_indexer.py --index --no-llm
python3 scripts/notes_to_cortex.py
```

The script is idempotent — duplicate content is skipped via SHA-256 hashing.
Running again when Notes is available will add note content without re-ingesting
anything already in Cortex.

## Notes Flagged for Manual Review

*(No Apple Notes available this run)*
