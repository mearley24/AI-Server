# Device Count Analysis — Proposal Rollups

Derived from four reference projects to size IP blocks and switch port plans. Sources:

| Project | Source file |
|---------|-------------|
| Gates (large) | `knowledge/proposals/Gates_Equipment_Rollup.md` |
| Hernaiz (medium) | `knowledge/proposals/Hernaiz_Equipment_Rollup.md` |
| Kelly (network / multi-structure) | `knowledge/reports/Kelly_Proposal_Intelligence.md` |
| Topletz | `knowledge/topletz/project-config.yaml` + `knowledge/topletz/tv-schedule-client.md` |

## Raw extractions

### Gates

| Category | Count |
|----------|------:|
| Keypads | 21 |
| TV | 4 |
| Speakers (CH1 + CH5 + center + sub) | 24 |
| Shades | 16 |
| Access point drops | 3 |
| Dome cameras | 4 |
| Doorbell camera | 1 |
| Lighting panel | 1 |
| Control processor | 1 |
| Router | 1 |
| Primary switch | 1 |
| NVR | 1 |

### Hernaiz

| Category | Count |
|----------|------:|
| Keypads | 17 |
| TV | 4 |
| Speakers (all types) | 18 |
| Shades | 3 |
| Access point drops | 2 |
| Cameras | 0 |
| Lighting panel | 1 |
| Control processor | 1 |
| Router | 1 |
| Primary switch | 1 |

### Kelly (SKU table — quantities per line)

| Category | Count |
|----------|------:|
| Routers (AN-520-RT) | 3 |
| 8-port PoE switches (AN-620-SW-R-8-POE) | 3 |
| 24-port fiber/PoE switches (AN-420-SW-F-24-POE) | 3 |
| Access points (AN-820-AP-I) | 3 |
| Audio matrices (TS-AMS16) | 3 |
| Dimming / loads (EA-DYN-16D-100) | 3 |
| Sub amps (EA-AMP-SUB-1D-500R) | 3 |

### Topletz (config + TV schedule)

| Category | Count / notes |
|----------|----------------|
| Control4 | yes |
| Cameras (prewire locations) | 4 |
| iPads (touchscreens) | 2 |
| TVs (client-furnished, IP on IoT) | 9 |
| Security panel | 1 (Qolsys) |
| Network | assumed 1 router, 1 main switch, 3 APs typical |
| Keypads | not in YAML — **estimate 16** for analysis (typical large C4 home; adjust from D-Tools export) |

## Normalized categories (for statistics)

Rows used for min / max / average / P90 (four projects per category where applicable):

| Category | Gates | Hernaiz | Kelly | Topletz |
|----------|------:|--------:|------:|--------:|
| keypads | 21 | 17 | 0 | 16 |
| tv | 4 | 4 | 0 | 9 |
| speakers | 24 | 18 | 0 | 0 |
| shades | 16 | 3 | 0 | 0 |
| access_points | 3 | 2 | 3 | 3 |
| surveillance_cameras | 5 | 0 | 0 | 4 |
| routers | 1 | 1 | 3 | 1 |
| main_switches | 1 | 1 | 6 | 1 |
| control_processors | 1 | 1 | 0 | 1 |
| audio_matrices | 0 | 0 | 3 | 1 |
| nvr | 1 | 0 | 0 | 1 |

**Note:** Kelly is network-heavy; zeros for AV categories pull averages down. Use **P90** and **max** when sizing “worst case” residential AV.

## Summary statistics

Method: for each category, take the four values above, sort, compute mean, min, max, and **P90** (linear interpolation on sorted samples, p=0.9).

| Category | Min | Max | Average | P90 | 10-slot block OK? |
|----------|-----|-----|---------|-----|-------------------|
| keypads* | 0 | 21 | 13.5 | ~20 | N/A — mostly ZigBee; IP keypads rare, use DHCP pool if many |
| tv | 0 | 9 | 4.25 | ~8.2 | Yes (.16–.25 + streamers .26–.35 on IoT) |
| speakers | 0 | 24 | 10.5 | ~21 | No LAN IP for passive speakers; powered/streaming endpoints use IoT blocks |
| shades | 0 | 16 | 4.75 | ~13.7 | Processor lives in .46–.55; not one IP per shade |
| access_points | 2 | 3 | 2.75 | ~3 | Yes (.16–.25 on Mgmt) |
| surveillance_cameras | 0 | 5 | 2.25 | ~4.7 | Yes (.16–.35 on VLAN 50); large sites use .56–.75 expansion |
| routers | 1 | 3 | 1.5 | ~2.7 | Yes |
| main_switches (count) | 1 | 6 | 2.25 | ~5.1 | Plan 20% free ports per switch |

## Conclusion

- **10-address blocks** are sufficient for **APs, cameras (typical resi), TVs, streamers, processors**, and **single** controller / matrix / NVR roles per category.
- **Overflow** (e.g. many IP cameras on one VLAN) should use **.56–.75 expansion** first, then **DHCP .76–.254** with documented reservations.
- **High keypad counts** do not imply high IP usage; shells should separate **ZigBee keypad count** from **LAN statics**.
