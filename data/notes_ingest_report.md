# Notes Ingest Report — 2026-04-12

## Summary

| Source | Total | Ingested | Skipped (empty) | Skipped (dup) | Failed |
|---|---|---|---|---|---|
| Apple Notes (notes_index.json) | 0 | 0 | 0 | 0 | 0 |
| Product files (knowledge/products/) | 20 | 20 | — | 0 | 0 |
| System shells (knowledge/projects/) | 4 | 4 | — | 0 | 0 |

## System Shells Ingested

- `gates`: `knowledge/projects/gates/system_shell.md`
- `hernaiz`: `knowledge/projects/hernaiz/system_shell.md`
- `kelly`: `knowledge/projects/kelly/system_shell.md`
- `topletz`: `knowledge/projects/topletz/system_shell.md`

## Procedures Extracted

*(Apple Notes JXA unavailable — no procedures extracted this run)*

Procedure library scaffolded at `knowledge/procedures/`. Procedures will be extracted on next run when Notes.app is accessible.

## Product Reference

- `20` entries compiled in `knowledge/product_reference.md`
- `20` product records ingested to Cortex

## Apple Notes Status

The Apple Notes JXA interface (`osascript`) timed out during this run.
This is a known issue when Notes.app has a large iCloud library syncing.

**To re-run when Notes is accessible:**
```zsh
# Open Notes.app and wait for iCloud sync to complete, then:
python3 integrations/apple_notes/notes_indexer.py --index --no-llm
python3 scripts/notes_to_cortex.py
```

The script is idempotent — duplicate content is skipped via SHA-256 hashing.

## Notes Flagged for Manual Review

*(No notes available this run — will populate once Notes.app is accessible)*
