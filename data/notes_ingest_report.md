# Notes Ingest Report — 2026-04-15

## Summary

**Total ingested to Cortex this run: 1** (0 failed)

| Source | Files | Ingested | Skipped (dup/empty) | Failed |
|---|---|---|---|---|
| Apple Notes | 2 | 1 | 1 | 0 |
| Products (knowledge/products/) | 20 | 0 | 20 | 0 |
| System shells (knowledge/projects/) | 4 | 0 | 4 | 0 |
| Procedures (knowledge/procedures/) | 3 | 0 | 3 | 0 |
| Operations Runbook | 1 | 0 | 1 | 0 |
| Hardware playbooks (knowledge/hardware/) | 3 | 0 | 3 | 0 |
| Network docs (knowledge/network/) | 2 | 0 | 2 | 0 |
| SOW blocks (knowledge/sow-blocks/) | 22 | 0 | 22 | 0 |
| Proposal library (knowledge/proposal_library/) | 26 | 0 | 26 | 0 |
| Incidents (knowledge/incidents/) | 1 | 0 | 1 | 0 |
| Reports (knowledge/reports/) | 3 | 0 | 3 | 0 |
| Cortex learnings | 1 | 0 | 1 | 0 |
| Agent runbooks (knowledge/agents/) | 2 | 0 | 2 | 0 |
| Equipment rollups (knowledge/proposals/) | 3 | 0 | 3 | 0 |

## Apple Notes — Categories Breakdown

- **install_notes**: 1

## Procedures Extracted

*(none new — all already in Cortex)*

Procedure library: `knowledge/procedures/`

## Product Reference

- `20` entries in `knowledge/product_reference.md`
- `0` new product records ingested to Cortex

## Knowledge Base Entries Ingested


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
