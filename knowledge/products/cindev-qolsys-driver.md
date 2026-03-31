---
name: "Cindev Qolsys Security Driver for Control4"
sku: "CINDEV-QOLSYS"
vendor: "Cindev (DriverCentral)"
msrp: "$199.99"
category: "Integration Drivers"
d_tools_id: ""
in_d_tools: false
notes: "Software driver — purchased through DriverCentral. Not a physical product. Requires OS 3.3+ and X4.0."
---

# Cindev Qolsys Security Driver for Control4

## Overview
A third-party Control4 driver that provides native integration between the Qolsys IQ Panel 4 security system and Control4. Enables security status visibility, arming/disarming, zone reporting, and alarm notifications within the Control4 interface. Communication is entirely local (no cloud dependency).

## Specs
- Compatibility: Control4 OS 3.3+, Qolsys X4.0
- Communication: Local network (SDDP auto-discovery on same VLAN)
- Partitions: Up to 8
- Features: Arm/disarm, alarm status, zone reporting, zone bypass, user management, custom zone events, auto-add common zone drivers
- Cloud: None required — local communication only
- Purchase: DriverCentral marketplace
- Version: 20250904

## Symphony Usage
Used on any project integrating a Qolsys IQ Panel 4 with Control4. Installed during the programming phase after the security panel is online and on the designated Security VLAN (VLAN 40). SDDP auto-discovery handles panel detection. On the Topletz project, this enables security status on Control4 keypads, iPads, and the C4 app — arming from a bedside keypad, door/window zone alerts, and alarm notifications.
