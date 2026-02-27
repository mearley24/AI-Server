# Scope Block: Networking Infrastructure
<!-- BOB INSTRUCTIONS: Use this block to populate the networking section of the proposal. Symphony installs Araknis Networks equipment as its standard networking platform. This block covers routers, switches, wireless access points, structured cabling, and rack infrastructure. -->

---

## SYSTEM DESCRIPTION

Symphony Smart Homes builds every project on a professionally designed, managed network — the foundation that all smart home systems depend on. We use Araknis Networks equipment (Snap One's professional networking brand), monitored and remotely managed via the OvrC platform. Every network is designed with VLANs, QoS, and guest isolation as standard practice, not optional extras.

---

## ARAKNIS NETWORKS EQUIPMENT SELECTION

### Routers / Gateways

| Model | Throughput | WAN Ports | Best For |
|-------|-----------|-----------|----------|
| Araknis AN-500-RT-4L | 1 Gbps | 1x Gigabit WAN | Standard residential, 1 Gbps ISP |
| Araknis AN-700-RT-4L | 2.5 Gbps multi-WAN | 2x WAN (failover) | Multi-WAN, fiber + backup ISP |
| Araknis AN-800-RT-2W2L | 2.5 Gbps | 2x WAN | Large home, multi-ISP, high device count |

*Standard specification: Araknis AN-500-RT-4L for most residential projects. Upgrade to AN-700 or AN-800 for homes with multiple ISP connections or fiber at 2.5 Gbps+.*

---

### Managed Switches

| Model | Ports | PoE | Speed | Best For |
|-------|-------|-----|-------|----------|
| Araknis AN-310-SW-8-POE | 8-port | 802.3at (4 PoE) | Gigabit | Small distribution switch, IDF closet |
| Araknis AN-310-SW-16-POE | 16-port | 802.3at (8 PoE) | Gigabit | Medium home, equipment room |
| Araknis AN-310-SW-24-POE | 24-port | 802.3at (12 PoE) | Gigabit | Larger homes with many wired devices |
| Araknis AN-510-SW-R-8-POE | 8-port | 802.3at/af | Gigabit | High-density PoE, AV VLAN isolation |
| Araknis AN-510-SW-R-16-POE | 16-port | 802.3at/af | Gigabit | Main distribution switch, large homes |
| Araknis AN-510-SW-R-24-POE | 24-port | 802.3at/af | Gigabit | Enterprise-class residential, estates |

*Standard specification: AN-310-SW-16-POE for most homes. Upgrade to AN-510 series for homes requiring AV VLAN isolation and high-density PoE.*

---

### Wireless Access Points (WAPs)

| Model | Standard | Bands | Spatial Streams | Best For |
|-------|---------|-------|----------------|----------|
| Araknis AN-510-AP-I-AC | Wi-Fi 5 (AC) | 2.4 + 5 GHz | 2x2 | Standard rooms, moderate device count |
| Araknis AN-510-AP-I-AX | Wi-Fi 6 (AX) | 2.4 + 5 + 6 GHz | 4x4 | High-density areas, future-proof |
| Araknis AN-810-AP-I-AX | Wi-Fi 6E (AX) | 2.4 + 5 + 6 GHz | 4x4 OFDMA | Premium performance, estate-level |
| Araknis AN-510-AP-O-AC | Outdoor Wi-Fi 5 | 2.4 + 5 GHz | 2x2 | Covered patios, outdoor areas |
| Araknis AN-810-AP-O-AX | Outdoor Wi-Fi 6E | 2.4 + 5 + 6 GHz | 4x4 | Premium outdoor/pool deck |

*WAP placement: Symphony follows the "1 AP per 1,000–1,500 sq ft" guideline, adjusted for floor plan, building materials (concrete, steel), and device density. Every AP hardwired via CAT6A to the managed switch — no mesh or daisy-chaining.*

---

## VLAN DESIGN (STANDARD SYMPHONY TEMPLATE)

Symphony deploys a standard 4-VLAN architecture on all managed network projects:

| VLAN ID | Name | Purpose | Devices |
|---------|------|---------|----------|
| VLAN 10 | Management | Network device management | Router, switches, WAPs, OvrC |
| VLAN 20 | IoT / Smart Home | All smart home devices | Control4, Lutron, cameras, thermostats, locks |
| VLAN 30 | AV / Video | AV distribution traffic | HDMI-over-IP encoders/decoders, AV switches |
| VLAN 40 | Guest | Isolated internet-only access | Guest Wi-Fi, visitor devices |
| VLAN 1 (default) | Client Trusted | Client personal devices | Phones, computers, tablets, smart TVs |

*VLANs are configured with inter-VLAN routing rules: Control4 (VLAN 20) can communicate with devices on all VLANs for control purposes. AV VLAN 30 is isolated from guest VLAN 40. Guest VLAN has no access to any other VLAN.*

---

## STRUCTURED CABLING

### Cable Types

| Cable | Standard | Use Case |
|-------|---------|----------|
| CAT6A (Augmented Category 6) | TIA-568-C.2 | All data drops, WAPs, IP cameras, PoE devices |
| CAT6 | TIA-568-C.2 | Secondary data drops, lower-priority runs |
| Coaxial (RG-6) | — | Cable TV feed, satellite, antenna distribution |
| Fiber (OM4 multimode) | — | Long inter-building runs (detached garage, guest house) |
| 18/2 Shielded (for Lutron) | — | Lutron HomeWorks QSX device wiring |
| 18/4 or 22/4 | — | Thermostat wiring |

*Symphony's standard: CAT6A for all data drops. CAT6 only if CAT6A is not feasible in a specific run. All cables labeled at both ends with room name and port number.*

### Cabling Standards & Installation Practice

- All horizontal cabling rated for in-wall use (CL2 or CL3 as applicable)
- Maximum run length: 295 ft (90m) per TIA-568 standard
- All data drops terminated on 110 patch panels in equipment rack
- Patch cables (cat6a, 6") from panel to switch; all patch cables labeled
- All conduit stubs installed at TV locations, equipment rooms, and WAP locations
- VELCRO cable management in rack (no zip ties on active cables)
- All coaxial terminated with compression connectors

---

## NETWORK INFRASTRUCTURE (RACK)

### Standard Equipment Rack Build

| Component | Model | Notes |
|-----------|-------|-------|
| Rack enclosure | Middle Atlantic / Legrand | 12U–30U depending on project scope |
| Power distribution | WattBox WB-800-IPVM-8 or WB-700 | IP-controlled PDU with surge, remote reboot |
| Router | Araknis per selection | Top of rack |
| Core switch | Araknis per selection | — |
| Distribution switches (IDFs) | Araknis per selection | Mounted at each IDF location |
| Patch panels | Belden or equivalent CAT6A | 24-port, 1U per 24 data drops |
| UPS (uninterruptible power supply) | CyberPower PR1500LCD or APC SMT1500 | 1500VA minimum for rack |
| Rack fan unit | Quiet, thermostat-controlled | Optional; required for enclosed racks |

### OvrC Remote Management

All Araknis networking equipment is managed via **OvrC** (Snap One's remote management platform):
- Real-time device status and monitoring
- Remote reboot of any device (WattBox integration)
- Bandwidth monitoring and utilization graphs
- Offline alerts (email/SMS notification when device goes offline)
- Remote configuration without site visit
- Client OvrC Home app (optional): Lets client see network status and request reboots

*Symphony includes OvrC Pro subscription in all managed network installs. OvrC Pro enables 24/7 proactive monitoring and supports Symphony's annual service agreements.*

---

## INTERNET SERVICE PROVIDER (ISP) COORDINATION

- Symphony does not provide ISP service.
- Client is responsible for securing broadband service prior to Symphony network commissioning.
- Symphony recommends minimum **500 Mbps symmetric** for smart home projects; **1 Gbps symmetric** for projects with 4K video distribution, work-from-home, and heavy AV streaming.
- ISP modem/ONT (fiber) is provided by ISP; Symphony connects to ISP handoff and installs Araknis router downstream.
- For projects with ISP-provided router (double-NAT scenario): Symphony configures Araknis router in DMZ mode or requests ISP place modem in bridge mode.

---

## STANDARD INCLUSIONS (Networking)

- Araknis router, switches, and WAPs per equipment list
- Full VLAN configuration per Symphony standard template
- All structured cabling (CAT6A) to specified drop locations
- Patch panel termination and labeling
- OvrC remote management setup and activation
- WattBox IP power distribution unit
- UPS (uninterruptible power supply) for rack
- Equipment rack (open frame or vented enclosure per scope)
- Full network documentation (IP address table, VLAN map, cable log)
- Post-install speed test and Wi-Fi coverage walk (results documented)

## STANDARD EXCLUSIONS (Networking)

- ISP service fees or modem equipment
- Electrical circuits for rack power (by electrical contractor)
- Conduit or innerduct installation (available as option if required by building type)
- Fiber optic termination at ends other than head-end and remote IDF (specialty fiber terminations quoted separately)
- Cybersecurity audits or penetration testing (available as optional service)
- Network monitoring beyond OvrC (PRTG, Auvik, etc. — available as premium option)
- Additional ISP failover hardware beyond AN-700 router capability

---

## COMMON ASSUMPTIONS (Networking)

- Client has selected an ISP and service will be active before network commissioning.
- All equipment room / IDF locations have adequate power (dedicated 20A circuit recommended for equipment room; included in electrical contractor scope).
- Cabling is installed during rough-in phase before drywall; Symphony requires access to stud bays and above-ceiling spaces during rough-in.
- Wi-Fi coverage design is based on standard residential construction. Homes with thick masonry walls, metal mesh in stucco, or concrete floors may require additional WAPs — identified at site survey.
- Client devices (phones, laptops, smart TVs) are set up by client. Symphony configures network and provides Wi-Fi credentials; client device configuration is not in scope.
- CAT6A runs exceeding 295 ft require fiber optic extension — Symphony will identify during design phase; masonry walls may require conduit installation — additional cost if not pre-planned
