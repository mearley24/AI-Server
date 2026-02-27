# Scope Block: Security & Surveillance
<!-- BOB INSTRUCTIONS: Use this block to populate the security and surveillance sections of the proposal. Symphony specializes in IP-based surveillance (Luma cameras + NVR), door stations, and smart lock integration. Symphony does NOT install monitored burglar alarm systems — refer clients who need monitoring to a licensed alarm company. -->

---

## SYSTEM DESCRIPTION

Symphony Smart Homes installs professional IP surveillance systems using Luma Surveillance (Snap One's professional camera brand), integrated into the Control4 automation platform for unified camera viewing, door station answering, and event-based recording triggers. All camera feeds are stored locally on a network video recorder (NVR) — no mandatory cloud subscription required.

---

## IP CAMERA SYSTEM

### Luma Camera Selection Guide

**Indoor Dome Cameras:**

| Model | Resolution | FOV | Best For |
|-------|-----------|-----|----------|
| Luma 310 IP Dome (LUM-310-DOM-IP) | 2MP (1080p) | 103° | Budget indoor, hallways, stairwells |
| Luma 510 IP Dome (LUM-510-DOM-IP) | 4MP (2688x1520) | 110° | Standard indoor coverage |
| Luma 510 IP Turret (LUM-510-TUR-IP) | 4MP | 103° | Ceiling-mount, wide coverage |
| Luma 720 IP Dome (LUM-720-DOM-IP) | 4K (8MP) | 103° | Premium indoor, detailed coverage |

**Outdoor Bullet / Dome Cameras:**

| Model | Resolution | FOV | IR Range | Best For |
|-------|-----------|-----|----------|----------|
| Luma 310 IP Bullet (LUM-310-BUL-IP) | 2MP | 102° | 100 ft | Entry-level exterior, driveway |
| Luma 510 IP Bullet (LUM-510-BUL-IP) | 4MP | 93° | 165 ft | Standard exterior, perimeter |
| Luma 510 IP Eyeball (LUM-510-EYE-IP) | 4MP | 103° | 98 ft | Eave-mount, angled views |
| Luma 720 IP Bullet (LUM-720-BUL-IP) | 4K (8MP) | 102° | 165 ft | Premium exterior, long-range |
| Luma 720 IP Dome (LUM-720-DOM-WH-IP) | 4K (8MP) | 105° | 98 ft | Outdoor dome, vandal-rated |

**PTZ Cameras (Pan / Tilt / Zoom):**

| Model | Resolution | Zoom | Best For |
|-------|-----------|------|----------|
| Luma 510 PTZ (LUM-510-PTZ-IP) | 4MP | 18x optical | Driveways, large properties, gates |
| Luma 720 PTZ (LUM-720-PTZ-IP) | 4K | 32x optical | Estate, large perimeter, commercial |

---

### Camera Placement Guidelines

**Priority 1 — Always Covered:**
- Front door (entry coverage + doorbell camera or door station)
- Driveway / garage approach
- Back door and primary secondary entrances
- Garage interior (if client requests)

**Priority 2 — Standard Coverage:**
- Side gates and yard perimeter
- Pool deck and backyard
- Driveway full length (if longer than 50 ft)
- Basement or ground floor windows (high-crime areas)

**Priority 3 — Optional / Client Request:**
- Interior hallways and common areas
- Nursery / children's rooms
- Gym, wine cellar, safe room
- Boat dock, detached structures

---

## NETWORK VIDEO RECORDER (NVR)

### Luma NVR Selection Guide

| Model | Channels | Max Resolution | Storage | Best For |
|-------|---------|---------------|---------|----------|
| Luma 510 NVR 8-ch (LUM-510-NVR-8N) | 8 cameras | 4K | 2TB HDD | Small system, up to 8 cameras |
| Luma 510 NVR 16-ch (LUM-510-NVR-16N) | 16 cameras | 4K | 4TB HDD | Standard system, up to 16 cameras |
| Luma 510 NVR 32-ch (LUM-510-NVR-32N) | 32 cameras | 4K | 6TB HDD | Larger systems, estates |
| Luma 720 NVR 8-ch (LUM-720-NVR-8N) | 8 cameras | 4K (AI) | 4TB HDD | AI analytics, small system |
| Luma 720 NVR 16-ch (LUM-720-NVR-16N) | 16 cameras | 4K (AI) | 8TB HDD | AI analytics, standard system |

**Storage Capacity Notes:**
- 1TB ≈ 7–10 days of continuous recording at 1080p (8 cameras)
- 1TB ≈ 3–5 days of continuous recording at 4K (8 cameras)
- Motion-triggered recording extends retention significantly (2–4x)
- For 30-day retention: upgrade storage or enable motion-only recording

---

## DOOR STATIONS & ENTRY CONTROL

### Video Door Stations

| Model | Type | Integration | Best For |
|-------|------|------------|----------|
| 2N IP Solo (2N-IP-SOLO) | Surface mount, minimal design | SIP, Control4 driver | Clean modern aesthetic |
| 2N IP Verso (2N-IP-VERSO) | Modular (video + keypad + cards) | SIP, Control4 driver | Multi-tenant, offices, estate entry |
| 2N IP Force (2N-IP-FORCE) | Vandal-resistant, rugged | SIP, Control4 driver | Driveways, gates, exposed locations |
| Luma IP Doorbell (LUM-510-VDB-WH) | Doorbell form factor | RTSP, Control4 driver | Standard home use, doorbell replacement |
| Doorbird D101 | Flush-mount, premium | SIP + RTSP | Design-forward, flush installation |

**How it works with Control4:**
- Doorbell press triggers all Control4 panels to display live camera view
- Two-way audio from any panel or mobile app
- Door unlock command sent via dry-contact or IP relay (Araknis switch, Schlage, Yale)
- Event logged and snapshot saved to NVR

### Smart Locks

| Model | Protocol | Best For |
|-------|---------|----------|
| Schlage Encode Plus (BE489WB) | Wi-Fi + Apple HomeKey | Preferred — best Control4 + HomeKey integration |
| Yale Assure Lock 2 (YRD420) | Z-Wave or Wi-Fi | Alternative to Schlage, strong Control4 driver |
| Kwikset Halo Touch | Wi-Fi + fingerprint | Biometric option, good for client convenience |
| August Wi-Fi Smart Lock (4th Gen) | Wi-Fi | Retrofit option (keeps existing deadbolt hardware) |

**Integration Notes:**
- Smart locks integrate into Control4 "Good Night" and "Away" scenes (auto-lock)
- Lock/unlock events trigger notifications in the Control4 app
- Access codes managed from Control4 interface or lock's native app
- Physical key backup always required per Symphony policy

---

## CONTROL4 INTEGRATION

### Camera Viewing:
- Live camera feeds accessible on all Control4 touch panels and mobile app
- Doorbell press auto-routes camera feed to panels (pop-up on ring)
- Camera grid view (4-up or 9-up) accessible from Security page
- Camera feeds accessible remotely via Control4 app (4Sight required)

### Recording Triggers:
- Motion detection → camera starts recording (standard)
- Doorbell press → NVR snapshot + 30-second clip saved
- Alarm trigger → all cameras switch to continuous recording
- Schedule-based recording (e.g., record exterior cameras 11pm–6am)

### Access Control:
- Front door lock status visible on all panels
- "Lock All Doors" button in Good Night scene
- "Unlock Front Door" button accessible from doorbell camera pop-up
- Guest PIN management from Control4 interface

---

## STANDARD INCLUSIONS (Security & Surveillance)

- All Luma IP cameras, installed and aimed per placement plan
- All CAT6A camera cabling from each camera location to equipment rack
- NVR installed, configured, and commissioned in equipment rack
- Camera feeds added to Control4 (Security page, doorbell pop-up)
- NVR remote access setup (Luma app + Control4 app)
- 2N or Luma door station, installed and integrated with Control4
- Smart lock installation and Control4 binding
- Scene integration: Good Night (lock), Away (lock + notify), Welcome Home (unlock option)
- Camera placement plan provided before installation
- Post-install recording verification (all cameras recording, all feeds verified)

## STANDARD EXCLUSIONS (Security & Surveillance)

- Monitored burglar alarm systems (ADT, Vivint, etc.) — Symphony does not provide alarm monitoring
- Alarm panel installation or integration with monitored alarm (available as optional if client has existing system)
- Access control for multi-tenant or commercial entry (card readers, badge systems)
- Additional NVR storage beyond what is specified (available as add-on upgrade)
- Outdoor conduit or weatherproof camera enclosures not standard (available if required)
- Any cabling through masonry, tile, or finished concrete without client authorization
- Video analytics subscriptions (AI-based person/vehicle detection may require subscription on some NVR models)

---

## COMMON ASSUMPTIONS (Security & Surveillance)

- All cameras are IP-based (no analog CCTV); client acknowledges that existing analog CCTV infrastructure is not reusable.
- Camera locations are agreed upon in the camera placement plan before installation begins; relocating cameras after cabling requires additional labor charges.
- NVR is located in the main equipment rack; if a secondary NVR location is required, that is a separate line item.
- All camera cabling is CAT6A run during rough-in phase. Cameras added after construction (retrofit) are priced at retrofit labor rates.
- Client is responsible for understanding local laws and HOA rules regarding camera placement and recording on their property.
