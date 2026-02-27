# Scope Block: HVAC / Climate Control Integration
<!-- BOB INSTRUCTIONS: Symphony does not install HVAC systems. This block covers Control4 integration of thermostats and climate systems installed by the HVAC contractor. Include this block when climate control is in scope. -->

---

## SYSTEM DESCRIPTION

Symphony Smart Homes integrates HVAC and climate control into the Control4 automation platform, giving clients a unified interface for managing temperature, schedules, and comfort modes alongside all other smart home systems. Symphony provides thermostat installation, wiring, and full Control4 integration — the HVAC equipment itself (air handlers, furnaces, condensers) is supplied and installed by the client's HVAC contractor.

---

## THERMOSTAT PLATFORM SELECTION

### Recommended Thermostats (Control4 Certified)

| Model | Type | Connectivity | Best For |
|-------|------|-------------|----------|
| Ecobee Smart Thermostat Premium | Smart, with room sensors | Wi-Fi + Ethernet | Standard whole-home, multi-zone; best Control4 driver |
| Ecobee Smart Thermostat Enhanced | Smart | Wi-Fi | Budget-friendly, standard Control4 integration |
| Nest Learning Thermostat (4th Gen) | Smart, learning | Wi-Fi | Clients who prefer Google/Nest ecosystem |
| Honeywell Home T6 Pro | Basic smart | Ethernet/Wi-Fi | Simple integration, budget |
| Honeywell Home T10 Pro | Multi-zone with RedLINK | Wi-Fi | Multi-zone systems with room sensors |
| Lutron Palladiom Thermostat | Premium, sleek design | Lutron QS bus | When homeowners want matching Lutron keypads/panels |
| Proliphix NT20e | Wired IP thermostat | Ethernet | High-reliability, commercial-grade |

*Symphony's standard specification: Ecobee Smart Thermostat Premium (best Control4 two-way integration; supports remote sensors for multi-zone comfort)*

---

## SCOPE BY ZONE

Each HVAC zone receives:
- 1x Ecobee Smart Thermostat Premium (or specified model)
- Wiring from thermostat location to air handler / HVAC control board (24V common wire + standard R, Y, W, G, C)
- Ethernet (CAT6A) or Wi-Fi connection for IP control
- Control4 driver configuration and binding

### Zones in This Project:

| Zone | Location | Thermostat Model | HVAC Equipment (by HVAC contractor) |
|------|----------|-----------------|--------------------------------------|
| Zone 1 | {{ZONE_1_LOCATION}} | {{THERMOSTAT_MODEL}} | {{HVAC_EQUIPMENT_1}} |
| Zone 2 | {{ZONE_2_LOCATION}} | {{THERMOSTAT_MODEL}} | {{HVAC_EQUIPMENT_2}} |
| Zone 3 | {{ZONE_3_LOCATION}} | {{THERMOSTAT_MODEL}} | {{HVAC_EQUIPMENT_3}} |
| Zone 4 | {{ZONE_4_LOCATION}} | {{THERMOSTAT_MODEL}} | {{HVAC_EQUIPMENT_4}} |

*Add/remove rows as needed. Standard homes: 1 zone per floor. Larger homes: 1 zone per wing or 1 per floor.*

---

## CONTROL4 INTEGRATION

### What's Included:
- Two-way thermostat binding in Control4 (temperature display, setpoint control, mode selection)
- "Climate" page on all Control4 panels and mobile app
- Current temperature and setpoint visible on home screen
- HVAC control in all scenes (Good Night, Away, Welcome Home, etc.)

### Automation Examples:
- **Away Mode:** When client leaves (geofence or keypad), thermostat sets to {{AWAY_HEAT_SETPOINT}}°F heat / {{AWAY_COOL_SETPOINT}}°F cool
- **Welcome Home:** 30 minutes before estimated arrival (geofence pre-condition), return to comfort setpoint
- **Good Night:** Reduce setpoint by 2°F at bedtime for sleeping comfort
- **Vacation Mode:** Extended away setpoints when triggered from app
- **Ecobee Room Sensors:** Comfort follows occupancy — auto-switch to occupied rooms for most accurate control

### Ecobee Room Sensors (Optional Add-On):
- Ecobee SmartSensor (Room Sensor) — 1x per additional room for multi-room temperature averaging
- Typical: 1 sensor in master bedroom, 1 in main living area
- Sensors report temperature and occupancy back to Ecobee and Control4

---

## SPECIALTY CLIMATE SYSTEMS

### Radiant Floor Heating (In-Floor)
- If radiant floor heating is installed, Symphony can integrate the thermostat/controller (Warmup, Schluter DITRA-HEAT, nVent Nuheat) into Control4
- Requires compatible Wi-Fi thermostat at each radiant zone
- Integration similar to standard thermostat; scene-based control available

### Steam Shower / Sauna
- Steam generators with Wi-Fi or RS-232 control (Mr. Steam, ThermaSol) can be integrated into Control4
- "Preheat Steam" button on Control4 panel or app triggers steam generator X minutes before use
- Safety: Steam controls require appropriate wiring and do not replace manufacturer safety devices

### Fireplace / Hearth Integration
- Gas fireplaces with switch-activated ignition or Skytech remote systems can be controlled via Control4 dry-contact relay
- "Fireplace On/Off" button added to Control4 panel and app
- Control4 relay module (RLY-4A) provides 4-channel dry-contact output for fireplace, AV equipment, and custom devices

### Whole-Home Ventilation / ERV / HRV
- ERV/HRV systems with wired control can be integrated via relay or thermostat integration
- Typically triggered on schedule or by occupancy/CO2 sensor

---

## STANDARD INCLUSIONS (Climate)

- All specified thermostats, installed and wired (24V control wiring to HVAC equipment)
- Ethernet/CAT6A cable to thermostat location for IP connectivity
- Control4 driver configuration and binding for all thermostat zones
- Scene integration (Away, Good Night, Welcome Home, etc.)
- Climate page on Control4 interfaces
- Ecobee app setup (separate from Control4 app — runs in parallel)

## STANDARD EXCLUSIONS (Climate)

- HVAC equipment of any kind (air handlers, furnaces, condensers, mini-splits)
- HVAC ductwork, refrigerant lines, or mechanical installation
- HVAC permits and mechanical inspections
- Humidifiers or dehumidifiers (available as optional integration if Wi-Fi capable)
- CO2 / air quality monitors (available as optional add; can trigger ventilation automation)
- Radiant boiler or in-floor heating equipment

---

## COMMON ASSUMPTIONS (Climate)

- HVAC equipment is installed, operational, and tested by HVAC contractor before Symphony connects thermostats.
- All HVAC systems provide a standard 24V R/C/Y/W/G control interface. Systems with proprietary control boards (some mini-splits) may require manufacturer-specific interface module — priced separately if applicable.
- A 24V "C" wire is available at each thermostat location. If C wire is not present (older systems), a Common Maker or Ecobee Power Extender Kit (PEK) may be used — included in scope.
- Client accepts that HVAC scheduling is managed via the Ecobee app or Control4 interface, not physical controls (thermostats will be configured for remote-control mode).
