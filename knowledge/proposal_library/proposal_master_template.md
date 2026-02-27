# Symphony Smart Homes — Proposal Master Template
<!-- BOB INSTRUCTIONS: This is the master proposal template. Replace all {{VARIABLE}} placeholders with project-specific data. 
     Use scope blocks from /scope_blocks/ and room configs from /room_configs/ to populate the Scope of Work section.
     Sections marked [INCLUDE IF APPLICABLE] should be omitted when not relevant to the project.
     Always review the assumptions_exclusions.md library when populating Sections 5 and 6. -->

---

# PROPOSAL

![Symphony Smart Homes Logo]
**Symphony Smart Homes**
Residential Custom AV & Smart Home Integration
License #: {{CONTRACTOR_LICENSE}}
www.symphonysmarthomes.com | ({{PHONE}}) | {{EMAIL}}

---

## COVER PAGE

**PREPARED FOR:**
{{CLIENT_NAME}}
{{CLIENT_ADDRESS_LINE1}}
{{CLIENT_ADDRESS_LINE2}}
{{CLIENT_CITY}}, {{CLIENT_STATE}} {{CLIENT_ZIP}}
{{CLIENT_EMAIL}}
{{CLIENT_PHONE}}

**PROJECT NAME:** {{PROJECT_NAME}}
**PROJECT ADDRESS:** {{PROJECT_ADDRESS}}
**PROPOSAL DATE:** {{DATE}}
**PROPOSAL NUMBER:** {{PROPOSAL_NUMBER}}
**VALID THROUGH:** {{EXPIRATION_DATE}}
**PREPARED BY:** {{SALESPERSON_NAME}}, {{SALESPERSON_TITLE}}

---
*This proposal is confidential and intended solely for {{CLIENT_NAME}}. Contents may not be shared without written consent from Symphony Smart Homes.*

---

## SECTION 1 — EXECUTIVE SUMMARY

<!-- BOB INSTRUCTIONS: Write 2–4 paragraphs. Paragraph 1: describe the project type (new construction, remodel, retrofit) and high-level client goals. Paragraph 2: summarize the major systems being installed. Paragraph 3: summarize the client experience and lifestyle benefits. Paragraph 4 (optional): note any phasing or future expansion provisions. Keep tone professional and aspirational. -->

Dear {{CLIENT_FIRST_NAME}},

Thank you for the opportunity to present this proposal for {{PROJECT_NAME}}. Symphony Smart Homes is pleased to offer a fully integrated smart home solution for your {{PROJECT_TYPE}} at {{PROJECT_ADDRESS}}.

{{EXECUTIVE_SUMMARY_PARAGRAPH_1}}
<!-- Example: "This proposal encompasses a complete whole-home automation, AV distribution, lighting control, networking, and surveillance solution designed to deliver seamless, intuitive control of every system in your home from a single interface." -->

{{EXECUTIVE_SUMMARY_PARAGRAPH_2}}
<!-- Example: "Working with your builder and design team, Symphony will coordinate the low-voltage pre-wire during construction, followed by a professionally managed installation and commissioning process that ensures every system performs exactly as designed." -->

{{EXECUTIVE_SUMMARY_PARAGRAPH_3}}
<!-- Example: "Our goal is to create an environment that adapts to your lifestyle — one where technology enhances everyday moments, from morning routines to entertaining guests, while remaining effortless to use for every member of your family." -->

We look forward to delivering an exceptional experience that will serve your family for years to come.

Sincerely,

**{{SALESPERSON_NAME}}**
{{SALESPERSON_TITLE}}, Symphony Smart Homes

---

## SECTION 2 — SYSTEM OVERVIEW

<!-- BOB INSTRUCTIONS: Provide a high-level narrative (not a bullet list) of the overall system architecture. Describe how systems connect and interact. Mention the primary control platform (Control4), lighting platform (Lutron), network backbone, and any specialized subsystems. This section should be readable by a non-technical client. Target 300–500 words. -->

### 2.1 Integrated Smart Home Platform

{{SYSTEM_OVERVIEW_NARRATIVE}}
<!-- Example narrative to adapt:
"The technology ecosystem at {{PROJECT_ADDRESS}} will be built on a Control4 automation platform — the industry’s leading residential control system trusted in over half a million homes worldwide. Control4 serves as the ‘conductor’ of your smart home, unifying every system into a single, intuitive interface accessible from wall-mounted touch panels, the Control4 app on any smartphone or tablet, and sleek handheld remotes.

Your lighting and shade control will be powered by Lutron, the global standard in residential lighting. [RadioRA 3 / HomeWorks QSX / Caseta] provides whisper-quiet motorized dimmers and keypads throughout the home, seamlessly integrated with your Control4 system for scene-based control.

Audio and video will be distributed throughout the home via a Snap One AV infrastructure, allowing you to enjoy your music, movies, and television in any room — independently or all at once. [Describe specific rooms with AV.]

Your home network will be built on enterprise-grade Araknis infrastructure — the same technology used in corporate environments — with fully managed access points providing reliable Wi-Fi coverage everywhere on the property. IoT devices, guest networks, and AV equipment are logically separated for security and performance.

[Include additional system summaries as applicable: Security, Climate, Intercom, etc.]"
-->

### 2.2 Systems Included in This Proposal

<!-- BOB INSTRUCTIONS: Check all that apply and delete the rest -->

| System | Platform | Scope |
|--------|----------|-------|
| Home Automation & Control | Control4 {{CONTROLLER_MODEL}} | {{CONTROL4_SCOPE_SUMMARY}} |
| Lighting Control | Lutron {{LUTRON_PLATFORM}} | {{LUTRON_SCOPE_SUMMARY}} |
| Motorized Shades | Lutron {{SHADE_PLATFORM}} | {{SHADE_SCOPE_SUMMARY}} |
| Distributed Audio | {{AUDIO_PLATFORM}} | {{AUDIO_SCOPE_SUMMARY}} |
| Video Distribution | {{VIDEO_PLATFORM}} | {{VIDEO_SCOPE_SUMMARY}} |
| Home Theater | {{THEATER_PLATFORM}} | {{THEATER_SCOPE_SUMMARY}} |
| Networking & Wi-Fi | Araknis / OvrC | {{NETWORK_SCOPE_SUMMARY}} |
| Surveillance | {{CAMERA_PLATFORM}} | {{CAMERA_SCOPE_SUMMARY}} |
| Video Intercom / Door Stations | {{INTERCOM_PLATFORM}} | {{INTERCOM_SCOPE_SUMMARY}} |
| HVAC / Climate Integration | {{THERMOSTAT_PLATFORM}} | {{CLIMATE_SCOPE_SUMMARY}} |
| Access Control / Door Locks | {{LOCK_PLATFORM}} | {{LOCK_SCOPE_SUMMARY}} |
| Garage Door Integration | {{GARAGE_PLATFORM}} | {{GARAGE_SCOPE_SUMMARY}} |

---

## SECTION 3 — SCOPE OF WORK

<!-- BOB INSTRUCTIONS: This is the most important section. Organize by room first, then by system within each room. Use the room_configs/ templates as a starting point for each room, selecting the appropriate tier (Good/Better/Best). Then pull specific language from scope_blocks/ for detailed system descriptions. Be specific — name the room, the system, and what is being installed. Use sub-sections (###) per room. -->

### 3.0 Whole-Home / Infrastructure

**Control4 Automation Controller**
{{CONTROLLER_SCOPE}}
<!-- Example: "One (1) Control4 CORE 3 controller will be installed in the equipment room/rack, providing automation control for all integrated systems throughout the home. The CORE 3 supports up to 100 independently controlled devices and is expandable as needed." -->

**Network Infrastructure**
{{NETWORK_SCOPE_BRIEF}}
<!-- Pull detail from scope_blocks/networking.md -->

**Equipment Rack / AV Closet**
{{RACK_SCOPE}}
<!-- Example: "One (1) rack-mounted equipment enclosure will be installed in the {{RACK_LOCATION}}, housing all head-end AV, networking, and automation equipment. Rack includes power conditioning/UPS, organized cable management, and proper ventilation." -->

---

### 3.1 {{ROOM_1_NAME}}
<!-- BOB INSTRUCTIONS: Repeat this room block for each room in the project. Replace with room name. List every system/device going into the room. Use bullet points. Be specific about quantities and models where possible. -->

**Systems in this room:** {{ROOM_1_SYSTEMS_LIST}}

{{ROOM_1_SCOPE_DETAIL}}
<!-- Example (Master Bedroom):
- One (1) Lutron RadioRA 3 dimmer controlling overhead lighting circuit
- One (1) Lutron Pico remote at nightstand location for scene and shade control
- Two (2) motorized roller shades on {{WINDOW_DESCRIPTION}} windows (Lutron Triathlon fabric)
- One (1) Lutron GRAFIK T keypad (2-button) at room entry
- One (1) Triad One stereo amplifier channel dedicated to in-ceiling speakers
- Two (2) Polk Audio 80F/X-LS in-ceiling speakers
- One (1) Apple TV 4K (4th gen) at TV location
- One (1) Samsung QN65 QLED display, wall-mounted
- Climate: Integration of existing/specified Ecobee Smart Thermostat Premium
-->

---

### 3.2 {{ROOM_2_NAME}}

**Systems in this room:** {{ROOM_2_SYSTEMS_LIST}}

{{ROOM_2_SCOPE_DETAIL}}

---

<!-- BOB INSTRUCTIONS: Continue repeating room blocks (3.3, 3.4, etc.) for all rooms in project. Add a "3.X Exterior / Outdoor" section if outdoor systems are included. Add "3.X Mechanical Room / Equipment Room" section for head-end equipment. -->

### 3.X Mechanical / Equipment Room

**Head-End Equipment Rack**

{{MECHANICAL_ROOM_SCOPE}}
<!-- Typically includes: rack enclosure, patch panels, network switch, router, NVR, Control4 controller, audio matrix/amplifiers, power conditioning, UPS -->

---

## SECTION 4 — SYSTEM PROGRAMMING & COMMISSIONING

<!-- BOB INSTRUCTIONS: Describe programming deliverables in plain language. This section reassures the client that the system will be set up and personalized, not just installed. -->

### 4.1 Control4 Programming

Symphony Smart Homes will program the Control4 system to deliver the following:

**Interfaces & Navigation**
- Custom home screen on all touch panels and mobile app with room-based navigation
- Dedicated control pages for: {{LIST_MAJOR_CONTROL_PAGES}}
- Consistent interface across wall panels, handheld remotes, and mobile app

**Lighting Scenes**
<!-- BOB: List the scenes being programmed. Common examples below — adjust to project. -->
- **Morning:** Gradual ramp-up of bedroom and kitchen lighting at scheduled time
- **All On / All Off:** One-touch control of all lights in the home or by floor
- **Good Night:** Confirmation of lighting off, shade position, thermostat setback, and lock status at bedside keypad or app
- **Away:** All lights off, shades to privacy position, thermostat to away setpoint
- **Welcome Home:** Triggered by geofencing or garage door opening — lights, music, and thermostat set to comfort levels
- **Entertain:** Preset lighting scenes in kitchen, dining, and living areas; music starts
- {{CUSTOM_SCENES}}

**Automation Rules (When >> Then)**
- {{AUTOMATION_RULE_1}}
- {{AUTOMATION_RULE_2}}
- {{AUTOMATION_RULE_3}}
<!-- Examples: "When the garage door opens after sunset, turn on mudroom and kitchen lights at 80%"; "When the last person leaves (geofence), set HVAC to away mode and send a push notification" -->

**AV Control**
- One-touch "Watch" macros for each display location (powers on display, selects input, sets volume)
- Whole-home audio control with room grouping and individual volume control
- {{THEATER_PROGRAMMING_NOTES}}

**Schedules**
- Sunrise/sunset-based outdoor lighting schedules
- Shade schedules (privacy mode at dusk, open at sunrise)
- {{CUSTOM_SCHEDULES}}

### 4.2 Lutron Programming

- All dimmer curves and fade times set per client preference
- All scenes (programmed through Lutron and integrated into Control4) set to client-approved levels
- Keypad engraving layout provided to client for approval prior to ordering

### 4.3 Commissioning & Client Orientation

Upon completion of programming, Symphony Smart Homes will conduct:

1. **System verification** — functional test of every device and integration point
2. **Client walkthrough** — minimum {{ORIENTATION_HOURS}} hours of on-site instruction covering daily use, app setup, and scene customization
3. **Documentation** — as-built wiring diagram, IP/device list, and user guide delivered digitally
4. **30-Day follow-up** — complimentary follow-up visit within 30 days to address any adjustments

---

## SECTION 5 — ASSUMPTIONS & CLARIFICATIONS

<!-- BOB INSTRUCTIONS: Pull applicable items from assumptions_exclusions.md. Add project-specific assumptions as needed. This section protects Symphony from scope creep. Always include the most relevant items for the project type (new construction vs. retrofit). -->

The following assumptions form the basis of this proposal. Changes to these conditions may result in a change order.

### Construction & Site

1. {{ASSUMPTION_CONSTRUCTION_1}}
2. {{ASSUMPTION_CONSTRUCTION_2}}
3. {{ASSUMPTION_CONSTRUCTION_3}}

<!-- Standard assumptions to select from (see assumptions_exclusions.md for full library):
- New construction: All low-voltage pre-wire per Symphony’s wire schedule to be performed during rough-in phase by Symphony or designated subcontractor
- Retrofit: Existing wire paths are accessible; if walls must be opened, drywall repair is by others
- Standard wood-frame or metal-stud drywall construction (no concrete, masonry, or specialty substrates without additional pricing)
- Ceilings are standard height (up to 10 ft); additional lift equipment required for ceilings above 12 ft
- Project site will be available to Symphony personnel during normal business hours (7am–5pm, Mon–Fri) during installation phases
-->

### Electrical & Power

4. {{ASSUMPTION_ELECTRICAL_1}}
5. {{ASSUMPTION_ELECTRICAL_2}}

<!-- Standard: Dedicated electrical circuits provided by licensed electrician to rack location, audio closet, and all specified display locations per Symphony’s electrical schedule -->

### Client & Third-Party

6. {{ASSUMPTION_CLIENT_1}}
7. {{ASSUMPTION_CLIENT_2}}
8. {{ASSUMPTION_CLIENT_3}}

<!-- Standard: Client to provide stable broadband internet service; minimum 100 Mbps symmetrical recommended, 500 Mbps+ preferred for systems in this proposal -->
<!-- Standard: Client to make all product selections (finishes, fabrics, etc.) within 5 business days of request to maintain project schedule -->

### Networking

9. {{ASSUMPTION_NETWORK_1}}

<!-- Standard: ISP modem/ONT to be installed and active prior to Symphony network commissioning -->

### {{ADDITIONAL_ASSUMPTION_CATEGORY}}

10. {{ADDITIONAL_ASSUMPTION}}

---

## SECTION 6 — EXCLUSIONS

<!-- BOB INSTRUCTIONS: Pull applicable items from assumptions_exclusions.md exclusions library. Always include the core exclusions. Add system-specific exclusions as relevant. -->

The following items are **not included** in this proposal unless explicitly listed in Section 3:

### Trades & Construction
- All electrical rough-in, conduit, circuit breakers, and load center work (by licensed electrician)
- Drywall repair, patching, texture matching, or painting following low-voltage installation
- Custom millwork, built-ins, cabinetry, or furniture modifications
- HVAC installation, ductwork, or mechanical work of any kind
- Plumbing (if applicable to steam/spa systems)

### Permits & Inspections
- Building permits (low-voltage permit to be pulled by Symphony where required; all other permits by GC or respective trades)
- Electrical inspection by licensed electrician
- Fire alarm, life safety, or smoke detection systems

### Technology & Services
- Internet service provider (ISP) equipment, monthly internet service, or ISP installation
- Subscription streaming services (Netflix, Spotify, Apple Music, etc.)
- Professional security/alarm monitoring service fees
- Control4 4Sight remote access subscription (recommended; billed annually at approx. ${{CONTROL4_4SIGHT_PRICE}}/yr — can be added to proposal at client request)
- Third-party platform subscriptions not specifically listed

### Equipment & Furniture
- Television furniture, credenzas, or entertainment consoles
- Furniture-mounted TV mounts (wall and ceiling mounts are included where specified)
- Appliances of any kind (refrigerators, dishwashers, etc.)
- {{PROJECT_SPECIFIC_EXCLUSION_1}}
- {{PROJECT_SPECIFIC_EXCLUSION_2}}

### Systems Specifically Excluded
<!-- BOB: List any systems the client asked about but are NOT in scope -->
- {{EXCLUDED_SYSTEM_1}}
- {{EXCLUDED_SYSTEM_2}}

---

## SECTION 7 — EQUIPMENT SUMMARY

<!-- BOB INSTRUCTIONS: This section lists all equipment by location. For each room/location, list quantity, manufacturer, model number, and description. This is what gets priced. Be thorough and accurate — this feeds the investment summary. Use real model numbers from Control4, Lutron, Snap One, Araknis, etc. -->

### Equipment Schedule by Location

#### Head-End / Equipment Room / Rack

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| 1 | Control4 | {{CONTROLLER_MODEL}} | Smart Home Controller |
| 1 | Araknis | {{ROUTER_MODEL}} | Router / Firewall |
| 1 | Araknis | {{SWITCH_MODEL}} | Managed PoE Network Switch |
| {{WAP_QTY}} | Araknis | {{WAP_MODEL}} | Wireless Access Points |
| 1 | {{RACK_BRAND}} | {{RACK_MODEL}} | Equipment Rack Enclosure |
| 1 | {{UPS_BRAND}} | {{UPS_MODEL}} | Rack UPS / Power Conditioner |
| {{AMP_QTY}} | Triad | {{AMP_MODEL}} | Multi-Channel Audio Amplifier |
| 1 | Snap One | {{AUDIO_MATRIX_MODEL}} | Audio Matrix / Distribution |
| {{NVR_QTY}} | {{CAMERA_BRAND}} | {{NVR_MODEL}} | Network Video Recorder |
| | | | |
| **Subtotal Head-End** | | | |

#### {{ROOM_1_NAME}}

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| {{QTY}} | {{MFR}} | {{MODEL}} | {{DESCRIPTION}} |
| {{QTY}} | {{MFR}} | {{MODEL}} | {{DESCRIPTION}} |
| | | | |
| **Subtotal {{ROOM_1_NAME}}** | | | |

#### {{ROOM_2_NAME}}

| Qty | Manufacturer | Model | Description |
|-----|-------------|-------|-------------|
| {{QTY}} | {{MFR}} | {{MODEL}} | {{DESCRIPTION}} |
| | | | |
| **Subtotal {{ROOM_2_NAME}}** | | | |

<!-- BOB: Continue for all rooms. Then add a grand total row. -->

#### Equipment Summary Totals

| Category | Item Count | Equipment Subtotal |
|----------|-----------|-------------------|
| Automation & Control | {{COUNT}} | ${{AUTOMATION_EQUIP_TOTAL}} |
| Lighting & Shades | {{COUNT}} | ${{LIGHTING_EQUIP_TOTAL}} |
| Audio / Video | {{COUNT}} | ${{AV_EQUIP_TOTAL}} |
| Networking | {{COUNT}} | ${{NETWORK_EQUIP_TOTAL}} |
| Surveillance | {{COUNT}} | ${{SURVEILLANCE_EQUIP_TOTAL}} |
| Accessories & Infrastructure | {{COUNT}} | ${{ACCESSORIES_TOTAL}} |
| **Total Equipment** | **{{TOTAL_COUNT}}** | **${{TOTAL_EQUIPMENT}}** |

---

## SECTION 8 — LABOR & PROJECT TIMELINE

<!-- BOB INSTRUCTIONS: Describe the installation phases and estimated timeline. Adjust phases based on project type. New construction has pre-wire + rough-in + trim-out phases; retrofit may skip pre-wire. Always include commissioning as a distinct final phase. -->

### 8.1 Installation Phases

#### Phase 1 — Pre-Wire / Low-Voltage Rough-In
<!-- New construction only; for retrofit, replace with "Phase 1 — Demolition & Wire Routing" -->

**Timing:** {{PREWIRE_PHASE_TIMING}}
<!-- Example: "During framing / prior to insulation" -->

**Scope:**
- Pull all low-voltage cable per approved wire schedule (CAT6A, speaker wire, HDMI, coax, control wire)
- Install all j-boxes, wall plates, and rough-in brackets at specified locations
- Label all home-run cables at rack location with room/device designation
- Coordinate with electrician for dedicated circuit placement

**Estimated Labor:** {{PREWIRE_HOURS}} hours

---

#### Phase 2 — Rough-In Verification & Termination
<!-- For new construction after drywall hang; for retrofit, this is post wire-routing -->

**Timing:** {{ROUGH_IN_TIMING}}
<!-- Example: "After drywall hang, prior to paint" or "After wire routing complete" -->

**Scope:**
- Verify all wire runs with continuity testing
- Install in-wall/in-ceiling speakers in rough-in rings (prior to texture)
- Install structured wiring panel / patch panel at rack location
- Pull any supplemental or add wire as required

**Estimated Labor:** {{ROUGH_IN_HOURS}} hours

---

#### Phase 3 — Trim-Out / Device Installation

**Timing:** {{TRIM_OUT_TIMING}}
<!-- Example: "After paint complete, final clean phase" -->

**Scope:**
- Install all wall plates, keypads, dimmers, and switch modules
- Mount all displays (TVs, touch panels) per approved layout
- Trim out all in-ceiling and in-wall speakers with grilles
- Install all rack equipment and perform initial configuration
- Mount and connect all cameras, door stations, and access points
- Install and wire all motorized shades with hardware

**Estimated Labor:** {{TRIM_OUT_HOURS}} hours

---

#### Phase 4 — Programming & System Configuration

**Timing:** {{PROGRAMMING_TIMING}}
<!-- Example: "Concurrent with trim-out; final programming after all devices installed" -->

**Scope:**
- Control4 project file build, driver installation, and device binding
- Lutron scene and keypad programming
- Network VLAN configuration and access point optimization
- Camera NVR configuration and motion zone setup
- AV system one-touch macro programming
- Integration testing of all subsystems

**Estimated Labor:** {{PROGRAMMING_HOURS}} hours

---

#### Phase 5 — Commissioning & Client Orientation

**Timing:** {{COMMISSIONING_TIMING}}
<!-- Example: "Final week prior to client move-in or occupancy" -->

**Scope:**
- Full system functional verification (every device, every integration)
- Client walkthrough and orientation (minimum {{ORIENTATION_HOURS}} hours)
- App installation on client devices (up to {{APP_DEVICE_COUNT}} devices)
- As-built documentation delivery
- Punch list completion

**Estimated Labor:** {{COMMISSIONING_HOURS}} hours

---

### 8.2 Project Timeline Summary

| Phase | Description | Start | Duration | End |
|-------|-------------|-------|----------|-----|
| Phase 1 | Pre-Wire / Rough-In | {{P1_START}} | {{P1_DURATION}} | {{P1_END}} |
| Phase 2 | Rough-In Verification | {{P2_START}} | {{P2_DURATION}} | {{P2_END}} |
| Phase 3 | Trim-Out & Installation | {{P3_START}} | {{P3_DURATION}} | {{P3_END}} |
| Phase 4 | Programming | {{P4_START}} | {{P4_DURATION}} | {{P4_END}} |
| Phase 5 | Commissioning | {{P5_START}} | {{P5_DURATION}} | {{P5_END}} |
| **Total** | | | **{{TOTAL_WEEKS}} weeks** | |

*All dates are estimates based on information available at time of proposal. Final schedule to be confirmed at project kickoff.*

---

## SECTION 9 — INVESTMENT SUMMARY

<!-- BOB INSTRUCTIONS: This is the pricing section. Break out Equipment, Labor, Programming, Project Management, and Tax clearly. Do not combine unless client requests a single-price format. Always show totals. Note payment schedule at bottom. -->

### 9.1 Investment Breakdown

| Line Item | Amount |
|-----------|--------|
| **Equipment** | |
| Automation & Control Equipment | ${{AUTOMATION_EQUIP_PRICE}} |
| Lighting & Shade Equipment | ${{LIGHTING_EQUIP_PRICE}} |
| Audio / Video Equipment | ${{AV_EQUIP_PRICE}} |
| Networking Equipment | ${{NETWORK_EQUIP_PRICE}} |
| Surveillance Equipment | ${{SURVEILLANCE_EQUIP_PRICE}} |
| Infrastructure & Accessories | ${{INFRASTRUCTURE_PRICE}} |
| **Equipment Subtotal** | **${{EQUIPMENT_SUBTOTAL}}** |
| | |
| **Labor** | |
| Pre-Wire / Rough-In Labor ({{PREWIRE_HOURS}} hrs @ ${{LABOR_RATE}}/hr) | ${{PREWIRE_LABOR_COST}} |
| Trim-Out / Installation Labor ({{TRIM_OUT_HOURS}} hrs @ ${{LABOR_RATE}}/hr) | ${{TRIM_OUT_LABOR_COST}} |
| **Labor Subtotal** | **${{LABOR_SUBTOTAL}}** |
| | |
| **Programming & Commissioning** | |
| Control4 System Programming | ${{C4_PROGRAMMING_COST}} |
| Lutron Programming & Commissioning | ${{LUTRON_PROGRAMMING_COST}} |
| AV Macro & Source Programming | ${{AV_PROGRAMMING_COST}} |
| Network Configuration & Optimization | ${{NETWORK_PROGRAMMING_COST}} |
| Client Orientation ({{ORIENTATION_HOURS}} hrs) | ${{ORIENTATION_COST}} |
| **Programming Subtotal** | **${{PROGRAMMING_SUBTOTAL}}** |
| | |
| **Project Management & Design** | |
| Design & Pre-Construction Coordination | ${{DESIGN_COST}} |
| Project Management | ${{PM_COST}} |
| **PM Subtotal** | **${{PM_SUBTOTAL}}** |
| | |
| **Subtotal** | **${{PROJECT_SUBTOTAL}}** |
| Sales Tax ({{TAX_RATE}}% on equipment) | ${{TAX_AMOUNT}} |
| **TOTAL INVESTMENT** | **${{TOTAL_INVESTMENT}}** |

### 9.2 Payment Schedule

<!-- BOB INSTRUCTIONS: Standard Symphony payment schedule below. Adjust percentages as appropriate for project size. Large projects (>$50K) typically use the 4-payment schedule. Smaller projects may use 50/50 or 33/33/33. -->

| Milestone | % | Amount |
|-----------|---|--------|
| Proposal Acceptance / Contract Signing | {{DEPOSIT_PCT}}% | ${{DEPOSIT_AMOUNT}} |
| Pre-Wire Phase Completion | {{P1_PAYMENT_PCT}}% | ${{P1_PAYMENT_AMOUNT}} |
| Trim-Out Phase Completion | {{P2_PAYMENT_PCT}}% | ${{P2_PAYMENT_AMOUNT}} |
| Final Commissioning & Client Acceptance | {{FINAL_PAYMENT_PCT}}% | ${{FINAL_PAYMENT_AMOUNT}} |
| **Total** | **100%** | **${{TOTAL_INVESTMENT}}** |

*Payment by check, ACH, or wire transfer. Credit card payments accepted ({{CC_FEE}}% processing fee applies). All invoices due Net 10 from milestone completion.*

---

## SECTION 10 — OPTIONAL UPGRADES & FUTURE PROVISIONS

<!-- BOB INSTRUCTIONS: List items that were discussed but not included in base scope, or natural add-ons that make sense for this project. Price each one individually. This section is key for upselling and future work. Group by system. -->

The following enhancements are available and can be added to this project at any time. Items marked with *(Pre-Wire Included)* have conduit and/or wire already pulled in the base scope, making future addition straightforward.

### Optional Audio / Video
| # | Description | Investment |
|---|-------------|-----------|
| A1 | {{AV_OPTION_1_DESCRIPTION}} | ${{AV_OPTION_1_PRICE}} |
| A2 | {{AV_OPTION_2_DESCRIPTION}} | ${{AV_OPTION_2_PRICE}} |
| A3 | {{AV_OPTION_3_DESCRIPTION}} | ${{AV_OPTION_3_PRICE}} |

### Optional Lighting & Shades
| # | Description | Investment |
|---|-------------|-----------|
| L1 | {{LIGHTING_OPTION_1_DESCRIPTION}} | ${{LIGHTING_OPTION_1_PRICE}} |
| L2 | {{LIGHTING_OPTION_2_DESCRIPTION}} | ${{LIGHTING_OPTION_2_PRICE}} |

### Optional Automation
| # | Description | Investment |
|---|-------------|-----------|
| C1 | {{AUTOMATION_OPTION_1_DESCRIPTION}} | ${{AUTOMATION_OPTION_1_PRICE}} |

### Optional Surveillance
| # | Description | Investment |
|---|-------------|-----------|
| S1 | {{SURVEILLANCE_OPTION_1_DESCRIPTION}} | ${{SURVEILLANCE_OPTION_1_PRICE}} |

### Future Phase Provisions
<!-- BOB: List any rough-in or conduit provisions included in this project for future expansion -->
- {{FUTURE_PROVISION_1}}
- {{FUTURE_PROVISION_2}}

---

## SECTION 11 — TERMS & CONDITIONS

<!-- BOB INSTRUCTIONS: Do not modify this section. These are Symphony's standard T&Cs. -->

### 11.1 Scope & Changes

This proposal constitutes the full scope of work as described. Any work not explicitly listed in Section 3 is excluded. Change orders are required for any additions or modifications to scope, and will be priced and presented in writing prior to work proceeding. Symphony Smart Homes reserves the right to adjust pricing if site conditions discovered during installation differ materially from those described in the assumptions (Section 5).

### 11.2 Equipment & Warranty

- **Hardware Warranty:** All equipment carries manufacturer’s standard warranty. Symphony Smart Homes will facilitate warranty claims on client’s behalf during the first year following installation.
- **Labor Warranty:** Symphony warrants all labor and workmanship for one (1) year from date of final commissioning. This covers defects in installation quality, not equipment failures or software/firmware issues.
- **Equipment Substitution:** Symphony Smart Homes reserves the right to substitute equivalent equipment in the event of manufacturer discontinuation, supply chain delays, or unforeseen availability issues. Client will be notified prior to any substitution.

### 11.3 Programming & Software

Control4 programming is delivered as a complete, functional system. Minor adjustments and "tweaks" within 30 days of commissioning are included at no charge. Major reprogramming (scene redesign, room additions, platform changes) is billed at Symphony’s current service rate.

Control4 dealer software and 4Sight remote access subscription are not included unless specifically listed. Symphony recommends 4Sight for ongoing remote support capability.

### 11.4 Project Schedule

Symphony will make every reasonable effort to meet the schedule outlined in Section 8. Symphony is not responsible for delays caused by GC scheduling conflicts, trade sequencing, material delivery delays, change orders, or client availability. Client will be notified promptly of any anticipated schedule changes.

### 11.5 Site Access & Safety

Client or authorized representative agrees to provide Symphony personnel safe and unobstructed access to all areas of the project during scheduled work periods. Symphony personnel will comply with all site safety requirements established by the general contractor.

### 11.6 Payment Terms

Invoices not paid within 30 days of due date may incur a 1.5% per month late fee. Symphony Smart Homes reserves the right to suspend work on projects with invoices more than 30 days past due. Returned checks are subject to a $50 fee.

### 11.7 Proposal Validity

This proposal is valid for {{VALIDITY_DAYS}} days from the date issued ({{DATE}}). Pricing is subject to change after expiration due to equipment pricing fluctuations, labor rate adjustments, or material availability changes.

### 11.8 Limitation of Liability

Symphony Smart Homes’ liability under this agreement shall not exceed the total contract value. Symphony is not liable for consequential, incidental, or indirect damages arising from system performance, connectivity interruptions, or third-party platform changes.

### 11.9 Governing Law

This agreement is governed by the laws of the State of {{STATE}}. Any disputes arising from this agreement shall be resolved through binding arbitration in {{COUNTY}} County, {{STATE}}.

---

## SECTION 12 — ACCEPTANCE & SIGNATURE

<!-- BOB INSTRUCTIONS: Do not modify this section. This is the contract execution block. -->

By signing below, Client accepts the terms and scope of this proposal and authorizes Symphony Smart Homes to proceed with the work as described. This signed proposal, together with the Terms & Conditions in Section 11, constitutes the entire agreement between the parties.

---

**CLIENT ACCEPTANCE**

| | |
|---|---|
| **Client Signature** | _________________________________ |
| **Printed Name** | _________________________________ |
| **Date** | _________________________________ |
| **Authorized Title** (if business) | _________________________________ |

| | |
|---|---|
| **Co-Client Signature** (if applicable) | _________________________________ |
| **Printed Name** | _________________________________ |
| **Date** | _________________________________ |

---

**SYMPHONY SMART HOMES ACCEPTANCE**

| | |
|---|---|
| **Authorized Signature** | _________________________________ |
| **Printed Name** | {{SALESPERSON_NAME}} |
| **Title** | {{SALESPERSON_TITLE}} |
| **Date** | _________________________________ |

---

*Questions? Contact {{SALESPERSON_NAME}} at {{SALESPERSON_EMAIL}} or {{SALESPERSON_PHONE}}.*

*Symphony Smart Homes | {{COMPANY_ADDRESS}} | www.symphonysmarthomes.com*
*Contractor License: {{CONTRACTOR_LICENSE}} | Insured & Bonded*

---
<!-- END OF PROPOSAL TEMPLATE -->
<!-- Bob: After generating a proposal, review all sections for consistency. Verify that equipment in Section 7 matches the scope described in Section 3. Verify that pricing in Section 9 matches the equipment list. Double-check that all {{VARIABLES}} have been replaced. -->
