# System Shell — Kelly
## [from proposal intelligence — fill at contract]

Generated: 2026-04-03 | Version: 1

### Network Overview
| VLAN | Subnet | Purpose | Devices |
|------|--------|---------|---------|
| 1 | 10.4.1.0/24 | Management | Router, Switch, APs |
| 20 | 10.4.20.0/24 | Control | Controller, touchscreens, audio matrix, security |
| 40 | 10.4.40.0/24 | Guest | DHCP only |

### Device Registry
| Room | Device | Model | IP | VLAN | Switch Port | Cable Label | Status |
|------|--------|-------|-----|------|-------------|-------------|--------|
| Building 1 Rack | Router | AN-520-RT | 10.4.1.1 | 1 | - | - | ⬜ |
| Building 1 Rack | Switch 8P | AN-620-SW-R-8-POE | 10.4.1.2 | 1 | - | - | ⬜ |
| Building 1 Rack | Switch 24P | AN-420-SW-F-24-POE | 10.4.1.3 | 1 | - | - | ⬜ |
| Building 1 Rack | Access Point B1 | AN-820-AP-I | 10.4.1.16 | 1 | Sw1-P1 | RK-AP-01 | ⬜ |
| Building 1 Rack | Audio Matrix B1 | TS-AMS16 | 10.4.20.16 | 20 | Sw1-P4 | RK-AMS-01 | ⬜ |
| Building 2 Rack | Router | AN-520-RT | 10.4.1.1 | 1 | - | - | ⬜ |
| Building 2 Rack | Switch 8P | AN-620-SW-R-8-POE | 10.4.1.2 | 1 | - | - | ⬜ |
| Building 2 Rack | Switch 24P | AN-420-SW-F-24-POE | 10.4.1.3 | 1 | - | - | ⬜ |
| Building 2 Rack | Access Point B2 | AN-820-AP-I | 10.4.1.17 | 1 | Sw1-P2 | RK-AP-02 | ⬜ |
| Building 2 Rack | Audio Matrix B2 | TS-AMS16 | 10.4.20.17 | 20 | Sw1-P5 | RK-AMS-02 | ⬜ |
| Building 3 Rack | Router | AN-520-RT | 10.4.1.1 | 1 | - | - | ⬜ |
| Building 3 Rack | Switch 8P | AN-620-SW-R-8-POE | 10.4.1.2 | 1 | - | - | ⬜ |
| Building 3 Rack | Switch 24P | AN-420-SW-F-24-POE | 10.4.1.3 | 1 | - | - | ⬜ |
| Building 3 Rack | Access Point B3 | AN-820-AP-I | 10.4.1.18 | 1 | Sw1-P3 | RK-AP-03 | ⬜ |
| Building 3 Rack | Audio Matrix B3 | TS-AMS16 | 10.4.20.18 | 20 | Sw1-P6 | RK-AMS-03 | ⬜ |

### Access Codes & Credentials
| System | Username | Password | Notes |
|--------|----------|----------|-------|
| Router Admin | admin | [set on site] | 10.4.1.1 |
| WiFi - Trusted | [client SSID] | [set on site] | VLAN 10 |
| WiFi - Guest | Kelly-Guest | [set on site] | VLAN 40 |
| Luma NVR | admin | [set on site] | VLAN 50 |
| Control4 Composer | Kelly | [set on site] | HE license |

### Cable Label Schedule
| Label | From | To | Cable Type | Length Est |
|-------|------|-----|------------|------------|
| RK-AP-01 | Building 1 Rack | Rack Sw1-P1 | Cat6 | TBD |
| RK-AP-02 | Building 2 Rack | Rack Sw1-P2 | Cat6 | TBD |
| RK-AP-03 | Building 3 Rack | Rack Sw1-P3 | Cat6 | TBD |
| RK-AMS-01 | Building 1 Rack | Rack Sw1-P4 | Cat6 | TBD |
| RK-AMS-02 | Building 2 Rack | Rack Sw1-P5 | Cat6 | TBD |
| RK-AMS-03 | Building 3 Rack | Rack Sw1-P6 | Cat6 | TBD |

### Switch Port Allocation
| Port | Device | VLAN | PoE | Cable Label |
|------|--------|------|-----|-------------|
| 1 | Access Point B1 | 1 | ✅ | RK-AP-01 |
| 2 | Access Point B2 | 1 | ✅ | RK-AP-02 |
| 3 | Access Point B3 | 1 | ✅ | RK-AP-03 |
| 4 | Audio Matrix B1 | 20 | ✅ | RK-AMS-01 |
| 5 | Audio Matrix B2 | 20 | ✅ | RK-AMS-02 |
| 6 | Audio Matrix B3 | 20 | ✅ | RK-AMS-03 |

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
