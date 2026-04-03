# Auto-16: Proposal Engine — End-to-End Automation

## Context Files to Read First
- proposals/proposal_engine.py
- proposals/pricing_calculator.py
- proposals/scope_builder.py
- proposals/api_server.py
- proposals/email_templates/*.md
- proposals/proposal_templates/*.md
- integrations/dtools/proposal_workflow.py
- openclaw/proposal_checker.py
- knowledge/proposal_library/

## Prompt

Wire the proposal engine into a complete pipeline from lead intake to signed agreement:

1. **Intake** — when Bob receives a consultation request (via email, voice, or iMessage):
   - Create a new project in the proposal pipeline
   - Auto-generate a room-by-room scope based on the walkthrough notes (use LLM to parse natural language notes into structured room configs)
   - Pull matching room packages from `knowledge/proposal_library/room_packages/`

2. **Pricing** (`proposals/pricing_calculator.py` — expand):
   - Auto-calculate equipment costs from SKU database (`knowledge/products/`)
   - Apply standard markup (verify against D-Tools pricing)
   - Labor estimate based on room count and complexity
   - Generate three tiers: Essential (base), Recommended (with upgrades), Premium (everything)

3. **Generation** (`proposals/proposal_engine.py` — expand):
   - Build proposal from template + room configs + pricing
   - Always include: VersaBox at every TV location, network infrastructure, support agreement
   - Hyperlink every product name to manufacturer page
   - File naming: "Symphony Smart Homes — [Address] — Proposal.pdf"
   - Version tracking internal only (client sees "Updated Proposal")

4. **Review** (`openclaw/proposal_checker.py` — expand):
   - Auto-run preflight check before any proposal goes out
   - Verify: all rooms have lighting, all TVs have VersaBox, network infrastructure sized correctly
   - Verify: pricing matches Samsung.com for TVs, D-Tools for equipment
   - Flag any issues, block sending until resolved

5. **Follow-up** (wire email templates):
   - Day 0: Proposal cover email (auto-send after preflight passes)
   - Day 3: First follow-up
   - Day 7: Second follow-up with value-add content
   - Day 14: Final follow-up
   - All follow-ups via Bob's email system (Zoho), logged in Linear

6. **D-Tools sync** — when proposal is accepted:
   - Auto-create project in D-Tools via `integrations/dtools/proposal_workflow.py`
   - Import equipment list
   - Generate SOW via sow_assembler.py
   - Create Linear project from template (22 issues)

Use standard logging.
