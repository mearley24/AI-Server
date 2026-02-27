# Scope Block: Audio / Video Distribution
<!-- BOB INSTRUCTIONS: Use this block to populate the AV portions of Section 3 (Scope of Work) and Section 7 (Equipment Summary). Select the appropriate speaker types, source architecture, and distribution platform for the project. This block covers whole-home audio, video distribution, and source management. Home theater-specific scope is included at the bottom. -->

---

## SYSTEM DESCRIPTION

Symphony Smart Homes deploys Snap One's ecosystem for AV distribution, including Triad audio amplifiers, WattBox power management, and HDMI-over-IP video distribution. Sources (Apple TV, streaming media players, cable/satellite) are centralized in the equipment rack and distributed to any TV or speaker zone throughout the home, all controlled via the Control4 automation platform.

---

## AUDIO SYSTEM ARCHITECTURE

### Multi-Room Audio Platform: Triad (Snap One)

**Amplifier Selection Guide:**

| Model | Channels | Power | Best For |
|-------|---------|-------|---------|----|
| Triad One | 1 stereo zone | 60W x 2 | Single room, simple background music |
| Triad Eight | 4 stereo zones | 60W x 2/ch | 4-room system, equipment room install |
| Triad Sixteen | 8 stereo zones | 60W x 2/ch | 8-room system, primary whole-home amp |
| Triad Eight Sub | 4 zones + 1 sub | 60W x 2 / 200W sub | Zones with subwoofer output |
| External amp (Sonance, Crown) | Custom | As specified | High-power outdoor or dedicated zones |

**Matrix / Source Distribution:**
- Sources are fed from head-end rack to all amplifier inputs via analog audio or digital (HDMI/optical) connections
- For simple systems: Direct source connection to Triad amplifier inputs
- For larger systems: Snap One audio matrix or HDMI audio extraction from video matrix

---

## ROOM TYPES & AV CONFIGURATIONS

### Background Music Zone
**Description:** Stereo in-ceiling or in-wall speakers connected to a Triad amplifier channel. Provides ambient music from any source. No dedicated video.

**Standard Equipment:**
- 1x Triad One or Triad Eight channel (2 speakers per zone)
- 2x in-ceiling speakers (see Speaker Selection below)
- 1x Control4 SR-260 remote or app control (no dedicated panel required)
- Sources from head-end rack via Control4

**Typical rooms:** Bedrooms, bathrooms (weatherized), hallways, kitchens, laundry, office

---

### AV Zone (Display + Audio)
**Description:** TV with full source switching, plus background music in the same room. TV can watch any source; speakers can play music independently.

**Standard Equipment:**
- 1x display (see Display Selection below)
- 1x HDMI over IP receiver (Snap One Binary BNR-1X1IP-R or WyreStorm — see Video Distribution)
- 1x Apple TV 4K (or specified streaming device) at display location OR centralized at rack
- 1x Triad One amplifier channel OR 2x in-ceiling speakers powered from head-end amp
- 1x Control4 T3/T4 in-wall panel OR SR-260 remote at viewing location
- Soundbar option (see below) as alternative to in-ceiling audio

**Typical rooms:** Living room, great room, bedrooms, kitchen, office

---

### Dedicated Home Theater / Media Room
*See Theater section at bottom of this document.*

---

## SPEAKER SELECTION BY LOCATION

### In-Ceiling Speakers

| Model | Use Case | Driver | Price Tier |
|-------|---------|--------|-----------|
| Polk Audio 80F/X-LS | Standard background music, general rooms | 8" poly woofer, 1" tweeter | Good |
| Polk Audio Reserve R900-LS | Mid-range rooms with better sound quality | 8" turbine cone, ring radiator | Better |
| Triad Gold In-Room LCR | Premium whole-home audio, critical listening | 8" driver, 1" dome tweeter | Best |
| Sonance VP89R (round) | General in-ceiling, clean grille aesthetic | 8" woofer | Better |
| Sonance MAG8R | Kitchen, wet areas (moisture-resistant) | 8" woofer, moisture rated | Better |
| Sonance JS Series | Premium listening zones | Coaxial, cloth surround | Best |
| Sonance SUR Series | Dedicated surround or wide-dispersion areas | Pivoting tweeter | Better/Best |

### In-Wall Speakers

| Model | Use Case | Price Tier |
|-------|---------|-----------|
| Triad Gold In-Wall LCR | Home theater L/C/R, premium music wall | Best |
| Sonance VP68R In-Wall | Mid-range two-channel music wall | Better |
| Polk Audio RC85i In-Wall | Budget two-channel music wall | Good |

### Outdoor / Landscape Speakers

| Model | Use Case | Price Tier |
|-------|---------|-----------|
| Sonance SL42 Landscape | Rock satellite, patio, garden beds | Better |
| Sonance SL43 SM Landscape | Full-range landscape satellite, powered sub option | Best |
| Polk Audio Atrium 8 SDI | Mounted under eave or on patio structure | Good |
| Triad Bronze Outdoor Landscape | Premium outdoor rock satellite | Better/Best |
| Triad Silver Outdoor LCR | Covered patio front/center channel | Best |
| Klipsch AW-650 | Eave-mount outdoor speaker | Good/Better |

### Subwoofers

| Model | Use Case | Price Tier |
|-------|---------|-----------|
| Triad Gold In-Room Sub | Custom-built in-room sub, variable depth | Best |
| Triad Silver In-Room Sub | In-room sub for small-medium spaces | Better |
| SunBrite Sub-100 (outdoor) | In-ground or under-deck outdoor subwoofer | Better/Best |
| Klipsch R-100SW | Freestanding sub, equipment room / theater | Good |
| SVS PB-3000 | Freestanding high-performance theater sub | Best |

---

## VIDEO DISTRIBUTION

### HDMI over IP (Recommended for 3+ displays)

**Platform: Binary by Snap One / WyreStorm / Just Add Power**

| Component | Model | Description |
|-----------|-------|-------------|
| Encoder (per source) | Binary BNR-1X1IP-T | HDMI source → IP network stream |
| Decoder (per display) | Binary BNR-1X1IP-R | IP network → HDMI to display |
| Management switch | Araknis AN-310-SW-8-POE or AN-510-SW-R-8-POE | VLAN-isolated AV switch (Gigabit PoE) |
| Control4 driver | Snap One certified | Two-way control, routing, source selection |

**Advantages:** Unlimited matrix scaling, runs on CAT6A, source accessible at any display, no dedicated HDMI matrix needed for most projects. Supports 4K HDR, HDCP 2.3.

**Limitations:** Requires proper AV VLAN and managed switch. Not recommended for projects with only 1–2 displays (direct HDMI connection is simpler).

---

### HDMI Matrix Switching (2–4 displays, simple architecture)

| Size | Model | Description |
|------|-------|-------------|
| 4x4 | Binary BLS-44-4KS | 4-input / 4-output HDMI matrix, 4K60 |
| 4x8 | Binary BLS-48-4KS | 4-input / 8-output HDMI matrix, 4K60 |
| 8x8 | Binary BLS-88-4KS | 8-input / 8-output HDMI matrix, 4K60 |

---

### Displays

| Category | Model | Size | Best For |
|----------|-------|------|---------|
| **Good** | Samsung QN-series QLED | 55"–75" | Standard rooms, bedrooms |
| **Good** | LG OLED C-series | 55"–77" | Living rooms, media rooms |
| **Better** | Samsung Frame TV (LS03B) | 43"–85" | Art mode, design-conscious spaces |
| **Better** | Sony BRAVIA XR A90K OLED | 55"–83" | Home theater adjacent rooms |
| **Best** | LG Signature OLED Z-series | 65"–97" | Premium living or theater |
| **Best** | Samsung Micro LED | 89"–163" | Ultra-premium, statement pieces |
| **Theater** | JVC DLA-NZ7 (4K laser projector) | N/A | Dedicated theaters |
| **Theater** | Sony VPL-XW5000ES (4K laser) | N/A | Dedicated theaters, brighter rooms |
| **Theater** | Epson Home Cinema LS12000 (4K laser) | N/A | Home theaters, better value |
| **Outdoor** | SunBrite SB-P2 Series (75", 65") | 55"–75" | Covered patio, outdoor viewing |
| **Outdoor** | SunBrite Veranda Series | 43"–65" | Shaded/covered outdoor |

---

### Projector Screens

| Model | Size | Gain | Best For |
|-------|------|------|---------|
| Screen Innovations 5-Series Motorized | 100"–160" | 1.0–1.3 | Theater, ambient light rejection |
| Screen Innovations Zero Edge | 100"–150" | Ambient Light Reject | Rooms with mixed lighting |
| Stewart Filmscreen Luxus | 100"–180" | Custom | High-end cinema rooms |
| Draper Clarion | 84"–135" | 1.0 | Budget-conscious theater |
| Elite Screens Aeon Edge | 100"–135" | 1.0 | Entry-level fixed frame |

---

## SOURCE DEVICES

### Standard Source Equipment (Rack-Based)

| Device | Model | Use Case |
|--------|-------|----------|
| Streaming / App | Apple TV 4K (4th Gen, 2022) | Primary streaming source; best Control4 integration |
| Streaming / App | Apple TV 4K (per zone or centralized) | One per display zone OR centralized with HDMI distribution |
| Cable / Satellite | {{CLIENT_PROVIDER}} IRD or DVR | Client's specified cable/satellite provider |
| Blu-ray / UHD | Sony UBP-X800M2 | Physical media playback, Dolby Atmos |
| Streaming Audio | WiiM Pro Plus | High-res streaming, AirPlay2, multi-room audio source |
| AM/FM Tuner | Sonance | Background music source (optional) |

### Source Strategy Notes
- **Centralized:** Sources installed in equipment rack, distributed via HDMI over IP or matrix. Best for ≥3 display zones.
- **Distributed:** One Apple TV per display zone (connected directly to TV). Best for ≤2 displays or when independence per zone is important.
- Control4 controls all Apple TVs via two-way IP driver.
- Cable boxes with CableCARD or streaming TV (YouTube TV, DirecTV Stream) may eliminate need for physical cable box.

---

## HOME THEATER SCOPE

### Theater System Components

**Display / Projection:**
- 1x {{PROJECTOR_MODEL}} 4K laser projector, ceiling-mounted with proper throw distance
- 1x {{SCREEN_MODEL}} motorized projection screen, {{SCREEN_SIZE}}"
  *OR*
- 1x {{TV_MODEL}} {{TV_SIZE}}" display, wall-mounted (for smaller media rooms or non-darkened rooms)

**AV Receiver / Processor:**
| Model | Channels | Use Case |
|-------|---------|----------|
| Denon AVR-X3800H | 9.4 | Good home theater (Dolby Atmos, DTS:X) |
| Marantz Cinema 60 | 9.4 | Better — audiophile-grade receiver |
| Anthem MRX 1140 | 11.4 | Best receiver; ARC room correction |
| Triad Audio Matrix + Monoprice Amp | N/A | Budget separates approach |
| Anthem AVM 90 + Anthem MCA525 | 11.4 | Reference separates (High-end) |
| StormAudio ISP 3D.32 ELITE MK2 | 32 channels | Flagship Dolby Atmos processing |

**Theater Speaker System:**

*Good (5.1 Dolby Atmos):*
- Front L/C/R: 3x Triad Silver In-Wall LCR or Polk Audio LSiM Series
- Surrounds: 2x Triad Gold Surround In-Wall or Polk Audio LSi7
- Subwoofer: 1x SVS PB-2000 Pro or Klipsch R-115SW
- Height/Atmos: 2x Triad Bronze In-Ceiling (for 5.1.2)

*Better (7.1.4 Dolby Atmos):*
- Front L/C/R: 3x Triad Gold In-Wall LCR
- Side Surrounds: 2x Triad Gold Surround In-Wall
- Rear Surrounds: 2x Triad Gold Surround In-Wall
- Subwoofer: 1x–2x Triad Gold In-Room Sub
- Height/Atmos (ceiling): 4x Triad Gold In-Ceiling (7.1.4 overhead)

*Best (9.2.4 or 11.2.4 Reference):*
- Front L/C/R: 3x Triad Reference In-Wall LCR or Meridian DSP Series
- Surrounds (full array): Triad Reference In-Wall
- Subwoofer: 2x Triad Reference In-Room Subwoofer
- Atmos Height: 4x Triad Reference In-Ceiling (or Dolby-certified overhead array)
- Acoustic treatments: GIK Acoustics panels (quoted separately; by acoustic consultant)

**Theater Control:**
- 1x Control4 T4 Series in-wall touch panel at theater entry
- 1x Control4 SR-260 handheld remote (or Neeo remote) for seated control
- 1x Lutron {{PLATFORM}} keypad for lighting (Watch, Bright, Intermission, All Off)
- Theater "Watch" macro: Screen drops, lights dim, projector warms up, receiver powers on, sources select — one button

**Theater Infrastructure:**
- All HDMI cabling in-wall (CL3 rated) or via conduit
- HDMI 2.1 (48Gbps) cables for 4K/120 or 8K capable connections
- Rack location: AV rack in equipment closet adjacent to theater (preferred) OR dedicated in-theater rack behind false wall

---

## STANDARD INCLUSIONS (Audio / Video)

- All amplifiers, speakers, and speaker wire to specified locations
- All display mounting hardware (wall mount or ceiling mount as specified)
- HDMI over IP encoders/decoders or matrix switch as specified
- All in-wall HDMI and audio cabling (CL3 rated)
- Apple TV units per specification
- NVR and camera power supply (see security scope block)
- Rack AV wiring, cable management, and organization
- Speaker volume controls where specified
- Control4 AV driver licensing
- AV programming: source routing, one-touch macros, volume control, source naming
- Client walkthrough of AV operation

## STANDARD EXCLUSIONS (Audio / Video)

- Display delivery fees or haul-away of old displays
- Custom cabinetry or millwork for display alcoves or equipment concealment
- Acoustic treatment panels or materials (available as optional; by acoustic consultant)
- Satellite dish, antenna, or cable infrastructure (by ISP/cable provider)
- Content subscriptions (Netflix, Apple TV+, etc.)
- Speaker painting or custom grille fabrication (standard white grilles included)
- 4K Ultra HD Blu-ray disc library
- Amplification for outdoor sound systems above {{OUTDOOR_WATTS}}W total (available as option)
- Equipment rack furniture or custom cabinetry (standard open rack included; custom rack enclosure available as optional)

---

## PROGRAMMING DELIVERABLES (Audio / Video)

- One-touch "Watch" macro per display zone (powers up all devices, selects source, sets volume)
- One-touch "All Off" per zone and whole-home
- "Listen to Music" macro for audio-only zones
- Source selection interface for all sources on all panels
- Volume control and mute per zone on Control4 interfaces
- Whole-home audio grouping (play same music everywhere)
- Now-playing metadata display (song title, album art from Apple TV/streaming sources)
- Theater macro sequence (screen drop, lighting dim, projector warm-up, receiver on)
- Volume ramping (gradual fade, not abrupt cut, when AV All Off triggered)
