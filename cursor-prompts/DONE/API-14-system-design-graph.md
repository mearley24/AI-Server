# API-14: System Design Graph — Compatibility Intelligence Layer

## The Vision

Drop in a room list and equipment selection → the system auto-validates every component against every other → flags incompatibilities (wrong VESA mount, insufficient PoE budget, control protocol mismatch, missing cable runs) → generates wiring diagrams. This is the long-term competitive moat for Symphony: no other integrator does this automatically. The system_graph.py has compatibility checking. Extend it into a full design validation engine.

Read the existing code first.

## Context Files to Read First

- `knowledge/hardware/system_graph.py`
- `knowledge/hardware/tvs.json`
- `knowledge/hardware/mounts.json`
- `knowledge/hardware/networking.json`
- `knowledge/hardware/c4_tv_driver_reference.json`

## Prompt

### 1. Understand the Existing Component Model

Read `system_graph.py` end to end:
- What does the component model look like? (fields, types, relationships)
- What compatibility rules are already defined?
- How are components stored and queried?
- What is the graph data structure? (NetworkX? Dict-based? SQLite?)

Read all JSON files in `knowledge/hardware/`:
- `tvs.json`: What TV fields exist? VESA pattern? Weight? Dimensions? IP control support?
- `mounts.json`: What mount fields exist? VESA compatibility? Weight rating? Size range?
- `networking.json`: What switch fields exist? PoE budget? Port count? VLAN support?
- `c4_tv_driver_reference.json`: What driver types exist? SDDP vs IP vs IR? Which TVs have native SDDP?

Map every existing field. The validation engine must use actual field names — do not invent new schema.

### 2. Extend the Component Model (`knowledge/hardware/system_graph.py`)

Add missing fields to the existing model (do not break what's there):

```python
# Add to existing component structure:
component = {
    # ... existing fields ...
    
    # Physical / mounting
    "vesa_pattern": "400x300",      # e.g. "400x400", "200x200" — for TV/mount matching
    "weight_lbs": 65.2,             # TV weight, or mount weight capacity
    "screen_size_inches": 75,       # for mount size rating check
    
    # Networking
    "vlan": 30,                     # which VLAN this device belongs to
    "poe_watts": 15.4,              # how much PoE power this device draws (0 if not PoE)
    "poe_type": "802.3af",          # af=15.4W, at=30W, bt=60W, null if not PoE
    "ip_ports": 1,                  # how many switch ports this device needs
    
    # Control
    "control_protocol": "SDDP",     # SDDP | IP | IR | RS232 | CEC | none
    "requires_controller": "C4",    # which controller family manages this device
    
    # Cable
    "cable_in": ["HDMI 2.1"],       # cables coming into this device
    "cable_out": ["HDMI 2.1"],      # cables going out from this device
    
    # Capacity
    "max_devices": 125,             # for hubs/controllers: max connected devices
    "zone_count": 16,               # for audio/video matrices: number of zones
    "poe_budget_watts": 370,        # for switches: total PoE output budget
}
```

Add compatibility relationships as edges in the existing graph:
- `COMPATIBLE_WITH`: verified to work together
- `INCOMPATIBLE_WITH`: known not to work together (with reason string)
- `REQUIRES`: device A requires device B to function (e.g., keypad requires controller)
- `CONNECTS_TO`: physical cable connection

### 3. Design Validator (`knowledge/hardware/design_validator.py` — new file)

Takes a project's room list and equipment selection, validates every pair:

```python
def validate_design(rooms: list[dict]) -> ValidationReport:
    """
    Input:  [{"name": "Living Room", "devices": ["SKU1", "SKU2"]}, ...]
    Output: ValidationReport with PASS/WARN/FAIL items
    """
```

**Required checks (implement all):**

**TV + Mount:**
- VESA pattern match (TV VESA must be in mount's compatible_vesa list)
- Weight: TV weight_lbs ≤ mount weight capacity
- Size: TV screen_size_inches within mount's min/max size range
- `FAIL` if any mismatch; `WARN` if no mount specified for a TV location

**TV + Controller driver:**
- Check c4_tv_driver_reference.json: does this TV have a SDDP driver, IP driver, or IR-only?
- `WARN` if IR-only (less reliable, harder to diagnose)
- `FAIL` if no driver exists for this TV model at all

**Switch + Devices (PoE):**
- Sum all PoE-drawing devices on the switch
- `FAIL` if total poe_watts > switch poe_budget_watts
- `WARN` if total > 80% of poe_budget_watts (headroom rule)
- `FAIL` if device count > switch port count

**Audio matrix + Amplifiers + Speakers:**
- Amp channel count must match speaker zone count (or be ≥)
- `WARN` if impedance data missing
- `FAIL` if zone_count mismatch

**VersaBox rule:**
- Every TV location must have a VersaBox (Strong) in the BOM
- `WARN` if missing — this is a preflight rule, not hard fail

**ZigBee/Lutron device limits:**
- ZigBee Pro: max 125 devices per Control4 controller
- Lutron RA3: max 100 devices per processor
- `FAIL` if exceeded

**VLAN assignment:**
- Every IP device must have a VLAN assignment
- `WARN` if any device has `vlan: null`

**Missing items (BOM gap check):**
- Count devices per room that need HDMI cables
- Count actual HDMI cables in the BOM
- `WARN` if device count > cable count for any cable type

```python
@dataclass
class ValidationItem:
    severity: str        # PASS | WARN | FAIL
    category: str        # mount | driver | poe | audio | versabox | zigbee | vlan | bom
    room: str            # which room (or "system-wide")
    device_a: str        # first device SKU/name
    device_b: str        # second device SKU/name (or None)
    message: str         # human-readable description of the issue
    fix: str             # recommended fix action

@dataclass
class ValidationReport:
    passes: list[ValidationItem]
    warnings: list[ValidationItem]
    failures: list[ValidationItem]
    is_valid: bool       # True only if failures is empty
    summary: str         # one-line summary
```

### 4. Wiring Diagram Generator (`knowledge/hardware/wiring_generator.py` — new file)

Generate a text-based wiring diagram from a validated design:

```python
def generate_wiring_diagram(rooms: list[dict], format: str = "mermaid") -> str:
    """
    Generates a wiring diagram in Mermaid or plain text format.
    
    Mermaid format (default):
        graph TD
            Rack[Equipment Rack] --> Switch[Cisco SG350-10P]
            Switch --> TV_LR[Samsung QN85 — Living Room]
            Switch --> Camera_Front[Hikvision — Front Entry]
            Switch --> NVR[Hikvision NVR]
            NVR --> Camera_Front
    
    Text format:
        RACK → SWITCH (2x CAT6)
        SWITCH → TV (Living Room) — CAT6, port 1, VLAN 30
        SWITCH → NVR — CAT6, port 7, VLAN 40
        NVR → CAMERA (Front Entry) — CAT6, port 1
    """
```

Per-room output: device, cable type, cable source/destination, VLAN, switch port.
System-wide summary: total cable runs by type, switch port allocation table, PoE budget table.
Export to CSV for cable labeling: `cable_label, from, to, type, length_ft, vlan`.

### 5. Integrate with Proposal Checker

When the proposal checker (Auto-16) validates a D-Tools proposal, also run design validation:

```python
# In Auto-16 proposal checker:
from knowledge.hardware.design_validator import validate_design

validation_report = validate_design(proposal.rooms)
if not validation_report.is_valid:
    # Add design issues to the proposal checker output
    # FAIL items block proposal from sending
    # WARN items are shown to Matt but don't block
```

The proposal must not go out with design FAILs unaddressed.

### 6. CLI

```bash
# Validate a project
python3 knowledge/hardware/system_graph.py --validate-project topletz
# Reads project data from data/projects/topletz/equipment_list.json
# Outputs validation report to stdout and saves to data/projects/topletz/validation_report.md

# Generate wiring diagram
python3 knowledge/hardware/system_graph.py --wiring-diagram topletz --format mermaid
# Outputs Mermaid diagram to stdout and saves to data/projects/topletz/wiring_diagram.md

# Validate a custom rooms YAML
python3 knowledge/hardware/system_graph.py --rooms rooms.yaml --output report.md
```

### 7. Test with Topletz Equipment List

```bash
# Validate Topletz
python3 knowledge/hardware/system_graph.py --validate-project topletz

# Expected: validation report showing all devices, any compatibility warnings,
# VersaBox presence check for each TV, PoE budget analysis for the network switch,
# VLAN assignments for all IP devices

# Generate wiring diagram
python3 knowledge/hardware/system_graph.py --wiring-diagram topletz --format mermaid

# Paste the Mermaid output into https://mermaid.live to verify it renders correctly
```

Fix any issues found in Topletz validation — these are real project defects.

Use standard logging. All log messages prefixed with `[design-graph]`.
