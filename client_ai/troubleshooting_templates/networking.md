# Networking Troubleshooting

## Common Issues

### Internet Completely Down
1. Check the modem LED status:
   - All solid: modem is fine — issue may be with the router or ISP.
   - Flashing DS/US (Downstream/Upstream) lights: modem is trying to sync — ISP outage likely.
2. Check your ISP's outage page or app to confirm service status.
3. Power-cycle sequence (order matters):
   a. Unplug the **modem** — wait 30 seconds.
   b. Plug the modem back in — wait 60 seconds for it to fully sync.
   c. Power-cycle the **router/firewall** — wait 30 seconds.
   d. Allow 2 minutes for all devices to reconnect.

### Slow Wi-Fi in Certain Rooms
1. Check which access point the device is connected to in the Araknis or UniFi app — it may be connected to a distant AP.
2. Force the device to disconnect and reconnect to Wi-Fi — it will re-associate to the nearest AP.
3. Check for interference: microwave ovens, baby monitors, and neighbouring Wi-Fi networks can impact 2.4 GHz performance. Try switching the device to 5 GHz.

### Device Can't Connect to Wi-Fi
1. Confirm the correct network name (SSID) and password are being used.
2. Check if other devices can connect — if yes, the issue is specific to that device.
3. On the affected device: forget the network and reconnect from scratch.
4. Check for MAC address filtering in the Araknis or UniFi controller — the device's MAC address may need to be added.

### Araknis / UniFi Controller Offline
1. The controller (typically a small cloud-key or NUC) needs a reboot.
2. Locate it in the AV rack — power-cycle it.
3. Note: rebooting the controller does **not** affect the access points or switches; Wi-Fi will remain active during controller downtime.

---

## Escalation Criteria

Schedule a technician if:
- Internet remains down after full power-cycle and ISP confirms no outage.
- Multiple access points go offline simultaneously.
- Slow speeds persist despite strong Wi-Fi signal (may indicate ISP speed degradation or switch issue).
- A wired device cannot get a DHCP address (possible switch or VLAN issue).
