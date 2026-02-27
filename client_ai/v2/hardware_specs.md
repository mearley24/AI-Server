# Symphony Concierge — Hardware Specifications

*Internal reference | Symphony Smart Homes Engineering*

---

## Overview

The Symphony Concierge runs entirely on-premise at the client's home. Hardware selection
depends on budget, desired response quality, and the complexity of the client's system.
All tiers support the full Concierge feature set; the primary difference is response
speed and model capability.

---

## Hardware Tiers

### Budget Tier — Raspberry Pi 5 8GB

**Best for:** Vacation homes, starter clients, cost-sensitive projects under $20k install value

| Spec | Detail |
|---|---|
| **Board** | Raspberry Pi 5 (8GB RAM) |
| **Storage** | Samsung 870 EVO 500GB 2.5" SSD (via USB 3.0 adapter) |
| **Power** | Official Raspberry Pi 27W USB-C PSU |
| **Case** | Argon ONE V3 M.2 case (includes fan, HDMI, M.2 slot) |
| **OS** | Raspberry Pi OS 64-bit (Bookworm) — headless |
| **LLM Engine** | Ollama 0.5+ (ARM64 build) |
| **Model** | `llama3.2:3b` (Q4_K_M quantization, ~2.0GB) |
| **Inference** | ~8–12 tokens/sec (CPU only, 4 cores) |
| **Response latency** | 8–20 seconds for typical responses |
| **Power draw** | 5–15W idle/load |
| **Dimensions** | 97mm × 74mm × 32mm (in Argon ONE case: 100mm × 100mm × 32mm) |

**Cost breakdown:**
| Item | Approx. Cost |
|---|---|
| Raspberry Pi 5 8GB | $80 |
| Argon ONE V3 case | $45 |
| Samsung 870 EVO 500GB | $55 |
| USB-C PSU + cable | $15 |
| SD card (boot) + microSD | $12 |
| **Total BOM** | **~$207** |
| **Symphony retail** | **$499 installed** |
| **Margin** | ~59% on hardware |

**Limitations:**
- Noticeably slower response time (8–20s vs. 2–5s on Mac Mini)
- 3B model has less reasoning capability; may give simpler answers
- Not suitable for voice integration (Premium/Enterprise feature)
- Cannot run 8B+ models reliably with 8GB unified memory

**When to sell this tier:**
- Vacation/secondary home with simple systems
- Client is primarily budget-focused
- Install value under $20,000
- System has ≤4 rooms, minimal automation

---

### Standard Tier — Mac Mini M2 8GB

**Best for:** Most residential clients, standard installations, the "right choice" for typical Symphony projects

| Spec | Detail |
|---|---|
| **System** | Apple Mac Mini M2 (2023) |
| **RAM** | 8GB unified memory |
| **Storage** | 256GB SSD (internal) |
| **OS** | macOS Sonoma / Sequoia |
| **LLM Engine** | Ollama 0.5+ (Apple Silicon native, Metal-accelerated) |
| **Model** | `llama3.1:8b` (Q4_K_M, ~4.7GB) |
| **Inference** | ~25–45 tokens/sec (Apple Neural Engine + GPU) |
| **Response latency** | 2–5 seconds for typical responses |
| **Power draw** | 6–12W idle, up to 39W peak |
| **Dimensions** | 197mm × 197mm × 35mm |
| **Rack mount** | HIDEit Mounts Mac Mini wall/rack bracket available |

**Cost breakdown:**
| Item | Approx. Cost |
|---|---|
| Mac Mini M2 8GB/256GB | $599 MSRP |
| Symphony labor (6 hrs × $125) | $750 |
| **Total cost to Symphony** | **~$1,349** |
| **Symphony retail price** | **$2,250 (with 1st year sub included)** |
| **Margin** | ~40% all-in |

**Capabilities at this tier:**
- llama3.1:8b handles nuanced questions, multi-step troubleshooting, context retention
- Supports voice integration via Control4 (Premium subscription)
- Full RAG pipeline with ChromaDB (5–10ms retrieval latency)
- Comfortable with 8,192 token context window (detailed conversation memory)
- Handles concurrent Web UI + API requests without degradation
- 5+ year appliance lifespan with standard macOS updates

**Limitations:**
- 8GB limits to Q4 quantized models (no unquantized 8B; no 13B)
- Cannot run 70B models (requires 16GB+)
- Shared memory architecture: don't run other heavy apps on this appliance

**When to sell this tier:**
- Most residential installs above $15,000
- Active families who will use the system daily
- Clients who've had recurring support calls
- Any install with voice integration requirement

---

### Premium Tier — Mac Mini M4 16GB

**Best for:** Large installs, tech-savvy clients, Enterprise subscription, flagship smart homes

| Spec | Detail |
|---|---|
| **System** | Apple Mac Mini M4 (2024) |
| **RAM** | 16GB unified memory |
| **Storage** | 256GB or 512GB SSD |
| **OS** | macOS Sequoia 15.x |
| **LLM Engine** | Ollama 0.5+ (Apple Silicon native, Metal-accelerated) |
| **Model** | `llama3.1:70b` (Q4_K_M, ~40GB) *or* `llama3.1:8b` (if 70B too slow for preference) |
| **Inference (70B Q4)** | ~8–15 tokens/sec |
| **Inference (8B Q4)** | ~50–80 tokens/sec |
| **Response latency (70B)** | 5–12 seconds (high quality) |
| **Response latency (8B)** | 1–3 seconds (very fast) |
| **Power draw** | 8–18W idle, up to 65W peak (M4 Pro option) |
| **Dimensions** | 127mm × 127mm × 50mm (M4 standard) |
| **Rack mount** | NewerTech NuMount vertical, or HIDEit wall bracket |

**Cost breakdown (16GB/256GB):**
| Item | Approx. Cost |
|---|---|
| Mac Mini M4 16GB/256GB | $799 MSRP |
| Symphony labor (6 hrs × $125) | $750 |
| **Total cost to Symphony** | **~$1,549** |
| **Symphony retail price** | **$2,750 (with 1st year sub included)** |
| **Margin** | ~44% all-in |

**Cost breakdown (16GB/512GB — recommended for Enterprise):**
| Item | Approx. Cost |
|---|---|
| Mac Mini M4 16GB/512GB | $999 MSRP |
| Symphony labor | $750 |
| **Total** | **~$1,749** |
| **Symphony retail** | **$3,000** |
| **Margin** | ~42% |

**Why the 70B model matters:**
The jump from 8B to 70B is significant:
- 70B understands multi-part questions more accurately
- Better at reasoning through complex troubleshooting sequences
- Handles ambiguous questions more gracefully
- Noticeably better "personality" — warmer, more natural responses
- Appropriate for clients who are power users of their smart home

**When to sell this tier:**
- Enterprise subscription clients
- Installs above $75,000
- Clients who are frequently technical (attorneys, engineers, tech executives)
- Large homes (6+ rooms, 50+ devices)
- When voice integration is a priority feature
- Any time the client will be a vocal advocate/referral source

---

## Model Comparison Table

| Model | Size | RAM Required | Tokens/sec (M4 16GB) | Quality | Best For |
|---|---|---|---|---|---|
| `llama3.2:3b` | ~2.0GB | 4GB+ | 80–120 | Good | Budget tier, simple Q&A |
| `llama3.1:8b` | ~4.7GB | 8GB+ | 50–80 | Very Good | Standard residential |
| `llama3.1:8b-instruct-q8_0` | ~8.5GB | 12GB+ | 35–55 | Excellent | Premium, quality-first |
| `llama3.1:70b-q4_K_M` | ~40GB | 48GB+ | 8–15 | Outstanding | Enterprise (Mac Mini M4 Pro) |
| `llama3.1:70b-q2_K` | ~26GB | 32GB+ | 12–20 | Excellent | Premium M4 16GB (fits in RAM) |

**Recommended models by tier:**
- **Budget** (Pi 5 8GB): `llama3.2:3b`
- **Standard** (Mac Mini M2 8GB): `llama3.1:8b`
- **Premium** (Mac Mini M4 16GB): `llama3.1:8b` or `llama3.1:70b-q2_K`
- **Enterprise** (Mac Mini M4 Pro 24GB+): `llama3.1:70b-q4_K_M`

---

## Response Time Benchmarks

Tested with a typical smart home query: *"How do I activate Movie Time and what does it do?"*

| Hardware | Model | Time to First Token | Full Response (100 tokens) |
|---|---|---|---|
| Raspberry Pi 5 8GB | llama3.2:3b | 3–6s | 12–25s |
| Mac Mini M2 8GB | llama3.1:8b | 1–2s | 4–8s |
| Mac Mini M4 8GB | llama3.1:8b | 0.5–1s | 2–4s |
| Mac Mini M4 16GB | llama3.1:8b | 0.4–0.8s | 1.5–3s |
| Mac Mini M4 16GB | llama3.1:70b-q2_K | 2–4s | 8–15s |
| Mac Mini M4 Pro 24GB | llama3.1:70b-q4_K_M | 1–2s | 6–12s |

*Benchmarks measured with Ollama 0.5.x on Apple Silicon with Metal acceleration enabled.
Real-world times may vary based on context length and system load.*

---

## Network Requirements

### Minimum Network Requirements

| Requirement | Spec |
|---|---|
| Connection type | Gigabit Ethernet (strongly preferred) |
| WiFi | 802.11ac (WiFi 5) minimum; 802.11ax (WiFi 6) preferred |
| LAN bandwidth (client → appliance) | 1 Mbps sufficient (local inference, small JSON payloads) |
| Internet dependency | **None** — all inference is local |
| VLAN placement | Management VLAN (same as Control4, Lutron, etc.) |
| Static IP / DHCP reservation | Required — reserve a static IP for the appliance |
| mDNS (Bonjour) | Recommended — enables `http://symphony-concierge.local` discovery |

### Recommended Network Placement

Place the Concierge appliance on the **Management VLAN** alongside Control4 and other
AV/smart home devices. This ensures:
- Clients on the Client VLAN (phones/tablets) can still reach the UI via the router
- Smart home devices don't compete with client device WiFi traffic
- Appliance is not accessible to guest network (Guest VLAN is isolated)

**IP reservation example (Araknis router):**
```
symphony-concierge  |  MAC: XX:XX:XX:XX:XX:XX  |  IP: 192.168.10.200
```

### mDNS Setup

On macOS, the appliance auto-advertises via Bonjour. Clients can reach it at:
- `http://symphony-concierge.local` (on the same VLAN)
- `http://192.168.10.200` (direct IP)

For cross-VLAN access (client devices on Client VLAN accessing the Management VLAN
appliance), configure a firewall rule to allow TCP 80/8080 from Client VLAN to the
appliance's IP.

---

## Power & Rack Mounting

### Power

| Hardware | Idle | Peak | Annual kWh (est.) |
|---|---|---|---|
| Raspberry Pi 5 | 5W | 15W | 44–131 kWh |
| Mac Mini M2 | 6W | 39W | 53–342 kWh |
| Mac Mini M4 | 8W | 65W | 70–569 kWh |

*Annual cost at $0.15/kWh: $7–$85/year — negligible appliance cost.*

Power both Mac Mini and Pi via UPS (Uninterruptible Power Supply) to prevent corruption
on power loss. The client's AV rack UPS (typically included in Symphony installs) is
sufficient. Add the Concierge appliance to an existing UPS outlet.

### Rack Mounting

**Mac Mini in AV rack:**

| Mount | Price | Notes |
|---|---|---|
| HIDEit 4X Universal Mount | ~$30 | Wall or rack panel mount; holds 1–4 Mac Minis |
| Sonnet RackMac Mini | ~$160 | 1U rack-mount enclosure; clean professional look |
| Ernitec 19" universal shelf (1U) | ~$25 | Generic shelf; just sets it on the shelf |

**Recommended:** Sonnet RackMac Mini for high-end installs; HIDEit bracket for standard.

**Raspberry Pi in AV rack:**
- Argon ONE V3 case fits on a 1U shelf with Velcro
- DIN rail mount adapters available (~$15)
- Keep away from heat sources; Pi 5 gets warm under load

### Thermal Considerations

- Mac Mini M4 runs warm but rarely needs airflow assistance in a ventilated rack
- Raspberry Pi 5 **requires** the Argon ONE case fan or equivalent cooling
- Ensure at least 2–4 inches of clearance above/below appliance in rack
- Avoid mounting directly on top of high-heat equipment (amplifiers, processors)

---

## Appendix: Suggested Bill of Materials

### Standard Install BOM

```
Symphony Concierge — Standard Tier BOM
========================================
Mac Mini M4 16GB/256GB          $799
HIDEit 4X Mount                  $30
Cat6A patch cable (0.5m)          $8
Power strip surge protector      $15
Label (printed)                   $2
                                ------
Total hardware BOM              $854
Symphony labor (6 hrs)          $750
                                ------
Total cost to Symphony        $1,604
Client invoice                $2,750
                                ------
Gross margin                  $1,146  (42%)
```

### Budget Install BOM

```
Symphony Concierge — Budget Tier BOM
======================================
Raspberry Pi 5 8GB               $80
Argon ONE V3 case                $45
Samsung 870 EVO 500GB SSD        $55
USB 3.0 → SATA adapter           $12
Official RPi PSU 27W             $15
32GB microSD (boot)              $10
Cat6 patch cable                  $5
                                ------
Total hardware BOM              $222
Symphony labor (4 hrs)          $500
                                ------
Total cost to Symphony          $722
Client invoice                  $999 + $49/mo Basic
                                ------
Gross margin (hardware)         $277  (28%)
```

---

*Symphony Smart Homes — Hardware Specifications v2.0*
*Last updated: February 2026*
