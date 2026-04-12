# Symphony IP Addressing Standard

## When to Use
Every new client site design. Building a network plan, VLAN scheme, or device registry.

## Steps

1. **Assign a client number** — sequential, from `knowledge/network/client_registry.json`. Never reused.

2. **Build the subnet scheme** — `10.{client}.{vlan}.0/24`:
   - Second octet = client number
   - Third octet = VLAN ID

3. **Standard VLANs:**
   | VLAN | Third Octet | Purpose |
   |---|---|---|
   | 1 | 1 | Management (router, switch, APs) |
   | 10 | 10 | Trusted (staff devices, iPads) |
   | 20 | 20 | Control (C4 controller, touchscreens, audio matrix, security panel) |
   | 30 | 30 | IoT (TVs, streamers, smart devices) |
   | 40 | 40 | Guest (DHCP only, internet access only) |
   | 50 | 50 | Surveillance (NVR, cameras) |

4. **Assign fourth-octet blocks** (same rule on every subnet):
   | Range | Role |
   |---|---|
   | .1–.15 | Networking gear (gateway, switches, NVRs) |
   | .16–.25 | Category A devices |
   | .26–.35 | Category B devices |
   | .36–.45 | Category C devices |
   | .46–.55 | Category D devices |
   | .56–.65 | Category E devices |
   | .66–.75 | Category F devices |

5. **VLAN-specific fourth-octet assignments:**
   - **VLAN 20 (Control):** .16=C4 controller, .17=audio matrix, .26–.35=iPads/touchscreens, .66=security panel
   - **VLAN 50 (Surveillance):** .2=NVR, .16+=cameras

6. **Document in system shell** — record every device in the system_shell.md device registry table.

## Notes
- Flat networks (no VLANs) still get a unique `10.X.1.0/24`. VLANs can be added later without renumbering.
- Identifiable from 4th octet alone — installers can recognize device roles without looking anything up.
- First three clients: Topletz=001 (10.1.X), Gates=002 (10.2.X), Hernaiz=003 (10.3.X), Kelly=004 (10.4.X).

## Related
- `knowledge/network/device_count_analysis.md`
- `knowledge/projects/*/system_shell.md`
