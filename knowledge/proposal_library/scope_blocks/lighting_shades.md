# Scope Block: Lutron Lighting & Shade Control
<!-- BOB INSTRUCTIONS: Use this block to populate the lighting and shade sections of the proposal. Choose the appropriate Lutron platform (RadioRA 3, HomeWorks QSX, or Caseta) based on project size and client budget. This block covers all Lutron platforms Symphony installs. -->

---

## SYSTEM DESCRIPTION

Symphony Smart Homes uses Lutron as its exclusive lighting control platform. Lutron is the industry gold standard for reliability, dimming performance, and smart home integration — trusted by architects, interior designers, and custom integrators for over 60 years.

All Lutron systems integrate natively with Control4 via certified two-way drivers, enabling scene control, scheduling, and automation from any Control4 interface.

---

## PLATFORM SELECTION GUIDE

### RadioRA 3 (Mid-Range Residential)
**Best for:** 2,000–8,000 sq ft homes | 20–150 devices | 3–6 bedroom homes

- Wireless RF mesh system — no dedicated wiring between devices
- Up to 200 devices per system; expandable with additional bridges
- Full dimming, occupancy sensing, daylight harvesting
- Clear Connect Type X RF protocol (most robust wireless lighting system available)
- Integrates with Control4, Alexa, Google Home, Apple HomeKit
- Typical install timeline: 1–2 days for standard homes

**Devices available:** Dimmers, switches, fan speed controllers, in-wall keypads (Sunnata series), tabletop keypads, occupancy sensors, daylight sensors, plug-in lamp dimmers, plug-in switches

---

### HomeWorks QSX (High-End Residential / Commercial)
**Best for:** 5,000+ sq ft | 50–2,000+ devices | Estates, multi-dwelling, commercial

- Wired + wireless hybrid system using Lutron's proprietary QS bus
- Requires dedicated home run wiring from each device to processor
- Highest reliability and performance — no range limitations
- Supports Sivoia QS motorized shades (native integration)
- Architectural keypads (seeTouch, Palladiom) with engraved or printed labels
- Required for projects with 150+ devices or where maximum reliability is mandated
- Programming via Lutron's HW Designer software

**Devices available:** HW dimmers, switches, keypads (seeTouch, Palladiom), GRAFIK Eye QS zone controllers, QSE-CI-NWK-E network interface, occupancy sensors, motorized shade interfaces

---

### Caseta (Entry-Level Smart Home)
**Best for:** < 2,000 sq ft | Under 75 devices | Retrofit or starter systems

- Wireless system using Lutron's Clear Connect RF protocol
- Simple installation — works with existing standard wiring
- Integrates with Control4 via Smart Bridge Pro
- Lower cost per point vs. RadioRA 3
- Pico remotes included with most kits — great for secondary control points
- Ideal for rental properties, condos, smaller homes, or budget-conscious builds

**Devices available:** Caseta dimmers, switches, fan speed controllers, plug-in dimmers, Pico remotes, Smart Bridge Pro, occupancy sensors

---

## LIGHTING SCOPE BY AREA

### Room-by-Room Lighting Control

*Fill in from project walkthrough notes or floor plan. BOB: Use {{ROOM}} placeholders for variable content.*

| Room | Load Type | Dimmer/Switch Model | Keypad | Notes |
|------|-----------|--------------------|---------|---------|
| Entry / Foyer | LED downlights (4–6 loads) | Lutron {{PLATFORM}} Dimmer | 6-button keypad | Scene: Welcome, All Off |
| Great Room | LED downlights, cove, accent | Lutron {{PLATFORM}} Dimmer x3 | 6-button keypad | Scene: Entertain, Movie, All Off |
| Kitchen | Under-cabinet, pendants, downlights | Lutron {{PLATFORM}} Dimmer x2 | 4-button keypad | Scenes: Bright, Cook, Evening |
| Dining Room | Chandelier (dimmed), accent | Lutron {{PLATFORM}} Dimmer x2 | 4-button keypad | Scene: Dinner, Candle, Bright |
| Master Bedroom | Overhead, nightstand lamps, accent | Lutron {{PLATFORM}} Dimmer x2 | 4-button keypad + Pico nightstand | Scenes: Evening, Sleep, Wake |
| Master Bath | Overhead, vanity | Lutron {{PLATFORM}} Dimmer x2 | 2-button keypad or Pico | — |
| Bedroom 2 | Overhead, nightstand | Lutron {{PLATFORM}} Dimmer | Pico | — |
| Bedroom 3 | Overhead, nightstand | Lutron {{PLATFORM}} Dimmer | Pico | — |
| Office / Study | Overhead, desk | Lutron {{PLATFORM}} Dimmer | 4-button keypad | — |
| Home Theater | Overhead, sconces, step lights | Lutron {{PLATFORM}} Dimmer | 6-button keypad | Scenes: Watch, Intermission, Bright, All Off |
| Garage | LED strip, overhead fluorescent/LED | Switch (non-dim) | — | Motion-activated optional |
| Exterior / Landscape | Pathway, flood, uplighting | Lutron {{PLATFORM}} Dimmer or Switch | — | Timer/astronomical schedule |
| Mechanical/Utility | Switch | Switch | — | — |

---

## SHADE CONTROL

### Lutron Motorized Shades (Sivoia QS / Palladiom / Ketra)

Symphony specifies Lutron motorized shades for all motorized shade scopes where the client is also using Lutron lighting. This allows native integration and shared keypad scenes between shading and lighting.

**Shade Platform Selection:**

| Platform | Best For | Motor Type | Control |
|---------|---------|------------|----------|
| Sivoia QS (wire-wound) | Integrated with HomeWorks QSX | QS bus wired motor | Keypad + Control4 |
| Sivoia QS Wireless | RadioRA 3 integration | Battery or hardwired RF motor | Keypad + Control4 |
| Lutron Palladiom (RF sheer/blackout) | Premium rooms, clean aesthetics | Hardwired RF motor | Keypad + Control4 |
| Lutron Serena | Entry-level wireless shading | Battery motor | App, Pico, Caseta bridge |

**Shade Types:**

| Type | Openness | Use Case |
|------|---------|----------|
| Solar Sheer (3% openness) | High | Daytime privacy with view retention |
| Blackout Roller | 0% | Master bedroom, home theater, media room |
| Sheer Woven Wood | Medium | Natural aesthetic, casual rooms |
| Automated Honeycomb / Cellular | Medium-Low | Energy efficiency, nurseries |
| Exterior Solar | High | Covered patios, pergolas |

### Shade Scope by Room:

| Room | Shade Type | Motor | Integration |
|------|-----------|-------|-------------|
| Great Room | Solar Sheer | Sivoia QS Wireless | Lutron + Control4 |
| Master Bedroom | Blackout Roller | Sivoia QS Wireless | Lutron + Control4 |
| Master Bedroom | Solar Sheer (layered) | Sivoia QS Wireless | Lutron + Control4 |
| Dining Room | Solar Sheer | Sivoia QS Wireless | Lutron + Control4 |
| Home Office | Solar Sheer | Sivoia QS Wireless | Lutron + Control4 |
| {{ADDITIONAL_ROOMS}} | {{SHADE_TYPE}} | {{MOTOR_TYPE}} | {{INTEGRATION}} |

---

## SCENES & PROGRAMMING

### Standard Scene Set Per Room

| Scene Name | Lighting Level | Shade Position | Notes |
|-----------|--------------|----------------|-------|
| Bright | 100% | Open | Daytime task lighting |
| Daytime | 70-80% | Open | Standard daytime |
| Evening | 40-60% | Closed (privacy) | After sunset default |
| Entertain | 60-80% | Open or 50% | Social settings |
| Dinner | 40% | Closed | Dining scenes |
| Movie / Watch | 10-20% | Closed (blackout) | Theater-adjacent rooms |
| Sleep | Off (or 0%) | Closed (blackout) | Bedroom sleep mode |
| Wake | Ramp to 30% | Open (gradual) | Morning wake |
| All Off | Off | No change | Whole-room off |

### Whole-Home Scenes (Keypad or Control4 trigger):

| Scene | Lights | Shades | HVAC | Doors |
|-------|--------|--------|------|-------|
| Good Morning | 30%, ramped over 5 min | Open (bedrooms) | Wake setpoint | — |
| Leave / Away | Off | 50% (privacy) | Away setpoint | Lock |
| Welcome Home | Entry 80%, main areas 70% | Open | Comfort setpoint | Unlock (optional) |
| Good Night | Off | Closed (blackout, bedrooms) | Sleep setpoint | Lock |
| Entertain | 60-80% (main areas) | 50% (evening) | Comfort | — |
| Vacation | Off (with random simulation optional) | Closed | Eco setpoint | Lock |

---

## STANDARD INCLUSIONS (Lighting & Shades)

- All specified Lutron dimmers, switches, keypads, and sensors
- All specified motorized shade motors and fabric
- Standard installation: wire/mount all devices per plan
- Lutron system programming (scenes, schedules, keypad engraving)
- Control4 driver configuration and two-way binding
- Astronomical scheduling for exterior lights and shades
- Client walkthrough of lighting and shade operation
- Keypad engraving (standard labels; custom engraving available as option)

## STANDARD EXCLUSIONS (Lighting & Shades)

- Electrical panels, circuits, or wiring beyond device connections
- Non-Lutron smart switches or dimmers (Symphony does not mix platforms within a system)
- Custom keypad engraving beyond standard labels (available as option)
- Window treatment hardware (curtain rods, tracks) not required for Lutron shades
- Drapery motors or curtain tracks (Symphony specializes in roller/solar shade systems; drapery track motors available as optional)
- Paint or drywall patching after installation
- Fan controls on non-Lutron-compatible ceiling fans
- LED driver or fixture modifications required for compatibility with Lutron dimmers — Symphony will identify during site survey; cost of LED driver changes or fixture swaps is excluded unless specified

---

## COMMON COMPATIBILITY NOTES

- Lutron dimmers are not compatible with all LED fixtures. Symphony performs a compatibility check at site survey and provides a compatibility report before finalizing scope.
- Lutron Caseta and RadioRA 3 systems cannot be mixed on the same project (different RF protocols). Select one platform per project.
- HomeWorks QSX and RadioRA 3 can coexist if properly configured (rare; consult engineering).
- Sivoia shade motors must match the Lutron platform in use. QS motors for HomeWorks QSX; RF wireless motors for RadioRA 3; Serena for Caseta.
- Track lighting systems (most are not dimmer-compatible without specific track heads)
