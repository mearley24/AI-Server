# Gates Equipment Roll-Up

Source schedule: `knowledge/proposals/Gates_Room_Device_Schedule.txt`

## Device Totals

- Keypad: 21
- TV: 4
- CH1 speaker: 20
- CH5 speaker: 2
- Center channel: 1
- Subwoofer: 1
- Shade: 16
- Access point drop: 3
- Dome camera: 4
- Doorbell camera: 1
- Lighting panel: 1
- Shade power: 1

## Rack/Core Checklist

- Control processor: 1 (Control4 family, exact SKU pending)
- Primary network switch: 1 (include hardwired TVs, APs, NVR uplink, Sonos/control endpoints)
- Router/firewall: 1
- NVR: 1 (cameras should land on NVR PoE per standard)
- Wireless access points: 3 (from room schedule drops)
- Audio distribution / amp channels: size for at least 24 speaker loads + theater 5.x layout
- Lighting + shade infrastructure: 1 lighting panel + shade power hub path confirmed
- UPS/power conditioning: 1 rack-level power plan

## Notes

- Camera count supports a dedicated surveillance VLAN path in final shell.
- Shade count is high (16); verify PoE/power injector strategy before final BOM lock.
