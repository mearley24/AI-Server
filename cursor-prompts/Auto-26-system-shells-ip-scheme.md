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

```
VLAN 1 — Management (192.168.1.0/24)
  .1          Gateway (router/firewall)
  .2-.10      Switches (primary, secondary, PoE, fiber — room for 9)
  .11-.25     Access points (indoor + outdoor — room for 15)
  .26-.35     UPS / WattBox / power management / PDUs
  .36-.49     Reserved (future management devices)
  .50-.99     Infrastructure expansion
  .200-.254   DHCP pool (for discovery)

VLAN 20 — Control (192.168.20.0/24)
  .1          Gateway
  .2-.15      Controllers (EA-5, EA-3, EA-1, CORE3, CORE5 — room for 14)
  .16-.45     Control endpoints (keypads w/ IP, touchscreens, iPads — room for 30)
  .46-.55     Audio matrix / DSP (AMS-8, AMS-16, DSP amps, Sonos ports — room for 10. Traditional amps are NOT networked)
  .56-.75     Lighting processors (Lutron RA3 processors, repeaters, panels — room for 20)
  .76-.95     Shade controllers (Lutron, Somfy, QMotion — room for 20)
  .96-.110    Climate / HVAC interfaces (thermostats, zone controllers — room for 15)
  .111-.125   Security panels & keypads (Qolsys, 2GIG, DSC — room for 15)
  .126-.199   Reserved for expansion
  .200-.254   DHCP pool (for discovery/commissioning)

VLAN 30 — IoT (192.168.30.0/24)
  .1          Gateway
  .2-.30      Smart TVs / displays (room for 29 — covers largest estates)
  .31-.55     Streaming devices (Apple TV, Roku, Shield, Fire — room for 25)
  .56-.80     Voice assistants (Alexa, Google Home — room for 25)
  .81-.120    Thermostats, smart locks, smart appliances, misc IoT (room for 40)
  .121-.150   Motorized furniture, fireplaces, pool/spa controllers
  .151-.199   Reserved for expansion
  .200-.254   DHCP pool

VLAN 40 — Guest (192.168.40.0/24)
  .1          Gateway
  .100-.254   DHCP only (no static assignments)

VLAN 50 — Surveillance (192.168.50.0/24)
  .1          Gateway
  .2-.6       NVR(s) (room for 5 — multi-NVR estates)
  .10-.59     Cameras (room for 50 — large estates with 30+ cameras)
  .60-.74     Doorbell cameras / video intercoms (room for 15)
  .75-.89     Access control (gate controllers, door stations — room for 15)
  .90-.99     Reserved
  .200-.254   DHCP pool (for camera discovery)

VLAN 10 — Trusted Devices (192.168.10.0/24)
  .1          Gateway
  .100-.254   DHCP only (client phones, laptops, tablets)
```

These ranges are sized for large custom homes (8+ bedrooms, 30+ cameras, 40+ speaker zones, multiple buildings). Small projects just use a subset. Validate ranges against the device count analysis — the scheme should never need to be modified per project, only filled in.

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
