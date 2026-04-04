# Symphony Standard IP Addressing

Permanent scheme for client sites: **client-numbered subnets** plus **consistent 10-address blocks** on every VLAN. Installers recognize device roles from the fourth octet alone.

## 1. Client numbering — `10.X.Y.0/24`

- **Second octet (X)** = client number from `knowledge/network/client_registry.json` (sequential, never reused).
- **Third octet (Y)** = VLAN ID: `1`, `10`, `20`, `30`, `40`, or `50`.
- **Fourth octet** = device slot per block rules below.

Examples:

| Client | Registry | Management | Control | Surveillance |
|--------|----------|------------|---------|--------------|
| Topletz | 001 | 10.1.1.0/24 | 10.1.20.0/24 | 10.1.50.0/24 |
| Gates | 002 | 10.2.1.0/24 | 10.2.20.0/24 | 10.2.50.0/24 |

Flat networks still get a unique `10.X.1.0/24`; VLANs can be added later without renumbering the core plan.

## 2. Ten-address blocks (every subnet)

| Fourth octet | Role |
|--------------|------|
| .1–.15 | Networking: gateway, routers, switches, NVRs (where applicable), uplinks |
| .16–.25 | Category A (per VLAN) |
| .26–.35 | Category B |
| .36–.45 | Category C |
| .46–.55 | Category D |
| .56–.65 | Category E |
| .66–.75 | Category F |
| .76–.254 | DHCP pool (new gear lands here; assign statics from reserved blocks as commissioned) |

## 3. Per-VLAN category assignments

### VLAN 1 — Management (`10.X.1.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway, router, switches, fiber uplinks |
| .16–.25 | Indoor access points |
| .26–.35 | Outdoor access points |
| .36–.45 | UPS / WattBox / PDUs |
| .46–.75 | Reserved |
| .76–.254 | DHCP pool |

### VLAN 10 — Trusted (`10.X.10.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway |
| .76–.254 | DHCP only (phones, laptops, tablets) |

### VLAN 20 — Control (`10.X.20.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway, VLAN SVI |
| .16–.25 | Control / distribution: EA-5, EA-3, CORE, AMS-8/AMS-16, networked DSP — not passive amps |
| .26–.35 | Touchscreens / iPads / control surfaces |
| .36–.45 | Lighting processors (e.g. Lutron RA3) |
| .46–.55 | Shade controllers |
| .56–.65 | HVAC interfaces |
| .66–.75 | Security panels & keypads (IP) |
| .76–.254 | DHCP pool |

### VLAN 30 — IoT (`10.X.30.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway |
| .16–.25 | Smart TVs / displays |
| .26–.35 | Streamers (Apple TV, Roku, etc.) |
| .36–.45 | Voice assistants |
| .46–.55 | Smart locks / appliances |
| .56–.65 | Pool / spa / outdoor IoT |
| .66–.75 | Misc IoT |
| .76–.254 | DHCP pool |

### VLAN 40 — Guest (`10.X.40.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway |
| .76–.254 | DHCP only |

### VLAN 50 — Surveillance (`10.X.50.0/24`)

| Block | Use |
|-------|-----|
| .1–.15 | Gateway, NVRs |
| .16–.25 | Exterior cameras |
| .26–.35 | Interior cameras |
| .36–.45 | Doorbells / video intercom |
| .46–.55 | Access control |
| .56–.75 | Camera expansion |
| .76–.254 | DHCP pool |

## 4. Validation vs proposal data

See `device_count_analysis.md`. High-volume categories (e.g. 21+ IP endpoints in one block) may need:

- **DHCP + reservations** for overflow, or
- **Sub-dividing** within .76–.254 with documentation, or
- **Expanding** blocks in a project-specific addendum (rare).

ZigBee/legacy Control4 keypads often have **no LAN IP** — list counts in the shell without consuming a /24 static slot.

## 5. Legacy `192.168.x.x` documentation

Some racks still document `192.168.VLAN.x` for field stickers. When generating shells, prefer **this 10.X.Y.Z standard** for new work; migrate legacy sites on a planned cutover.
