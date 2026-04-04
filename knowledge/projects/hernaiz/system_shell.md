# System Shell — Hernaiz
## [from proposal schedule — fill at contract]

Generated: 2026-04-03 | Version: 1

### Network Overview
| VLAN | Subnet | Purpose | Devices |
|------|--------|---------|---------|
| 1 | 10.3.1.0/24 | Management | Router, Switch, APs |
| 20 | 10.3.20.0/24 | Control | Controller, touchscreens, audio matrix, security |
| 30 | 10.3.30.0/24 | IoT | TVs, streamers |
| 40 | 10.3.40.0/24 | Guest | DHCP only |

### Device Registry
| Room | Device | Model | IP | VLAN | Switch Port | Cable Label | Status |
|------|--------|-------|-----|------|-------------|-------------|--------|
| Rack | Router | AN-520-RT | 10.3.1.1 | 1 | - | - | ⬜ |
| Rack | Switch | AN-820-24P | 10.3.1.2 | 1 | - | - | ⬜ |
| Rack | NVR | Luma NVR | 10.3.50.2 | 50 | Sw1-P3 | RK-NVR-01 | ⬜ |
| AP Zone 1 | Access Point 1 | AN-820-AP-I | 10.3.1.16 | 1 | Sw1-P1 | Z1-AP-01 | ⬜ |
| AP Zone 2 | Access Point 2 | AN-820-AP-I | 10.3.1.17 | 1 | Sw1-P2 | Z2-AP-02 | ⬜ |
| Rack | Controller | Control4 | 10.3.20.16 | 20 | Sw1-P4 | RK-EA-01 | ⬜ |
| Various | Keypads (×17) | C4 (ZigBee) | — | — | — | — | ⬜ |
| TV 1 | Display | TV | 10.3.30.16 | 30 | - | - | ⬜ |
| TV 2 | Display | TV | 10.3.30.17 | 30 | - | - | ⬜ |
| TV 3 | Display | TV | 10.3.30.18 | 30 | - | - | ⬜ |
| TV 4 | Display | TV | 10.3.30.19 | 30 | - | - | ⬜ |

### Access Codes & Credentials
| System | Username | Password | Notes |
|--------|----------|----------|-------|
| Router Admin | admin | [set on site] | 10.3.1.1 |
| WiFi - Trusted | [client SSID] | [set on site] | VLAN 10 |
| WiFi - Guest | Hernaiz-Guest | [set on site] | VLAN 40 |
| Luma NVR | admin | [set on site] | VLAN 50 |
| Control4 Composer | Hernaiz | [set on site] | HE license |

### Cable Label Schedule
| Label | From | To | Cable Type | Length Est |
|-------|------|-----|------------|------------|
| Z1-AP-01 | Zone 1 | Rack Sw1-P1 | Cat6 | TBD |
| Z2-AP-02 | Zone 2 | Rack Sw1-P2 | Cat6 | TBD |
| RK-NVR-01 | Rack | Rack Sw1-P3 | Cat6 | TBD |
| RK-EA-01 | Rack | Rack Sw1-P4 | Cat6 | TBD |

### Switch Port Allocation
| Port | Device | VLAN | PoE | Cable Label |
|------|--------|------|-----|-------------|
| 1 | Access Point 1 | 1 | ✅ | Z1-AP-01 |
| 2 | Access Point 2 | 1 | ✅ | Z2-AP-02 |
| 3 | NVR | 50 | — | RK-NVR-01 |
| 4 | Controller | 20 | ✅ | RK-EA-01 |

### Commissioning Checklist
| # | Task | Status |
|---|------|--------|
| 1 | Router configured, VLANs created | ⬜ |
| 2 | Switch configured, port VLANs assigned | ⬜ |
| 3 | All APs powered and adopted | ⬜ |
| 4 | Controller online, rooms created | ⬜ |
| 5 | All cameras visible in NVR | ⬜ |
| 6 | Qolsys enrolled, C4 driver connected | ⬜ |
| 7 | All audio zones tested | ⬜ |
| 8 | Client WiFi networks active | ⬜ |
| 9 | Remote access verified (Tailscale/VPN) | ⬜ |
| 10 | Client walkthrough complete | ⬜ |
