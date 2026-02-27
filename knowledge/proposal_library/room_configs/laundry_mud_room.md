# Room Config: Laundry / Mud Room
<!-- BOB INSTRUCTIONS: Laundry and mud rooms are often overlooked in home technology but have practical automation opportunities. Smart lighting (motion-activated), appliance status notifications (washer/dryer done), and access control (if adjacent to garage) are the key wins here. Keep scopes lean in these rooms. -->

---

## TYPICAL SYSTEMS IN THIS ROOM

- Lighting control (motion-activated or switch-based)
- Appliance integration (washer/dryer cycle complete notification)
- Access control (if mud room has entry from garage)
- Audio (optional — some clients like music in laundry area)

---

## GOOD TIER — Essential

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Lutron | RRST-W6A-WH (RadioRA 3) | On/Off switch — overhead lights (non-dimmable LED shop/utility lights common) |
| 1 | Lutron | RRK-3BRL-WH Pico | Pico for quick control or occupancy sensor trigger |

**Approx. Equipment Investment (Good):** $250 – $500

### Good Tier Notes
- Laundry room overhead lights are often non-dimmable utility LEDs — use switch not dimmer
- No audio or AV at this tier
- Washer/dryer notifications at this tier: use native app on phone (Samsung SmartThings, LG ThinQ) rather than Control4 integration

---

## BETTER TIER — Recommended

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Lutron | RRST-W6A-WH (RadioRA 3) | On/Off switch — overhead lights |
| 1 | Lutron | RRLK-3BRL-WH | 3-button keypad (Lights, All Off, Away) |
| 1 | Control4 | HC-250 or EA-1 driver-only | Smart plug or Z-Wave outlet monitor for washer/dryer power monitoring |

**Approx. Equipment Investment (Better):** $500 – $1,200

### Better Tier Notes
- Power monitoring on washer or dryer: Control4 detects when power drops below threshold (cycle complete) — sends push notification "Laundry Done!"
- Extremely popular with clients once they experience it
- Mud room entry: if adjacent to garage, "Arriving Home" scene can turn on lights automatically when garage door opens

---

## BEST TIER — Premium Mud Room / Entry Drop Zone

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Lutron | RRD-6ND-WH (RadioRA 3) | Dimmer — overhead/decorative light fixture |
| 1 | Lutron | RRLK-3BRL-WH | 3-button keypad |
| 1 | Schlage | Encode Plus | Smart deadbolt — mud room/garage entry door |
| 2 | Polk Audio | RC80i | In-ceiling speakers (laundry + mud room zone) |
| 1 | Triad | Triad One | Amplifier channel |

**Approx. Equipment Investment (Best):** $1,800 – $3,200

### Best Tier Notes
- Smart lock on mud room entry: integration with "Arriving Home" scene
- In-ceiling speakers: clients like music while doing laundry
- Dimmer appropriate if overhead is a decorative fixture; use switch for utility fluorescent/shop lights

---

## COMMON CLIENT REQUESTS — LAUNDRY / MUD ROOM

- **"Can I get a notification when the laundry is done?"** → Yes — Control4 power monitoring on washer outlet detects cycle completion. Push notification to phone.
- **"I want the lights to come on when I walk into the laundry room"** → Motion sensor (Lutron occupancy sensor or Control4 driver with third-party sensor) triggers lights on entry, turns off after 5 minutes of no motion.
- **"The mud room has a door to the garage — can the lights come on automatically?"** → Yes — garage door open trigger → mud room lights on.
