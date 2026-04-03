# API-3: Neural Map — System Compatibility Engine

## Context Files to Read First
- knowledge/hardware/c4_tv_driver_reference.json
- knowledge/hardware/c4_tv_driver_reference.md
- knowledge/hardware/ssh_mount_clearance_validation.md
- knowledge/hardware/ssh_tv_mount_recommendations_playbook.md

## Prompt

Build the system compatibility engine — every component validated against every other component it connects to.

Create knowledge/hardware/system_graph.py:

1. Component Registry:
   - Define component types: TV, Mount, Speaker, Amplifier, Switch, Panel, Camera, iPad, Network_Switch, Access_Point, Shade_Motor, Conduit
   - Each component has: model, manufacturer, specs (VESA, weight, power_draw, protocol, etc.)
   - Load from JSON files in knowledge/hardware/

2. Connection Types:
   - HDMI (version, length limit, ARC/eARC)
   - Cat6 (PoE budget, VLAN assignment)
   - Speaker Wire (gauge, impedance, max run)
   - IR (line of sight, flasher required)
   - WiFi (band, coverage area)
   - Power (voltage, amperage, outlet type)
   - Control Protocol (SDDP, IR, RS232, Zigbee, Z-Wave)

3. Validation Rules:
   - Mount must clear recessed box plugs (profile > plug protrusion)
   - Mount VESA must match TV VESA
   - Mount weight capacity must exceed TV weight + 20%
   - TV C4 integration method must be known (native/3rd-party/IR/none)
   - Speaker impedance must match amplifier zone
   - PoE device power draw must not exceed switch PoE budget
   - Network device must have VLAN assignment
   - iPad must have PoE or in-wall power solution

4. Validation Engine:
   - validate_system(components: list[Component]) -> ValidationReport
   - Returns: passes, warnings, failures with specific details
   - "TV: Hisense 100" U8 VESA 800x400 — Mount: Peerless PLCM-2 max VESA 600x400 — FAIL: VESA pattern incompatible"

5. Project Template:
   - Given a project's component list, validate everything and generate a report
   - Flag missing components (e.g., TV specified but no mount)
   - Flag incompatible pairs
   - Suggest alternatives from the compatibility database

6. Create starter databases:
   - knowledge/hardware/tvs.json — Samsung, Sony, LG, TCL, Hisense models with VESA, weight, C4 integration
   - knowledge/hardware/mounts.json — Sanus, Strong, Peerless models with VESA, weight cap, profile, tilt
   - knowledge/hardware/networking.json — Araknis switches, Access Points with PoE budgets, port counts

CLI: python knowledge/hardware/system_graph.py validate --project topletz
Output: validation report showing all passes, warnings, failures

Commit and push.
