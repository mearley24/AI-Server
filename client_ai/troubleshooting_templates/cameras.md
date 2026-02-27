# Camera System Troubleshooting

## Common Issues

### All Cameras Offline
1. Locate the PoE (Power over Ethernet) switch in your AV rack — it is typically a grey or black box with many Ethernet ports.
2. Power-cycle the PoE switch: unplug the power cable, wait 20 seconds, plug back in.
3. Allow 2–3 minutes for all cameras to reconnect.
4. If cameras are still offline, power-cycle the NVR (Network Video Recorder) as well.

### One or Several Cameras Offline
1. Check the camera's LED indicator:
   - **Solid green**: camera is powered and connected.
   - **Solid amber/red**: powered but network issue.
   - **No LED**: no power.
2. For amber/red LED: re-seat the Ethernet cable at both the camera and the PoE switch port.
3. For no LED: check the PoE switch port for that camera — if the port LED is active but the camera is dark, the camera may have failed.

### Poor Image Quality
1. Clean the camera lens with a soft, dry cloth.
2. Check for IR reflections at night — remove any objects too close to the camera.
3. In the camera app, check resolution settings — ensure the stream is set to the maximum available resolution.

### Motion Alerts Not Arriving
1. Open the camera app (Luma, Axis, or Hikvision) and verify push notifications are enabled.
2. Check the motion detection zones in the app — zones may have been accidentally cleared.
3. Ensure the app has notification permissions in your phone's Settings.

---

## Escalation Criteria

Schedule a technician if:
- A camera shows no LED and is confirmed powered from the PoE switch.
- Image quality is degraded and cleaning / settings changes don't help.
- Cameras are rebooting repeatedly (check NVR event log).
