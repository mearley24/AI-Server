# Symphony Smart Homes — System Design Graph Specification

**Version:** 1.0  
**Author:** AI-Server / Matt Earley  
**Company:** Symphony Smart Homes — Vail/Eagle County, Colorado  
**Website:** symphonysh.com  
**Purpose:** Compatibility intelligence layer powering faster quoting, BOM generation, field-failure prevention, and tech training.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Component Database Schema](#2-component-database-schema)
3. [Validation Rules Engine](#3-validation-rules-engine)
4. [Room Template System](#4-room-template-system)
5. [BOM Generator Logic](#5-bom-generator-logic)
6. [Seed Data — 30+ Components](#6-seed-data)
7. [Integration Points](#7-integration-points)
8. [Implementation Roadmap](#8-implementation-roadmap)

---

## 1. Architecture Overview

The System Design Graph is a directed graph where **nodes are components** and **edges are relationships** (compatibility, dependency, upgrade path). The graph is stored as JSON documents queryable by the AI server and exposed via a REST API.

```
┌────────────────────────────────────────────────────────────┐
│                    AI-Server (Node.js / Python)            │
│                                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
│  │ Component DB │   │  Rules Engine│   │ Room Templates│  │
│  │  (JSON/PG)   │   │  (JSON Rules)│   │  (JSON)       │  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬────────┘  │
│         │                  │                   │           │
│  ┌──────▼───────────────────▼───────────────────▼────────┐ │
│  │              Design Graph Query Engine                 │ │
│  │   - Compatibility checks (hard/soft rules)             │ │
│  │   - Dependency resolution                              │ │
│  │   - BOM generation                                     │ │
│  │   - Power/network calculations                         │ │
│  └──────────────────────────────┬─────────────────────────┘ │
│                                 │                           │
│  ┌──────────────────────────────▼─────────────────────────┐ │
│  │                   REST API Layer                        │ │
│  │  POST /api/graph/check-compatibility                   │ │
│  │  POST /api/graph/generate-bom                          │ │
│  │  GET  /api/graph/room-template/:type/:tier             │ │
│  │  GET  /api/graph/component/:id                         │ │
│  │  POST /api/graph/upgrade-path                          │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
         │                │                │
   Mission Control   Voice Agent    Client Concierge
   Dashboard         (Receptionist)  (Local LLM)
```

### Data Storage Options

| Option | Best For | Notes |
|--------|----------|-------|
| PostgreSQL + JSONB | Production, complex queries | Full-text search, relational JOINs possible |
| MongoDB | Rapid iteration | Schema-flexible, easy to add fields |
| JSON flat files | Dev / edge LLM | Can be embedded in system prompt context |
| SQLite | Offline / field laptop | Single-file, no server required |

**Recommendation:** JSON flat files for the AI context layer; PostgreSQL for the web dashboard and proposal system.

---

## 2. Component Database Schema

### 2.1 TypeScript Interface (Canonical Definition)

```typescript
// types/component.ts

export type Category =
  | "processor"       // Control4 EA-5, CORE 5
  | "display"         // TVs, projectors
  | "screen"          // Projection screens
  | "speaker"         // In-wall, in-ceiling, on-wall, freestanding
  | "amplifier"       // External amps
  | "receiver"        // AV receivers
  | "streaming"       // Sonos Port, Amp, streaming boxes
  | "soundbar"        // Sonos Arc, Beam
  | "lighting_control"  // Lutron keypads, processors
  | "shading"         // Motorized shades
  | "networking"      // Switches, WAPs, routers
  | "power"           // WattBox, UPS, power conditioners
  | "security"        // Cameras, NVRs, door stations
  | "climate"         // Thermostats, sensors
  | "intercom"        // Door stations, intercoms
  | "control_surface" // Touchscreens, remotes, keypads
  | "cable_infrastructure"; // HDMI cables, HDBaseT, etc.

export type Tier = "standard" | "premium" | "ultra";

export type RoomType =
  | "theater"
  | "living"
  | "bedroom"
  | "outdoor"
  | "office"
  | "gym"
  | "wine_cellar"
  | "garage"
  | "pool"
  | "dining"
  | "kitchen";

export type ConnectivityType =
  | "HDMI_1.4"
  | "HDMI_2.0"
  | "HDMI_2.1"
  | "HDBaseT"
  | "HDBaseT_2.0"
  | "PoE"
  | "PoE_plus"
  | "WiFi_5"
  | "WiFi_6"
  | "WiFi_6E"
  | "Bluetooth_5"
  | "Zigbee"
  | "Z-Wave"
  | "RS-232"
  | "IR"
  | "IP"
  | "LAN_RJ45"
  | "USB_A"
  | "USB_C"
  | "Analog_RCA"
  | "Analog_XLR"
  | "Dante"
  | "4K_UHD"
  | "eARC"
  | "ARC"
  | "ClearConnect_RF"
  | "Control4_Zigbee"
  | "SPDIF"
  | "Optical_TOSLINK";

export interface Component {
  // ─── Identity ────────────────────────────────────────────
  component_id: string;          // Slug: "control4-ea-5"
  brand: string;                 // "Control4"
  model: string;                 // "EA-5"
  model_number: string;          // "C4-EA5" (manufacturer SKU)
  category: Category;
  subcategory?: string;          // "home_automation_controller"
  description: string;           // Short human-readable description

  // ─── Pricing ─────────────────────────────────────────────
  msrp: number;                  // USD, published list price
  dealer_cost_estimate: number;  // Estimated at 40-50% off MSRP
  labor_hours: number;           // Typical install hours (not programming)
  programming_hours?: number;    // Control4/Lutron programming time

  // ─── Physical ─────────────────────────────────────────────
  rack_units?: number;           // 1U, 2U, etc. (null = not rack mountable)
  power_draw_watts: number;      // Max draw (for circuit planning)
  power_draw_idle_watts?: number;
  weight_lbs?: number;
  dimensions?: {
    width_in: number;
    height_in: number;
    depth_in: number;
  };

  // ─── Connectivity ─────────────────────────────────────────
  connectivity: ConnectivityType[];  // All ports/protocols supported

  // ─── Graph Relationships ──────────────────────────────────
  requires: string[];            // component_ids that MUST be present
  requires_license?: string[];   // Non-hardware dependencies (dealer certs, etc.)
  recommended_with: string[];    // component_ids for common pairings
  incompatible_with?: string[];  // component_ids that conflict
  replaces?: string[];           // component_ids this upgrades from
  replaced_by?: string[];        // component_ids that succeed this

  // ─── Suitability ──────────────────────────────────────────
  room_types: RoomType[];
  tier: Tier;
  indoor_outdoor: "indoor" | "outdoor" | "both";
  max_screen_size_inches?: number;  // For projectors
  min_throw_distance_ft?: number;
  max_throw_distance_ft?: number;
  channel_count?: number;           // For amps/receivers
  zone_count?: number;              // For multi-zone devices

  // ─── Metadata ─────────────────────────────────────────────
  discontinued: boolean;
  notes?: string;                // Installer tips, gotchas
  data_sources?: string[];       // URLs for spec verification
  updated_at: string;            // ISO 8601
}
```

### 2.2 JSON Database Document Format

```json
{
  "schema_version": "1.0",
  "last_updated": "2025-01-01",
  "components": [
    {
      "component_id": "control4-ea-5",
      "brand": "Control4",
      "model": "EA-5",
      "model_number": "C4-EA5",
      "category": "processor",
      "subcategory": "home_automation_controller",
      "description": "Flagship home automation controller with 5 audio zones, gigabit switch, and eSATA expansion",
      "msrp": 2000,
      "dealer_cost_estimate": 1000,
      "labor_hours": 2.0,
      "programming_hours": 8.0,
      "rack_units": 1,
      "power_draw_watts": 40,
      "power_draw_idle_watts": 15,
      "weight_lbs": 5.5,
      "connectivity": ["IP", "LAN_RJ45", "RS-232", "IR", "Zigbee", "Control4_Zigbee"],
      "requires": [],
      "requires_license": ["control4-dealer-certification"],
      "recommended_with": ["control4-t4-touchscreen-10", "araknis-310-16-poe", "wattbox-800-12"],
      "incompatible_with": [],
      "replaces": ["control4-hc-800"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office", "gym", "wine_cellar", "garage", "pool"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "zone_count": 5,
      "discontinued": false,
      "notes": "Use EA-5 for projects with 5+ audio zones or complex multi-room setups. EA-3 suffices for 3-zone projects. Requires Control4 dealer license (Snap One account) to program.",
      "updated_at": "2025-01-01"
    }
  ]
}
```

### 2.3 Relationship Graph Edge Schema

```typescript
// types/relationship.ts

export type RelationshipType =
  | "requires"          // Hard dependency — cannot function without
  | "recommended_with"  // Strong pairing suggestion
  | "compatible_with"   // Works together (explicit confirmation)
  | "incompatible_with" // Will not work / causes problems
  | "replaces"          // Upgrade path from → to
  | "same_ecosystem";   // Same brand ecosystem, easy integration

export interface ComponentRelationship {
  source_id: string;
  target_id: string;
  relationship: RelationshipType;
  notes?: string;
  rule_ids?: string[];   // References to validation rules
}
```

---

## 3. Validation Rules Engine

Rules are stored as JSON and evaluated by the rules engine at design-time (BOM generation) and query-time (compatibility checks).

### 3.1 Rule Schema

```typescript
// types/rule.ts

export type RuleSeverity = "hard" | "soft" | "info";
export type RuleCategory =
  | "compatibility"
  | "power"
  | "network"
  | "licensing"
  | "distance"
  | "signal_bandwidth"
  | "ecosystem";

export interface ValidationRule {
  rule_id: string;
  name: string;
  severity: RuleSeverity;     // hard = blocks, soft = warns, info = notes
  category: RuleCategory;
  description: string;         // Plain English for UI display
  condition: RuleCondition;    // Evaluated programmatically
  message: string;             // Message shown when rule fires
  resolution: string;          // How to fix the issue
  applies_to?: string[];       // component_ids or category filters
}

export interface RuleCondition {
  type: "connectivity_requires" | "component_conflict" | "threshold" | "ecosystem_mismatch" | "distance" | "license";
  params: Record<string, unknown>;
}
```

### 3.2 Hard Rules (Will Break the System)

```json
{
  "rules": [
    {
      "rule_id": "hard-001",
      "name": "4K120 HDMI 2.1 Requirement",
      "severity": "hard",
      "category": "signal_bandwidth",
      "description": "4K @ 120Hz (48Gbps) requires HDMI 2.1 on both source and display. HDMI 2.0 maxes at 18Gbps (4K@60Hz only).",
      "condition": {
        "type": "connectivity_requires",
        "params": {
          "if_source_has": ["4K_UHD", "HDMI_2.1"],
          "then_display_must_have": ["HDMI_2.1"]
        }
      },
      "message": "Display lacks HDMI 2.1 — 4K@120Hz from this source is not possible.",
      "resolution": "Upgrade display to one with HDMI 2.1 input (e.g. Sony XR-85X93L, Sony XR-77A95L) OR limit source to 4K@60Hz."
    },
    {
      "rule_id": "hard-002",
      "name": "Control4 Dealer Certification Required",
      "severity": "hard",
      "category": "licensing",
      "description": "All Control4 products require a certified Control4 dealer (Snap One account) to purchase and program.",
      "condition": {
        "type": "license",
        "params": {
          "brand": "Control4",
          "required_license": "control4-dealer-certification"
        }
      },
      "message": "Control4 components cannot be purchased or programmed without an active Snap One dealer account.",
      "resolution": "Verify dealer account is active at snapav.com before quoting."
    },
    {
      "rule_id": "hard-003",
      "name": "Lutron HomeWorks QSX Dealer Certification",
      "severity": "hard",
      "category": "licensing",
      "description": "Lutron HomeWorks QSX requires Lutron dealer certification and cannot be programmed by uncertified installers.",
      "condition": {
        "type": "license",
        "params": {
          "product_line": "HomeWorks QSX",
          "required_license": "lutron-hwqs-certification"
        }
      },
      "message": "HomeWorks QSX requires Lutron Advanced System Design certification.",
      "resolution": "Use RadioRA 3 for projects where HW QSX certification is unavailable. Or schedule Lutron training."
    },
    {
      "rule_id": "hard-004",
      "name": "Epson LS12000 HDMI 2.1 for 4K120",
      "severity": "hard",
      "category": "signal_bandwidth",
      "description": "Epson LS12000 has HDMI 2.1 but uses pixel-shifting (not native 4K). True 4K@120Hz with full bandwidth requires verification of source compatibility.",
      "condition": {
        "type": "connectivity_requires",
        "params": {
          "component_id": "epson-ls12000",
          "if_feature": "4K_120Hz_gaming",
          "requires_source": "HDMI_2.1"
        }
      },
      "message": "LS12000 supports HDMI 2.1 input and 120Hz, but uses 3LCD pixel-shift — verify source frame rate with client.",
      "resolution": "Confirm client use case. For native 4K gaming, recommend Sony VPL-XW5000ES or VPL-XW7000ES."
    },
    {
      "rule_id": "hard-005",
      "name": "Sonos Arc eARC Requirement",
      "severity": "hard",
      "category": "compatibility",
      "description": "Sonos Arc requires HDMI eARC for Dolby Atmos passthrough. ARC supports Atmos metadata only for compatible formats.",
      "condition": {
        "type": "connectivity_requires",
        "params": {
          "component_id": "sonos-arc",
          "if_feature": "dolby_atmos",
          "tv_must_have": "eARC"
        }
      },
      "message": "Arc connected to ARC-only port will not pass Dolby Atmos TrueHD. Use eARC port on TV.",
      "resolution": "Connect Arc to the HDMI eARC port on the TV. All Sony XR-series TVs from 2021+ have eARC."
    },
    {
      "rule_id": "hard-006",
      "name": "JBL Synthesis Dante Networking Requirement",
      "severity": "hard",
      "category": "compatibility",
      "description": "JBL Synthesis SDA-7120 amplifier communicates with SDR-35 AVR via Dante audio networking — requires dedicated network infrastructure.",
      "condition": {
        "type": "ecosystem_mismatch",
        "params": {
          "if_includes": ["jbl-sda-7120"],
          "then_must_include": ["jbl-sdr-35"],
          "requires_network": "Dante_capable_switch"
        }
      },
      "message": "SDA-7120 Dante link to SDR-35 requires a switch that supports multicast (IGMP snooping). Standard unmanaged switches may cause audio dropout.",
      "resolution": "Use Araknis 310-series managed switch with IGMP snooping enabled on the Dante VLAN."
    },
    {
      "rule_id": "hard-007",
      "name": "Screen Innovations Black Diamond Ambient Light Requirement",
      "severity": "hard",
      "category": "compatibility",
      "description": "Black Diamond ALR screens require the projector to be placed directly in front of the screen (within the viewing cone). Off-axis projection destroys contrast.",
      "condition": {
        "type": "distance",
        "params": {
          "component_id": "si-black-diamond",
          "projector_placement": "on_axis_only",
          "max_offset_degrees": 15
        }
      },
      "message": "Black Diamond screens reject off-axis light — projector must be ceiling-mounted on-axis, NOT from a side or rear position.",
      "resolution": "Verify ceiling mount location is within 15° horizontal of screen center before specifying Black Diamond."
    },
    {
      "rule_id": "hard-008",
      "name": "HDMI Cable Distance Without Extender",
      "severity": "hard",
      "category": "distance",
      "description": "Passive HDMI cables degrade signal beyond 15 feet at 4K. Active cables extend to ~25 feet. Beyond that requires HDBaseT or fiber.",
      "condition": {
        "type": "distance",
        "params": {
          "signal_type": "HDMI",
          "passive_max_ft": 15,
          "active_max_ft": 25,
          "hd_base_t_max_ft": 330
        }
      },
      "message": "HDMI run exceeds 15ft — passive cable will fail at 4K. Add active HDMI cable or HDBaseT extender.",
      "resolution": "Under 25ft: use Monoprice or Blustream active HDMI. 25–330ft: use HDBaseT over Cat6 (e.g. Atlona AT-HDR-EX-70). Over 330ft: use fiber HDMI extender."
    },
    {
      "rule_id": "hard-009",
      "name": "HDBaseT Maximum Distance",
      "severity": "hard",
      "category": "distance",
      "description": "HDBaseT over Cat6 has a maximum run of 330 feet (100m). Beyond this, signal degradation causes video artifacts or loss.",
      "condition": {
        "type": "distance",
        "params": {
          "signal_type": "HDBaseT",
          "max_ft": 330,
          "cable_type": "Cat6_or_better"
        }
      },
      "message": "HDBaseT run exceeds 330ft maximum. Signal will not pass reliably.",
      "resolution": "Use fiber-optic HDMI extender for runs over 330ft. Alternatively, place source equipment closer to display."
    },
    {
      "rule_id": "hard-010",
      "name": "PoE Budget Oversubscription",
      "severity": "hard",
      "category": "power",
      "description": "Total simultaneous PoE device draw cannot exceed switch PoE power budget.",
      "condition": {
        "type": "threshold",
        "params": {
          "metric": "poe_total_draw_watts",
          "must_be_less_than": "switch_poe_budget_watts"
        }
      },
      "message": "Total PoE device draw exceeds switch power budget. Devices will not power on or will power cycle.",
      "resolution": "Upgrade to higher-budget switch (AN-310-SW-F-24-POE: 375W budget) or reduce PoE device count on this switch."
    }
  ]
}
```

### 3.3 Soft Rules (Suboptimal / Warns)

```json
{
  "soft_rules": [
    {
      "rule_id": "soft-001",
      "name": "Lutron Caseta Mixed with RadioRA 3",
      "severity": "soft",
      "category": "ecosystem",
      "description": "Caseta (ClearConnect Type A) works in a RadioRA 3 system but limits load count and lacks full seeTouch keypad features.",
      "condition": {
        "type": "ecosystem_mismatch",
        "params": {
          "components_present": ["lutron-caseta-pro", "lutron-radiora3-processor"]
        }
      },
      "message": "Caseta devices in a RadioRA 3 system count toward the legacy Type A limit (95 devices) and cannot use RadioRA 3's advanced features.",
      "resolution": "Replace Caseta dimmers with Sunnata RF Pro dimmers for full RA3 feature set. Use Caseta only for accessory locations."
    },
    {
      "rule_id": "soft-002",
      "name": "Sonos as Primary Theater Audio",
      "severity": "soft",
      "category": "compatibility",
      "description": "Sonos Arc is excellent for casual home theater but cannot be integrated into a full discrete surround processor chain. Max channels are 7.1.4 with Arc + 2x Era 300 + Sub.",
      "condition": {
        "type": "ecosystem_mismatch",
        "params": {
          "components_present": ["sonos-arc"],
          "room_type": "theater",
          "tier": "ultra"
        }
      },
      "message": "Sonos Arc is not recommended as primary audio for an ultra-tier dedicated home theater. It lacks discrete channel processing required for JBL Synthesis or Triad speaker systems.",
      "resolution": "For ultra-tier theater: use JBL Synthesis SDR-35 + SDA-7120 + SCL series speakers. Sonos is excellent in living rooms and secondary rooms."
    },
    {
      "rule_id": "soft-003",
      "name": "Sony VPL-XW5000ES with 4K@120Hz Gaming",
      "severity": "soft",
      "category": "signal_bandwidth",
      "description": "Sony XW5000ES has HDMI 2.0b inputs (18Gbps) — it does NOT support 4K@120Hz or HDMI 2.1 features (VRR, ALLM).",
      "condition": {
        "type": "connectivity_requires",
        "params": {
          "component_id": "sony-vpl-xw5000es",
          "if_source_feature": "HDMI_2.1",
          "alert": "source_feature_unsupported"
        }
      },
      "message": "XW5000ES has HDMI 2.0b — PS5/Xbox Series X 4K@120Hz will not pass. Client gaming use case must be confirmed before spec.",
      "resolution": "For gaming + projection: upgrade to Epson LS12000 (HDMI 2.1) or Sony VPL-XW7000ES. Or place a 4K@120Hz-capable TV at gaming location and use projector for movies only."
    },
    {
      "rule_id": "soft-004",
      "name": "Control4 EA-1 Zone Limitation",
      "severity": "soft",
      "category": "compatibility",
      "description": "EA-1 supports one audio zone and limited I/O. Overkill for single-room, underpowered for multi-room.",
      "condition": {
        "type": "threshold",
        "params": {
          "component_id": "control4-ea-1",
          "if_room_count_greater_than": 2,
          "alert": "consider_upgrade"
        }
      },
      "message": "EA-1 is limited to 1 audio zone. Projects with 2+ zones should use EA-3 or EA-5.",
      "resolution": "Upgrade to EA-3 (3 zones, $1,000 MSRP) or EA-5 (5 zones, $2,000 MSRP)."
    },
    {
      "rule_id": "soft-005",
      "name": "Outdoor Speaker Weather Rating",
      "severity": "soft",
      "category": "compatibility",
      "description": "Standard indoor speakers installed outdoors will fail prematurely. Outdoor locations require IP54+ rated speakers.",
      "condition": {
        "type": "ecosystem_mismatch",
        "params": {
          "room_type": "outdoor",
          "if_speaker_indoor_outdoor": "indoor"
        }
      },
      "message": "Indoor speaker specified for outdoor location. Will fail in Vail's freeze-thaw climate.",
      "resolution": "Specify outdoor-rated speakers: Episode ES-OD-HP-6, Sonance, or Polk Audio Atrium series rated for outdoor use."
    },
    {
      "rule_id": "soft-006",
      "name": "Projector Screen Gain vs Throw",
      "severity": "soft",
      "category": "compatibility",
      "description": "High-gain screens (>1.5 gain) narrow the viewing cone. Use lower gain for wide seating arrangements.",
      "condition": {
        "type": "threshold",
        "params": {
          "if_screen_gain_greater_than": 1.5,
          "if_seating_width_degrees_greater_than": 45,
          "alert": "hot_spotting_risk"
        }
      },
      "message": "High-gain screen with wide seating layout will cause hot-spotting and color shift for off-axis viewers.",
      "resolution": "Use lower-gain screen material (0.8–1.0 gain) for wide seating. Black Diamond 0.8 or SI White Advance 1.1."
    },
    {
      "rule_id": "soft-007",
      "name": "Network IoT VLAN Segmentation",
      "severity": "soft",
      "category": "network",
      "description": "Smart home devices on the same VLAN as personal computers creates security risk and can cause network congestion.",
      "condition": {
        "type": "threshold",
        "params": {
          "if_iot_device_count_greater_than": 5,
          "if_vlan_segmentation": false
        }
      },
      "message": "IoT devices and client computers share the same VLAN. Recommend VLAN segmentation for security and performance.",
      "resolution": "Configure VLANs: VLAN 10 = Management, VLAN 20 = IoT/AV, VLAN 30 = Client Data, VLAN 40 = Guest. Use Araknis 310 managed switch."
    }
  ]
}
```

### 3.4 Power Rules

```json
{
  "power_rules": [
    {
      "rule_id": "pwr-001",
      "name": "Rack Circuit Capacity",
      "severity": "hard",
      "category": "power",
      "description": "Total rack power draw must not exceed 80% of circuit breaker capacity (NEC derating for continuous loads).",
      "formula": "total_rack_watts / (circuit_breaker_amps × 120V) ≤ 0.80",
      "example": "A 20A circuit (2,400W) should not carry more than 1,920W of continuous load.",
      "resolution": "Add a second 20A circuit or specify larger circuit. WattBox IP PDU allows remote monitoring of actual draw."
    },
    {
      "rule_id": "pwr-002",
      "name": "UPS Runtime Calculation",
      "severity": "soft",
      "category": "power",
      "description": "UPS should provide minimum 15-minute runtime for graceful system shutdown during power outage.",
      "formula": "required_va = (sum_of_device_watts × 1.4) / power_factor",
      "notes": "Typical smart home rack: Control4 EA-5 (40W) + switches (30W) + WattBox (15W) + misc = ~150W. APC BE600M1 (600VA/330W) provides ~20 min runtime at 150W load.",
      "resolution": "Specify CyberPower CP1500PFCLCD (1500VA/1000W) for larger racks."
    },
    {
      "rule_id": "pwr-003",
      "name": "Projector Dedicated Circuit",
      "severity": "soft",
      "category": "power",
      "description": "High-power projectors (Sony XW7000ES: 420W, Epson LS12000: 491W) should be on a dedicated circuit to avoid dimming/noise when other loads switch.",
      "applies_to": ["sony-vpl-xw7000es", "epson-ls12000", "sony-vpl-xw5000es"],
      "resolution": "Run dedicated 20A circuit from panel to projection alcove."
    },
    {
      "rule_id": "pwr-004",
      "name": "JBL SDA-7120 High Power Draw",
      "severity": "info",
      "category": "power",
      "description": "JBL SDA-7120 amplifier has 1,500W maximum draw — must be on its own 20A circuit. Do not share with other rack equipment.",
      "applies_to": ["jbl-sda-7120"],
      "resolution": "Dedicated 20A circuit required. Consider JBL SDA-7120 on a separate rack circuit."
    }
  ]
}
```

### 3.5 Network Rules

```json
{
  "network_rules": [
    {
      "rule_id": "net-001",
      "name": "Minimum Switch for Control4 System",
      "severity": "soft",
      "category": "network",
      "description": "Control4 systems with 10+ IP devices benefit from managed switching with VLAN and QoS support.",
      "condition": {
        "type": "threshold",
        "params": {
          "if_control4_ip_devices_greater_than": 10,
          "requires_switch_type": "managed"
        }
      },
      "resolution": "Specify Araknis AN-310-SW-F-16-POE or AN-310-SW-F-24-POE for managed L2 switching with OvrC integration."
    },
    {
      "rule_id": "net-002",
      "name": "PoE Budget Planning",
      "severity": "hard",
      "category": "network",
      "table": {
        "device": "Typical PoE Draw",
        "Control4 T4 Touchscreen": "13W (802.3af)",
        "Control4 DS2 Door Station": "13W (802.3af)",
        "IP Camera (Luma 510)": "15W (802.3at)",
        "Wireless Access Point": "15-25W (802.3at)",
        "Lutron RadioRA3 Processor": "4W (802.3af)",
        "VoIP Phone": "5-10W (802.3af)"
      },
      "resolution": "AN-310-SW-F-16-POE provides 250W total PoE budget. AN-310-SW-F-24-POE provides 375W."
    },
    {
      "rule_id": "net-003",
      "name": "VLAN Architecture Standard",
      "severity": "soft",
      "category": "network",
      "description": "Standard VLAN architecture for Symphony Smart Homes installations.",
      "vlan_design": {
        "VLAN_10": { "name": "Management", "devices": "Switches, WattBox, OvrC cloud management" },
        "VLAN_20": { "name": "Control4_AV", "devices": "Control4 processors, touchscreens, IP-controlled AV gear" },
        "VLAN_30": { "name": "IoT_Lighting", "devices": "Lutron processors, Sonos, smart bulbs, climate devices" },
        "VLAN_40": { "name": "Security", "devices": "IP cameras, NVR, door stations — isolated for security" },
        "VLAN_50": { "name": "Client_Data", "devices": "Client computers, phones, tablets" },
        "VLAN_60": { "name": "Guest", "devices": "Guest Wi-Fi — internet only, no local access" }
      }
    }
  ]
}
```

### 3.6 Distance Rules Summary Table

| Signal Type | Cable | Max Distance | Notes |
|-------------|-------|-------------|-------|
| HDMI (passive) | HDMI | 15 ft | 4K60 degrades faster than 1080p |
| HDMI (active) | HDMI | 25 ft | Active redrivers extend range |
| HDMI (fiber) | Fiber HDMI | 300+ ft | No signal loss, one-way only |
| HDBaseT | Cat6 | 330 ft (100m) | Carries HDMI + power + control |
| HDBaseT 2.0 | Cat6A | 330 ft (100m) | Adds USB 2.0 |
| 4K HDBaseT | Cat6A | 230 ft (70m) | 4K requires shorter runs |
| 8-ohm speaker wire (18 AWG) | Copper | 50 ft | Beyond this, use 16 AWG |
| 8-ohm speaker wire (16 AWG) | Copper | 80 ft | Standard residential run |
| 8-ohm speaker wire (14 AWG) | Copper | 130 ft | Long runs to outdoor/garage |
| RS-232 | Cat5 | 50 ft | Standard control run |
| IR over Cat5 | Cat5 | 100 ft | Via IR balun |
| PoE (802.3af/at) | Cat5e/6 | 328 ft (100m) | Same as standard Ethernet |
| Dante audio | Cat5e/6 | 328 ft (100m) | Standard IP network |

---

## 4. Room Template System

Templates define the minimum component set for each room type and tier. They are the starting point for BOM generation — the rules engine then validates and resolves dependencies.

### 4.1 Template Schema

```typescript
// types/room-template.ts

export interface RoomTemplate {
  template_id: string;           // "home-theater-ultra"
  room_type: RoomType;
  tier: Tier;
  display_name: string;          // "Ultra Home Theater"
  description: string;
  typical_sqft_range: [number, number];
  components: TemplateComponent[];
  labor_hours_estimate: number;
  notes: string;
}

export interface TemplateComponent {
  component_id: string;
  quantity: number;
  role: string;                  // "primary_display", "surround_left", etc.
  optional: boolean;
  swap_options?: string[];       // Alternative component_ids at same tier
}
```

### 4.2 Home Theater Templates

#### Standard Home Theater (~$15,000–$30,000 installed)
```json
{
  "template_id": "home-theater-standard",
  "room_type": "theater",
  "tier": "standard",
  "display_name": "Standard Home Theater",
  "description": "5.1 surround sound, 4K projector or large TV, Control4 automation, Lutron lighting",
  "typical_sqft_range": [200, 350],
  "components": [
    { "component_id": "epson-ls12000", "quantity": 1, "role": "primary_display_projector", "optional": false, "swap_options": ["sony-vpl-xw5000es"] },
    { "component_id": "si-zero-edge-120", "quantity": 1, "role": "projection_screen", "optional": false, "swap_options": ["si-black-diamond-120"] },
    { "component_id": "jbl-scl-6", "quantity": 3, "role": "LCR_speakers", "optional": false, "swap_options": ["episode-es-ht-lc-6"] },
    { "component_id": "jbl-scl-8", "quantity": 2, "role": "surround_speakers", "optional": false },
    { "component_id": "jbl-ssi-8", "quantity": 1, "role": "subwoofer", "optional": false },
    { "component_id": "jbl-sdr-35", "quantity": 1, "role": "av_receiver", "optional": false },
    { "component_id": "control4-ea-3", "quantity": 1, "role": "automation_processor", "optional": false },
    { "component_id": "control4-t4-touchscreen-8", "quantity": 1, "role": "control_surface", "optional": false },
    { "component_id": "lutron-radiora3-processor", "quantity": 1, "role": "lighting_controller", "optional": false },
    { "component_id": "lutron-sunnata-rf-dimmer", "quantity": 4, "role": "lighting_dimmer", "optional": false },
    { "component_id": "araknis-310-16-poe", "quantity": 1, "role": "network_switch", "optional": false },
    { "component_id": "wattbox-800-12", "quantity": 1, "role": "power_management", "optional": false },
    { "component_id": "snap-one-rack-12u", "quantity": 1, "role": "equipment_rack", "optional": false }
  ],
  "labor_hours_estimate": 24,
  "notes": "Standard theater assumes dedicated room with acoustic treatment rough-in. Recommend adding at least $3,000 for acoustic panels and bass traps (not in this BOM). Control4 programming adds 8–12 hours."
}
```

#### Premium Home Theater (~$50,000–$90,000 installed)
```json
{
  "template_id": "home-theater-premium",
  "room_type": "theater",
  "tier": "premium",
  "display_name": "Premium Home Theater",
  "description": "7.2.4 Dolby Atmos, Sony 4K laser projector, Screen Innovations Black Diamond, JBL Synthesis full system",
  "typical_sqft_range": [300, 500],
  "components": [
    { "component_id": "sony-vpl-xw5000es", "quantity": 1, "role": "primary_display_projector", "optional": false, "swap_options": ["sony-vpl-xw7000es"] },
    { "component_id": "si-black-diamond-130", "quantity": 1, "role": "projection_screen", "optional": false },
    { "component_id": "jbl-scl-6", "quantity": 3, "role": "LCR_speakers", "optional": false },
    { "component_id": "jbl-scl-7", "quantity": 4, "role": "surround_speakers", "optional": false },
    { "component_id": "jbl-scl-8", "quantity": 4, "role": "atmos_height_speakers", "optional": false },
    { "component_id": "jbl-ssi-10", "quantity": 2, "role": "dual_subwoofers", "optional": false },
    { "component_id": "jbl-sdr-35", "quantity": 1, "role": "av_receiver_processor", "optional": false },
    { "component_id": "jbl-sda-7120", "quantity": 1, "role": "external_amplifier", "optional": false },
    { "component_id": "control4-ea-5", "quantity": 1, "role": "automation_processor", "optional": false },
    { "component_id": "control4-t4-touchscreen-10", "quantity": 1, "role": "control_surface", "optional": false },
    { "component_id": "control4-ds2-door-station", "quantity": 1, "role": "door_intercom", "optional": true },
    { "component_id": "lutron-radiora3-processor", "quantity": 1, "role": "lighting_controller", "optional": false },
    { "component_id": "lutron-sunnata-rf-dimmer", "quantity": 6, "role": "lighting_dimmers", "optional": false },
    { "component_id": "si-solo-shade", "quantity": 2, "role": "blackout_shades", "optional": false },
    { "component_id": "araknis-310-16-poe", "quantity": 1, "role": "network_switch", "optional": false },
    { "component_id": "wattbox-800-12", "quantity": 1, "role": "power_management", "optional": false },
    { "component_id": "snap-one-rack-16u", "quantity": 1, "role": "equipment_rack", "optional": false }
  ],
  "labor_hours_estimate": 40,
  "notes": "7.2.4 configuration. JBL SDR-35 decodes up to 15.1 channels but drives 7 channels internally; SDA-7120 handles remaining channels. Dedicated 20A circuits required for SDR-35 and SDA-7120. Dante networking between SDR-35 and SDA-7120 requires managed switch."
}
```

#### Ultra Home Theater (~$120,000–$250,000+ installed)
```json
{
  "template_id": "home-theater-ultra",
  "room_type": "theater",
  "tier": "ultra",
  "display_name": "Ultra Home Theater",
  "description": "9.4.6 Dolby Atmos, Sony VPL-XW7000ES, dual subs, Triad full system, Lutron HomeWorks QSX, dedicated acoustic room",
  "typical_sqft_range": [400, 800],
  "components": [
    { "component_id": "sony-vpl-xw7000es", "quantity": 1, "role": "primary_display_projector", "optional": false },
    { "component_id": "si-black-diamond-150", "quantity": 1, "role": "projection_screen", "optional": false, "swap_options": ["si-zero-edge-pro-150"] },
    { "component_id": "triad-inroom-gold-lcr", "quantity": 3, "role": "LCR_speakers", "optional": false },
    { "component_id": "triad-inwall-gold-surround", "quantity": 6, "role": "surround_speakers", "optional": false },
    { "component_id": "triad-inceiling-gold-atmos", "quantity": 6, "role": "atmos_height_speakers", "optional": false },
    { "component_id": "jbl-ssi-12", "quantity": 2, "role": "dual_subwoofers", "optional": false },
    { "component_id": "jbl-sdr-35", "quantity": 1, "role": "av_processor", "optional": false },
    { "component_id": "jbl-sda-7120", "quantity": 2, "role": "amplifiers", "optional": false, "notes": "Two amps for 9.4.6 channel count" },
    { "component_id": "control4-ea-5", "quantity": 1, "role": "automation_processor", "optional": false },
    { "component_id": "control4-t4-touchscreen-10", "quantity": 2, "role": "control_surfaces", "optional": false },
    { "component_id": "lutron-hwqs-processor", "quantity": 1, "role": "lighting_controller", "optional": false },
    { "component_id": "lutron-hwqs-keypad", "quantity": 6, "role": "lighting_keypads", "optional": false },
    { "component_id": "si-solo-shade", "quantity": 4, "role": "blackout_shades", "optional": false },
    { "component_id": "araknis-710-24-poe", "quantity": 1, "role": "network_switch", "optional": false },
    { "component_id": "wattbox-800-12", "quantity": 2, "role": "dual_power_management", "optional": false },
    { "component_id": "snap-one-rack-20u", "quantity": 1, "role": "equipment_rack", "optional": false },
    { "component_id": "luma-510-nvr", "quantity": 1, "role": "security_nvr", "optional": true },
    { "component_id": "luma-510-dome-camera", "quantity": 2, "role": "theater_security_cameras", "optional": true }
  ],
  "labor_hours_estimate": 72,
  "notes": "Ultra theater assumes licensed acoustic designer and custom room construction (not included in this BOM). Lutron HomeWorks QSX requires HWQS certification. Two JBL SDA-7120 amplifiers require two dedicated 20A circuits each. Araknis 710-series for advanced AV networking."
}
```

### 4.3 Living Room Templates

#### Standard Living Room (~$8,000–$15,000 installed)
```json
{
  "template_id": "living-room-standard",
  "room_type": "living",
  "tier": "standard",
  "display_name": "Standard Living Room",
  "description": "Large format TV, Sonos soundbar system, Lutron Caseta lighting, Control4 automation",
  "components": [
    { "component_id": "sony-xr-75x90l", "quantity": 1, "role": "primary_display_tv", "optional": false, "swap_options": ["sony-xr-85x93l"] },
    { "component_id": "sonos-arc", "quantity": 1, "role": "soundbar", "optional": false },
    { "component_id": "sonos-sub-gen3", "quantity": 1, "role": "subwoofer", "optional": true },
    { "component_id": "sonos-era-300", "quantity": 2, "role": "surround_speakers", "optional": true },
    { "component_id": "control4-ea-1", "quantity": 1, "role": "automation_processor", "optional": false },
    { "component_id": "lutron-caseta-bridge-pro", "quantity": 1, "role": "lighting_bridge", "optional": false },
    { "component_id": "lutron-caseta-dimmer", "quantity": 4, "role": "lighting_dimmers", "optional": false }
  ],
  "labor_hours_estimate": 8,
  "notes": "Simple integration. Sonos via IP to Control4. Lutron Caseta via IP. No rack required — neat closet mount with WattBox strip."
}
```

#### Premium Living Room (~$25,000–$45,000 installed)
```json
{
  "template_id": "living-room-premium",
  "room_type": "living",
  "tier": "premium",
  "display_name": "Premium Living Room",
  "description": "Sony XR OLED TV, architectural speakers, Sonos Amp, Lutron RadioRA 3, Control4 with shading",
  "components": [
    { "component_id": "sony-xr-77a95l", "quantity": 1, "role": "primary_display_tv", "optional": false },
    { "component_id": "jbl-scl-6", "quantity": 2, "role": "in-wall_main_speakers", "optional": false, "swap_options": ["episode-es-ht-lc-6"] },
    { "component_id": "jbl-scl-8", "quantity": 2, "role": "in-ceiling_surround", "optional": false },
    { "component_id": "sonos-amp", "quantity": 1, "role": "audio_amplifier", "optional": false },
    { "component_id": "sonos-port", "quantity": 1, "role": "streaming_source", "optional": true },
    { "component_id": "control4-ea-3", "quantity": 1, "role": "automation_processor", "optional": false },
    { "component_id": "control4-t4-touchscreen-8", "quantity": 1, "role": "control_surface", "optional": false },
    { "component_id": "lutron-radiora3-processor", "quantity": 1, "role": "lighting_controller", "optional": false },
    { "component_id": "lutron-sunnata-rf-dimmer", "quantity": 6, "role": "lighting_dimmers", "optional": false },
    { "component_id": "si-solo-shade", "quantity": 3, "role": "motorized_shades", "optional": false },
    { "component_id": "araknis-310-8-poe", "quantity": 1, "role": "network_switch", "optional": false },
    { "component_id": "wattbox-800-8", "quantity": 1, "role": "power_management", "optional": false }
  ],
  "labor_hours_estimate": 20,
  "notes": "Architectural speakers wired through walls — allow for rough-in coordination with builder. SI Solo shades are wireless battery-powered — ideal for retrofit."
}
```

### 4.4 Master Bedroom Template (Premium)
```json
{
  "template_id": "master-bedroom-premium",
  "room_type": "bedroom",
  "tier": "premium",
  "display_name": "Premium Master Bedroom",
  "description": "TV, Sonos audio, Lutron shading + lighting, climate integration, Control4",
  "components": [
    { "component_id": "sony-xr-65a95l", "quantity": 1, "role": "primary_display_tv", "optional": false },
    { "component_id": "sonos-era-300", "quantity": 2, "role": "stereo_pair", "optional": false },
    { "component_id": "control4-ea-1", "quantity": 1, "role": "automation_processor", "optional": false, "notes": "Or EA-3 if this is one of several rooms" },
    { "component_id": "lutron-radiora3-processor", "quantity": 1, "role": "lighting_controller", "optional": false, "notes": "Share with whole-home system" },
    { "component_id": "lutron-sunnata-rf-dimmer", "quantity": 3, "role": "lighting_dimmers", "optional": false },
    { "component_id": "si-solo-shade", "quantity": 3, "role": "blackout_shades", "optional": false },
    { "component_id": "ecobee-smartthermostat", "quantity": 1, "role": "thermostat", "optional": false }
  ],
  "labor_hours_estimate": 6,
  "notes": "SI Solo shades preferred for bedroom due to wireless/battery operation — no wiring to window motors. Sonos Era 300 stereo pair eliminates need for separate receiver."
}
```

### 4.5 Outdoor Entertainment Template (Premium)
```json
{
  "template_id": "outdoor-entertainment-premium",
  "room_type": "outdoor",
  "tier": "premium",
  "display_name": "Premium Outdoor Entertainment",
  "description": "Outdoor TV, weatherproof speakers, Lutron landscape lighting, Control4, outdoor heating control",
  "components": [
    { "component_id": "sunbrite-pro2-65", "quantity": 1, "role": "outdoor_tv", "optional": false, "notes": "Full-weatherproof 65\" 4K. Symphony dealer note: Vail altitude/cold requires rated outdoor display." },
    { "component_id": "episode-es-od-hp-6", "quantity": 4, "role": "outdoor_speakers", "optional": false, "notes": "High-performance outdoor rated" },
    { "component_id": "sonos-amp", "quantity": 1, "role": "audio_amplifier", "optional": false },
    { "component_id": "control4-ea-1", "quantity": 1, "role": "automation_processor", "optional": false, "notes": "Shared with main system or dedicated" },
    { "component_id": "lutron-caseta-dimmer", "quantity": 4, "role": "landscape_lighting_dimmers", "optional": false },
    { "component_id": "infratech-heater-c-series", "quantity": 2, "role": "patio_heaters", "optional": true, "notes": "Control via Control4 relay module" }
  ],
  "labor_hours_estimate": 12,
  "notes": "All outdoor wiring must be rated for outdoor/direct-burial. Vail environment: -30°F capable equipment required. Check altitude specs — standard UL listing may not cover 8,000+ ft elevations. Confirm with manufacturer for Eagle County altitude."
}
```

### 4.6 Home Office Template (Standard)
```json
{
  "template_id": "home-office-standard",
  "room_type": "office",
  "tier": "standard",
  "display_name": "Standard Home Office",
  "description": "Network, lighting, display, Sonos background audio, Control4 integration",
  "components": [
    { "component_id": "sony-xr-55x90l", "quantity": 1, "role": "display", "optional": false },
    { "component_id": "sonos-era-100", "quantity": 2, "role": "desktop_stereo", "optional": false },
    { "component_id": "lutron-caseta-dimmer", "quantity": 2, "role": "lighting_dimmers", "optional": false },
    { "component_id": "lutron-caseta-bridge-pro", "quantity": 1, "role": "lighting_bridge", "optional": false, "notes": "Shared with home system" },
    { "component_id": "araknis-wap-610", "quantity": 1, "role": "wireless_access_point", "optional": false }
  ],
  "labor_hours_estimate": 4,
  "notes": "Home office prioritizes network performance. Dedicated WAP recommended over relying on whole-home Wi-Fi. Sonos Era 100 stereo pair provides excellent background music and can double as conference call audio with Bluetooth pairing."
}
```

### 4.7 Wine Cellar Template (Standard)
```json
{
  "template_id": "wine-cellar-standard",
  "room_type": "wine_cellar",
  "tier": "standard",
  "display_name": "Standard Wine Cellar",
  "description": "Climate monitoring, background audio, lighting, Control4 alerts for temperature excursions",
  "components": [
    { "component_id": "sonos-era-100", "quantity": 1, "role": "background_audio", "optional": false, "notes": "Low humidity concern — verify install location is not direct condensation zone" },
    { "component_id": "lutron-caseta-dimmer", "quantity": 2, "role": "lighting_dimmers", "optional": false, "notes": "Low-wattage LED only — heat from incandescent/halogen unacceptable" },
    { "component_id": "ecobee-smartthermostat", "quantity": 1, "role": "climate_monitor", "optional": false, "notes": "Control4 integration via IP — alert when temperature > 58°F or < 50°F" },
    { "component_id": "luma-510-dome-camera", "quantity": 1, "role": "security_camera", "optional": true }
  ],
  "labor_hours_estimate": 3,
  "notes": "Wine cellar climate is critical. Control4 can send push alerts if temperature drifts out of safe range (50–58°F). Consider dedicated temperature/humidity sensor (Daikin, Sensata) in addition to thermostat."
}
```

---

## 5. BOM Generator Logic

### 5.1 Input Model

```typescript
// types/bom-request.ts

export interface BOMRequest {
  project_name: string;
  client_name: string;
  address: string;
  rooms: RoomBOMRequest[];
  global_overrides?: {
    automation_system?: "control4" | "lutron_homeworks" | "none";
    networking_vendor?: "araknis" | "ubiquiti" | "other";
    include_rack?: boolean;
    target_margin_pct?: number;    // Default 45%
  };
}

export interface RoomBOMRequest {
  room_name: string;
  room_type: RoomType;
  tier: Tier;
  custom_components?: string[];      // Add specific component_ids
  exclude_components?: string[];     // Remove from template
  quantity?: number;                 // For rooms that repeat (e.g. 3 bedrooms)
}
```

### 5.2 BOM Generator Pseudocode

```python
# bom_generator.py

def generate_bom(request: BOMRequest) -> BOMOutput:
    """
    Master BOM generation function.
    1. Pull room templates
    2. Deduplicate shared infrastructure
    3. Resolve dependencies
    4. Run validation rules
    5. Calculate totals
    6. Apply markup
    """
    
    # ── Step 1: Collect all room templates ────────────────────
    raw_components = {}  # component_id → {quantity, rooms[]}
    
    for room in request.rooms:
        template = get_template(room.room_type, room.tier)
        
        for tc in template.components:
            if tc.component_id in room.exclude_components:
                continue
            
            cid = tc.component_id
            qty = tc.quantity * (room.quantity or 1)
            
            if cid not in raw_components:
                raw_components[cid] = {"quantity": 0, "rooms": []}
            raw_components[cid]["quantity"] += qty
            raw_components[cid]["rooms"].append(room.room_name)
        
        # Add any custom components
        for cid in room.custom_components:
            if cid not in raw_components:
                raw_components[cid] = {"quantity": 0, "rooms": []}
            raw_components[cid]["quantity"] += 1
            raw_components[cid]["rooms"].append(room.room_name)
    
    # ── Step 2: Deduplicate shared infrastructure ─────────────
    # If EA-5 appears in multiple rooms, keep only ONE (whole-home processor)
    # Shared components: processors, switches, rack, WattBox, Lutron processor
    SHARED_COMPONENTS = [
        "control4-ea-1", "control4-ea-3", "control4-ea-5",
        "lutron-radiora3-processor", "lutron-hwqs-processor",
        "lutron-caseta-bridge-pro",
        "araknis-310-16-poe", "araknis-310-24-poe", "araknis-710-24-poe",
        "wattbox-800-12",
        "snap-one-rack-12u", "snap-one-rack-16u", "snap-one-rack-20u"
    ]
    
    for cid in SHARED_COMPONENTS:
        if cid in raw_components and raw_components[cid]["quantity"] > 1:
            raw_components[cid]["quantity"] = 1
    
    # ── Step 3: Resolve dependencies ─────────────────────────
    # Check requires[] for all components and add missing deps
    dependency_additions = []
    
    for cid, data in raw_components.items():
        component = get_component(cid)
        for required_id in component.requires:
            if required_id not in raw_components:
                dependency_additions.append({
                    "component_id": required_id,
                    "quantity": 1,
                    "added_by": f"dependency of {cid}"
                })
    
    for add in dependency_additions:
        raw_components[add["component_id"]] = {
            "quantity": add["quantity"],
            "rooms": ["infrastructure"],
            "auto_added": True,
            "reason": add["added_by"]
        }
    
    # ── Step 4: Run Validation Rules ──────────────────────────
    violations = []
    warnings = []
    
    component_list = list(raw_components.keys())
    
    for rule in get_all_rules():
        result = evaluate_rule(rule, component_list, raw_components)
        if result.fired:
            if rule.severity == "hard":
                violations.append(result)
            elif rule.severity == "soft":
                warnings.append(result)
    
    # ── Step 5: Calculate Power & Network Requirements ────────
    total_rack_watts = 0
    total_poe_watts = 0
    rack_units_used = 0
    
    for cid, data in raw_components.items():
        component = get_component(cid)
        qty = data["quantity"]
        
        total_rack_watts += component.power_draw_watts * qty
        rack_units_used += (component.rack_units or 0) * qty
        
        if "PoE" in component.connectivity or "PoE_plus" in component.connectivity:
            total_poe_watts += estimate_poe_draw(component) * qty
    
    # ── Step 6: Build Line Items ──────────────────────────────
    line_items = []
    total_dealer_cost = 0
    total_msrp = 0
    total_labor_hours = 0
    
    for cid, data in raw_components.items():
        component = get_component(cid)
        qty = data["quantity"]
        
        extended_dealer = component.dealer_cost_estimate * qty
        extended_msrp = component.msrp * qty
        extended_labor = component.labor_hours * qty
        
        line_items.append({
            "component_id": cid,
            "brand": component.brand,
            "model": component.model,
            "model_number": component.model_number,
            "quantity": qty,
            "rooms": data["rooms"],
            "unit_msrp": component.msrp,
            "unit_dealer_cost": component.dealer_cost_estimate,
            "extended_dealer_cost": extended_dealer,
            "extended_msrp": extended_msrp,
            "labor_hours_per_unit": component.labor_hours,
            "extended_labor_hours": extended_labor,
            "auto_added": data.get("auto_added", False),
            "reason": data.get("reason", None)
        })
        
        total_dealer_cost += extended_dealer
        total_msrp += extended_msrp
        total_labor_hours += extended_labor
    
    # ── Step 7: Apply Markup & Calculate Client Price ─────────
    target_margin = request.global_overrides.get("target_margin_pct", 45) / 100
    # Margin = (sell_price - cost) / sell_price
    # Therefore: sell_price = cost / (1 - margin)
    
    equipment_sell_price = total_dealer_cost / (1 - target_margin)
    
    # Labor pricing (separate from equipment)
    labor_rate_per_hour = 125  # Symphony standard rate, adjust as needed
    total_labor_cost = total_labor_hours * labor_rate_per_hour
    
    # Programming hours (roughly 20% of install hours for C4)
    programming_hours = estimate_programming_hours(component_list)
    programming_cost = programming_hours * labor_rate_per_hour
    
    total_project_price = equipment_sell_price + total_labor_cost + programming_cost
    
    # ── Step 8: Output ────────────────────────────────────────
    return BOMOutput(
        project_name=request.project_name,
        generated_at=datetime.now().isoformat(),
        line_items=sorted(line_items, key=lambda x: x["component_id"]),
        summary={
            "total_dealer_cost": total_dealer_cost,
            "total_msrp": total_msrp,
            "equipment_sell_price": equipment_sell_price,
            "implied_margin_pct": target_margin * 100,
            "total_labor_hours": total_labor_hours,
            "total_labor_cost": total_labor_cost,
            "programming_hours": programming_hours,
            "programming_cost": programming_cost,
            "total_project_price": total_project_price,
            "rack_units_used": rack_units_used,
            "total_rack_watts": total_rack_watts,
            "total_poe_watts": total_poe_watts,
            "circuit_count_recommended": math.ceil(total_rack_watts / 1500)
        },
        violations=violations,    # Hard rule failures — must resolve before quoting
        warnings=warnings,        # Soft rule warnings — review with client
        room_summary=[
            {
                "room_name": r.room_name,
                "tier": r.tier,
                "component_count": len([li for li in line_items if r.room_name in li["rooms"]])
            }
            for r in request.rooms
        ]
    )
```

### 5.3 Markup Calculation Reference

| Scenario | Dealer Cost | Target Margin | Multiplier | Client Price |
|----------|------------|--------------|------------|-------------|
| Standard equipment | $10,000 | 45% | 1.82× | $18,182 |
| Premium equipment | $30,000 | 42% | 1.72× | $51,724 |
| Ultra equipment | $80,000 | 40% | 1.67× | $133,333 |
| Labor (in-house) | $125/hr cost | — | Bill at $125/hr | — |
| Programming | $125/hr cost | — | Bill at $125/hr | — |
| Subcontracted labor | Cost + 20% | — | 1.20× | — |

**Symphony Margin Guidance:**
- Equipment margin should be ≥40% to cover overhead, warranty callbacks, and programming revisions
- Labor is billed separately and is not subject to the equipment markup formula
- Programming is billed at the same labor rate but tracked separately

### 5.4 BOM Output Format (JSON)

```json
{
  "project_name": "Vail Mountain Residence — Theater + Living Room",
  "client_name": "Sample Client",
  "generated_at": "2025-01-15T10:30:00Z",
  "generated_by": "System Design Graph v1.0",
  "summary": {
    "total_dealer_cost": 42500,
    "equipment_sell_price": 77272,
    "implied_margin_pct": 45,
    "total_labor_hours": 56,
    "total_labor_cost": 7000,
    "programming_hours": 14,
    "programming_cost": 1750,
    "total_project_price": 86022,
    "rack_units_used": 14,
    "total_rack_watts": 680,
    "total_poe_watts": 85,
    "circuit_count_recommended": 3
  },
  "violations": [],
  "warnings": [
    {
      "rule_id": "soft-007",
      "message": "12 IoT devices without VLAN segmentation — recommend managed switch configuration.",
      "resolution": "Configure VLAN 20 for IoT/AV devices on Araknis 310 switch."
    }
  ],
  "line_items": [
    {
      "component_id": "control4-ea-5",
      "brand": "Control4",
      "model": "EA-5",
      "model_number": "C4-EA5",
      "quantity": 1,
      "rooms": ["infrastructure"],
      "unit_msrp": 2000,
      "unit_dealer_cost": 1000,
      "extended_dealer_cost": 1000,
      "extended_msrp": 2000,
      "labor_hours_per_unit": 2.0,
      "extended_labor_hours": 2.0
    }
  ]
}
```

---

## 6. Seed Data

Complete seed data for 35 components with real specs. Dealer costs estimated at 45–50% off MSRP for CEDIA dealers.

```json
{
  "schema_version": "1.0",
  "last_updated": "2025-01-01",
  "components": [

    {
      "component_id": "control4-ea-1",
      "brand": "Control4",
      "model": "EA-1",
      "model_number": "C4-EA1",
      "category": "processor",
      "description": "Entry-level home automation controller, 1 audio zone, ideal for single rooms or small systems",
      "msrp": 600,
      "dealer_cost_estimate": 300,
      "labor_hours": 1.5,
      "programming_hours": 4,
      "rack_units": 1,
      "power_draw_watts": 15,
      "connectivity": ["IP", "LAN_RJ45", "RS-232", "IR", "Control4_Zigbee"],
      "requires": [],
      "requires_license": ["control4-dealer-certification"],
      "recommended_with": ["lutron-caseta-bridge-pro", "araknis-310-8-poe"],
      "room_types": ["living", "bedroom", "office", "kitchen"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "zone_count": 1,
      "discontinued": false,
      "notes": "Suitable for 1-2 room projects. Upgrade to EA-3 for 3+ zones or EA-5 for full home.",
      "data_sources": ["https://docs.control4.com/docs/product/ea-1/data-sheet/english/revision/B/"]
    },

    {
      "component_id": "control4-ea-3",
      "brand": "Control4",
      "model": "EA-3",
      "model_number": "C4-EA3",
      "category": "processor",
      "description": "Mid-tier home automation controller, 3 audio zones, 4-port gigabit switch, hi-res audio",
      "msrp": 1000,
      "dealer_cost_estimate": 500,
      "labor_hours": 2.0,
      "programming_hours": 6,
      "rack_units": 1,
      "power_draw_watts": 25,
      "connectivity": ["IP", "LAN_RJ45", "RS-232", "IR", "Control4_Zigbee", "Analog_RCA"],
      "requires": [],
      "requires_license": ["control4-dealer-certification"],
      "recommended_with": ["araknis-310-16-poe", "wattbox-800-8", "control4-t4-touchscreen-8"],
      "room_types": ["theater", "living", "bedroom", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "zone_count": 3,
      "discontinued": false,
      "notes": "Sweet spot for 2-4 room projects. Includes integrated 4-port gigabit switch.",
      "data_sources": ["https://www.strata-gee.com/control4s-new-ea-controller-series-reaches-for-a-broader-audience/"]
    },

    {
      "component_id": "control4-ea-5",
      "brand": "Control4",
      "model": "EA-5",
      "model_number": "C4-EA5",
      "category": "processor",
      "description": "Flagship home automation controller, 5 audio zones, 5-port gigabit switch, eSATA, hi-res audio",
      "msrp": 2000,
      "dealer_cost_estimate": 1000,
      "labor_hours": 2.0,
      "programming_hours": 8,
      "rack_units": 1,
      "power_draw_watts": 40,
      "power_draw_idle_watts": 15,
      "connectivity": ["IP", "LAN_RJ45", "RS-232", "IR", "Control4_Zigbee", "Analog_RCA", "HDMI_1.4"],
      "requires": [],
      "requires_license": ["control4-dealer-certification"],
      "recommended_with": ["araknis-310-16-poe", "araknis-310-24-poe", "wattbox-800-12", "control4-t4-touchscreen-10"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office", "gym", "wine_cellar", "garage", "pool"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "zone_count": 5,
      "discontinued": false,
      "notes": "Use for 5+ room projects or any project requiring 5 independent audio zones. 40W max draw — leave headroom in rack circuit.",
      "data_sources": ["https://docs.control4.com/docs/product/ea-5/data-sheet/english/revision/B/"]
    },

    {
      "component_id": "control4-ds2-door-station",
      "brand": "Control4",
      "model": "DS2 Door Station",
      "model_number": "C4-DS2FM",
      "category": "intercom",
      "description": "HD video door station with audio intercom, integrates directly with Control4 system for full video doorbell functionality",
      "msrp": 499,
      "dealer_cost_estimate": 250,
      "labor_hours": 2.0,
      "rack_units": null,
      "power_draw_watts": 13,
      "connectivity": ["IP", "LAN_RJ45", "PoE"],
      "requires": ["control4-ea-1"],
      "recommended_with": ["control4-t4-touchscreen-8", "luma-510-nvr"],
      "room_types": ["living", "theater", "office"],
      "tier": "standard",
      "indoor_outdoor": "outdoor",
      "discontinued": false,
      "notes": "Flush mount (C4-DS2FM) or surface mount (C4-DS2SM) variants. Requires Control4 processor for intercom functionality. PoE powered — no power run to door required.",
      "data_sources": ["https://www.snapav.com/shop/en/snapav/ds2"]
    },

    {
      "component_id": "control4-t4-touchscreen-8",
      "brand": "Control4",
      "model": "T4 Touchscreen 8\"",
      "model_number": "C4-T4IW8",
      "category": "control_surface",
      "description": "8-inch in-wall PoE touchscreen for Control4, 1920x1200 resolution, dual microphones, 720p camera",
      "msrp": 550,
      "dealer_cost_estimate": 275,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 13,
      "connectivity": ["IP", "LAN_RJ45", "PoE", "WiFi_5"],
      "requires": ["control4-ea-1"],
      "recommended_with": ["control4-ds2-door-station"],
      "room_types": ["theater", "living", "bedroom", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Powered via PoE (802.3af). Uses same backbox as T3 — easy retrofit. Must be connected via Cat cable to PoE switch.",
      "data_sources": ["https://www.snapav.com/shop/en/snapav/control4-t4-series-10-in-wall-touchscreen-c4-t4iw10-a"]
    },

    {
      "component_id": "control4-t4-touchscreen-10",
      "brand": "Control4",
      "model": "T4 Touchscreen 10\"",
      "model_number": "C4-T4IW10",
      "category": "control_surface",
      "description": "10-inch in-wall PoE touchscreen for Control4, 1920x1200 resolution, dual microphones, 720p camera",
      "msrp": 700,
      "dealer_cost_estimate": 350,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 13,
      "connectivity": ["IP", "LAN_RJ45", "PoE", "WiFi_5"],
      "requires": ["control4-ea-1"],
      "recommended_with": ["control4-ea-5"],
      "room_types": ["theater", "living", "office"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Prefer 10\" in main theater and primary living spaces. 8\" for secondary locations."
    },

    {
      "component_id": "lutron-caseta-dimmer",
      "brand": "Lutron",
      "model": "Caseta Wireless Dimmer",
      "model_number": "PD-6WCL-WH",
      "category": "lighting_control",
      "description": "Wireless dimmer, ClearConnect RF, 150W LED, works with Caseta Smart Bridge Pro",
      "msrp": 80,
      "dealer_cost_estimate": 40,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 1,
      "connectivity": ["ClearConnect_RF", "IP"],
      "requires": ["lutron-caseta-bridge-pro"],
      "recommended_with": ["control4-ea-1"],
      "room_types": ["living", "bedroom", "office", "kitchen", "dining"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Consumer-grade. Use for budget projects or secondary rooms. Control4 integrates via IP through Caseta Bridge Pro. Caseta and RadioRA 3 can coexist but Caseta devices count toward RadioRA 3 legacy device limit.",
      "data_sources": ["https://assets.lutron.com/a/documents/2caseta_wireless_price_list_product_descriptions_us_.pdf"]
    },

    {
      "component_id": "lutron-caseta-bridge-pro",
      "brand": "Lutron",
      "model": "Caseta Smart Bridge Pro",
      "model_number": "L-BDGPRO2-WH",
      "category": "lighting_control",
      "description": "Smart Bridge Pro enables third-party integration (Control4, Apple HomeKit, Google, Alexa) with Caseta devices",
      "msrp": 200,
      "dealer_cost_estimate": 100,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 5,
      "connectivity": ["IP", "LAN_RJ45", "ClearConnect_RF"],
      "requires": [],
      "recommended_with": ["control4-ea-1"],
      "room_types": ["living", "bedroom", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Required for Control4 or any 3rd-party integration with Caseta. One bridge serves up to 75 devices.",
      "data_sources": ["https://assets.lutron.com/a/documents/2caseta_wireless_price_list_product_descriptions_us_.pdf"]
    },

    {
      "component_id": "lutron-radiora3-processor",
      "brand": "Lutron",
      "model": "RadioRA 3 All-In-One Processor",
      "model_number": "RR-PROC3-KIT1",
      "category": "lighting_control",
      "description": "RadioRA 3 system processor, controls up to 200 Lutron devices, ClearConnect Type X/A, PoE powered, LEAP API",
      "msrp": 550,
      "dealer_cost_estimate": 275,
      "labor_hours": 1.0,
      "programming_hours": 4,
      "rack_units": null,
      "power_draw_watts": 4,
      "connectivity": ["IP", "LAN_RJ45", "PoE", "ClearConnect_RF"],
      "requires": [],
      "requires_license": ["lutron-rra3-certification"],
      "recommended_with": ["control4-ea-3", "control4-ea-5", "lutron-sunnata-rf-dimmer"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office", "gym", "dining"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "PoE powered — no AC outlet required at installation location. Controls up to 200 devices (100 Type X + 100 Type A). Backwards compatible with RadioRA 2 devices. LEAP API for Control4 integration.",
      "data_sources": ["https://www.wave-electronics.com/lutron-rr-proc3-kit1-radiora-3-all-in-one-processor"]
    },

    {
      "component_id": "lutron-sunnata-rf-dimmer",
      "brand": "Lutron",
      "model": "Sunnata RF PRO LED+ Dimmer",
      "model_number": "RRST-PRO-N",
      "category": "lighting_control",
      "description": "RadioRA 3 touch dimmer, ClearConnect Type X RF, 250W LED, sleek glass-panel design",
      "msrp": 260,
      "dealer_cost_estimate": 130,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 1,
      "connectivity": ["ClearConnect_RF"],
      "requires": ["lutron-radiora3-processor"],
      "room_types": ["theater", "living", "bedroom", "dining", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Available in multiple finishes (midnight, linen, white, truffle). Premium appearance vs Caseta. Required for RadioRA 3 Type X full-feature operation.",
      "data_sources": ["https://unionlighting.com/products/lutron-radiora-3-sunnata-pro-led-rf-touch-dimmer-switch"]
    },

    {
      "component_id": "lutron-hwqs-processor",
      "brand": "Lutron",
      "model": "HomeWorks QSX Processor",
      "model_number": "HQP7-1",
      "category": "lighting_control",
      "description": "Enterprise-grade lighting processor, supports wired + wireless devices, advanced scenes, whole-home integration",
      "msrp": 1929,
      "dealer_cost_estimate": 965,
      "labor_hours": 2.0,
      "programming_hours": 16,
      "rack_units": 1,
      "power_draw_watts": 20,
      "connectivity": ["IP", "LAN_RJ45", "RS-232", "ClearConnect_RF"],
      "requires": [],
      "requires_license": ["lutron-hwqs-certification"],
      "recommended_with": ["control4-ea-5", "araknis-710-24-poe"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office", "gym", "wine_cellar", "garage", "pool"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Requires Lutron Advanced System Design certification. Use for high-end projects requiring wired Grafik Eye QS panels, seeTouch keypads, and advanced timeclock features. Significant programming investment.",
      "data_sources": ["https://iqelectro.com/products/hqp7-1-lutron-homeworks-qsx-processor-for-advanced-wired-wireless-system-control"]
    },

    {
      "component_id": "sonos-era-100",
      "brand": "Sonos",
      "model": "Era 100",
      "model_number": "ERA100G1US1BLK",
      "category": "streaming",
      "description": "Smart speaker with stereo sound, Wi-Fi 6, Bluetooth 5.0, USB-C line-in, Alexa & AirPlay 2",
      "msrp": 249,
      "dealer_cost_estimate": 175,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 15,
      "connectivity": ["WiFi_6", "Bluetooth_5", "USB_C", "IP"],
      "requires": [],
      "recommended_with": ["control4-ea-1", "sonos-port"],
      "replaces": ["sonos-one"],
      "room_types": ["bedroom", "office", "kitchen", "gym", "wine_cellar"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Two Era 100 units can be stereo-paired. Works as rear speakers with Sonos Arc or Beam. Pairs well with Sonos Sub Gen 3. Control4 driver available.",
      "data_sources": ["https://valueelectronics.com/product/sonos-era-100-era-300-choose-black-or-white/"]
    },

    {
      "component_id": "sonos-era-300",
      "brand": "Sonos",
      "model": "Era 300",
      "model_number": "ERA300G1US1BLK",
      "category": "streaming",
      "description": "Spatial audio speaker with Dolby Atmos Music, Wi-Fi 6, Bluetooth 5.0, 6 drivers, USB-C line-in",
      "msrp": 449,
      "dealer_cost_estimate": 315,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 35,
      "connectivity": ["WiFi_6", "Bluetooth_5", "USB_C", "IP"],
      "requires": [],
      "recommended_with": ["sonos-arc", "sonos-sub-gen3"],
      "replaces": ["sonos-one"],
      "room_types": ["living", "bedroom", "theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Two Era 300 units used as surrounds with Sonos Arc create a 7.1.4 system when combined with two Sub Gen 3. Adds Atmos height channels that Era 100 cannot provide.",
      "data_sources": ["https://www.sonos.com/en-us/shop/era-300", "https://www.coastalprotect.com/wp-content/uploads/2025/01/Price-list_US_MSRP_Updated.pdf"]
    },

    {
      "component_id": "sonos-arc",
      "brand": "Sonos",
      "model": "Arc",
      "model_number": "ARCG1US1BLK",
      "category": "soundbar",
      "description": "Premium smart soundbar with Dolby Atmos, 11 drivers, HDMI eARC, Wi-Fi, Alexa & AirPlay 2",
      "msrp": 899,
      "dealer_cost_estimate": 630,
      "labor_hours": 1.0,
      "rack_units": null,
      "power_draw_watts": 105,
      "connectivity": ["HDMI_2.0", "eARC", "WiFi_5", "IP"],
      "requires": [],
      "recommended_with": ["sonos-era-300", "sonos-sub-gen3", "sony-xr-77a95l", "sony-xr-85x93l"],
      "room_types": ["living", "bedroom"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Connect to TV eARC port for Dolby Atmos TrueHD passthrough. Regular ARC port limits to Dolby Atmos via DD+. HDMI 2.0 — no 4K@120Hz. Best fit for living rooms and master bedrooms.",
      "data_sources": ["https://www.coastalprotect.com/wp-content/uploads/2025/01/Price-list_US_MSRP_Updated.pdf"]
    },

    {
      "component_id": "sonos-amp",
      "brand": "Sonos",
      "model": "Amp",
      "model_number": "AMPG1US1BLK",
      "category": "amplifier",
      "description": "125W × 2 streaming amplifier, HDMI ARC, 3.5mm/USB-C line-in, Wi-Fi, powers passive speakers",
      "msrp": 699,
      "dealer_cost_estimate": 490,
      "labor_hours": 1.0,
      "rack_units": 1,
      "power_draw_watts": 250,
      "connectivity": ["WiFi_5", "HDMI_1.4", "ARC", "USB_C", "Analog_RCA", "IP", "LAN_RJ45"],
      "requires": [],
      "recommended_with": ["jbl-scl-6", "episode-es-ht-lc-6", "control4-ea-1"],
      "room_types": ["living", "outdoor", "office", "gym"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Ideal for driving in-wall/in-ceiling speakers from Sonos ecosystem. 125W per channel into 8Ω, 250W per channel into 4Ω. Wi-Fi can be disabled when wired via Ethernet for cooler rack operation.",
      "data_sources": ["https://www.coastalprotect.com/wp-content/uploads/2025/01/Price-list_US_MSRP_Updated.pdf"]
    },

    {
      "component_id": "sonos-port",
      "brand": "Sonos",
      "model": "Port",
      "model_number": "PORT1US1BLK",
      "category": "streaming",
      "description": "Streaming component for existing stereo or AV receiver, variable/fixed analog output, coaxial digital out",
      "msrp": 449,
      "dealer_cost_estimate": 315,
      "labor_hours": 0.5,
      "rack_units": null,
      "power_draw_watts": 10,
      "connectivity": ["WiFi_5", "Analog_RCA", "SPDIF", "LAN_RJ45", "IP"],
      "requires": [],
      "recommended_with": ["control4-ea-3"],
      "room_types": ["theater", "living", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Adds Sonos streaming to any existing amplifier or receiver. Preferred over Amp when existing amp/receiver is already present. Wi-Fi can be disabled when using Ethernet.",
      "data_sources": ["https://www.coastalprotect.com/wp-content/uploads/2025/01/Price-list_US_MSRP_Updated.pdf"]
    },

    {
      "component_id": "sony-vpl-xw5000es",
      "brand": "Sony",
      "model": "VPL-XW5000ES",
      "model_number": "VPLXW5000ES",
      "category": "display",
      "subcategory": "projector",
      "description": "Native 4K SXRD laser projector, 2000 lumens, X1 Ultimate processor, 20,000hr lamp, HDMI 2.0b",
      "msrp": 5999,
      "dealer_cost_estimate": 3000,
      "labor_hours": 3.0,
      "rack_units": null,
      "power_draw_watts": 295,
      "connectivity": ["HDMI_2.0", "RS-232", "LAN_RJ45", "IP"],
      "requires": ["si-zero-edge-120"],
      "recommended_with": ["si-black-diamond-120", "si-zero-edge-120", "jbl-sdr-35"],
      "room_types": ["theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "max_screen_size_inches": 300,
      "discontinued": false,
      "notes": "HDMI 2.0b ONLY — does NOT support 4K@120Hz or HDMI 2.1 features (VRR/ALLM). Inform gaming clients. 2000 lumens suited for dedicated dark rooms. Manual zoom/focus (unlike XW7000ES which has motorized).",
      "data_sources": ["https://electronics.sony.com/tv-video/projectors/all-projectors/p/vplxw5000es", "https://www.projectorreviews.com/sony/sony-vpl-xw5000es-4k-sxrd-home-theater-projector-review/"]
    },

    {
      "component_id": "sony-vpl-xw7000es",
      "brand": "Sony",
      "model": "VPL-XW7000ES",
      "model_number": "VPLXW7000ES",
      "category": "display",
      "subcategory": "projector",
      "description": "Native 4K SXRD laser projector, 3200 lumens, motorized ACF lens 2.1×, X1 Ultimate, 20,000hr, RS-232 + IP control",
      "msrp": 26000,
      "dealer_cost_estimate": 13000,
      "labor_hours": 3.0,
      "rack_units": null,
      "power_draw_watts": 420,
      "connectivity": ["HDMI_2.0", "RS-232", "LAN_RJ45", "IP"],
      "requires": ["si-zero-edge-130"],
      "recommended_with": ["si-black-diamond-150", "jbl-sdr-35", "jbl-sda-7120"],
      "room_types": ["theater"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "max_screen_size_inches": 300,
      "discontinued": false,
      "notes": "3200 lumens enables 150-inch screen even with some ambient light. Motorized zoom/focus/lens memory = no manual adjustment after calibration. Still HDMI 2.0 — same 4K@120Hz limitation as XW5000ES. Dedicated 20A circuit strongly recommended.",
      "data_sources": ["https://www.projectorreviews.com/sony/sony-vpl-xw5000es-4k-sxrd-home-theater-projector-review/"]
    },

    {
      "component_id": "epson-ls12000",
      "brand": "Epson",
      "model": "Pro Cinema LS12000",
      "model_number": "V11HA47020MB",
      "category": "display",
      "subcategory": "projector",
      "description": "4K PRO-UHD 3LCD laser projector, 2700 lumens, HDMI 2.1, HDR10+, 120Hz, motorized lens, 20,000hr",
      "msrp": 4999,
      "dealer_cost_estimate": 2500,
      "labor_hours": 3.0,
      "rack_units": null,
      "power_draw_watts": 491,
      "connectivity": ["HDMI_2.1", "RS-232", "LAN_RJ45", "IP"],
      "requires": [],
      "recommended_with": ["si-zero-edge-120", "si-black-diamond-120"],
      "room_types": ["theater"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "max_screen_size_inches": 300,
      "discontinued": false,
      "notes": "Best value 4K projector with HDMI 2.1 — supports 4K@120Hz gaming. 3LCD pixel-shift (not native 4K panels) but excellent real-world image quality. 2700 lumens = brighter than Sony XW5000ES. Motorized lens included. Paired well with SI Zero Edge screens.",
      "data_sources": ["https://www.bestbuy.com/product/epson-pro-cinema-ls12000-4k-pro-uhd-laser-projector", "https://www.projectorreviews.com/epson/epson-pro-cinema-ls12000-laser-projector-review/"]
    },

    {
      "component_id": "sony-xr-85x93l",
      "brand": "Sony",
      "model": "BRAVIA XR X93L 85\"",
      "model_number": "XR85X93L",
      "category": "display",
      "subcategory": "television",
      "description": "85-inch Mini LED 4K TV, Cognitive Processor XR, Google TV, HDMI 2.1 (4K@120Hz), full array backlight",
      "msrp": 3999,
      "dealer_cost_estimate": 2000,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 230,
      "connectivity": ["HDMI_2.1", "eARC", "WiFi_6", "Bluetooth_5", "IP"],
      "requires": [],
      "recommended_with": ["sonos-arc", "control4-ea-3"],
      "room_types": ["living", "theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Two HDMI 2.1 ports (4K@120Hz). eARC on HDMI 3 for Sonos Arc. Excellent HDR performance with full-array backlight. Google TV = native streaming. Use as main TV for living rooms or secondary theater display.",
      "data_sources": ["https://electronics.sony.com/tv-video/televisions/all-tvs/p/xr85x93l"]
    },

    {
      "component_id": "sony-xr-77a95l",
      "brand": "Sony",
      "model": "BRAVIA XR A95L 77\"",
      "model_number": "XR77A95L",
      "category": "display",
      "subcategory": "television",
      "description": "77-inch QD-OLED 4K TV, Cognitive Processor XR, Google TV, HDMI 2.1 (4K@120Hz), best Sony picture quality",
      "msrp": 4999,
      "dealer_cost_estimate": 2500,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 155,
      "connectivity": ["HDMI_2.1", "eARC", "WiFi_6", "Bluetooth_5", "IP"],
      "requires": [],
      "recommended_with": ["sonos-arc", "control4-ea-5"],
      "room_types": ["living", "bedroom", "theater"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Sony's flagship TV — QD-OLED delivers best blacks + widest color gamut. HDMI 2.1 supports 4K@120Hz, VRR, ALLM. Two HDMI 2.1 ports. eARC for Arc soundbar. Premium living room or master bedroom centerpiece.",
      "data_sources": ["https://electronics.sony.com/tv-video/televisions/all-tvs/p/xr77a95l"]
    },

    {
      "component_id": "si-zero-edge-120",
      "brand": "Screen Innovations",
      "model": "Zero Edge 120\" 16:9",
      "model_number": "ZT120W-A",
      "category": "screen",
      "description": "Fixed frame projection screen, SI White 1.1 gain, ultra-thin bezel, 120-inch diagonal",
      "msrp": 1200,
      "dealer_cost_estimate": 600,
      "labor_hours": 2.0,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": [],
      "requires": [],
      "recommended_with": ["epson-ls12000", "sony-vpl-xw5000es"],
      "room_types": ["theater"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "max_screen_size_inches": 120,
      "discontinued": false,
      "notes": "Standard entry into SI line. White 1.1 gain = bright neutral image suitable for dark rooms. Not ALR — will show ambient light. Thin bezel gives premium appearance.",
      "data_sources": ["https://www.screeninnovations.com"]
    },

    {
      "component_id": "si-black-diamond-130",
      "brand": "Screen Innovations",
      "model": "Black Diamond Zero Edge 130\"",
      "model_number": "ZT130BD14",
      "category": "screen",
      "description": "130-inch ALR (Ambient Light Rejecting) fixed frame screen, Black Diamond 1.4 gain, rejects off-axis light",
      "msrp": 4500,
      "dealer_cost_estimate": 2250,
      "labor_hours": 2.5,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": [],
      "requires": [],
      "recommended_with": ["sony-vpl-xw5000es", "sony-vpl-xw7000es", "epson-ls12000"],
      "incompatible_with": [],
      "room_types": ["theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "max_screen_size_inches": 130,
      "discontinued": false,
      "notes": "ALR material rejects ambient light from sides/ceiling while passing projector light from on-axis. CRITICAL: projector must be ceiling-mounted on-axis (within 15° horizontal). Off-axis placement destroys the ALR effect.",
      "data_sources": ["https://www.audioholics.com/projector-screen-reviews/screen-innovations-black-diamond-zero-edge-g2-pre"]
    },

    {
      "component_id": "si-solo-shade",
      "brand": "Screen Innovations",
      "model": "Solo Motorized Shade",
      "model_number": "SOLO-84-W-BLK",
      "category": "shading",
      "description": "Wireless battery-powered motorized roller shade, Zero Edge style, 2-year battery life, no wiring required",
      "msrp": 1200,
      "dealer_cost_estimate": 600,
      "labor_hours": 1.0,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": ["Zigbee", "IP"],
      "requires": [],
      "recommended_with": ["lutron-radiora3-processor", "control4-ea-3"],
      "room_types": ["theater", "living", "bedroom", "office"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Battery-powered — ideal for retrofits where no wire to motor is possible. Integrates with Control4 via Zigbee or RS-485 bridge. 2-year battery life at typical use. Price varies with fabric and size — $1,200 is mid-size estimate.",
      "data_sources": ["https://www.screeninnovations.com/screen/solo/"]
    },

    {
      "component_id": "jbl-scl-6",
      "brand": "JBL Synthesis",
      "model": "SCL-6",
      "model_number": "SCL-6",
      "category": "speaker",
      "subcategory": "in-wall",
      "description": "2.5-way in-wall LCR speaker, 4× 5.25\" woofers, 1\" compression driver, HDI horn, designed for on-axis listening",
      "msrp": 1500,
      "dealer_cost_estimate": 750,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": ["Analog_RCA"],
      "requires": [],
      "recommended_with": ["jbl-sdr-35", "jbl-sda-7120", "sonos-amp"],
      "room_types": ["theater", "living"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Use as L/C/R in main theater front stage. Designed to pair with SCL-7/SCL-8 for surrounds and heights. Cat Claw installation mechanism — easy one-person install. MSRP $1,500/each.",
      "data_sources": ["https://www.jblsynthesis.com/news-reviews/news/JBL+Synthesis+Expands+Award-winning+SCL+Loudspeaker+Range+With+Four+New+Advanced+Architectural+Models.html"]
    },

    {
      "component_id": "jbl-sdr-35",
      "brand": "JBL Synthesis",
      "model": "SDR-35",
      "model_number": "SDR-35",
      "category": "receiver",
      "description": "16-channel Class G immersive surround AV receiver, Dirac Live, decodes up to 15.1 channels, Dante networking",
      "msrp": 8250,
      "dealer_cost_estimate": 4125,
      "labor_hours": 3.0,
      "rack_units": 4,
      "power_draw_watts": 600,
      "connectivity": ["HDMI_2.0", "HDMI_2.1", "LAN_RJ45", "Analog_XLR", "Analog_RCA", "SPDIF", "Optical_TOSLINK", "Dante", "RS-232", "IP"],
      "requires": [],
      "recommended_with": ["jbl-sda-7120", "jbl-scl-6", "sony-vpl-xw5000es"],
      "room_types": ["theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "channel_count": 16,
      "discontinued": false,
      "notes": "Flagship JBL Synthesis AVR. 7 internal channels of Class G amp + 9 pre-outs for external amps. Dante port connects to SDA-7120 amplifier over Ethernet. Dirac Live included for room correction. 4U rack space. Dedicated 20A circuit.",
      "data_sources": ["https://www.audiosciencereview.com/forum/index.php?threads/jbl-sdr-35-avr-review.36669/"]
    },

    {
      "component_id": "jbl-sda-7120",
      "brand": "JBL Synthesis",
      "model": "SDA-7120",
      "model_number": "SDA-7120",
      "category": "amplifier",
      "description": "7-channel 100W/ch Class G power amplifier, Dante audio networking, XLR/RCA balanced inputs, RS-232+IP control",
      "msrp": 4840,
      "dealer_cost_estimate": 2420,
      "labor_hours": 2.0,
      "rack_units": 4,
      "power_draw_watts": 1500,
      "connectivity": ["Analog_XLR", "Analog_RCA", "Dante", "RS-232", "IP", "LAN_RJ45"],
      "requires": [],
      "recommended_with": ["jbl-sdr-35"],
      "room_types": ["theater"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "channel_count": 7,
      "discontinued": false,
      "notes": "1,500W max draw — MUST have dedicated 20A circuit. 0.002% THD at 80% power. Dante link to SDR-35 requires managed switch with IGMP snooping. Class G design: Class A at low power, Class A/B at high power — very low distortion.",
      "data_sources": ["https://theaudiosolutions.com/products/jbl-synthesis-sda-7120-7-channel-class-g-home-theater-amplifier"]
    },

    {
      "component_id": "araknis-310-16-poe",
      "brand": "Araknis Networks",
      "model": "AN-310-SW-F-16-POE",
      "model_number": "AN-310-SW-F-16-POE",
      "category": "networking",
      "description": "16-port L2 managed gigabit switch, full PoE+ on all ports, 250W budget, OvrC cloud management, dual SFP uplinks",
      "msrp": 550,
      "dealer_cost_estimate": 275,
      "labor_hours": 1.0,
      "rack_units": 1,
      "power_draw_watts": 30,
      "connectivity": ["LAN_RJ45", "PoE_plus", "IP"],
      "requires": [],
      "recommended_with": ["control4-ea-3", "control4-ea-5", "wattbox-800-12"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "250W PoE budget across 16 ports. 30W max per port. VLAN, QoS, IGMP snooping. OvrC integration for remote reboot of PoE ports. Control4 driver available for power cycling devices from C4 UI. 1U rack mount.",
      "data_sources": ["https://www.snapav.com/shop/en/snapav/araknis-networks-reg;-310-series-l2-managed-gigabit-switch-with-full-poe-and-front-ports-an-310-sw-f-poe"]
    },

    {
      "component_id": "araknis-310-24-poe",
      "brand": "Araknis Networks",
      "model": "AN-310-SW-F-24-POE",
      "model_number": "AN-310-SW-F-24-POE",
      "category": "networking",
      "description": "24-port L2 managed gigabit switch, full PoE+ on all ports, 375W budget, OvrC, dual SFP uplinks",
      "msrp": 750,
      "dealer_cost_estimate": 375,
      "labor_hours": 1.0,
      "rack_units": 1,
      "power_draw_watts": 40,
      "connectivity": ["LAN_RJ45", "PoE_plus", "IP"],
      "requires": [],
      "recommended_with": ["control4-ea-5", "wattbox-800-12"],
      "room_types": ["theater", "living", "bedroom", "outdoor", "office"],
      "tier": "premium",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "375W PoE budget. Use for larger projects with 15+ PoE devices. Supports Dante VLAN with IGMP snooping for JBL Synthesis networking.",
      "data_sources": ["https://www.snapav.com/wcsstore/ExtendedSitesCatalogAssetStore/attachments/documents/Networking/SupportDocuments/AraknisNetworksX10SwitchComparison-B_210621tw.pdf"]
    },

    {
      "component_id": "araknis-710-24-poe",
      "brand": "Araknis Networks",
      "model": "AN-710-SW-F-24-POE",
      "model_number": "AN-710-SW-F-24-POE",
      "category": "networking",
      "description": "24-port 10G-capable managed switch, PoE+, advanced routing, OvrC, for ultra-tier AV networks",
      "msrp": 1800,
      "dealer_cost_estimate": 900,
      "labor_hours": 1.5,
      "rack_units": 1,
      "power_draw_watts": 60,
      "connectivity": ["LAN_RJ45", "PoE_plus", "IP"],
      "requires": [],
      "recommended_with": ["control4-ea-5", "lutron-hwqs-processor", "jbl-sda-7120"],
      "room_types": ["theater", "living", "office"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Use for ultra-tier projects with Dante audio networking, 4K matrix distribution, or large camera systems. Supports advanced routing and L3 features."
    },

    {
      "component_id": "wattbox-800-12",
      "brand": "Snap One / WattBox",
      "model": "WB-800-IPVM-12",
      "model_number": "WB-800-IPVM-12",
      "category": "power",
      "description": "12-outlet IP power conditioner, individually controlled and metered outlets, surge protection, OvrC integration",
      "msrp": 799,
      "dealer_cost_estimate": 400,
      "labor_hours": 1.0,
      "rack_units": 1,
      "power_draw_watts": 15,
      "connectivity": ["IP", "LAN_RJ45"],
      "requires": [],
      "recommended_with": ["control4-ea-5", "araknis-310-16-poe"],
      "room_types": ["theater", "living", "office"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Critical for remote troubleshooting — can reboot individual outlets via OvrC without site visit. Monitor power draw per outlet. Surge protection for all connected gear. 1U rack mount. Essential on every rack.",
      "data_sources": ["https://plutohouse.store/products/wattbox-wb-800-ipvm-12-800-series-ip-power-conditioner-12-individually-controlled-metered-outlets"]
    },

    {
      "component_id": "luma-510-nvr",
      "brand": "Snap One / Luma",
      "model": "Luma 510 NVR",
      "model_number": "LUM-510-NVR",
      "category": "security",
      "description": "Network video recorder, up to 12MP cameras, 4K TV output, Smart Motion analytics, OvrC integration",
      "msrp": 650,
      "dealer_cost_estimate": 325,
      "labor_hours": 1.5,
      "rack_units": 1,
      "power_draw_watts": 25,
      "connectivity": ["IP", "LAN_RJ45", "HDMI_1.4"],
      "requires": [],
      "recommended_with": ["luma-510-dome-camera", "araknis-310-16-poe"],
      "room_types": ["theater", "living", "outdoor"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Integrates with Control4 for camera viewing on touchscreens. OvrC for remote management. Supports Luma 500/510 series cameras."
    },

    {
      "component_id": "luma-510-dome-camera",
      "brand": "Snap One / Luma",
      "model": "Luma 510 Dome IP Camera",
      "model_number": "LUM-510-DOM-IP",
      "category": "security",
      "description": "4MP PoE IP dome camera, Starlight night vision, IP67 outdoor rated, OvrC, Control4 integration",
      "msrp": 250,
      "dealer_cost_estimate": 125,
      "labor_hours": 1.0,
      "rack_units": null,
      "power_draw_watts": 15,
      "connectivity": ["IP", "LAN_RJ45", "PoE"],
      "requires": ["luma-510-nvr"],
      "recommended_with": ["araknis-310-16-poe"],
      "room_types": ["outdoor", "garage", "wine_cellar"],
      "tier": "standard",
      "indoor_outdoor": "both",
      "discontinued": false,
      "notes": "PoE powered — single Cat6 run for power and video. 4MP = 2× resolution of 1080p. Starlight sensor for low-light color. IP67 for Vail outdoor environments."
    },

    {
      "component_id": "triad-inroom-gold-lcr",
      "brand": "Triad",
      "model": "InRoom Gold LCR",
      "model_number": "INROOM-GOLD-LCR",
      "category": "speaker",
      "subcategory": "on-wall",
      "description": "Three-way on-wall LCR speaker, dual 8.5\" woofers, 5.5\" midrange, 92dB sensitivity, premium MDF enclosure",
      "msrp": 3300,
      "dealer_cost_estimate": 1650,
      "labor_hours": 2.0,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": ["Analog_RCA"],
      "requires": [],
      "recommended_with": ["jbl-sdr-35", "jbl-sda-7120"],
      "room_types": ["theater"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Ultra-tier theater front stage. 50Hz–20kHz. 92dB sensitivity = easily driven. Acoustic suspension (sealed) for tight, accurate bass. Made in USA.",
      "data_sources": ["https://erinsaudiocorner.com/loudspeakers/triad_inroom_gold_lcr/"]
    },

    {
      "component_id": "triad-inwall-gold-surround",
      "brand": "Triad",
      "model": "InWall Gold Surround",
      "model_number": "INWALL-GOLD-SURROUND",
      "category": "speaker",
      "subcategory": "in-wall",
      "description": "Bipole in-wall surround speaker, compact design, premium drivers, wide dispersion for surround channels",
      "msrp": 2000,
      "dealer_cost_estimate": 1000,
      "labor_hours": 1.5,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": ["Analog_RCA"],
      "requires": [],
      "recommended_with": ["triad-inroom-gold-lcr", "jbl-sda-7120"],
      "room_types": ["theater"],
      "tier": "ultra",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Bipole design disperses surround information — enveloping sound without precise localization. Acoustiperf metal grille. Premium MDF enclosure.",
      "data_sources": ["https://new-age-electronics.com/triad-gold-series-in-wall-surround-speaker-46408-1000-1.html"]
    },

    {
      "component_id": "episode-es-ht-lc-6",
      "brand": "Episode",
      "model": "ES-HT-LCR-6",
      "model_number": "ES-HT-LCR-6",
      "category": "speaker",
      "subcategory": "in-wall",
      "description": "In-wall/in-ceiling LCR speaker for home theater, 6.5\" woofer, 1\" tweeter, 8Ω, budget-friendly architectural speaker",
      "msrp": 399,
      "dealer_cost_estimate": 200,
      "labor_hours": 1.0,
      "rack_units": null,
      "power_draw_watts": 0,
      "connectivity": ["Analog_RCA"],
      "requires": [],
      "recommended_with": ["sonos-amp", "control4-ea-3"],
      "room_types": ["theater", "living"],
      "tier": "standard",
      "indoor_outdoor": "indoor",
      "discontinued": false,
      "notes": "Good value entry for standard-tier theater. Swap up to JBL SCL-6 for premium tier. Pairs well with Sonos Amp for multi-room audio without separate receiver."
    }

  ]
}
```

---

## 7. Integration Points

### 7.1 REST API Endpoints

The System Design Graph exposes a REST API consumed by all Symphony AI systems:

```typescript
// api/routes/design-graph.ts

// ── Component Lookup ───────────────────────────────────────
GET /api/graph/component/:component_id
// Returns: Component object with all fields

GET /api/graph/components?category=speaker&tier=premium&room_type=theater
// Returns: Filtered component array

GET /api/graph/search?q=sonos+arc
// Returns: Full-text search results

// ── Compatibility ──────────────────────────────────────────
POST /api/graph/check-compatibility
// Body: { component_ids: string[] }
// Returns: { valid: boolean, violations: Rule[], warnings: Rule[] }

GET /api/graph/compatible-with/:component_id
// Returns: Components that pair well with given component

GET /api/graph/incompatible-with/:component_id
// Returns: Components that conflict with given component

// ── Room Templates ─────────────────────────────────────────
GET /api/graph/room-template/:room_type/:tier
// Example: GET /api/graph/room-template/theater/premium
// Returns: RoomTemplate object with component list

GET /api/graph/room-templates
// Returns: All templates as summary array

// ── BOM Generation ─────────────────────────────────────────
POST /api/graph/generate-bom
// Body: BOMRequest object
// Returns: BOMOutput object with line items, totals, violations

// ── Upgrade Paths ──────────────────────────────────────────
GET /api/graph/upgrade-path/:component_id
// Returns: Array of components that replace or succeed given component

GET /api/graph/replaces/:component_id
// Returns: Components that the given component upgrades from

// ── Network & Power ────────────────────────────────────────
POST /api/graph/calculate-power
// Body: { component_ids: string[], quantities: Record<string, number> }
// Returns: { total_watts, rack_units, poe_watts, circuit_count }

// ── Proposal Output ────────────────────────────────────────
POST /api/graph/generate-proposal-pdf
// Body: BOMRequest + proposal metadata
// Returns: { pdf_url: string }  (triggers PDF generation pipeline)
```

### 7.2 Mission Control Dashboard Integration

The Mission Control dashboard surfaces the graph via a compatibility checker widget:

```javascript
// dashboard/widgets/CompatibilityChecker.js

// Scenario: Tech is building a quote and adding components
async function checkDesign(selectedComponents) {
  const response = await fetch('/api/graph/check-compatibility', {
    method: 'POST',
    body: JSON.stringify({ component_ids: selectedComponents }),
    headers: { 'Content-Type': 'application/json' }
  });
  
  const result = await response.json();
  
  if (!result.valid) {
    // Show red banner: hard rule violations
    showViolations(result.violations);
  }
  
  if (result.warnings.length > 0) {
    // Show yellow banner: soft warnings
    showWarnings(result.warnings);
  }
  
  return result;
}

// Auto-complete component search
async function searchComponents(query) {
  const response = await fetch(`/api/graph/search?q=${encodeURIComponent(query)}`);
  return response.json();
}

// Generate BOM for proposal
async function generateBOM(rooms) {
  const request = {
    project_name: currentProject.name,
    client_name: currentProject.client,
    rooms: rooms.map(r => ({
      room_name: r.name,
      room_type: r.type,
      tier: r.tier
    }))
  };
  
  const response = await fetch('/api/graph/generate-bom', {
    method: 'POST',
    body: JSON.stringify(request),
    headers: { 'Content-Type': 'application/json' }
  });
  
  return response.json();
}
```

### 7.3 Voice Receptionist Integration

The Voice AI (receptionist) can answer questions about equipment requirements by querying the graph:

```python
# voice/handlers/equipment_query.py

SYSTEM_PROMPT_GRAPH_CONTEXT = """
You are Symphony Smart Homes' voice assistant. 
When asked about equipment needs, use the System Design Graph to give accurate answers.
Always mention brands Symphony carries: Control4, Lutron, Sonos, Sony, JBL Synthesis, 
Screen Innovations, Epson, Araknis Networks, Snap One.
"""

async def handle_equipment_query(user_query: str) -> str:
    """
    Called when voice agent receives a query like:
    'What do I need for a home theater?'
    'What projector would you recommend?'
    'Does the Sonos Arc work with Sony TVs?'
    """
    
    # Step 1: Classify query intent
    intent = classify_intent(user_query)
    
    if intent == "room_requirements":
        # "What do I need for a home theater?"
        room_type = extract_room_type(user_query)
        tier = extract_tier(user_query) or "premium"  # Default premium
        
        template = await fetch(f'/api/graph/room-template/{room_type}/{tier}')
        return format_room_requirements_response(template)
    
    elif intent == "product_recommendation":
        # "What projector would you recommend?"
        category = extract_category(user_query)
        components = await fetch(f'/api/graph/components?category={category}&tier=premium')
        return format_recommendation_response(components)
    
    elif intent == "compatibility_check":
        # "Does the Sonos Arc work with Sony TVs?"
        products = extract_product_mentions(user_query)
        component_ids = resolve_product_names_to_ids(products)
        result = await fetch('/api/graph/check-compatibility', 
                           method='POST', 
                           body={"component_ids": component_ids})
        return format_compatibility_response(result)
    
    elif intent == "pricing_inquiry":
        # "How much does a home theater cost?"
        tier = extract_tier(user_query) or "premium"
        # Route to sales — receptionist gives ranges, not exact quotes
        return f"Our {tier}-tier home theaters typically range from " \
               f"${TIER_PRICE_RANGES[tier]['min']:,} to ${TIER_PRICE_RANGES[tier]['max']:,} " \
               f"installed. I'll have Matt reach out to schedule a site visit for an exact quote."

TIER_PRICE_RANGES = {
    "standard":  {"min": 15000,  "max": 35000},
    "premium":   {"min": 50000,  "max": 100000},
    "ultra":     {"min": 120000, "max": 300000}
}
```

### 7.4 Client AI Concierge (Local Inference)

The on-site Client AI Concierge can answer equipment questions using a compressed version of the graph as context:

```python
# concierge/context_builder.py

def build_graph_context_for_llm(
    max_tokens: int = 4000,
    categories: list[str] = None,
    tiers: list[str] = None
) -> str:
    """
    Builds a compressed text representation of the component database
    suitable for injection into an LLM system prompt.
    
    Used by the local Client AI Concierge to answer product questions
    without making API calls.
    """
    
    components = load_components(categories=categories, tiers=tiers)
    
    lines = [
        "## Symphony Smart Homes — Product Database Summary\n",
        "Brand partners: Control4, Lutron, Sonos, Sony, JBL Synthesis, ",
        "Screen Innovations, Epson, Araknis Networks, Snap One/Luma\n\n",
        "### Key Products by Category\n"
    ]
    
    by_category = group_by_category(components)
    
    for category, items in by_category.items():
        lines.append(f"\n**{category.upper()}**\n")
        for item in items[:5]:  # Top 5 per category for token budget
            lines.append(
                f"- {item.brand} {item.model} (${item.msrp:,} MSRP): "
                f"{item.description[:100]}. "
                f"Tier: {item.tier}. "
                f"Rooms: {', '.join(item.room_types[:3])}.\n"
            )
    
    lines.append("\n### Common Compatibility Rules\n")
    for rule in load_rules(severity="hard")[:10]:
        lines.append(f"- {rule.name}: {rule.message}\n")
    
    return "".join(lines)
```

### 7.5 Proposal Generation Pipeline

```python
# proposals/generator.py

async def generate_client_proposal(bom_request: BOMRequest, 
                                   template: str = "symphony_standard") -> ProposalOutput:
    """
    Full proposal generation pipeline:
    1. Generate BOM from graph
    2. Apply company branding and formatting
    3. Produce PDF for client delivery
    """
    
    # Step 1: Generate BOM
    bom = await generate_bom(bom_request)
    
    # Step 2: Check for hard violations — don't generate proposal with errors
    if bom.violations:
        raise DesignViolationError(
            f"Cannot generate proposal: {len(bom.violations)} hard rule violations. "
            f"Resolve: {[v.rule_id for v in bom.violations]}"
        )
    
    # Step 3: Format line items for client-facing proposal
    # (hide dealer costs, show client prices only)
    client_line_items = [
        {
            "description": f"{item.brand} {item.model}",
            "quantity": item.quantity,
            "unit_price": item.unit_dealer_cost / (1 - TARGET_MARGIN),
            "extended_price": item.extended_dealer_cost / (1 - TARGET_MARGIN),
            "rooms": item.rooms,
            "notes": get_client_facing_notes(item.component_id)
        }
        for item in bom.line_items
    ]
    
    # Step 4: Assemble proposal document
    proposal = ProposalDocument(
        company="Symphony Smart Homes",
        client_name=bom_request.client_name,
        project_name=bom_request.project_name,
        date=datetime.now().strftime("%B %d, %Y"),
        prepared_by="Matt Earley",
        line_items=client_line_items,
        labor_total=bom.summary["total_labor_cost"],
        programming_total=bom.summary["programming_cost"],
        equipment_total=bom.summary["equipment_sell_price"],
        grand_total=bom.summary["total_project_price"],
        notes=bom.warnings,  # Surface soft warnings as client-facing notes
        template=template
    )
    
    # Step 5: Render PDF
    pdf_url = await render_proposal_pdf(proposal)
    
    return ProposalOutput(
        proposal=proposal,
        bom=bom,
        pdf_url=pdf_url
    )

TARGET_MARGIN = 0.45  # 45% equipment margin
```

### 7.6 Graph Maintenance Workflow

```markdown
## Keeping the Graph Current

**Monthly tasks (Matt or admin):**
1. Check for discontinued products — set `discontinued: true` in component JSON
2. Update MSRP for products with known price changes (Sony, Lutron announce annually)
3. Review new product launches from Control4, Lutron, Sonos — add new components

**Quarterly tasks:**
1. Review room templates against actual projects — are BOM estimates accurate?
2. Update `labor_hours` estimates based on real project data
3. Add new validation rules discovered from field problems
4. Update `dealer_cost_estimate` fields based on current Snap One pricing

**Annual tasks:**
1. Full product line review with Snap One rep
2. Retire discontinued products (move to archive, update `replaced_by` field)
3. Review tier definitions against market pricing

**Adding a new component:**
```json
{
  "component_id": "brand-model-slug",  // Lowercase, hyphens
  "brand": "Brand Name",
  "model": "Model Number",
  "model_number": "MFR-SKU",
  "category": "speaker",
  "description": "...",
  "msrp": 0,           // Required — use manufacturer published MSRP
  "dealer_cost_estimate": 0,  // Estimate at 45-50% off MSRP
  "labor_hours": 0,    // Estimate conservatively
  "rack_units": null,  // Only if rack-mountable
  "power_draw_watts": 0,
  "connectivity": [],
  "requires": [],
  "recommended_with": [],
  "room_types": [],
  "tier": "standard",
  "indoor_outdoor": "indoor",
  "discontinued": false,
  "notes": "",
  "data_sources": ["URL to manufacturer spec sheet"],
  "updated_at": "YYYY-MM-DD"
}
```
```

---

## 8. Implementation Roadmap

### Phase 1 — Foundation (Weeks 1–2)
- [ ] Set up component database as JSON flat files in `/data/components/`
- [ ] Load seed data (all 35 components above)
- [ ] Build basic REST API: `GET /component/:id`, `GET /components`, `GET /search`
- [ ] Implement `POST /check-compatibility` with hard rules engine
- [ ] Write unit tests for all hard rules

### Phase 2 — Room Templates & BOM (Weeks 3–4)
- [ ] Load room template JSON files into `/data/templates/`
- [ ] Implement `GET /room-template/:type/:tier`
- [ ] Implement `POST /generate-bom` with full deduplication + markup logic
- [ ] Add labor hour calculation to BOM output
- [ ] Build BOM output formatter (JSON → PDF via Puppeteer or WeasyPrint)

### Phase 3 — Integrations (Weeks 5–6)
- [ ] Connect to Mission Control dashboard — compatibility checker widget
- [ ] Provide Voice Receptionist with graph context in system prompt
- [ ] Build `build_graph_context_for_llm()` function for Client Concierge
- [ ] Connect proposal generator to BOM output

### Phase 4 — Operations (Ongoing)
- [ ] Add remaining components (full Symphony catalog)
- [ ] Refine labor hour estimates from real project data
- [ ] Add soft rules based on field experience
- [ ] Train new techs using the compatibility checker as a learning tool

### Key File Structure

```
/data/
  components/
    control4.json
    lutron.json
    sonos.json
    sony.json
    jbl-synthesis.json
    screen-innovations.json
    epson.json
    araknis.json
    snap-one.json
    triad.json
    episode.json
  templates/
    home-theater.json
    living-room.json
    bedroom.json
    outdoor.json
    office.json
    wine-cellar.json
  rules/
    hard-rules.json
    soft-rules.json
    power-rules.json
    network-rules.json
    distance-rules.json

/api/
  routes/
    design-graph.ts
  services/
    bom-generator.ts
    rules-engine.ts
    component-lookup.ts
  types/
    component.ts
    rule.ts
    bom.ts
    room-template.ts

/proposals/
  generator.py
  templates/
    symphony_standard.html
    symphony_premium.html
```

---

## Appendix A: Tier Definitions

| Tier | Client Budget | Typical Scope | Brands |
|------|-------------|--------------|--------|
| **Standard** | $10K–$40K | 1–3 room system, Caseta lighting, Sonos audio, single-zone Control4 | Control4 EA-1/EA-3, Lutron Caseta, Sonos, Epson LS12000, Episode speakers |
| **Premium** | $40K–$120K | Whole-home system, RadioRA 3, Sony projector or OLED TV, JBL Synthesis, architectural speakers | Control4 EA-5, Lutron RadioRA 3, Sony VPL-XW5000ES, JBL SDR-35/SDA-7120, SCL speakers, SI Black Diamond |
| **Ultra** | $120K+ | Dedicated theater, HomeWorks QSX, Sony VPL-XW7000ES, Triad full system, full-home integration | Control4 EA-5, Lutron HomeWorks QSX, Sony VPL-XW7000ES, Triad Gold series, dual JBL SDA-7120, Araknis 710 |

## Appendix B: Symphony Brand Partner Summary

| Brand | Category | Tier | Notes |
|-------|---------|------|-------|
| Control4 | Automation | All | Snap One dealer required |
| Lutron | Lighting/Shading | All | Caseta = standard, RadioRA 3 = premium, HW QSX = ultra |
| Sonos | Streaming/Audio | Standard-Premium | Consumer brand, strong Control4 integration |
| Sony | Displays/Projectors | Premium-Ultra | BRAVIA TV line + VPL-XW projectors |
| JBL Synthesis | AV Electronics/Speakers | Premium-Ultra | SDR-35 AVR + SDA-7120 amp + SCL speakers |
| Epson | Projectors | Standard | LS12000 = best value 4K laser with HDMI 2.1 |
| Screen Innovations | Screens/Shading | All | Zero Edge = standard, Black Diamond = premium/ultra, Solo = all tiers |
| Araknis Networks | Networking | All | 110 = unmanaged, 310 = managed, 710 = ultra |
| Snap One (OvrC) | Platform/Power | All | WattBox PDU, Luma cameras, OvrC cloud management |
| Triad | Speakers | Ultra | Made in USA, ultra-tier theater and living room |
| Episode | Speakers | Standard | Budget architectural speakers, good value |

## Appendix C: Common Upgrade Paths

```
Control4 EA-1 → EA-3 → EA-5
Lutron Caseta → RadioRA 3 → HomeWorks QSX
Sonos Era 100 → Era 300 → Architectural speakers
Epson LS12000 → Sony VPL-XW5000ES → Sony VPL-XW7000ES
Sony X90L TV → Sony A95L OLED
Araknis 310-8 → 310-16 → 310-24 → 710-24
SI Zero Edge → SI Black Diamond → SI Black Diamond XL
Episode speakers → JBL SCL series → Triad Gold series
```

---

*Document generated for Symphony Smart Homes — symphonysh.com — Vail/Eagle County, Colorado*  
*This specification is intended for implementation in the Symphony AI-Server codebase.*  
*Pricing data sourced from manufacturer websites, authorized dealer listings, and CEDIA channel publications.*  
*Sources: [Sony Electronics](https://electronics.sony.com), [Sonos](https://www.sonos.com), [Snap One](https://www.snapav.com), [Lutron](https://assets.lutron.com), [JBL Synthesis](https://www.jblsynthesis.com), [Screen Innovations](https://www.screeninnovations.com), [Projector Reviews](https://www.projectorreviews.com), [Audio Advice](https://www.audioadvice.com), [Erin's Audio Corner](https://erinsaudiocorner.com)*
