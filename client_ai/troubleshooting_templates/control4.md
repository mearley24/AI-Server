# Control4 Troubleshooting

## Common Issues

### All Touch-Screens / App Unresponsive
1. Check the Control4 controller (HC-800, EA-5, or CA-10) LED:
   - **Solid green**: normal.
   - **Blinking green**: booting — wait 2 minutes.
   - **Red or amber**: fault — reboot required.
2. Unplug the controller's power adapter, wait 20 seconds, plug back in.
3. Allow up to 3 minutes for the controller to fully reboot and reconnect all devices.
4. Force-quit and relaunch the Control4 app on your phone.

### One Touch-Screen Not Responding
1. On the touch-screen, hold the power button for 8 seconds to force a reboot.
2. If the screen is blank: check the PoE injector or PoE switch port powering that screen.
3. If the screen shows a "Connecting…" message for more than 2 minutes, the screen has lost its network connection — check the Ethernet cable or Wi-Fi signal.

### Lights / Devices Not Responding via App
1. Verify the device is responding to its physical button or switch — if yes, it's a Control4 communication issue, not a hardware fault.
2. Refresh the Control4 app (pull down to refresh on mobile).
3. Check that your phone is on the same network as the Control4 system (home Wi-Fi, not cellular).

### Scenes or Automations Not Triggering
1. Open Control4 app → When → find the scene → confirm it is enabled (not paused).
2. Check for a "Director communication lost" error in the app — if present, the controller needs a reboot.
3. For time-based automations: confirm the controller has the correct time zone (visible in Composer settings).

---

## Escalation Criteria

Schedule a technician if:
- The controller reboots successfully but devices still don't respond.
- An error code appears on the controller LED that is not blinking green.
- Programming changes are needed (adding/removing devices, changing scenes).
