# Assumptions & Exclusions Library
<!-- BOB INSTRUCTIONS: This is the master library of assumptions and exclusions for Symphony Smart Homes proposals. When populating Sections 5 and 6 of any proposal, pull the most relevant items from this library. Items are organized by category. Always include ALL items in the "Core — Always Include" sections. Add category-specific items based on which systems are in scope. Mark any project-specific assumptions clearly. -->

---

## PART 1: STANDARD ASSUMPTIONS

### 1.1 Core Assumptions — Always Include

1. **Scope Boundary:** This proposal covers only the systems and equipment explicitly listed in Section 3. All other systems, trades, and work items are excluded.

2. **Site Readiness:** Client or general contractor will notify Symphony Smart Homes a minimum of **{{LEAD_TIME_DAYS}} business days** in advance of each project phase to allow scheduling.

3. **Site Access:** Unobstructed access to all installation areas will be provided to Symphony personnel during scheduled work days (standard hours: Monday–Friday, 7:00 AM – 5:00 PM). After-hours or weekend work is available at a premium rate.

4. **Standard Construction:** Project involves standard wood-frame or metal-stud, drywall-clad construction. Specialty substrates (poured concrete, ICF, brick/masonry, SIPS, Rastra/alternative building systems) may require alternate installation methods and additional labor.

5. **Ceiling Height:** Standard ceiling heights up to 10 feet are included in base pricing. Ceilings above 12 feet require lift equipment and additional labor — quoted separately or via change order if discovered on-site.

6. **Pricing Validity:** All pricing in this proposal is valid for **{{VALIDITY_DAYS}} days** from the proposal date. After expiration, pricing may change due to equipment cost fluctuations, supply chain conditions, or labor rate adjustments.

7. **Project Coordination:** A single point of contact (client or GC) will be designated for scheduling, access, and decision-making throughout the project.

---

### 1.2 New Construction Assumptions

8. **Pre-Wire Coordination:** Symphony will coordinate with the general contractor for rough-in access during the framing/pre-wire phase (prior to insulation and drywall). GC to provide Symphony with minimum **{{PREWIRE_NOTICE_DAYS}} business days** advance notice of framing completion.

9. **Pre-Wire Scope:** All low-voltage cable rough-in (CAT6A, speaker wire, HDMI, control wiring) is performed by Symphony during the framing/rough-in phase per Symphony’s wire schedule. If pre-wire is performed by a low-voltage subcontractor, Symphony assumes all cabling meets Symphony’s specifications and will verify prior to trim-out.

10. **Electrical Coordination:** Electrical contractor (licensed) to provide dedicated 120V circuits to the following locations per Symphony’s electrical schedule: equipment rack/AV closet, all display mounting locations, shade motor locations, and in-ceiling speaker amplifier locations. Symphony’s electrical schedule to be furnished within {{ELEC_SCHEDULE_DAYS}} business days of contract execution.

11. **Stud/Joist Access:** Walls and ceilings will be open (uninsulated, un-drywalled) during the pre-wire phase, providing unobstructed wire routing between floors and through walls.

12. **Drywall Inspection:** Symphony to perform a rough-in verification walk-through with the GC after drywall hang and prior to texture/paint to confirm all J-boxes, brackets, and conduit stubs are properly positioned.

13. **Fixture Specifications:** Client to provide Symphony with final lighting fixture specifications (manufacturer, model, LED driver specifications) prior to ordering Lutron dimmers. Dimmer compatibility must be confirmed before fixture order is finalized.

14. **Keypad Engraving:** Lutron engraved keypads are custom-manufactured and require **4–6 weeks lead time**. Final keypad engraving layout approval by client required no later than {{KEYPAD_LEAD_TIME_WEEKS}} weeks before scheduled trim-out start.

---

### 1.3 Retrofit / Remodel Assumptions

15. **Existing Wire Paths:** Assumed that wire routing paths (walls, ceilings, attic, crawl space) are accessible with standard fishing techniques. Discovery of insulated closed-wall cavities, fire blocking, or inaccessible chase paths may require additional labor and wall opening — any resulting drywall work is by others.

16. **Existing Infrastructure:** Existing low-voltage wiring, conduit, or equipment discovered during installation that conflicts with Symphony’s scope will be identified and resolved via change order.

17. **Asbestos / Hazardous Materials:** Symphony’s scope assumes no hazardous materials (asbestos insulation, lead paint, etc.) are present in work areas. If hazardous materials are discovered, work will pause and client/GC is responsible for remediation before Symphony resumes.

18. **Existing Display Mounts:** TV wall mounts already installed by others are assumed to be structurally adequate. Symphony will verify stud/blocking anchoring; if mount replacement is needed, it will be priced as a change order.

19. **Finished Space Access:** Running wire through finished spaces (attic access unavailable, no crawl space) may require surface-mounted raceways or conduit — included where visible in occupied areas only when no concealed path is available. Raceway/conduit aesthetics to be reviewed with client.

---

### 1.4 Network & Connectivity Assumptions

20. **Internet Service:** Client to provide an active broadband internet connection at the specified rack/equipment closet location prior to network commissioning. **Minimum recommended speeds for this project: {{MIN_DOWNLOAD}} Mbps download / {{MIN_UPLOAD}} Mbps upload.** Recommended: 500 Mbps+ symmetrical (fiber preferred).

21. **ISP Equipment Location:** The ISP modem, ONT, or gateway will be located at or near the equipment rack/network closet. If ISP equipment is located in a remote location, a fiber or CAT6A extension run may be required — quoted as optional.

22. **Single ISP:** Pricing assumes a single ISP connection. Multi-WAN failover (two ISPs for redundancy) is available as an optional upgrade.

23. **Domain / Business Network:** This proposal assumes a standard residential network. If client requires corporate domain, Active Directory, VPN, or business-class network policy management, additional engineering time applies.

---

### 1.5 Client & Decision Assumptions

24. **Product Selection:** Client to make all required product selections (TV finish, speaker grille color, keypad finish, shade fabric/color, etc.) within **{{SELECTION_DEADLINE_DAYS}} business days** of Symphony’s request. Delays in selection may impact project schedule and are not Symphony’s responsibility.

25. **Furniture Placement:** Final TV mounting heights and speaker placement locations assume final furniture layout is confirmed prior to Symphony’s trim-out phase. Changes after installation may incur relabor costs.

26. **Design Team Coordination:** For projects with interior designers or architects, Symphony will coordinate device placement, keypad finishes, and shade fabric selections with the design team as a courtesy. Design team decisions that conflict with previously approved Symphony plans are subject to change order.

27. **Occupancy:** Client understands that full system commissioning and orientation requires occupancy-ready or near-occupancy-ready conditions. Commissioning in an active construction zone will be limited; a follow-up commissioning visit may be required after occupancy.

---

### 1.6 System-Specific Assumptions

28. **Lutron Dimmer Compatibility:** All dimmable light fixtures will be confirmed compatible with specified Lutron dimmers prior to final fixture order. Lutron’s online dimmer compatibility tool will be used. Symphony is not responsible for flicker, buzz, or performance issues with incompatible fixtures that were not reviewed prior to installation.

29. **Shade Rough-In Power:** Hardwired motorized shades require a 120V electrical box at each shade motor location. Power provision is by licensed electrician per Symphony’s electrical schedule. Battery motor option is available as an alternative if power cannot be provided.

30. **Control4 Device Count:** The Control4 controller specified is sized for the device count in this proposal. Adding significant additional devices or systems post-commissioning may require a controller upgrade — Symphony will notify client if approaching capacity limits.

31. **Camera Cabling:** Camera locations assume cable routing through attic, soffit, eave, or interior wall cavities. Underground conduit runs for camera cabling are excluded unless specifically listed.

32. **HVAC Equipment:** HVAC system is installed, operational, and provides a standard 24V thermostat interface. Proprietary communication buses (e.g., some Carrier, Trane, or Daikin mini-split systems) may require manufacturer-specific interface modules — priced separately if applicable.

---

## PART 2: STANDARD EXCLUSIONS

### 2.1 Core Exclusions — Always Include

1. **Electrical Work:** All line-voltage electrical work — including circuit breakers, load center modifications, conduit installation, 120V/240V wiring, outlet installation, dedicated circuit installation, and associated permits and inspections — is the responsibility of a licensed electrician and is NOT included in Symphony’s scope.

2. **Drywall & Finish Work:** Any drywall cutting, patching, texturing, or painting required to install or conceal low-voltage wiring or devices is NOT included. For retrofit projects, Symphony will take reasonable care to minimize wall openings, but any finish work is by the client or GC.

3. **Custom Millwork & Cabinetry:** Custom built-ins, media walls, AV consoles, speaker enclosures integrated into millwork, shade pockets, or any custom woodworking or cabinetry is NOT included.

4. **Permits:** Building permits for low-voltage installation are obtained by Symphony where required by local jurisdiction. All other permits (electrical, mechanical, building, fire) are by the respective licensed trade or general contractor.

5. **HVAC & Mechanical:** HVAC equipment, ductwork, refrigerant lines, and all mechanical work are NOT included. Symphony integrates but does not install mechanical systems.

6. **Plumbing:** All plumbing is excluded. For steam shower integration, plumbing for steam generator is by plumbing contractor.

---

### 2.2 Technology & Subscription Exclusions

7. **ISP Equipment & Service:** Internet service provider (ISP) equipment (modem, router, gateway, ONT), monthly internet service fees, and ISP installation or service calls are NOT included.

8. **Subscription Services:** All third-party subscription services are excluded, including but not limited to:
   - Music streaming (Spotify, Apple Music, Tidal, Pandora)
   - Video streaming (Netflix, Apple TV+, Hulu, Disney+, Max)
   - Satellite or cable TV service and monthly fees
   - Security/alarm monitoring service fees
   - Control4 4Sight remote access (after first year; ~${{CONTROL4_4SIGHT_PRICE}}/yr)
   - OvrC Pro network monitoring (after first year; ~${{OVRC_ANNUAL_PRICE}}/yr)
   - Cloud storage subscriptions for camera footage

9. **Third-Party Integrations:** Integration with any smart home device, platform, or system not explicitly listed in Section 3. Examples of excluded integrations (unless specified): home gym equipment, robot vacuums, smart appliances beyond specified scope, pet doors, custom hobby/entertainment systems.

10. **Software & App Licenses:** Third-party application licenses, cloud subscriptions, or software licenses beyond those explicitly included. Control4 driver annual renewal fees (if applicable to specific third-party drivers) will be disclosed prior to installation.

---

### 2.3 Equipment & Furniture Exclusions

11. **Light Fixtures & Lamps:** All lighting fixtures, bulbs, and lamps. Symphony provides control (dimmers, switches, keypads) only. Fixture procurement and installation is by GC, electrician, or client.

12. **Furniture & Entertainment Consoles:** Television furniture, AV consoles, entertainment centers, credenzas, and TV stand-type mounts are NOT included.

13. **Wall/Ceiling Mounts:** Wall mounts for TVs and ceiling mounts for projectors are included ONLY where explicitly listed in Section 7. Furniture mounts, floor stands, and articulating mounts for non-fixed locations are excluded.

14. **Appliances:** Kitchen appliances, smart refrigerators, washers/dryers, and other household appliances are NOT included, even where smart/connected versions exist. Smart appliance integration may be available as an optional add-on via specific drivers.

15. **Physical Media Library:** Blu-ray discs, DVDs, CDs, vinyl records, or any content media are NOT included.

---

### 2.4 Infrastructure & Construction Exclusions

16. **Trenching & Underground Work:** Underground conduit trenching for cable runs between buildings, under driveways, or through landscaped areas is NOT included unless specifically quoted. All outdoor runs in base scope are assumed to be routed above-ground via conduit on structure.

17. **Concrete Core Drilling:** Drilling through concrete slabs, foundations, or masonry for wire routing is NOT included in standard scope and will be priced as a change order if required.

18. **Ceiling Access:** Attic or crawl space access is assumed available and safe. If ceiling access is required but obstructed (spray foam insulation, finished attic, inaccessible crawl space), alternative routing or additional labor costs apply.

19. **Landscape / Site Work:** Outdoor speaker placement assumes mounting on structure (eave, wall, post). Landscape speaker cable burial, in-ground installation, or trench-and-conduit is NOT included unless specified.

20. **Generator / Backup Power:** Whole-home generator, transfer switch, or emergency power systems are NOT included. Battery backup UPS for network equipment is included in the networking scope.

---

### 2.5 System-Specific Exclusions

21. **Fire Alarm & Life Safety:** Fire alarm systems, smoke detectors (unless Control4-integrated notification only), CO detectors, and all life-safety systems are NOT included and are governed by separate code-compliant installation by licensed fire alarm contractor.

22. **Intrusion Alarm / Security Monitoring System:** DSC, Honeywell, or other monitored alarm systems (keypads, sensors, sirens, monitoring) are NOT included. Control4 integration with an existing or separately contracted alarm system is available and may be included if specified.

23. **Telephone / VoIP Systems:** Telephone wiring, phone systems, VoIP infrastructure, and PBX equipment are NOT included.

24. **Nurse Call / Medical Alert Systems:** Not included.

25. **Intercom Systems Beyond Specified:** If a structured intercom system (beyond the door station specified) is desired, this is an optional upgrade available upon request.

26. **Elevator / Dumbwaiter Control:** Smart elevator or dumbwaiter integration is NOT included unless specifically listed. Integration is available via relay or specialized driver.

27. **EV Charging / Whole-Home Energy Monitoring:** EV charger installation is by licensed electrician. Control4 integration with EV chargers (ChargePoint, Tesla Wall Connector) is available as an optional add-on.

28. **Solar / Battery Storage Monitoring:** Solar panel monitoring or battery storage system integration (Tesla Powerwall, Enphase) is NOT included unless specified.

---

## PART 3: CHANGE ORDER TRIGGERS

*The following conditions, if encountered, will result in a written change order proposal presented to client before additional work proceeds:*

- Discovery of hazardous materials (asbestos, lead paint) in work areas
- Wire routing requiring concrete core drilling or masonry penetrations not anticipated at proposal
- Installation of additional devices or rooms beyond those in Section 3
- Change in equipment selections after order placement resulting in restocking fees
- Client-requested schedule changes requiring overtime, weekend work, or expedited delivery
- Site conditions (ceiling heights, wall materials, attic access) materially different from those represented
- Reprogramming requests substantially different from originally approved programming scope
- Network infrastructure upgrades required due to increased device count beyond original scope
- Third-party vendor changes (e.g., builder changes AV rough-in contractor, resulting in non-compliant pre-wire requiring remediation)
- Delays caused by other trades, GC, or client that result in additional mobilization trips for Symphony

---

*Last updated: {{TEMPLATE_VERSION_DATE}}*
*This library is maintained by Symphony Smart Homes. Bob: Always check for the most recent version of this file when generating proposals.*
