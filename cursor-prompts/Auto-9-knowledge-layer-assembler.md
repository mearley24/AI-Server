# Auto-9: Knowledge Layer & SOW Assembler

## Context Files to Read First
- knowledge/proposal_library/README.md
- knowledge/proposal_library/proposal_master_template.md
- knowledge/proposal_library/scope_blocks/*.md
- knowledge/proposal_library/room_configs/*.md
- knowledge/sow-blocks/*.md
- openclaw/sow_assembler.py
- openclaw/preflight_check.py
- openclaw/proposal_checker.py

## Prompt

Complete the knowledge layer that powers automated proposal and SOW generation:

1. **SOW Assembler** (`openclaw/sow_assembler.py` — expand existing):
   - Takes a room list + selected packages as input (JSON config)
   - Pulls the correct scope blocks from `knowledge/sow-blocks/`
   - Assembles a complete SOW document with proper section ordering
   - Auto-fills project-specific variables (client name, address, room names)
   - Output: markdown SOW ready for PDF conversion
   - CLI: `python3 sow_assembler.py --config project_config.yaml --output sow.md`

2. **Preflight Checker** (`openclaw/preflight_check.py` — expand existing):
   - Validates a proposal/SOW against confirmed decisions
   - Cross-references equipment list against room configs (every room should have its expected devices)
   - Checks for common errors: missing VersaBox at TV locations, missing network drops, orphaned devices without a room
   - Validates pricing against known SKU costs from `knowledge/products/`
   - Output: pass/fail report with specific issues listed
   - CLI: `python3 preflight_check.py --proposal path/to/proposal.md --decisions path/to/decisions.md`

3. **Room Package Generator** (`knowledge/proposal_library/room_packages/`):
   - Standardize room packages: for each room type, define the base equipment list, optional upgrades, and pricing
   - Already have some (Bedroom, Kitchen, Entry_Hall, etc.) — complete the full set
   - Each package should list: required items, recommended add-ons, wire runs needed, estimated labor hours
   - Make packages composable: a "Theater" package can include the "Audio" sub-package + "Video" sub-package + "Lighting" sub-package

4. **Knowledge Scanner** (`knowledge-scanner/` — wire up existing):
   - `scanner.py` should crawl all `knowledge/` directories and build an index
   - `processor.py` should extract key facts from each file (product specs, compatibility notes, pricing)
   - `main.py` should produce a unified `knowledge/Bob_Master_Index.md` (already exists, auto-update it)
   - Run weekly via heartbeat

5. Wire the SOW assembler into Bob's email workflow: when a proposal is approved and deposit received, auto-generate the SOW and send it to the project's Linear ticket.

Use standard logging.
