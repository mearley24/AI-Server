# Room Config: Garage
<!-- BOB INSTRUCTIONS: Garage integration is primarily about door status monitoring, safety automation, and lighting. Smart garage door openers are a client favorite because of the anxiety-reducing "Did I leave the garage open?" automation. AV in garages is increasingly requested in workshop/hobby garages. -->

---

## TYPICAL SYSTEMS IN THIS ROOM

- Lighting control (LED shop lights — usually non-dimmable)
- Garage door opener integration (smart)
- Surveillance camera (interior + exterior approach)
- Audio (workshop/hobby use — optional)
- Vehicle detection (optional — for security awareness)
- EV charger monitoring (optional — out of Symphony scope for hardware; integration only)

---

## GOOD TIER — Essential

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | LiftMaster | 87504-267 (with WiFi/myQ) | Smart garage door opener with myQ |
| 1 | Lutron | RRST-W6A-WH (RadioRA 3) | On/Off switch — garage overhead lights (LED shop lights are non-dimmable) |

**Approx. Equipment Investment (Good):** $400 – $800

### Good Tier Notes
- LiftMaster myQ integrates with Control4 via certified driver — open/close/status
- Automation: "If garage door is open after 10pm → send notification and optionally close"
- Automation: "When garage door opens, turn on mudroom lights"

---

## BETTER TIER — Recommended

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | LiftMaster | 87504-267 OR Chamberlain myQ + Control4 integration | Smart garage door opener |
| 1 | Lutron | RRST-W6A-WH (RadioRA 3) | Switch — garage lighting |
| 1 | Lutron | RRLK-3BRL-WH | 3-button keypad inside garage (All On, All Off, Lock) |
| 1 | Luma | 510 Dome | Interior garage camera — ceiling mount |
| 1 | Luma | 510 Bullet | Exterior — driveway/garage approach |

**Approx. Equipment Investment (Better):** $1,800 – $3,200

### Better Tier Notes
- Interior camera: captures vehicle presence and contents
- Exterior driveway camera: license plate legibility at approach
- Keypad inside garage: useful for quick control when entering/leaving

---

## BEST TIER — Premium / Workshop / Hobby Garage

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 2 | LiftMaster | 87504-267 (per door bay) | Smart garage door opener per bay |
| 1 | Lutron | RRST-W6A-WH (RadioRA 3) x2–3 | Switches — garage lighting zones |
| 1 | Lutron | RRLK-3BRL-WH | 3-button keypad |
| 2 | Luma | 510 Dome | Interior camera per bay |
| 1 | Luma | 510 PTZ or 510 Bullet | Exterior driveway / approach — wide angle |
| 2 | Polk Audio | Atrium 8 SDI or Klipsch AW-650 | Outdoor/garage-rated speakers |
| 1 | Triad | Triad Eight channel (head-end amp) | Garage audio zone |
| 1 | Samsung | QN43QN85B (43") or SunBrite Veranda 43" | Garage workshop TV (weatherproof if not conditioned) |
| 1 | Apple | Apple TV 4K (4th gen, 2022) | Streaming source |

**Approx. Equipment Investment (Best):** $5,000 – $9,000

### Best Tier Notes
- Workshop/hobby garage owners frequently want music and TV — this makes the garage genuinely enjoyable
- If garage is conditioned (heated/cooled): standard TV acceptable. If not conditioned: SunBrite Veranda or equivalent temperature-rated display recommended
- Acoustic speakers are splash/dust-rated (Atrium 8 is IP66)
- Multiple garage bays each get their own LiftMaster unit and camera

---

## CONTROL4 AUTOMATION — GARAGE

**"Garage Status" panel widget:**
- Open/Closed indicator visible on all Control4 panels and app
- Push notification if garage is open for >{{GARAGE_OPEN_TIMEOUT}} minutes

**Automation examples:**
- Garage opens → mudroom/entry lights on at 80%
- Garage opens (after 10pm) → send push notification
- "Leaving Home" scene button → close all garage doors + lock front door + arm alarm
- Garage door open at bedtime → "Good Night" keypad will prompt "Garage is open — close?" via Control4 notification
- Vehicle arrives/departs (via camera AI detection) → optional notification (requires compatible camera + Control4 driver)

---

## COMMON CLIENT REQUESTS — GARAGE

- **"I always forget if I closed the garage"** → Best feature in the product: status push notification + remote close from the app. Clients love this.
- **"Can it close automatically at night?"** → Yes — schedule a "Close Garage" at a specific time, or include in Good Night scene.
- **"Can it open when I pull up the driveway?"** → Geofence-based garage trigger available but can have false-positive issues (nearby streets, sensitivity). LiftMaster also offers dedicated in-car remote and myQ garage-open scheduling. Recommend manual trigger from app or dedicated button over automatic geofence open for safety.
- **"We have 3 garage bays"** → Each bay gets its own LiftMaster opener, camera, and Control4 binding. All visible on one "Garage" status page.
