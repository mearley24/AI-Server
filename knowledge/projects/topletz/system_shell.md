# System Shell — Topletz Residence
## 84 Aspen Meadow Drive, Edwards, CO 81632

Generated: 2026-04-03 | Version: 1

### Network Overview
| VLAN | Subnet | Purpose | Devices |
|------|--------|---------|---------|
| 1 | 10.1.1.0/24 | Management | Router, Switch, APs |
| 20 | 10.1.20.0/24 | Control | Controller, touchscreens, audio matrix, security |
| 30 | 10.1.30.0/24 | IoT | TVs, streamers |
| 40 | 10.1.40.0/24 | Guest | DHCP only |
| 50 | 10.1.50.0/24 | Surveillance | NVR, 4× Camera |

### Device Registry
| Room | Device | Model | IP | VLAN | Switch Port | Cable Label | Status |
|------|--------|-------|-----|------|-------------|-------------|--------|
| Rack | Router | AN-520-RT | 10.1.1.1 | 1 | - | - | ⬜ |
| Rack | Switch | AN-620-SW-R-24-POE | 10.1.1.2 | 1 | - | - | ⬜ |
| Great Room | Access Point 1 | AN-820-AP-I | 10.1.1.16 | 1 | Sw1-P1 | LR-AP-01 | ⬜ |
| Master Bedroom | Access Point 2 | AN-820-AP-I | 10.1.1.17 | 1 | Sw1-P2 | MBR-AP-02 | ⬜ |
| Kitchen | Access Point 3 | AN-820-AP-I | 10.1.1.18 | 1 | Sw1-P3 | KIT-AP-03 | ⬜ |
| Rack | NVR | Luma NVR | 10.1.50.2 | 50 | Sw1-P4 | RK-NVR-01 | ⬜ |
| Front Entry | Camera 1 | Luma IP | 10.1.50.16 | 50 | NVR-P1 | FE-CAM-01 | ⬜ |
| Rear | Camera 2 | Luma IP | 10.1.50.17 | 50 | NVR-P2 | OUT-CAM-02 | ⬜ |
| Garage | Camera 3 | Luma IP | 10.1.50.18 | 50 | NVR-P3 | GAR-CAM-03 | ⬜ |
| Driveway | Camera 4 | Luma IP | 10.1.50.19 | 50 | NVR-P4 | DRV-CAM-04 | ⬜ |
| Rack | Controller | C4-EA5 | 10.1.20.16 | 20 | Sw1-P5 | RK-EA-01 | ⬜ |
| Rack | Audio Matrix | TS-AMS16 | 10.1.20.17 | 20 | Sw1-P6 | RK-AMS-01 | ⬜ |
| Kitchen/TV Room | iPad 1 | Apple iPad | 10.1.20.26 | 20 | - | - | ⬜ |
| Master Bedroom | iPad 2 | Apple iPad | 10.1.20.27 | 20 | - | - | ⬜ |
| Garage Entry | Security Panel | Qolsys IQ Panel 4 | 10.1.20.66 | 20 | Sw1-P7 | GAR-QOL-01 | ⬜ |
| TV Zone 1 | Smart TV | Client TV | 10.1.30.16 | 30 | - | - | ⬜ |
| TV Zone 2 | Smart TV | Client TV | 10.1.30.17 | 30 | - | - | ⬜ |
| TV Zone 3 | Smart TV | Client TV | 10.1.30.18 | 30 | - | - | ⬜ |
| TV Zone 4 | Smart TV | Client TV | 10.1.30.19 | 30 | - | - | ⬜ |
| TV Zone 5 | Smart TV | Client TV | 10.1.30.20 | 30 | - | - | ⬜ |
| TV Zone 6 | Smart TV | Client TV | 10.1.30.21 | 30 | - | - | ⬜ |
| TV Zone 7 | Smart TV | Client TV | 10.1.30.22 | 30 | - | - | ⬜ |
| TV Zone 8 | Smart TV | Client TV | 10.1.30.23 | 30 | - | - | ⬜ |
| TV Zone 9 | Smart TV | Client TV | 10.1.30.24 | 30 | - | - | ⬜ |
| Various | Control4 Keypads (×16, est.) | C4 / ZigBee | — | — | — | — | ⬜ |

### Access Codes & Credentials
| System | Username | Password | Notes |
|--------|----------|----------|-------|
| Router Admin | admin | [set on site] | 10.1.1.1 |
| WiFi - Trusted | [client SSID] | [set on site] | VLAN 10 |
| WiFi - Guest | Topletz Residence-Guest | [set on site] | VLAN 40 |
| Luma NVR | admin | [set on site] | VLAN 50 |
| Control4 Composer | Topletz Residence | [set on site] | HE license |

### Cable Label Schedule
| Label | From | To | Cable Type | Length Est |
|-------|------|-----|------------|------------|
| FE-CAM-01 | Front Entry | Rack NVR-P1 | Cat6 | TBD |
| OUT-CAM-02 | Rear | Rack NVR-P2 | Cat6 | TBD |
| GAR-CAM-03 | Garage | Rack NVR-P3 | Cat6 | TBD |
| DRV-CAM-04 | Driveway | Rack NVR-P4 | Cat6 | TBD |
| LR-AP-01 | Great Room | Rack Sw1-P1 | Cat6 | TBD |
| MBR-AP-02 | Master Bedroom | Rack Sw1-P2 | Cat6 | TBD |
| KIT-AP-03 | Kitchen | Rack Sw1-P3 | Cat6 | TBD |
| RK-NVR-01 | Rack | Rack Sw1-P4 | Cat6 | TBD |
| RK-EA-01 | Rack | Rack Sw1-P5 | Cat6 | TBD |
| RK-AMS-01 | Rack | Rack Sw1-P6 | Cat6 | TBD |
| GAR-QOL-01 | Garage Entry | Rack Sw1-P7 | Cat6 | TBD |

### Switch Port Allocation
| Port | Device | VLAN | PoE | Cable Label |
|------|--------|------|-----|-------------|
| 1 | Access Point 1 | 1 | ✅ | LR-AP-01 |
| 2 | Access Point 2 | 1 | ✅ | MBR-AP-02 |
| 3 | Access Point 3 | 1 | ✅ | KIT-AP-03 |
| 4 | NVR | 50 | — | RK-NVR-01 |
| 5 | Controller | 20 | ✅ | RK-EA-01 |
| 6 | Audio Matrix | 20 | ✅ | RK-AMS-01 |
| 7 | Security Panel | 20 | ✅ | GAR-QOL-01 |

### NVR PoE Ports (cameras only)
| Port | Device | VLAN | PoE | Cable Label |
|------|--------|------|-----|-------------|
| NVR-P1 | Camera 1 | 50 | ✅ | FE-CAM-01 |
| NVR-P2 | Camera 2 | 50 | ✅ | OUT-CAM-02 |
| NVR-P3 | Camera 3 | 50 | ✅ | GAR-CAM-03 |
| NVR-P4 | Camera 4 | 50 | ✅ | DRV-CAM-04 |

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
