# Control4 TV Driver Compatibility Reference

**Last Updated:** April 1, 2026  
**Purpose:** AI assistant (Bob) lookup table — validate client TV selections against C4 integration capability before spec/proposal.  
**Primary Sources:** [Control4 Driver Search Database](https://drivers.control4.com/solr/drivers/browse), [Chowmain Software](https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv), [DriverCentral](https://drivercentral.io/platforms/control4-drivers/audio-video/), CE Pro, Residential Systems, Reddit/r/Control4

---

## Integration Level Definitions

| Level | Label | Description |
|-------|-------|-------------|
| **1** | **Native SDDP (IP)** | TV auto-discovers on network, two-way IP control, no extra hardware. Certified driver free in C4 ecosystem. **Best.** |
| **2** | **3rd-Party IP Driver** | Requires purchased driver (Chowmain or DriverCentral). Works but dependent on third-party updates and DriverCentral Cloud Driver in project. |
| **3** | **IR Only** | Requires physical IR flasher + wire run per location. One-way, no status feedback. |
| **4** | **No Driver** | Cannot be controlled from C4 at all. |

---

## Quick Reference Summary Table

| Brand | Model Line | Year | Level | Integration | Driver Source | Snap One Channel |
|-------|-----------|------|-------|------------|--------------|-----------------|
| Samsung | QN90F (Neo QLED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | QN80F (Neo QLED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | QN70F (Neo QLED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | Q80D / Q8F (QLED) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | Q70D / Q7F (QLED) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | Q60D / Q6F (QLED) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | S95F (QD-OLED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | S90D / S90F (QD-OLED) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | S85D / S85F (QD-OLED) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | The Frame (LS03) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Samsung | Crystal UHD (DU8000/DU7200) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| Sony | XR90 / BRAVIA 9 (Mini LED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Sony | XR80 / BRAVIA 8 (OLED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Sony | XR70 / BRAVIA 7 (Mini LED) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Sony | XR50 / BRAVIA 5 (LCD) | 2025 | 1 | Native SDDP (IP) | Control4 | No |
| Sony | X90L / X85L (4K LED) | 2023 | 1 | Native SDDP (IP) | Control4 | No |
| LG | G5 OLED evo | 2025 | 1 | Native SDDP (IP) | Control4 | **Yes** |
| LG | C5 OLED evo | 2025 | 1 | Native SDDP (IP) | Control4 | **Yes** |
| LG | B5 OLED | 2025 | 1 | Native SDDP (IP) | Control4 | **Yes** |
| LG | C4 / B4 OLED | 2024 | 1 | Native SDDP (IP) | Control4 | **Yes** |
| LG | QNED (2024–2025) | 2024 | 1 | Native SDDP (IP) | Control4 | **Yes** |
| LG | NanoCell (2024–2025) | 2024 | 1 | Native SDDP (IP) | Control4 | No |
| LG | UQ Series | 2022 | 1 | Native SDDP (IP) | Control4 | No |
| TCL | QM8K (Mini LED QLED) | 2024 | 2 | 3rd-Party IP Driver | DriverCentral (Cindev) | No |
| TCL | QM7 / QM6K (Google TV) | 2024 | 2 | 3rd-Party IP Driver | DriverCentral (Cindev) | No |
| TCL | Q7 / S4 / 4-Series (Roku) | 2024 | 3 | IR Only | IR or generic Roku | No |
| Hisense | U9N (Mini LED ULED) | 2024 | 2 | 3rd-Party IP Driver | Chowmain + native | No |
| Hisense | U8N (Mini LED ULED) | 2024 | 2 | 3rd-Party IP Driver | Chowmain + native | No |
| Hisense | U7N (ULED 4K) | 2024 | 2 | 3rd-Party IP Driver | Chowmain | No |
| Hisense | U6N (ULED 4K) | 2024 | 2 | 3rd-Party IP Driver | Chowmain | No |
| Hisense | A-Series (Android/Google TV) | 2024 | 3 | IR Only | IR | No |
| Vizio | M-Series (QLED) | 2024 | 2 | 3rd-Party IP Driver | DriverCentral (Solidified) | No |
| Vizio | V-Series (4K LED) | 2024 | 2 | 3rd-Party IP Driver | DriverCentral (Solidified) | No |
| Vizio | P-Series (legacy) | 2022 | 3 | IR Only | IR | No |

---

## Detailed Brand Entries

---

### SAMSUNG

**Overview:** Samsung has been a Control4 SDDP partner since 2017. All current mainstream 4K lines — QLED, Neo QLED, QD-OLED, Crystal UHD, and The Frame — have native certified IP drivers created by Control4, with SDDP auto-discovery. Driver is free. Samsung is retail-only (not through Snap One/Mountain West dealer channel), but the driver itself is freely available within the Control4 ecosystem.

**Critical caveat:** Samsung TVs purchased from warehouse clubs (Costco, Sam's Club) often carry stripped/alternate model numbers that don't match standard driver entries and may fail SDDP auto-discovery. Always specify retail channel purchases and verify model number format ends in standard suffix (e.g., FXZA).

---

#### Samsung QN90F (2025 Neo QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 215 |
| **Driver Last Updated** | October 24, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only (Best Buy, Samsung.com) |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed model numbers: QN65QN90FAFXZA, QN75QN90FAFXZA, QN65QN90FDFXZA, QN75QN90FDFXZA. Top-tier Neo QLED with Mini LED, NQ4 AI Gen3 processor, 4.2.2 channel audio. Auto-discovers via SDDP. |
| **Bob Recommendation** | **APPROVE** — Best-in-class C4 integration. |

---

#### Samsung QN80F (2025 Neo QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 215 |
| **Driver Last Updated** | October 24, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN65QN80FAFXZA, QN75QN80FAFXZA, QN65QN80FDFXZA, QN75QN80FDFXZA. Mid-tier Neo QLED. SDDP auto-discovers. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung QN70F (2025 Neo QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 215 |
| **Driver Last Updated** | October 24, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN75QN70FAFXZA, QN75QN70FDFXZA, QN85QN70FAFXZA. Entry Neo QLED (same 144Hz gaming features as QN90F). |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung Q80D / Q8F (2024 QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN65Q80DAFXZA, QN75Q80DAFXZA, QN85Q80DAFXZA, QN75Q80DDFXZA. Standard QLED VA panel. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung Q70D / Q7F (2024 QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN65Q70DAFXZA, QN65Q72DDFXZA. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung Q60D / Q6F (2024 QLED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN32Q60DAFXZA, QN50Q60DAFXZA, QN65Q60DAFXZA, QN65Q60DDFXZA, QN70Q60DAFXZA. Entry QLED. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung S95F (2025 QD-OLED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: QN55S95DAFXZA, QN65S95DAFXZA, QN77S95DAFXZA. Flagship Samsung QD-OLED. VDE 'Real Black' certification. Glare-Free 2.0. Excellent picture quality. Full SDDP. |
| **Bob Recommendation** | **APPROVE** — Premium QD-OLED, best-in-class integration. |

---

#### Samsung S90D / S90F (2024 QD-OLED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Notes** | Confirmed: QN48S90DDEXZA, QN55S90DAFXZA, QN65S90DAFXZA, QN65S90DDFXZA. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung S85D / S85F (2024 QD-OLED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Notes** | Confirmed: QN55S85DDEXZA, QN65S85DAEXZA, QN65S85DDEXZA, QN77S85DDEXZA, QN83S85DAEXZA, QN83S85DDEXZA. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung The Frame (LS03 — 2024/2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024–2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 (2024) / 215 (2025) |
| **Driver Last Updated** | October 24, 2025 (2025 model) |
| **Notes** | Confirmed 2024: QN75LS03DAFXZA, QN75LS03DDFXZA. Confirmed 2025: QN85LS03FWFXZA. Art mode lifestyle display with full C4 integration. |
| **Bob Recommendation** | **APPROVE** |

---

#### Samsung Crystal UHD (DU8000 / DU7200 — 2024)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 213 |
| **Driver Last Updated** | January 30, 2025 |
| **Notes** | Confirmed: UN43DU6900FXZA, UN55DU7200DXZA, UN55DU7200FXZA, UN55DU8000BXZA, UN55DU8000DXZA, UN55DU8000FXZA. Entry 4K Samsung. Warehouse club variants (DU6900 sold at Costco) may not SDDP-discover — always use retail model number. |
| **Bob Recommendation** | **APPROVE** — verify retail model number, not warehouse variant. |

---

### SONY

**Overview:** Sony BRAVIA XR and X-series TVs (2019+) support Control4 SDDP and native IP control. **Setup required on TV:** Settings > Network > IP Control > enable Simple IP Control, set Pre-Shared Key (PSK) to any value, toggle Control4/SDDP setting on. Some firmware updates have disabled the SDDP toggle menu — workaround is to manually enter TV IP address in Composer and configure the PSK in the driver settings. All current XR-series (BRAVIA 9, 8, 7, 5) have certified IP drivers in the Control4 database. Sony is retail-only, not through Snap One/Mountain West dealer channel.

---

#### Sony XR90 / BRAVIA 9 (2025 Mini LED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes (manual PSK setup required) |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 307 |
| **Driver Last Updated** | July 9, 2024 (US market); July 21, 2025 (additional region variants) |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed US: K-65XR90, K-75XR90, K-85XR90. Confirmed other markets: Y-65XR90, Y-75XR90, Y-85XR90. Sony's top Mini LED with cognitive processor XR. Requires PSK activation on TV. |
| **Bob Recommendation** | **APPROVE** — flagship Sony, full C4 integration. |

---

#### Sony XR80 / BRAVIA 8 (2025 OLED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes (manual PSK setup required) |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 307 |
| **Driver Last Updated** | July 9, 2024 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: K-65XR80, K-77XR80, K-77XR80C, K-65XR80CM2, Y-55XR80, Y-65XR80, Y-77XR80, Y-85XR80, K-55XR80CM2, K-55XR80M2, K-65XR81M2, K-55XR81M2. Sony OLED. Requires PSK. |
| **Bob Recommendation** | **APPROVE** |

---

#### Sony XR70 / BRAVIA 7 (2025 Mini LED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes (manual PSK setup required) |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 307 |
| **Driver Last Updated** | July 9, 2024 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: K-65XR70, K-75XR70, K-85XR70, Y-55XR70, Y-65XR70, Y-75XR70, Y-85XR70. Requires PSK. |
| **Bob Recommendation** | **APPROVE** |

---

#### Sony XR50 / BRAVIA 5 (2025 4K LED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes (manual PSK setup required) |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 307 |
| **Driver Last Updated** | July 21, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: K-55XR50, K-65XR50, K-75XR50, K-85XR50, K-98XR50, K-65XR50C, K-75XR50C, K-85XR50C, Y-55XR50, Y-65XR50, Y-75XR50, Y-85XR50, K-85XR51Z, K-75XR51Z. New entry BRAVIA tier added July 2025. Requires PSK. |
| **Bob Recommendation** | **APPROVE** |

---

#### Sony X90L / X85L (2023 4K LED)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2023 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes (manual PSK setup required) |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 304 |
| **Driver Last Updated** | June 30, 2023 |
| **Notes** | Confirmed: XR-65X90L, XR-75X90L, XR-65X91L, XR-75X91L, XR-65X93L, XR-65X95L. Still common in inventory. Requires PSK. |
| **Bob Recommendation** | **APPROVE** |

---

### LG

**Overview:** LG has supported Control4 SDDP since 2018. All current webOS LG TVs at 4K resolution (OLED, QNED, NanoCell) have native certified IP drivers. IP control must be enabled in the TV settings (Settings > General > IP Control). LG is a CI-channel-friendly brand with a dedicated dealer portal ([reachlg.com](https://reachlg.com)) and is sold through Snap One partner stores. Free C4 certified drivers. Some integrators also use a Chowmain third-party LG webOS driver for faster power-on response time after standby (native driver has ~60-second cooldown before it can power back on; Chowmain driver eliminates this).

---

#### LG G5 OLED evo (2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 212 |
| **Driver Last Updated** | July 15, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Snap One partner stores + retail |
| **Snap One / Mountain West** | **Yes** |
| **Notes** | Confirmed: OLED55G5PCA, OLED77G5PSA. Gallery OLED evo, wall-mount display. webOS 25. Native C4 IP driver free. Optional Chowmain LG driver for improved power-on responsiveness. |
| **Bob Recommendation** | **APPROVE** — premium OLED, dealer channel available. |

---

#### LG C5 OLED evo (2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 212 |
| **Driver Last Updated** | July 15, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Snap One partner stores + retail |
| **Snap One / Mountain West** | **Yes** |
| **Notes** | Confirmed: OLED55C5PSA, OLED77C5PSA. Most popular LG OLED for CI installations. webOS 25. Native C4 IP driver free. Hardwire Ethernet recommended for reliable IP control. |
| **Bob Recommendation** | **APPROVE** — top choice for LG OLED in C4 projects. |

---

#### LG B5 OLED (2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 212 |
| **Driver Last Updated** | July 15, 2025 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Snap One + retail |
| **Snap One / Mountain West** | **Yes** |
| **Notes** | Entry LG OLED. webOS 25. Native C4 IP driver free. |
| **Bob Recommendation** | **APPROVE** |

---

#### LG C4 / B4 OLED (2024)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 212 |
| **Driver Last Updated** | August 1, 2024 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Snap One + retail |
| **Snap One / Mountain West** | **Yes** |
| **Notes** | Confirmed C4: OLED48C4xLA/LB, OLED55C4xLA, OLED65C4xLA. Confirmed B4: OLED48B4xLA, OLED55B4ELA, OLED65B4xLA. Extensive variant coverage. webOS 24. |
| **Bob Recommendation** | **APPROVE** |

---

#### LG QNED (2024–2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024–2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 209 |
| **Driver Last Updated** | July 29, 2024 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Snap One + retail |
| **Snap One / Mountain West** | **Yes** |
| **Notes** | Confirmed: 65QNED996QB, 75QNED99VPA, 86QNED99VPA, 65QNED916QA. 2025 QNED93 Evo (Mini LED) and QNED86 launched May 2025. Per LG CI training, all 4K QNED models have IP control. Excellent option for bright room environments. |
| **Bob Recommendation** | **APPROVE** |

---

#### LG NanoCell (2024–2025)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2024–2025 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 209 |
| **Driver Last Updated** | July 29, 2024 |
| **Driver Source** | Free — C4 certified DB |
| **Dealer Channel** | Retail primarily |
| **Snap One / Mountain West** | No |
| **Notes** | Confirmed: 50NANO763QA, 50NANO766QA, 55NANO763QA, 55NANO766QA, 65NANO763QA, 65NANO766QA. LG replaced entry UHD tier with NanoCell in 2025 lineup. Entry LG 4K. |
| **Bob Recommendation** | **APPROVE** |

---

#### LG UQ Series (2022)
| Field | Value |
|-------|-------|
| **Integration Level** | 1 — Native SDDP (IP) |
| **Year** | 2022 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | Yes |
| **Driver Creator** | Control4 (certified) |
| **Driver Version** | 209 |
| **Driver Last Updated** | July 29, 2024 |
| **Notes** | Confirmed: 43UQ76906LE, 43UQ76909LE. Legacy tier, discontinued. Still in service in existing installs. |
| **Bob Recommendation** | **APPROVE (existing inventory/installs)** |

---

### TCL

**Overview:** TCL has no native Control4 SDDP partnership. Integration requires third-party DriverCentral drivers (Cindev). TCL is retail-only and not available through Snap One or Mountain West dealer channel. The universal TCL driver supports both IP and IR. A specific TCL Google TV IP driver also exists on DriverCentral. Known issue with all TCL IP drivers: the connection does not auto-reconnect after a power failure until the TV is manually powered on — TCL is aware and working on a fix.

---

#### TCL QM8K (2024 QLED Mini LED)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP or IR |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Cindev via DriverCentral |
| **Driver Product** | TCL TV — Universal Driver |
| **Driver URL** | https://drivercentral.io/platforms/control4-drivers/audio-video/tcl-tv/ |
| **Driver Last Updated** | December 2, 2025 |
| **Dealer Channel** | Retail only (Amazon, Best Buy, Costco) |
| **Snap One / Mountain West** | No |
| **Notes** | TCL flagship QLED Mini LED. Requires DriverCentral Cloud Driver in project. Known limitation: IP driver does not auto-reconnect after power failure until TV is manually turned on or powered via OEM remote — TCL has acknowledged this and is working on a firmware fix. |
| **Bob Recommendation** | **CONDITIONAL** — budget-friendly but 3rd-party dependency and reconnect caveat. Not recommended for primary display in demanding installs. |

---

#### TCL QM7 / QM6K (2024 Google TV)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP or IR |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Cindev via DriverCentral |
| **Driver Product** | TCL TV — Universal Driver or TCL Google TV Driver |
| **Driver URL** | https://drivercentral.io/platforms/control4-drivers/audio-video/tcl-tv/ |
| **Driver Last Updated** | December 2, 2025 |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Google TV OS models. Same power failure reconnect limitation as QM8K. |
| **Bob Recommendation** | **CONDITIONAL** — same caveats as QM8K. |

---

#### TCL Q7 / S4 / 4-Series (2024 Roku TV)
| Field | Value |
|-------|-------|
| **Integration Level** | 3 — IR Only (or basic Roku IP) |
| **Year** | 2024 |
| **Control Method** | IR preferred; generic Roku IP possible |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Control4 (generic Roku driver or IR) |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Roku TV OS models. No dedicated model-specific driver. Generic Roku TV driver provides limited IP control but feedback is inconsistent. IR + IR flasher hardware is more reliable but one-way only. No status feedback either way. |
| **Bob Recommendation** | **AVOID for new projects** — use IP-capable TCL model line or different brand entirely. |

---

### HISENSE

**Overview:** Hisense has two distinct OS platforms requiring different C4 approaches:
1. **VIDAA OS** (U-series, HL-series): Full IP integration available via Chowmain VIDAA driver (released July 25, 2025) plus Hisense-authored native drivers in the C4 certified DB (modified July 24, 2025). Two-way IP control with real-time feedback.
2. **Android TV / Google TV** (A-series): Not compatible with VIDAA driver. IR flasher required.

Hisense is retail-only and not sold through Snap One or Mountain West dealer channel.

---

#### Hisense U9N (2024 Mini LED ULED)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Chowmain (VIDAA driver) + Hisense native in C4 DB |
| **Driver Product** | Hisense VIDAA Smart TV Driver for Control4 |
| **Driver URL** | https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv |
| **Driver Version** | 20260311 |
| **Driver Last Updated** | July 25, 2025 (Chowmain) / July 24, 2025 (Hisense native) |
| **Dealer Channel** | Retail only (Best Buy, Amazon, Costco) |
| **Snap One / Mountain West** | No |
| **Notes** | Hisense:TV:98U9LUA and Hisense:TV:85U9LUA confirmed in C4 certified DB (Hisense creator). Chowmain VIDAA driver provides power, volume, input, transport, channel, app launch (Netflix, YouTube, Prime Video, Disney+), real-time feedback. 90-day trial on Chowmain driver. Driver released July 2025 — still relatively new, monitor for updates. VIDAA_TV_HL7NULTRA also in C4 DB (VIDAA creator, Feb 2025). |
| **Bob Recommendation** | **CONDITIONAL** — good integration capability, but newer driver ecosystem. |

---

#### Hisense U8N (2024 Mini LED ULED)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Chowmain (VIDAA driver) + Hisense native in C4 DB |
| **Driver Product** | Hisense VIDAA Smart TV Driver for Control4 |
| **Driver URL** | https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv |
| **Driver Last Updated** | July 25, 2025 |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Hisense:TV:85U86LUA confirmed in C4 certified DB. Full VIDAA IP control. Two-way feedback. 90-day trial. |
| **Bob Recommendation** | **CONDITIONAL** — solid budget option with workable C4 integration. |

---

#### Hisense U7N (2024 ULED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Chowmain (VIDAA driver) |
| **Driver Product** | Hisense VIDAA Smart TV Driver for Control4 |
| **Driver URL** | https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv |
| **Driver Last Updated** | July 25, 2025 |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Hisense:TV:85U75LUA in C4 certified DB. VIDAA OS. Chowmain driver covers VIDAA-powered models. Driver new (July 2025). |
| **Bob Recommendation** | **CONDITIONAL** |

---

#### Hisense U6N (2024 ULED 4K)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (two-way) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Chowmain (VIDAA driver) |
| **Driver Product** | Hisense VIDAA Smart TV Driver for Control4 |
| **Driver URL** | https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv |
| **Driver Last Updated** | July 25, 2025 |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Entry ULED. VIDAA OS. Covered by Chowmain VIDAA driver. Driver released July 2025. |
| **Bob Recommendation** | **CONDITIONAL** |

---

#### Hisense A-Series (2024 Android TV / Google TV)
| Field | Value |
|-------|-------|
| **Integration Level** | 3 — IR Only |
| **Year** | 2024 |
| **Control Method** | IR (one-way) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Control4 (IR) / Chowmain Android TV driver (limited) |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Hisense A-series runs Android TV or Google TV OS — NOT VIDAA. The Chowmain VIDAA driver does NOT work with A-series. Chowmain's separate Android TV driver may provide generic IP control but is not model-specific. IR flasher + wire run required for reliable control. No status feedback with IR. |
| **Bob Recommendation** | **AVOID for new projects** — use Hisense U-series (VIDAA) if Hisense brand is required. |

---

### VIZIO

**Overview:** Vizio has no native Control4 SDDP integration. The only current C4 driver is a third-party IP driver released **February 10, 2026** on DriverCentral by Solidified Systems (MSRP $125). This is an extremely new driver with no field track record. Vizio was acquired by Walmart in 2023 and continues retail-channel sales only. Not available through Snap One or Mountain West dealer channel.

---

#### Vizio M-Series (2024 QLED)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (local network) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Solidified Systems via DriverCentral |
| **Driver Product** | Vizio TV Driver |
| **Driver URL** | https://drivercentral.io/platforms/control4-drivers/audio-video/vizio-tv/ |
| **Driver Version** | 20260210 |
| **Driver Last Updated** | February 10, 2026 |
| **MSRP** | $125 |
| **Dealer Channel** | Retail only (Walmart, Best Buy) |
| **Snap One / Mountain West** | No |
| **Notes** | Supports Vizio OS (formerly SmartCast) models. Features: discrete power, volume, input switching, channel control, navigation, mini app launching (Netflix, Disney+, Apple TV+, Prime, YouTube, Hulu). Requires DriverCentral Cloud Driver. **Driver released February 2026 — zero field track record.** Not recommended for mission-critical primary displays. |
| **Bob Recommendation** | **CONDITIONAL (with strong caution)** — extremely new driver, no field track record. Prefer Samsung/LG/Sony for any serious install. |

---

#### Vizio V-Series (2024 4K LED)
| Field | Value |
|-------|-------|
| **Integration Level** | 2 — 3rd-Party IP Driver |
| **Year** | 2024 |
| **Control Method** | IP (local network) |
| **SDDP Auto-Discovery** | No |
| **Driver Creator** | Solidified Systems via DriverCentral |
| **Driver Product** | Vizio TV Driver |
| **Driver URL** | https://drivercentral.io/platforms/control4-drivers/audio-video/vizio-tv/ |
| **Driver Last Updated** | February 10, 2026 |
| **MSRP** | $125 |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | Entry tier Vizio. Same driver as M-Series. Very new (February 2026). Budget tier with limited CI install base. |
| **Bob Recommendation** | **AVOID** — driver too new, budget tier, no C4 track record. |

---

#### Vizio P-Series / P-Quantum (Legacy — 2022)
| Field | Value |
|-------|-------|
| **Integration Level** | 3 — IR Only (or new DriverCentral IP driver) |
| **Year** | 2022 |
| **Control Method** | IR or IP (new driver, untested on older models) |
| **Driver Creator** | Control4 (IR) / Solidified Systems (IP, new) |
| **Dealer Channel** | Retail only |
| **Snap One / Mountain West** | No |
| **Notes** | P-series discontinued in current lineup. Pre-SmartCast models use IR only. SmartCast-equipped P-series may work with DriverCentral driver but untested. |
| **Bob Recommendation** | **NOT RECOMMENDED** — discontinued line. |

---

## Bob's Decision Logic (AI Assistant Rules)

Use the following logic when evaluating a client TV selection:

```
IF integration_level == 1 (Native SDDP):
  → APPROVE. Note whether Sony PSK setup is required.
  → If Samsung: confirm retail purchase (not warehouse club variant).
  → If LG: recommend Snap One dealer channel purchase if available.

IF integration_level == 2 (3rd-Party IP Driver):
  → Flag for human review.
  → Note driver source, MSRP cost, and driver release date.
  → If driver released < 6 months ago: add "NEW DRIVER" caution.
  → Hisense VIDAA driver: approved for U-series, not A-series.
  → TCL: flag power-failure reconnect limitation.
  → Vizio: strong caution, driver released Feb 2026.
  → Add DriverCentral Cloud Driver requirement to project checklist.

IF integration_level == 3 (IR Only):
  → WARN client. One-way control only. IR flasher hardware + wire run required.
  → No feedback, no input detection.
  → Recommend upgrading to Level 1 or Level 2 brand/model.

IF integration_level == 4 (No Driver):
  → REJECT. Inform client TV is not compatible with C4.
```

---

## Driver Source URLs

| Source | URL |
|--------|-----|
| Control4 Driver Search Database | https://drivers.control4.com/solr/drivers/browse |
| Chowmain Hisense VIDAA Driver | https://chowmain.software/drivers/control4-hisense-vidaa-smart-tv |
| DriverCentral TCL TV Driver | https://drivercentral.io/platforms/control4-drivers/audio-video/tcl-tv/ |
| DriverCentral Vizio TV Driver | https://drivercentral.io/platforms/control4-drivers/audio-video/vizio-tv/ |
| CE Pro — Hisense VIDAA Driver Launch | https://www.cepro.com/news/hisense-launches-new-vidaa-control4-driver-with-help-from-chowmainsoft/620412/ |
| Residential Systems — Hisense Driver | https://www.residentialsystems.com/news/chowmainsoft-launches-control4-driver-for-hisense-tvs |
| LG CI Portal | https://reachlg.com |
| Samsung SDDP Partnership (2017) | https://ravepubs.com/samsung-integrates-control4-sddp-technology-2017-4k-ultra-hdtv-lineup-new-ultra-hd-blu-ray-player-2/ |

---

*Reference compiled April 1, 2026. Driver database entries verified against drivers.control4.com. Third-party driver information verified against Chowmain and DriverCentral marketplaces.*
