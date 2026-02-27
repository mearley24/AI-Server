# Scope Block: Control4 Home Automation
<!-- BOB INSTRUCTIONS: Use this block to populate the Control4 automation sections of the proposal. Every Symphony Smart Homes project that includes automation should reference this block. Select the appropriate controller, interfaces, and integration scope for the project. -->

---

## SYSTEM DESCRIPTION

Control4 is the automation platform of choice for Symphony Smart Homes projects — a professional-grade, dealer-installed system trusted in over 500,000 homes and businesses worldwide. Unlike DIY systems, Control4 provides true device interoperability, local processing (not cloud-dependent for basic functions), and a unified interface across all rooms and all devices.

Control4 acts as the central orchestration layer — connecting Lutron lighting, Triad audio, IP cameras, thermostats, smart locks, garage doors, and hundreds of other devices into a single, intuitive experience on a wall panel, handheld remote, or mobile app.

---

## CONTROLLER SELECTION GUIDE

### Control4 CORE Series (Current Generation)

| Model | Processing | Connections | Max Devices | Best For |
|-------|-----------|-------------|-------------|----------|
| Control4 CORE 1 | Entry | Ethernet, USB | ~30 devices | Small home, 1–2 room retrofit, condo |
| Control4 CORE 3 | Mid-range | Ethernet, USB, RS-232, IR | ~100 devices | Standard 3–5 bedroom home |
| Control4 CORE 5 | High-performance | Ethernet, USB, RS-232 x2, IR | ~200+ devices | Large home, 6+ bedrooms, complex integrations |

*Note: Control4 EA (EA-1, EA-3, EA-5) are the prior generation (still fully supported and capable). EA-3 and EA-5 remain strong choices for projects where the CORE series is unavailable. EA-1 ≈ CORE 1, EA-3 ≈ CORE 3, EA-5 ≈ CORE 5.*

### Controller Selection Decision Guide:
- ≤ 3 rooms, basic lighting + AV: **CORE 1**
- 3–5 bedrooms, standard whole-home automation: **CORE 3** *(most common selection)*
- 6+ bedrooms, multiple systems, theater, estate: **CORE 5**
- Multi-controller or director redundancy: **CORE 5 + CORE 3 (slave)**
- Audio-only controller (for additional audio zones): **CA-1 Audio Controller**

### Additional Processing Modules (as needed):
| Module | Purpose |
|--------|----------|
| Control4 CA-1 Audio Controller | Adds 2 additional audio zones / amplifier channels |
| Control4 C2-AMP | 40W x 2 integrated amplifier for single zone |
| Control4 4K Audio Video Switch | HDMI 2.0b matrix (4x4) for smaller AV systems |

---

## TOUCH SCREENS & INTERFACES

### In-Wall Touch Panels

| Model | Screen | Display | Features | Best For |
|-------|--------|---------|----------|---------|
| Control4 T3 Series (6") | 6" LCD | 1024x600 | Standard, full-color touchscreen | Bedrooms, hallways, secondary rooms |
| Control4 T3 Series (7") | 7" LCD | 1024x600 | Slightly larger format | Wider wall box openings |
| Control4 T4 Series (7") | 7" IPS | 1280x800 | Full HD, improved visuals, faster UI | All rooms — current standard |
| Control4 T4 Series (10") | 10" IPS | 1920x1200 | Full HD, statement installation | Entry, kitchen, main living areas |
| Control4 T4 Series (10" Flush) | 10" IPS | 1920x1200 | Flush-mount, premium aesthetic | Kitchen, entry, high-visibility locations |

*Symphony's standard specification: T4 7" in bedrooms and secondary rooms; T4 10" at primary locations (entry, kitchen, main living, master bedroom entry).*

### Handheld Remotes

| Model | Type | Best For |
|-------|------|----------|
| Control4 SR-260 | RF/IR universal remote | Primary TV rooms, hands-on AV control |
| Control4 SR-150 | RF/IR simplified remote | Clients who want simpler remote |
| Neeo Remote (Control4 OEM) | Touchscreen remote | Premium feel, touchscreen display |

*Each AV room typically receives one SR-260. Bedrooms and non-primary rooms may use Pico or app control instead.*

### Mobile App

- **Control4 app (iOS / Android / Amazon Fire)** — included with every system
- Full system control from anywhere with internet connectivity
- Remote access requires **4Sight subscription** (see Exclusions)
- Push notifications for doorbell, security, and automation events
- App setup on up to {{APP_DEVICE_COUNT}} client devices during commissioning

### Keypads & Tabletop

| Model | Type | Use Case |
|-------|------|----------|
| Lutron Pico (via lighting platform) | Scene control | Nightstands, secondary control points |
| Control4 Wireless Keypad | 6-button RF keypad | Secondary control points; nightstand, bedside |
| Control4 Tabletop Touch 7" | 7" IPS tabletop | Coffee table, nightstand — portable tablet-style |

---

## INTEGRATION SCOPE

### Systems Integrated in This Project

<!-- BOB INSTRUCTIONS: Check all that apply and include relevant detail below. Delete inapplicable rows. -->

| System | Integration Method | Driver |
|--------|------------------|--------|
| Lutron RadioRA 3 | IP (via Lutron bridge) | Certified C4 driver |
| Lutron HomeWorks QSX | IP | Certified C4 driver |
| Lutron Caseta | IP (via Smart Bridge Pro) | Certified C4 driver |
| Triad Audio (amplifiers) | IP | Certified C4 driver |
| Apple TV (4th gen+) | IP (TUDN/HDMI CEC) | Certified C4 driver |
| Luma Surveillance NVR | IP (RTSP/ONVIF) | Certified C4 driver |
| Ecobee Smart Thermostat | IP | Certified C4 driver |
| Nest Learning Thermostat | IP | C4 driver |
| Honeywell/Resideo T6 Pro | IP | C4 driver |
| Schlage Encode Plus | Z-Wave or IP | C4 driver |
| Yale Assure Lock 2 | Z-Wave or IP | C4 driver |
| LiftMaster MyQ | IP | C4 driver |
| Chamberlain MyQ | IP | C4 driver |
| 2N Door Station | IP (SIP) | C4 driver |
| Luma IP Doorbell | IP | C4 driver |
| Sony/JVC/Epson Projector | IP or RS-232 | Certified C4 driver |
| Denon/Marantz AVR | IP or RS-232 | Certified C4 driver |
| Samsung Smart TV | IP (SmartThings) | C4 driver |
| LG Smart TV | IP (webOS) | C4 driver |
| Araknis Networking | IP/OvrC | OvrC integration |
| HVAC (via thermostat) | Per thermostat driver | Two-way status + setpoint control |

---

## PROGRAMMING DELIVERABLES

### Control4 System Programming

**Interfaces & Navigation**
- Custom home screen with room-based navigation (every room accessible in ≤2 taps)
- Dedicated control pages: Lighting, AV / Sources, Climate, Cameras, Security, Garage
- Consistent interface on all touch panels, remotes, and app
- Room list with all active rooms and quick-access icons

**Lighting Scenes (from Lutron scope block)**
- Programmed as described in lighting_shades.md
- All scenes accessible from Control4 interfaces and triggered via keypads/schedules

**AV Macros (from AV scope block)**
- One-touch Watch/Listen macros per room
- Theater macro sequence (screen, projector, receiver, lighting)
- All-Off macro (whole-home or per-room)

**When >> Then Automations**
Symphony's standard automation set (customize per project):

| Trigger | Condition | Action |
|---------|-----------|--------|
| Doorbell pressed | Any time | All panels show camera, audible chime |
| Front door opens | After sunset | Entry lights on at 80% |
| Garage door opens | After sunset | Mudroom/kitchen lights on at 80% |
| Last person leaves (geofence) | Away mode | HVAC to away setpoint, all lights off, send notification |
| First person arrives (geofence) | Home mode | Lights to welcome scene, HVAC to comfort |
| Good Night keypad press | Any time | All lights off, shades to blackout, thermostat -2°, doors locked, confirmation status sent to app |
| Wake time (schedule) | Weekdays / weekends | Bedroom lights ramp to 30%, shades open, thermostat to wake setpoint |
| Intrusion alarm triggered | If alarm integrated | All lights to 100%, notification to app, cameras start recording |
| {{CUSTOM_AUTOMATION}} | {{CONDITION}} | {{ACTION}} |

**Schedules**
- Sunrise/sunset dynamic scheduling (adjusts daily based on location — no manual updates needed)
- Outdoor lighting on/off at dusk/dawn
- Shade open/close schedule (sunrise open, sunset privacy)
- HVAC schedules (home, sleep, away)
- {{CUSTOM_SCHEDULE}}

**Driver Licensing**
Control4 uses a driver licensing model. Symphony includes licensing for all certified drivers needed for specified integrations. Third-party drivers (non-Snap One marketplace) may require annual license fees — disclosed prior to installation.

---

## STANDARD INCLUSIONS (Control4 Automation)

- Control4 controller (model per scope)
- All in-wall touch panels, remotes, and keypads per specification
- Control4 4Sight remote access — first year included
- All certified driver licenses for specified integrations
- System programming (as described above)
- Client app setup on up to {{APP_DEVICE_COUNT}} devices
- System documentation (device list, IP table, programming notes)
- 30-day post-commissioning support (phone/remote)

## STANDARD EXCLUSIONS (Control4 Automation)

- Control4 4Sight subscription renewal after first year (~$99/year — billed direct by Snap One)
- Non-certified third-party driver licensing (quoted per driver if required)
- Programming changes after client sign-off on programming spec (available at hourly rate)
- Integration of systems not listed in scope (available as additional scope items)
- Physical networking infrastructure (see networking scope block)
- Rack furniture or custom rack enclosures (see rack/infrastructure scope block)

---

## COMMON ASSUMPTIONS (Control4)

- Network infrastructure (managed switch, router, Wi-Fi) is installed and operational before Control4 programming begins. Control4 requires a stable, managed network with VLANs per networking scope block.
- Client will designate a primary "admin" user for the Control4 system. Symphony will configure one admin account and up to {{USER_COUNT}} standard user accounts.
- All third-party devices to be integrated are powered, connected to the network, and accessible via their native apps before Control4 programming.
- Programming spec (room list, scene names, automation triggers) to be approved by client before programming begins. Changes after approval may require additional programming time.
- Major OS upgrades after commissioning may require paid reprogramming time.
