# Symphony Smart Homes — Proposal Template Library
## Bob the Conductor Reference Index

**Version:** 1.0
**Created:** February 2026
**Purpose:** Complete template library for generating professional residential AV and smart home proposals.

---

## HOW BOB SHOULD USE THIS LIBRARY

### Step 1 — Start with the Master Template
Open `proposal_master_template.md`. This is the full proposal structure. Every section has `{{VARIABLE}}` placeholders and inline `<!-- BOB INSTRUCTIONS: -->` comments explaining what to fill in.

### Step 2 — Select Scope Blocks
Based on which systems are in the project, pull the relevant scope blocks from `scope_blocks/`. Each block provides detailed technical language, product selection guidance, and standard inclusions/exclusions.

### Step 3 — Select Room Configs
For each room in the project, pull the appropriate tier (Good/Better/Best) from `room_configs/`. Use the equipment tables to populate Section 7 (Equipment Summary) and the scope descriptions to populate Section 3 (Scope of Work).

### Step 4 — Populate Assumptions & Exclusions
Pull relevant items from `assumptions_exclusions.md` into Sections 5 and 6 of the proposal. Always include all "Core" items. Add system-specific and project-specific items as appropriate.

### Step 5 — Verify
- All `{{VARIABLES}}` replaced with real data
- Equipment in Section 7 matches scope described in Section 3
- Pricing in Section 9 rolls up correctly
- Assumptions in Section 5 match the project type (new construction vs. retrofit)

---

## FILE INDEX

### Core Documents

| File | Purpose |
|------|---------|
| `proposal_master_template.md` | Master proposal template — all 12 sections, all variables |
| `assumptions_exclusions.md` | Library of ~60 standard assumptions and exclusions |

### Scope Blocks (`scope_blocks/`)

| File | Systems Covered |
|------|----------------|
| `lighting_shades.md` | Lutron RadioRA 3, HomeWorks QSX, Caseta; motorized shades (Triathlon, Palladiom, Serena) |
| `audio_video.md` | Triad amplifiers, Snap One AV distribution, HDMI over IP, displays, projectors, home theater |
| `networking.md` | Araknis router/switch/WAPs, VLAN design, OvrC, structured cabling |
| `security_surveillance.md` | Luma cameras, NVR, door stations, video intercom, Control4 integration |
| `control_automation.md` | Control4 CORE/EA controllers, touch panels, remotes, integration scope, programming |
| `climate.md` | Ecobee/Nest thermostat integration, radiant floor, steam shower, Control4 climate control |

### Room Configs (`room_configs/`)

| File | Typical Budget Range (Equipment) |
|------|--------------------------------|
| `master_bedroom.md` | Good: $3,800–$5,500 / Better: $7,500–$10,500 / Best: $18,000–$35,000+ |
| `bedroom.md` | Good: $400–$900 / Better: $2,500–$4,500 / Best: $5,500–$9,000 |
| `kitchen.md` | Good: $1,200–$2,200 / Better: $4,500–$7,500 / Best: $10,000–$18,000 |
| `living_great_room.md` | Good: $4,500–$6,500 / Better: $14,000–$22,000 / Best: $40,000–$90,000+ |
| `theater_media_room.md` | Good: $18,000–$28,000 / Better: $45,000–$70,000 / Best: $90,000–$200,000+ |
| `dining_room.md` | Good: $600–$1,000 / Better: $2,800–$5,000 / Best: $6,500–$12,000 |
| `office_study.md` | Good: $800–$1,500 / Better: $2,500–$5,000 / Best: $6,000–$10,000 |
| `outdoor_patio.md` | Good: $1,200–$2,200 / Better: $6,500–$11,000 / Best: $18,000–$35,000+ |
| `entry_hallway.md` | Good: $800–$1,500 / Better: $3,000–$5,500 / Best: $7,000–$12,000 |
| `garage.md` | Good: $400–$800 / Better: $1,800–$3,200 / Best: $5,000–$9,000 |
| `bathroom.md` | Good: $250–$500 / Better: $2,200–$4,500 / Best: $5,500–$12,000 |
| `laundry_mud_room.md` | Good: $350–$700 / Better: $1,200–$2,200 / Best: $2,800–$5,000 |
| `mechanical_room.md` | Infrastructure — sized per project scale |

---

## PRODUCT BRANDS REFERENCE

| Brand | Category | Notes |
|-------|---------|-------|
| Control4 | Automation Platform | CORE 1/3/5, EA series; touch panels T3/T4; SR-260 remote |
| Lutron | Lighting & Shades | RadioRA 3 (mid-range), HomeWorks QSX (premium), Caseta (entry-level) |
| Snap One / Triad | AV Distribution, Amplifiers | Triad One/Eight/Sixteen amps; Binary HDMI-IP; WattBox power |
| Araknis | Networking | AN-310 series (standard), AN-510 series (advanced); OvrC remote management |
| Luma (Snap One) | Surveillance | Luma 310/510/710 cameras; NVR510 series |
| Apple | Source Devices | Apple TV 4K 4th gen (2022) — primary streaming source recommendation |
| Ecobee | Climate | Smart Thermostat Premium — primary thermostat recommendation |
| Schlage / Yale | Smart Locks | Schlage Encode Plus; Yale Assure Lock 2 |
| LiftMaster | Garage | 87504-267 (myQ-enabled) — Control4 certified |
| Samsung / LG / Sony | Displays | Samsung QLED/OLED, LG OLED, Sony BRAVIA — see audio_video.md |
| SunBrite | Outdoor Displays | Veranda series (covered), Pro series (full-sun) |
| 2N / Doorbird | Door Stations | 2N Helios IP Verso/Force — premium intercom |
| JVC / Sony / Epson | Projectors | See theater_media_room.md for full selection guide |
| Screen Innovations / Stewart | Projection Screens | See theater_media_room.md |

---

## COMMON PROJECT ARCHETYPES

### New Construction (Builder-Grade Smart Home)
**Typical scope:** Control4 CORE 3, Lutron RadioRA 3, Triad Sixteen, Araknis networking, Luma 8-camera surveillance, 4–6 TV zones, climate integration
**Estimated project value:** $85,000 – $150,000

### New Construction (Luxury Custom Home)
**Typical scope:** Control4 CORE 5, Lutron HomeWorks QSX, Palladiom shades throughout, Triad Gold speakers, dedicated theater, Araknis full estate networking, 12+ camera system
**Estimated project value:** $200,000 – $500,000+

### Retrofit (Whole-Home)
**Typical scope:** Control4 CORE 3, Lutron RadioRA 3 (wireless), Caseta in less critical areas, Triad Eight, Araknis networking, Luma 6-camera system
**Estimated project value:** $45,000 – $90,000

### Retrofit (Targeted AV Upgrade)
**Typical scope:** Living room surround sound, master bedroom AV, outdoor speakers, Araknis networking refresh
**Estimated project value:** $15,000 – $40,000

### Condo / Apartment
**Typical scope:** Control4 CORE 1 or CORE 3, Lutron Caseta, Triad Eight or Triad One per room, Araknis networking
**Estimated project value:** $10,000 – $35,000

---

## NOTES FOR BOB

1. **Never invent model numbers** — if a model is not in this library and you’re not certain it’s current, use the closest listed equivalent and flag for human review.

2. **Labor rates** — Typical Symphony labor rate is `${{LABOR_RATE}}/hr`. Programming rates may differ. Confirm with Symphony management before generating pricing.

3. **Lead times** — Lutron engraved keypads: 4–6 weeks. Motorized shades (Palladiom/Triathlon): 6–10 weeks. Control4 and Snap One equipment: 2–5 business days typically. Flag any lead-time-sensitive items in the proposal when schedule is tight.

4. **Tax rates** — Apply equipment sales tax at the rate for `{{CLIENT_STATE}}`. Confirm whether labor is taxable in the project state (varies by jurisdiction).

5. **Proposal review** — Every AI-generated proposal should be reviewed by a Symphony salesperson before sending to a client. The AI generates the structure and language; a human confirms scope accuracy, pricing, and client-specific customizations.
