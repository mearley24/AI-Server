# Auto-26: System Shells — Pre-Planned IP Addressing & Device Registry

## The Vision

Every device in a proposal that needs a network address gets a pre-planned IP before a single cable is pulled. The system shell is a one-page reference sheet for each project: every device, its IP, VLAN, switch port, cable label, access codes, passwords, and commissioning status. The installer walks in, opens the shell, and knows exactly where everything goes.

IP ranges are standardized by device category so any Symphony tech instantly knows "192.168.20.16 is a controller" without looking it up.

## Context Files to Read First
- AGENTS.md (System Shell Generator, Port Allocator, VLAN Best Practices sections)
- knowledge/topletz/project-config.yaml
- knowledge/proposals/Gates_Equipment_Rollup.md
- knowledge/proposals/Hernaiz_Equipment_Rollup.md
- knowledge/reports/Kelly_Proposal_Intelligence.md
- knowledge/reports/SKU_Frequency_Report.md
- knowledge/reports/Room_Archetype_Packages.md
- knowledge/proposal_library/scope_blocks/networking.md
- knowledge/sow-blocks/network-infrastructure.md

## Prompt

Build the system shell generator and standardized IP addressing scheme:

### 1. Analyze Past Proposals for Device Counts

First, parse all existing proposal data to determine typical device counts per category:

- Read equipment rollups: Gates (large: 21 keypads, 4 TVs, 20 speakers, 16 shades, 5 cameras), Hernaiz (medium: 17 keypads, 4 TVs, 14 speakers, 3 shades, 0 cameras), Kelly (large: 3 switches, 3 APs, 3 amps), Topletz (medium-large: 18 switches, 4 cameras, iPads)
- Categorize every device type: networking, control/automation, audio, video/displays, surveillance, security, shades, misc
- Calculate: average, min, max, and P90 device count per category across all proposals
- Output analysis to `knowledge/network/device_count_analysis.md`

### 2. Symphony Standard IP Scheme (`knowledge/network/ip_addressing_standard.md`)

Based on the analysis, define permanent IP ranges per VLAN. Use .1-.254 space wisely with room to grow:

The scheme uses two key principles:

**1. Client-numbered subnets** — Each client gets a unique second octet so VPN/remote monitoring never has subnet collisions. You can VPN into every client site simultaneously.

**2. Consistent 10-address blocks** — Same block pattern on every subnet. .1-.15 is always networking, .16-.25 is always the first device category, etc. A tech sees .20 and instantly knows that's a control/distribution device regardless of which client or VLAN.

#### Client Numbering (10.X.Y.0/24)

- Second octet (X) = client number (assigned sequentially, permanent)
- Third octet (Y) = VLAN ID (1, 10, 20, 30, 40, 50)
- Fourth octet = device address within the 10-block scheme

```
Client 001 (Topletz):    10.1.1.0/24, 10.1.10.0/24, 10.1.20.0/24, 10.1.30.0/24, 10.1.40.0/24, 10.1.50.0/24
Client 002 (Next):       10.2.1.0/24, 10.2.10.0/24, 10.2.20.0/24, 10.2.30.0/24, 10.2.40.0/24, 10.2.50.0/24
Client 003 (Next):       10.3.1.0/24, ...
```

Even clients with a flat network (no VLANs) get a unique subnet: 10.3.1.0/24. If they add VLANs later, the scheme is already waiting.

Maintain a client registry in `knowledge/network/client_registry.json`:
```json
{"001": "Topletz - 84 Aspen Meadow", "002": "...", ...}
```

#### 10-Address Block Standard (same on every subnet)

```
.1-.15      Networking (gateway, router, switches, NVRs, fiber uplinks)
.16-.25     Category A (varies by VLAN — see below)
.26-.35     Category B
.36-.45     Category C
.46-.55     Category D
.56-.65     Category E
.66-.75     Category F
.76-.254    DHCP pool (new devices land here, get assigned a static later)
```

#### Per-VLAN Category Assignments

```
VLAN 1 — Management (10.X.1.0/24)
  .1-.15      Networking (gateway, router, switches, fiber uplinks)
  .16-.25     Access points — indoor
  .26-.35     Access points — outdoor
  .36-.45     UPS / WattBox / PDUs / power management
  .46-.75     Reserved
  .76-.254    DHCP pool

VLAN 20 — Control (10.X.20.0/24)
  .1-.15      Networking (gateway, VLAN interface)
  .16-.25     Control / distribution (EA-5, EA-3, CORE3, audio matrix AMS-8/AMS-16, DSP amps — anything that routes signals. Traditional amps are NOT networked)
  .26-.35     Touchscreens / iPads / control surfaces
  .36-.45     Lighting processors (Lutron RA3 processors, repeaters)
  .46-.55     Shade controllers (Lutron, Somfy, QMotion processors)
  .56-.65     Climate / HVAC interfaces (thermostats, zone controllers)
  .66-.75     Security panels & keypads (Qolsys, 2GIG, DSC)
  .76-.254    DHCP pool

VLAN 30 — IoT (10.X.30.0/24)
  .1-.15      Networking (gateway, VLAN interface)
  .16-.25     Smart TVs / displays
  .26-.35     Streaming devices (Apple TV, Roku, Shield, Fire)
  .36-.45     Voice assistants (Alexa, Google Home)
  .46-.55     Smart locks / smart appliances
  .56-.65     Pool / spa / outdoor automation
  .66-.75     Misc IoT
  .76-.254    DHCP pool

VLAN 40 — Guest (10.X.40.0/24)
  .1-.15      Networking (gateway)
  .76-.254    DHCP only (no static assignments)

VLAN 50 — Surveillance (10.X.50.0/24)
  .1-.15      Networking (gateway, NVRs)
  .16-.25     Cameras — exterior
  .26-.35     Cameras — interior
  .36-.45     Doorbell cameras / video intercoms
  .46-.55     Access control (gate controllers, door stations)
  .56-.75     Camera expansion (large estates)
  .76-.254    DHCP pool

VLAN 10 — Trusted Devices (10.X.10.0/24)
  .1-.15      Networking (gateway)
  .76-.254    DHCP only (client phones, laptops, tablets)
```

VLANs are optional but always pre-planned. A flat-network client still uses the 10-block standard on their single subnet — if they upgrade later, VLANs snap in without re-addressing anything.

Cursor should analyze past proposals (Gates, Hernaiz, Kelly, Topletz) to validate that 10-address blocks are sufficient per category and flag any that need more.

### 3. System Shell Generator (`tools/system_shell.py`)

Takes a project config (like `knowledge/topletz/project-config.yaml`) and generates the complete shell:

```python
shell = generate_shell(project_config="knowledge/topletz/project-config.yaml")
```

Output: `knowledge/projects/[project]/system_shell.md`

```markdown
# System Shell — Topletz Residence
## 84 Aspen Meadow Drive, Edwards, CO

Generated: 2026-04-03 | Version: 1

### Network Overview
| VLAN | Subnet | Purpose | Devices |
|------|--------|---------|---------|
| 1 | 192.168.1.0/24 | Management | Router, Switch, 3x AP, WattBox |
| 20 | 192.168.20.0/24 | Control | EA-5, 18x Keypad, 2x iPad, AMS-16, Qolsys |
| 30 | 192.168.30.0/24 | IoT | 4x Smart TV, Apple TV |
| 50 | 192.168.50.0/24 | Surveillance | NVR, 4x Camera, 1x Doorbell |

### Device Registry
| Room | Device | Model | IP | VLAN | Switch Port | Cable Label | Status |
|------|--------|-------|------|------|-------------|-------------|--------|
| Rack | Router | AN-520-RT | 192.168.1.1 | 1 | - | - | ⬜ |
| Rack | Switch | AN-620-SW-R-24-POE | 192.168.1.2 | 1 | - | - | ⬜ |
| Living Room | AP | AN-820-AP-I | 192.168.1.6 | 1 | Sw1-P1 | LR-AP-01 | ⬜ |
| Rack | Controller | C4-EA5 | 192.168.20.10 | 20 | Sw1-P5 | RK-EA5-01 | ⬜ |
| Kitchen | iPad | Apple iPad | 192.168.20.16 | 20 | - | - | ⬜ |
| Rack | Audio Matrix | TS-AMS16 | 192.168.20.26 | 20 | Sw1-P8 | RK-AMS-01 | ⬜ |
| Garage | Security | Qolsys IQ4 | 192.168.20.66 | 20 | Sw1-P12 | GR-QOL-01 | ⬜ |
| Front Entry | Camera | Luma LNB8A | 192.168.50.10 | 50 | NVR-P1 | FE-CAM-01 | ⬜ |

### Access Codes & Credentials
| System | Username | Password | Notes |
|--------|----------|----------|-------|
| Router Admin | admin | [set on site] | 192.168.1.1 |
| WiFi - Trusted | [client SSID] | [set on site] | VLAN 10 |
| WiFi - Guest | [client]-Guest | [set on site] | VLAN 40 |
| Qolsys Panel | installer | [set on site] | Default: 1111 |
| Luma NVR | admin | [set on site] | 192.168.50.2 |
| Control4 Composer | [project] | [set on site] | HE license |

### Cable Label Schedule
| Label | From | To | Cable Type | Length Est |
|-------|------|-----|-----------|-----------|
| LR-AP-01 | Living Room ceiling | Rack Sw1-P1 | Cat6 | 45ft |
| FE-CAM-01 | Front Entry soffit | Rack NVR-P1 | Cat6 | 60ft |
...

### Switch Port Allocation
| Port | Device | VLAN | PoE | Cable Label |
|------|--------|------|-----|-------------|
| 1 | Living Room AP | 1 | ✅ af | LR-AP-01 |
| 2 | Master Bedroom AP | 1 | ✅ af | MB-AP-01 |
...

### Commissioning Checklist
| # | Task | Status |
|---|------|--------|
| 1 | Router configured, VLANs created | ⬜ |
| 2 | Switch configured, port VLANs assigned | ⬜ |
| 3 | All APs powered and adopted | ⬜ |
| 4 | Controller online, rooms created | ⬜ |
| 5 | All cameras visible in NVR | ⬜ |
| 6 | Qolsys enrolled, C4 driver connected | ⬜ |
| 7 | All audio zones tested | ⬜ |
| 8 | Client WiFi networks active | ⬜ |
| 9 | Remote access verified (Tailscale/VPN) | ⬜ |
| 10 | Client walkthrough complete | ⬜ |
```

Status: ⬜ pending, 🟡 in progress, ✅ complete, ❌ issue

### 4. Auto-Generation from Proposal

When a proposal is finalized:
- Parse the equipment list
- Match each device to its category → assign IP from the standard scheme
- Assign switch ports (cameras → NVR PoE ports, everything else → main switch)
- Generate cable labels: `[ROOM_CODE]-[DEVICE_TYPE]-[##]`
- Generate the full shell markdown
- Save to `knowledge/projects/[project]/system_shell.md`

CLI:
```
python3 tools/system_shell.py --generate "Topletz" --config knowledge/topletz/project-config.yaml
python3 tools/system_shell.py --show "Topletz"
python3 tools/system_shell.py --update "Topletz" --device "Front Camera" --ip 192.168.50.10 --status complete
python3 tools/system_shell.py --export "Topletz" --format pdf
python3 tools/system_shell.py --export-labels "Topletz" --format csv
```

### 5. Port Allocator (`tools/port_allocator.py`)

Auto-assign switch ports following Symphony rules:
- Cameras ALWAYS connect to NVR PoE ports, never the main switch
- APs get sequential ports starting from Port 1
- Controllers and audio get sequential from the next available
- Leave 20% ports unassigned for future expansion
- Output: port allocation table + cable label CSV for printing

### 6. Integration with Notes Indexer (Auto-25)

When the Notes Indexer extracts access codes from project notes:
- Auto-populate the Access Codes section of the system shell
- WiFi passwords, alarm codes, gate codes, lock codes all flow in
- Installer gets one document with everything

### 7. Integration with Client Lifecycle (API-13)

- Shell auto-generated when proposal is accepted (Phase 1)
- Shell updated during commissioning (Phase 4) as devices come online
- Status field updated as each device is configured
- Final shell with all passwords populated becomes part of the client handoff package
- Shell feeds into the Client AI Concierge knowledge base (API-9)

### 8. Retroactive Generation

Generate shells for existing projects:
- Parse Gates, Hernaiz, Kelly equipment rollups → generate shells
- Parse Topletz project-config.yaml → generate shell
- These become reference examples for the standard

Use standard logging.

---

## Implementation Notes

These notes give Cursor concrete file locations and implementation details to complete the build without guessing at project structure.

### File Locations

| Artifact | Path |
|----------|------|
| Shell generator | `tools/system_shell.py` |
| Port allocator | `tools/port_allocator.py` |
| IP addressing standard | `knowledge/network/ip_addressing_standard.md` |
| Client registry | `knowledge/network/client_registry.json` |
| Device count analysis | `knowledge/network/device_count_analysis.md` |
| Generated shells | `knowledge/projects/[project_slug]/system_shell.md` |
| Device specs reference | `knowledge/hardware/networking.json` |

### Input Data for Device Count Analysis

Parse these files to derive the per-category device count analysis (step 1 of the prompt):
- `knowledge/proposals/Gates_Equipment_Rollup.md` — large residential: 21 keypads, 4 TVs, 20 speakers, 16 shades, 5 cameras
- `knowledge/proposals/Hernaiz_Equipment_Rollup.md` — medium residential: 17 keypads, 4 TVs, 14 speakers, 3 shades, 0 cameras
- `knowledge/reports/Kelly_Proposal_Intelligence.md` — large estate networking: 3 switches, 3 APs, 3 amps
- `knowledge/topletz/project-config.yaml` — medium-large: 18 keypads, 4 cameras, 2 iPads, 1 EA-5, 1 AMS-16

From these four projects, compute average/min/max/P90 per device category and write to `knowledge/network/device_count_analysis.md`. The output should validate whether the 10-address blocks (.16-.25, .26-.35, etc.) are sufficient or need expanding.

### Device Specs Reference

`knowledge/hardware/networking.json` contains SKU-level specs for Araknis switches and APs. When generating a shell, look up each networking device's SKU here to get: port count, PoE budget, PoE ports count, management VLAN support. This feeds the port allocator — you can't allocate a port on a 24-port switch if the switch model only has 8 ports.

### system_shell.py — Dual Mode

The shell generator must work both ways:

```python
# As CLI:
python3 tools/system_shell.py --generate topletz --config knowledge/topletz/project-config.yaml
python3 tools/system_shell.py --generate gates --rollup knowledge/proposals/Gates_Equipment_Rollup.md

# As importable module:
from tools.system_shell import generate_shell
shell = generate_shell(project_slug="topletz", config_path="knowledge/topletz/project-config.yaml")
```

The importable form is needed by Auto-26's integration with the client lifecycle (API-13) — when a proposal is accepted, the lifecycle system calls `generate_shell()` programmatically.

### port_allocator.py — Hard Rules

Implement these rules without exception:

1. **Cameras → NVR PoE ports only.** Never put a camera on the main switch. The NVR has dedicated PoE ports for this. Cameras go to NVR-P1, NVR-P2, etc.
2. **APs start at Port 1** of the main switch and fill sequentially. Port 1 is always the first AP.
3. **20% port reserve.** On a 24-port switch: max 19 assigned ports. On an 8-port switch: max 6. Leave the rest unassigned for future expansion.
4. **PoE budget check.** Sum the PoE draw of all connected devices. Alert if it exceeds 80% of the switch's rated PoE budget.
5. **Port → cable label.** Every assigned port gets a cable label in the format `[ROOM_CODE]-[DEVICE_TYPE]-[##]`.

Room codes to use (derive from room name if not in this list):
```
LR  Living Room       MBR  Master Bedroom     KIT  Kitchen
DR  Dining Room       BR2  Bedroom 2          BR3  Bedroom 3
OFF  Office           GAR  Garage             OUT  Outdoor
FE   Front Entry      RK   Rack / Equipment   GYM  Gym
THR  Theater          LAU  Laundry            UTL  Utility
```

Device type codes:
```
AP   Access Point     CAM  Camera             SW   Switch
EA   Controller (C4)  NVR  NVR                AMP  Amplifier
AMS  Audio Matrix     IPD  iPad               LUT  Lutron
QOL  Qolsys           WB   WattBox
```

Example cable labels: `LR-AP-01`, `FE-CAM-01`, `MBR-AP-02`, `RK-NVR-01`

### client_registry.json Format

```json
{
  "001": {
    "name": "Topletz",
    "address": "84 Aspen Meadow Drive, Edwards, CO",
    "slug": "topletz",
    "assigned_at": "2026-01-01"
  },
  "002": {
    "name": "Gates",
    "address": "[address from proposal]",
    "slug": "gates",
    "assigned_at": "2026-04-03"
  }
}
```

Client numbers are permanent and sequential. Never reuse a number. The second octet in the IP scheme (`10.X.Y.0`) maps directly to this registry number. Topletz = client 001 = `10.1.Y.0` on all subnets.

### Shell Output Location

Generated shells go to `knowledge/projects/[project_slug]/system_shell.md`. Create the directory if it doesn't exist. For retroactive generation from existing proposals:
- Topletz → `knowledge/projects/topletz/system_shell.md`
- Gates → `knowledge/projects/gates/system_shell.md`
- Hernaiz → `knowledge/projects/hernaiz/system_shell.md`
- Kelly → `knowledge/projects/kelly/system_shell.md`

### Auto-25 Integration (Access Codes)

After `integrations/apple_notes/notes_indexer.py` runs, it writes `knowledge/projects/[slug]/access_codes.md` files. The shell generator should check for this file and, if present, merge the extracted codes into the "Access Codes & Credentials" section of the shell:

```python
codes_path = Path(f"knowledge/projects/{project_slug}/access_codes.md")
if codes_path.exists():
    shell_data["access_codes_source"] = "auto_extracted"
    shell_data["access_codes"] = parse_access_codes_md(codes_path)
```

This is the key integration: Matt's field notes become the installer reference sheet automatically.
