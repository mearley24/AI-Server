# Proposal Generation Workflow

**Symphony Smart Homes — Phase 2**  
Module: Proposals  
Location: `~/AI-Server/phase2/proposals/`  
Last Updated: 2026-02-27

---

## Overview

This module is Bob the Conductor's proposal generation engine. It converts client 
requirements — rooms, systems, budget, tier — into professional proposals, complete 
D-Tools Cloud project packages, and client-ready email communications.

The proposal workflow sits at the center of Symphony Smart Homes' sales process:

```
Client Conversation
       │
       ▼
Bob (OpenClaw) ──→ @proposals agent
                        │
                        ▼
               ScopeBuilder + ProposalEngine
                        │
               ┌────────┴─────────┐
               ▼                  ▼
         Proposal JSON        D-Tools CSV
               │                  │
               ▼                  ▼
      Email Templates     DToolsCloudClient
               │                  │
               ▼                  ▼
        Client Email        D-Tools Cloud
                           portal.d-tools.com
```

---

## Files in This Module

### Python Modules

| File | Purpose |
|------|---------|
| `proposal_engine.py` | Main proposal generation engine — orchestrates all components |
| `dtool_cloud_client.py` | D-Tools Cloud integration via HARPA browser automation bridge |
| `scope_builder.py` | Room-by-room scope of work builder with dependency detection |
| `pricing_calculator.py` | Labor rates, markups, tax, payment schedules, margin analysis |

### Templates

| File | Type | Use |
|------|------|-----|
| `proposal_templates/residential_av.md` | Proposal | Home theater, distributed audio, TV mounting |
| `proposal_templates/full_automation.md` | Proposal | Lighting, shades, HVAC, security, AV, network |
| `proposal_templates/retrofit.md` | Proposal | Upgrading existing systems |
| `proposal_templates/commercial.md` | Proposal | Conference rooms, digital signage, background music |
| `proposal_templates/maintenance_agreement.md` | Service | Monthly/annual service plans |

### Email Templates

| File | Purpose | Trigger |
|------|---------|---------|
| `email_templates/proposal_cover.md` | Send with new proposal | Proposal generated |
| `email_templates/follow_up_3day.md` | 3-day follow-up | No reply after 3 business days |
| `email_templates/follow_up_7day.md` | 7-day follow-up | No reply after 7 business days |
| `email_templates/revision_notification.md` | Proposal updated | proposal_engine.revise() called |
| `email_templates/acceptance_confirmation.md` | Contract executed | Contract signed + deposit received |

### OpenClaw

| File | Purpose |
|------|---------|
| `openclaw_proposal_agent.json` | OpenClaw agent definition — add to `setup/openclaw/openclaw.json` |

---

## Quick Start

### 1. Generate a Proposal (Python)

```python
from proposal_engine import ProposalEngine, ProjectRequirements, ClientInfo, RoomRequirement, ProposalTemplate, ClientTier

engine = ProposalEngine()

requirements = ProjectRequirements(
    client=ClientInfo(
        name="Johnson",
        address="1234 Maple Drive",
        city="Denver",
        state="CO",
        zip_code="80203",
        email="johnson@example.com",
    ),
    template=ProposalTemplate.FULL_AUTOMATION,
    tier=ClientTier.BETTER,
    rooms=[
        RoomRequirement("Living Room"),
        RoomRequirement("Master Bedroom"),
        RoomRequirement("Kitchen"),
        RoomRequirement("Theater / Media Room", ClientTier.BEST),
        RoomRequirement("Outdoor Patio"),
        RoomRequirement("Entry"),
        RoomRequirement("Mechanical Room"),
    ],
    budget_high=120_000,
    is_new_construction=True,
)

proposal = engine.generate(requirements)
engine.save(proposal, Path("~/AI-Server/proposals/drafts").expanduser())
```

### 2. Build a Scope Package

```python
from scope_builder import ScopeBuilder, ClientTier

builder = ScopeBuilder()
scope = builder.build(
    rooms=[
        {"name": "Living Room", "tier": "better"},
        {"name": "Master Bedroom", "tier": "better"},
        {"name": "Theater / Media Room", "tier": "best"},
        {"name": "Mechanical Room", "tier": "better"},
    ],
    tier=ClientTier.BETTER,
    systems=["lighting_shades", "audio_video", "networking", "control_automation"],
    budget=95_000,
)

print(f"{scope.total_rooms} rooms, {scope.total_labor_hours}h labor")
for dep in scope.detected_dependencies:
    print(f"Dependency: {dep.source_system} → {dep.required_system}: {dep.reason}")
```

### 3. Create D-Tools Project

```python
import asyncio
from dtool_cloud_client import get_dtools_client

async def create_project():
    client = get_dtools_client()
    
    # Check session first
    if not await client.check_session():
        print("D-Tools session expired — re-login required on Maestro/Stagehand")
        return
    
    project_id = await client.create_project(
        client_name="Johnson",
        project_name="Johnson Residence",
        address="1234 Maple Drive, Denver CO 80203",
    )
    print(f"Project created: {project_id}")

asyncio.run(create_project())
```

### 4. Create Project from Proposal (Full Workflow)

```python
import asyncio
import json
from proposal_engine import ProposalEngine, ProjectRequirements  # ... (see above)
from dtool_cloud_client import get_dtools_client

async def full_workflow():
    # 1. Generate proposal
    engine = ProposalEngine()
    proposal = engine.generate(requirements)  # requirements from above
    
    # 2. Check coverage gaps
    errors = [g for g in proposal.coverage_gaps if not g.passed and g.severity == "error"]
    if errors:
        print(f"⚠ {len(errors)} coverage gap errors — resolve before proceeding")
        for e in errors:
            print(f"  [{e.check_id}]: {e.details}")
        return
    
    # 3. Create D-Tools project from proposal
    dtclient = get_dtools_client()
    proposal_dict = json.loads(engine.to_json(proposal))
    project_id, import_result = await dtclient.create_project_from_proposal(proposal_dict)
    
    print(f"D-Tools project: {project_id}")
    print(f"Equipment imported: {import_result.items_imported}")

asyncio.run(full_workflow())
```

### 5. Calculate Pricing

```python
from pricing_calculator import PricingCalculator, MarkupTier, SkillLevel, DiscountType

calc = PricingCalculator()

result = calc.calculate(
    equipment_items=equipment_list,  # from proposal.equipment_list
    labor_hours_by_phase={
        "Pre-Wire":     {SkillLevel.TECH: 24.0, SkillLevel.LEAD_TECH: 8.0},
        "Trim":         {SkillLevel.TECH: 20.0, SkillLevel.LEAD_TECH: 10.0},
        "Programming":  {SkillLevel.PROGRAMMER: 28.0},
        "Commissioning":{SkillLevel.TECH: 4.0,  SkillLevel.LEAD_TECH: 4.0},
    },
    markup_tier=MarkupTier.RESIDENTIAL_STANDARD,
    state="CO",
    discounts=[DiscountType.BUNDLE],
    system_count=5,
)

print(calc.format_summary(result))
```

---

## Proposal Templates

### Template Selection Guide

| Template | Use When |
|----------|---------|
| `basic_av` | Client wants AV only — no Control4, no Lutron, no automation |
| `full_automation` | Full smart home — lighting, AV, security, networking, Control4 |
| `retrofit` | Existing home with systems to assess, retain, and upgrade |
| `commercial` | Office, conference rooms, retail, commercial spaces |
| `maintenance_agreement` | Post-installation service plan |

### Good / Better / Best Tier Guide

| Tier | Philosophy |
|------|-----------|
| **Good** | Core functionality; meets minimum Symphony Smart Homes standard |
| **Better** | Enhanced experience; recommended for most clients |
| **Best** | Premium specification; budget is secondary to experience |

### Proposal Structure (10 Sections)

Every Symphony Smart Homes proposal follows this structure:

| # | Section | Content |
|---|---------|---------|
| 1 | Cover Page | Client info, date, version |
| 2 | Executive Summary | Lifestyle vision — no product names |
| 3 | Scope of Work | By system (3.1 Lighting, 3.2 AV, etc.) |
| 4 | Assumptions | What the proposal is based on |
| 5 | Exclusions | What is NOT included |
| 6 | Equipment List | Model numbers, quantities, D-Tools prices |
| 7 | Labor & Timeline | Phases, durations, hours |
| 8 | Pricing Summary | Equipment + labor + programming totals |
| 9 | Terms & Conditions | Payment, warranty, change orders |
| 10 | Optional Upgrades | Good/Better/Best upsells |

---

## D-Tools Integration

### Architecture

```
Bob (OpenClaw)
      │
      ▼
DToolsCloudClient
      │
      ▼
HARPABridge (HTTP → port 3000)
      │
      ├─→ Maestro (192.168.1.20) — Primary HARPA node
      └─→ Stagehand (192.168.1.30) — Fallback HARPA node
              │
              ▼
        HARPA AI Chrome Extension
              │
              ▼
        D-Tools Cloud (portal.d-tools.com)
        Authenticated browser session
```

**Important:** D-Tools Cloud has no public REST API. All automation routes through 
HARPA browser automation. The Chrome session must be logged in on Maestro or Stagehand.

### D-Tools Commands Available

| Command | What It Does |
|---------|-------------|
| `create_project` | Creates a new project in D-Tools Cloud |
| `import_equipment_csv` | Imports equipment CSV into a project |
| `get_project_status` | Gets current phase and status |
| `export_proposal` | Exports proposal PDF (returns download URL) |
| `update_project_phase` | Advances project to next phase |
| `search_projects` | Searches by client or project name |

### D-Tools Project Phases

```
Proposal → Contract → Work Order → Installation → Punch List → Invoicing → Closed
```

### Equipment CSV Format

```csv
Model,Manufacturer,Category,Quantity,Room,Notes
"Control4 CORE 3","Control4","Control",1,"Mechanical Room","Primary controller"
"AN-310-RT","Araknis","Networking",1,"Mechanical Room","Managed router"
```

**Valid Categories (exact match required):**
`Audio`, `Video`, `Lighting`, `Networking`, `Control`, `Security`, `Climate`, `Power`, `Cabling`, `Rack`, `Labor`

---

## Coverage Gap Checks

The ProposalEngine runs 10 mandatory checks before marking any proposal deliverable.

| Check ID | What It Verifies | Severity |
|----------|-----------------|---------|
| `every_ip_device_has_ethernet_drop` | Cat6 cabling present for IP devices | Error |
| `amp_channel_count_matches_speaker_count` | Amplification sized correctly | Error |
| `theater_has_blackout_shades` | Theater rooms have blackout shades | Error |
| `network_rack_has_ups` | UPS present in mechanical room | Error |
| `programming_hours_budgeted` | Control4 programming hours in scope | Warning |
| `all_equipment_in_dtools_has_room_assignment` | No unassigned equipment | Error |
| `outdoor_devices_have_ip_ratings` | Outdoor gear is weatherproof | Warning |
| `all_fixtures_are_dimmer_compatible` | Dimmer-compatible fixtures | Warning |
| `keypad_locations_on_floor_plan` | Advisory only | Warning |
| `control4_drivers_verified_for_third_party_devices` | Advisory only | Warning |

**Error-level gaps: Do not deliver the proposal. Fix first.**

---

## Pricing Engine

### Markup Tiers

| Tier | Equipment Markup | Use Case |
|------|-----------------|---------|
| `residential_standard` | 35% | Standard residential projects |
| `residential_high_end` | 45% | Best-tier premium clients |
| `commercial` | 30% | Commercial/office projects |

### Labor Rates (per hour)

| Skill Level | Standard | High-End | Commercial |
|-------------|----------|----------|------------|
| Tech | $95 | $110 | $100 |
| Lead Tech | $125 | $145 | $135 |
| Programmer | $175 | $200 | $185 |

### Discount Types

| Type | Percentage | Qualifies When |
|------|-----------|---------------|
| `bundle` | 5% | 3+ systems (auto-applied) |
| `loyalty` | 3% | Returning client |
| `referral` | 2.5% | Referred by existing client |
| `builder` | 7% | Builder/GC relationship |
| `seasonal` | 4% | Seasonal promotion |

**Maximum combined discount: 12%**

---

## OpenClaw Agent Setup

Add the proposals agent to `setup/openclaw/openclaw.json`:

```bash
# Option 1: Copy the agent JSON block from openclaw_proposal_agent.json
# and add it to the "agents" array in setup/openclaw/openclaw.json

# Option 2: Validate the config after adding
npx strip-json-comments setup/openclaw/openclaw.json | python3 -m json.tool

# Restart OpenClaw to load the new agent
openclaw restart
# or:
docker compose restart openclaw
```

**Trigger via Telegram:** `@proposals [message]`

**Example Telegram messages:**
```
@proposals Draft a full automation proposal for the Johnson residence — 
7 rooms, Better tier, new construction in Denver CO.

@proposals Build a scope of work for a Basic AV project — 
Living Room, Master Bedroom, Office, Mechanical Room. Good tier.

@proposals What's a ballpark budget for a 10-room Better tier 
full automation project in Colorado?
```

---

## Environment Variables Required

Add these to `~/AI-Server/.env`:

```bash
# HARPA Bridge (required for D-Tools integration)
HARPA_PRIMARY_URL=http://192.168.1.20:3000
HARPA_FALLBACK_URL=http://192.168.1.30:3000
HARPA_GRID_API_KEY=your_harpa_grid_api_key

# D-Tools Cloud credentials (used by HARPA for browser session)
DTOOLS_USERNAME=your@email.com
DTOOLS_PASSWORD=your_password
```

---

## Common Errors & Solutions

| Error | Cause | Fix |
|-------|-------|-----|
| `HARPANodeUnavailable` | Both HARPA nodes offline | Start HARPA on Maestro/Stagehand |
| `DTSessionExpired` | Chrome D-Tools session expired | Re-login at portal.d-tools.com on Maestro |
| `DTImportError` | Equipment CSV validation failed | Check category strings, room assignments |
| `DTValidationError` | Invalid category or missing room | Fix equipment list before import |
| `Coverage gap: theater_has_blackout_shades` | Theater missing shades | Add Lutron shade motor to theater |
| `Coverage gap: network_rack_has_ups` | No UPS in equipment list | Add APC UPS to Mechanical Room |

---

## File Dependencies

This module depends on:
- `~/AI-Server/knowledge/proposal_library/` — scope blocks and room configs
- `~/AI-Server/knowledge/standards/bob_system_prompt.md` — Bob's identity
- `setup/harpa/bob_harpa_bridge.py` — HARPA bridge (for D-Tools)
- `setup/openclaw/openclaw.json` — add the proposals agent definition

---

## Testing

```bash
# Run proposal engine demo
python3 ~/AI-Server/phase2/proposals/proposal_engine.py

# Run scope builder demo
python3 ~/AI-Server/phase2/proposals/scope_builder.py

# Run pricing calculator demo
python3 ~/AI-Server/phase2/proposals/pricing_calculator.py

# Run D-Tools client smoke test (requires HARPA running)
python3 ~/AI-Server/phase2/proposals/dtool_cloud_client.py

# Run all with logging
PYTHONPATH=~/AI-Server python3 -m pytest phase2/proposals/ -v
```

---

## Design Decisions

**Why are equipment prices always None?**  
Equipment prices come from D-Tools Cloud's product catalog. Hardcoding prices creates 
stale data that erodes trust and generates change orders. D-Tools is the single source 
of truth — always.

**Why does the proposals agent use claude-haiku-3-5?**  
Template filling and scope generation are structured, repetitive tasks. Haiku-3-5 is 
fast, cost-efficient, and sufficient for the task. Bob (claude-sonnet-4-5) handles 
complex reasoning; proposals handles template work.

**Why HARPA instead of a REST API?**  
D-Tools Cloud does not expose a public REST API. HARPA browser automation is the only 
integration path. The architecture is designed with retry logic and fallover to minimize 
this fragility.

**Why are coverage gap checks mandatory?**  
A proposal with an undersized amplifier, missing blackout shades, or no UPS creates 
real problems on the job site — and damages Symphony's reputation. Better to catch 
it in a 2-second automated check than at commissioning.

---

*Symphony Smart Homes — Bob the Conductor*  
*Phase 2: Proposal Generation Workflow*
