# API-15: Symphony Ops Web Dashboard — Business Operations GUI

## The Vision

An intuitive web dashboard that anyone — Matt, a future employee, or a substitute — can open and immediately understand and operate the entire Symphony business. Not a developer tool. Not a terminal. A real GUI where you browse products, build SOWs, track projects, and run pre-flight checks without touching the command line.

## Context Files to Read First
- mission_control/main.py (service health dashboard — separate from this)
- knowledge/products/*.md
- knowledge/proposal_library/
- knowledge/sow-blocks/*.md
- knowledge/operations-runbook.md
- openclaw/sow_assembler.py
- openclaw/preflight_check.py
- openclaw/project_template.py
- tools/system_shell.py

## Prompt

Build the Symphony Ops web dashboard as a standalone web app:

### 1. Product Catalog (`/products`)

- Searchable grid of all Symphony products with photos, specs, pricing
- Filter by category: lighting, audio, video, networking, surveillance, control, shades
- Click a product → full detail view with: specs, compatible devices, cable requirements, VLAN assignment, labor hours, MSRP
- "Add to Room" button that adds to the active project design
- Data source: `knowledge/products/*.md` parsed into JSON on startup

### 2. SOW Builder (`/sow-builder`)

Visual drag-and-drop SOW assembly:
- Left panel: room templates (bedroom, theater, kitchen, etc.) — drag into project
- Each room expands to show default equipment + optional upgrades
- Toggle upgrades on/off per room
- Right panel: live SOW preview updating in real-time as you add/remove items
- Bottom bar: running total (equipment cost, labor estimate, total price)
- "Generate SOW" button → produces markdown SOW using sow_assembler.py
- "Run Pre-Flight" button → validates against design rules, shows pass/fail with details
- "Export PDF" button → generates Symphony-branded proposal PDF

### 3. Project Tracker (`/projects`)

- List of all active projects with status badges (Lead, Proposal, Won, Pre-Wire, Install, Commission, Complete)
- Click project → timeline view showing all 22 Linear issues across 4 phases
- Phase progress bars
- Key dates: proposal sent, deposit received, pre-wire date, install date, commission date
- Recent activity feed (emails sent, files uploaded, status changes)
- Client contact info and Dropbox folder link

### 4. Runbook (`/runbook`)

- The operations runbook as an interactive web guide
- Expandable sections with step-by-step instructions
- Quick-reference cards for common tasks: "How to add a product to D-Tools", "How to generate a proposal", "How to run a pre-flight check"
- Search across all runbook content
- Video embeds where applicable (future)

### 5. System Design Tool (`/design`)

- Room-based system designer (feeds into API-14 design validator)
- Add rooms → select equipment per room → auto-validate
- Visual compatibility warnings inline (red/yellow/green badges)
- Auto-generated wiring diagram
- Export: validated design → proposal → SOW in one flow

### 6. Technical Stack

- FastAPI backend on port 8097
- Vanilla HTML/CSS/JS frontend (no React/Vue — keep it simple and fast)
- Dark theme matching Mission Control
- Mobile responsive (iPad-friendly for on-site use)
- Authentication: simple password gate (single shared password for the team)
- Data: reads from `knowledge/` directory on startup, caches in memory
- API endpoints mirror the frontend pages for programmatic access

### 7. Docker Service

Add `symphony-ops` to docker-compose.yml:
- Port 8097
- Mounts `knowledge/` directory read-only
- Health endpoint at `/health`
- Separate from Mission Control (API-5) which is infrastructure-focused

Use standard logging.
