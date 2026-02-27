# Room Config: Mechanical Room / Equipment Room / AV Rack Room
<!-- BOB INSTRUCTIONS: The mechanical room is where the home's smart systems brain lives. While clients don't see this room, it's where BOB and the Symphony team spend the most time. A well-organized rack is critical for serviceability, reliability, and future scalability. This config covers AV rack build, networking infrastructure, and system head-end equipment. Always ask about the mechanical room/rack location early in the design process. -->

---

## TYPICAL EQUIPMENT IN THIS SPACE

- AV/Control4 equipment rack (Rack Solutions or Middle Atlantic)
- Network switch (managed, PoE)
- NVR (network video recorder for cameras)
- Control4 controller (EA-3, EA-5, or CA-1)
- Lutron main repeater or HomeWorks QSX processor
- Whole-home amplifier (Triad Eight, Sixteen, or Forty channel)
- Power conditioning / UPS
- ISP modem + router (Araknis, Pakedge, or Ubiquiti)
- Streaming devices (Apple TV 4K at rack for distributed video)
- HDMI matrix switcher (if distributed video to multiple rooms)
- Cable management (horizontal + vertical)

---

## GOOD TIER — Essential Network + Control

**Philosophy:** A functional, well-organized rack with network foundation and Control4 processor. The home runs on this.

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Middle Atlantic | WMRK-4427 or Rack Solutions 20U | Wall-mount or floor rack |
| 1 | Araknis | AN-310-SW-R-16 | 16-port managed PoE switch |
| 1 | Araknis | AN-310-RT-4L2W | Dual-WAN router |
| 1 | Control4 | EA-3 | System controller |
| 1 | Lutron | RR-MAIN-REP-WH | RadioRA 3 main repeater |
| 1 | Triad | Triad Eight channel | 8-zone whole-home audio amplifier |
| 1 | APC | SMT750RM2U | UPS battery backup — rack-mount |
| 1 | Middle Atlantic | PDX series | Rack power distribution unit |
| 1 | Luxul or Ubiquiti | Wi-Fi 6 AP (1–2 units) | Wireless access points |

**Approx. Equipment Investment (Good):** $9,000 – $15,000

### Good Tier Notes
- EA-3 controller handles up to 100 connections — appropriate for 1,500–4,000 sq ft projects
- Triad Eight: 8 independent audio zones — covers most mid-sized homes
- Managed PoE switch is essential for Control4 — powers PoE cameras, panels, and access points
- UPS protects equipment from power outages and ensures Clean Room of the home stays online
- Araknis equipment integrates natively with Control4 for network monitoring inside the C4 interface

---

## BETTER TIER — Recommended

**Philosophy:** More processing power, full NVR for surveillance, and a dedicated streaming video matrix for multi-room AV distribution.

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Middle Atlantic | WMRK-4432 or 30U floor rack | Full-height rack |
| 1 | Araknis | AN-310-SW-R-24 | 24-port managed PoE switch |
| 1 | Araknis | AN-310-RT-4L2W | Router |
| 1 | Control4 | EA-5 | Primary system controller (up to 100 connections, full media) |
| 1 | Lutron | RR-MAIN-REP-WH (x2) | RadioRA 3 main repeaters (large home — redundant) |
| 1 | Triad | Triad Sixteen channel | 16-zone whole-home audio amplifier |
| 1 | Luma | NVR-3216 | 32-channel NVR for surveillance |
| 1 | Apple TV 4K | 3rd gen (rack-mount bracket) | Head-end streaming source for whole-home video distribution |
| 1 | APC | SMT1500RM2U | Rack-mount UPS — 1500VA |
| 2 | Ubiquiti | UniFi U6 Pro | Wi-Fi 6 access points |

**Approx. Equipment Investment (Better):** $16,000 – $24,000

### Better Tier Notes
- EA-5 is the most common Control4 controller for full-home projects — handles AV matrix, full drivers, and complex programming
- NVR-3216: 32-channel NVR supports up to 32 cameras — scales for large homes
- Triad Sixteen: 16 independent audio zones — large home coverage (every room + outdoor zones)
- UniFi U6 Pro APs provide enterprise-grade Wi-Fi for smart home devices — critical for reliability
- Dual RadioRA 3 repeaters: extended range and redundancy for large square footage

---

## BEST TIER — Premium Infrastructure / Whole-Home AV Distribution

**Philosophy:** CA-1 (next-gen Control4 controller), HomeWorks QSX processor, full HDMI matrix for distributed video, and enterprise-grade networking. Built for 5,000+ sq ft estates.

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Middle Atlantic | WRK-40SL or custom | 40U equipment rack (seismic-rated if applicable) |
| 1 | Araknis | AN-810-SW-24P-SFP | Managed 24-port 10G PoE switch |
| 1 | Araknis | AN-810-RT-4L2W | 10G router |
| 1 | Control4 | CA-1 | Flagship controller — unlimited connections |
| 1 | Lutron | HW-QSX-8-128 | HomeWorks QSX processor (up to 128 devices) |
| 1 | Triad | Triad Forty channel | 40-zone whole-home audio amplifier |
| 1 | Luma | NVR-3232 | 32-channel NVR with RAID storage (redundancy) |
| 1 | WyreStorm | NHD-600-TX/RX pairs | 4K HDMI over IP matrix — AV distribution |
| 4 | Apple TV 4K | 4th gen | Head-end streaming sources |
| 1 | APC | SURT3000RMXLT3U | 3000VA online UPS with extended runtime |
| 4 | Ubiquiti | UniFi U6 Enterprise | Wi-Fi 6E APs for estate coverage |

**Approx. Equipment Investment (Best):** $35,000 – $60,000+

### Best Tier Notes
- CA-1 controller: next-generation Control4 flagship with unlimited device support and advanced programming
- HomeWorks QSX: separate processor from Control4 controller — Lutron runs independently, never affected by C4 issues
- WyreStorm NHD-600 matrix: true 4K AV over IP distribution — any source to any display, no dedicated HDMI runs required
- Triad Forty: 40 independent audio zones — complete estate coverage
- RAID NVR: redundant storage for surveillance footage — critical for high-security estates
- 10G network infrastructure: future-proof for 8K, multi-source streaming, and AI video analytics

---

## RACK BUILD STANDARDS — SYMPHONY BEST PRACTICES

### Rack Layout (Top to Bottom)
1. **Patch panel** (network and AV terminations)
2. **Managed PoE switch** (top of rack for cable management)
3. **Router**
4. **Control4 controller**
5. **Lutron processor / repeaters**
6. **Whole-home amplifier** (Triad)
7. **NVR** (heavy — middle-to-bottom)
8. **AV distribution / matrix switcher**
9. **Apple TV units**
10. **UPS** (bottom — heavy, near power entry)
11. **PDU (power distribution)**

### Cabling Standards
- CAT6A for all structured wiring (future 10G capable)
- Labeled at both ends with wire-tag labels (label maker, not hand-written)
- HDMI: active fiber HDMI for runs over 25'
- Speaker wire: 16-gauge CL2 minimum
- Rack U documentation: physical u-map printed and laminated inside rack door

### Rack Access
- Leave minimum 2U of blank space above and below amplifiers for heat dissipation
- Control4 controller and Lutron processor get dedicated front/rear access (NOT buried)
- Keystone patch panel preferred over punchdown for field-serviceable connections

---

## COMMON CLIENT REQUESTS — MECHANICAL / EQUIPMENT ROOM

- **"Where does all this equipment go?"** → A dedicated rack room, closet, or utility room. Ideally climate-controlled or ventilated. Symphony can specify rack cooling fans or a mini-split for large rack rooms.
- **"What happens if the power goes out?"** → UPS provides 30–60 minutes of runtime for router, switch, and Control4 controller. Security cameras stay online. Smart locks work offline. Full power: generator integration with automatic transfer switch (ATS) is a Premium option.
- **"Can I see the status of all my network devices?"** → Yes — Araknis OvrC integration in Control4: network health visible on any panel or app. Alerts for offline devices.
- **"How often does the equipment need service?"** → Symphony provides proactive monitoring via OvrC. Most issues are resolved remotely. Annual rack inspection and firmware updates recommended.
