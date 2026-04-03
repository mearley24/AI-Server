# API-14: System Design Graph — Compatibility Intelligence Layer

## The Vision

Drop in a room list and equipment selection → the system auto-validates every component against every other → flags incompatibilities (wrong VESA mount, insufficient PoE budget, VLAN conflict, missing cable runs) → generates wiring diagrams → eventually powers automated 3D layout previews. This is the long-term competitive moat for Symphony.

## Context Files to Read First
- tools/knowledge_graph.py (81 nodes, 76 relationships already)
- tools/graph_learner.py
- knowledge/products/*.md
- knowledge/network/smart_home_protocols.md
- knowledge/network/vlan_best_practices.md
- knowledge/hardware/ssh_mount_clearance_validation.md
- knowledge/hardware/c4_tv_driver_reference.md
- tools/system_shell.py

## Prompt

Evolve the knowledge graph into a full system design validation engine:

### 1. Product Compatibility Database (`knowledge/compatibility/compatibility_db.py`)

Expand beyond the current 81 nodes into a complete compatibility matrix:

```python
product = {
    "sku": "C4-KPZ-B",
    "name": "Control4 Keypad Dimmer",
    "category": "lighting",
    "protocols": ["zigbee_pro"],
    "requires": ["C4_controller"],  # needs a controller to function
    "power": {"type": "line_voltage", "watts": null, "poe": false},
    "network": {"vlan": 20, "ports": 0, "wifi": false},
    "compatible_with": ["C4-EA5", "C4-EA3", "C4-EA1", "C4-CORE3"],
    "incompatible_with": [],
    "cable_requirements": [],  # no cable — wireless zigbee
    "mounting": null,
    "max_per_controller": 125,  # zigbee device limit
    "msrp": 350.00,
    "labor_hours": 0.5
}
```

- Import all products from `knowledge/products/*.md` into this structured format
- Add compatibility relationships: what works with what, what conflicts
- Add protocol-level rules: ZigBee Pro max 125 devices per controller, Lutron RA3 max 100 devices per processor
- Add network rules: cameras ALWAYS go through NVR not switch, mDNS reflector needed across VLANs for Sonos

### 2. Design Validator (`knowledge/compatibility/design_validator.py`)

Takes a room list + equipment selection and validates everything:

```python
validation = validate_design({
    "rooms": [
        {"name": "Living Room", "devices": ["C4-KPZ-B", "C4-KPZ-B", "EP-SPEAKER-6", "SAMSUNG-QN85"]},
        {"name": "Theater", "devices": ["HISENSE-100U8", "PEERLESS-PLCM2", "TRIAD-AMS16"]}
    ]
})
# Returns:
# FAIL: Theater — Peerless PLCM-2 incompatible with Hisense 100" U8 (VESA 800x400, 137lbs exceeds mount capacity)
# WARN: Living Room — No VersaBox specified for Samsung TV location
# WARN: No network switch specified — 4 IP devices need switch ports
# PASS: ZigBee device count (4) within EA-5 limit (125)
# PASS: VLAN assignments correct for all devices
```

Validation rules:
- Every TV location needs a VersaBox (Strong)
- Every TV needs a mount rated for its VESA pattern and weight
- Total PoE draw cannot exceed switch PoE budget
- ZigBee/Lutron device counts within controller limits
- Every IP device has a VLAN assignment
- Every camera routes through NVR, not directly to switch
- Cable run count matches device count per room
- Amplifier channels match speaker zone count

### 3. Wiring Diagram Generator (`knowledge/compatibility/wiring_generator.py`)

Auto-generate a wiring diagram from validated design:

- Output: Markdown table + optional Mermaid diagram
- Per room: device, cable type, cable destination (rack/NVR/local), VLAN, switch port
- Summary: total cable runs by type, switch port allocation, PoE budget
- Export to CSV for cable labeling
- Integrates with existing `tools/system_shell.py` and `tools/port_allocator.py`

### 4. Pre-Sale Design Tool

When Bob receives a room list from a consultation:
- Auto-select recommended equipment packages per room (from `knowledge/proposal_library/room_packages/`)
- Run design validator
- Flag any issues before the proposal goes out
- Generate the wiring diagram for the pre-wire crew
- Attach validation report to the Linear project

### 5. Integration

- Wire into proposal engine (Auto-16): every proposal auto-validated before sending
- Wire into SOW assembler (Auto-9): cable runs and port allocations auto-generated
- Wire into Bob's Brain (API-11): design validation results in context store
- API endpoint: `POST /api/validate-design` for Mission Control / Symphony Ops dashboard
- CLI: `python3 design_validator.py --rooms rooms.yaml --output report.md`

### 6. Future: 3D Layout Preview

Not building this now, but the data model should support it:
- Each product has physical dimensions (width, height, depth)
- Room dimensions can be input
- Rack layout: U-space allocation per device
- Wall plate locations per room
- This data feeds a future 3D renderer (Three.js or similar)

Use standard logging.
