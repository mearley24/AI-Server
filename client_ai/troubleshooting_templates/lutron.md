# Lutron Lighting Troubleshooting

## Common Issues

### All Dimmers Unresponsive
1. Locate the Lutron hub (LEAP Bridge, RadioRA2 main repeater, or RadioRA3 processor) in your AV rack or electrical panel.
2. Power-cycle the hub: unplug, wait 20 seconds, plug back in.
3. Allow 2 minutes for all dimmers to reconnect.
4. If the Lutron app shows "Hub not found": check the hub's Ethernet cable and network connection.

### Specific Dimmer Unresponsive
1. Check the dimmer LED:
   - **Solid amber**: normal standby.
   - **Rapidly blinking**: fault or pairing issue.
   - **No LED**: no power — check the circuit breaker for that room.
2. Try pressing the dimmer's top button 3 times rapidly — this is a soft reset that can restore communication.
3. If the dimmer blinks rapidly: hold the top and bottom buttons simultaneously for 6 seconds (factory reset). Note: this will un-pair the dimmer and require re-pairing by a technician.

### Dimmer Turns On But Won't Dim
1. Ensure the bulbs in the fixture are dimmable LED — non-dimmable LEDs will not dim and may buzz.
2. Check the minimum dim level setting in the Lutron app (Settings → Devices → select dimmer → Low End).
3. If buzzing occurs: the dimmer may need a different "fade" setting — a technician can adjust this in Lutron Composer.

### Schedules Not Triggering
1. Open the Lutron app → Automations — confirm the schedule is active (not paused).
2. Check that the Lutron hub has the correct time (visible in app Settings → Hub → Time).
3. Ensure your phone's Lutron app is up to date — outdated apps can fail to sync schedules.

---

## Escalation Criteria

Schedule a technician if:
- A dimmer has been factory-reset and needs re-pairing.
- Multiple dimmers lose communication after the hub reboot.
- A circuit breaker has tripped and won't reset.
- New fixtures or dimmers need to be added to the system.
