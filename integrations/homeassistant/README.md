# Symphony Smart Homes — Home Assistant Integration

> **Bob the Conductor × Home Assistant**
> Giving Bob physical-world awareness through the Raspberry Pi smart home hub.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LOCAL NETWORK (192.168.x.x)                      │
│                                                                       │
│  ┌─────────────────────┐         ┌──────────────────────────────┐    │
│  │   Bob (Mac Mini M4) │         │  Raspberry Pi (smartassistant│    │
│  │   OpenClaw Multi-   │◄───────►│  -ai)                        │    │
│  │   Agent Framework   │  HTTP   │                              │    │
│  │                     │  WS     │  ┌──────────────────────┐   │    │
│  │  ┌───────────────┐  │  MQTT   │  │  Home Assistant      │   │    │
│  │  │ ha_bridge.py  │◄─┼─────────┼─►│  :8123               │   │    │
│  │  │ (HAClient)    │  │         │  │  REST + WebSocket     │   │    │
│  │  └───────────────┘  │         │  └──────────────────────┘   │    │
│  │  ┌───────────────┐  │         │  ┌──────────────────────┐   │    │
│  │  │ha_mqtt_agent  │◄─┼─────────┼─►│  Mosquitto MQTT      │   │    │
│  │  │.py            │  │  MQTT   │  │  Broker :1883        │   │    │
│  │  └───────────────┘  │         │  └──────────────────────┘   │    │
│  │  ┌───────────────┐  │         │  ┌──────────────────────┐   │    │
│  │  │ha_camera_     │◄─┼─────────┼─►│  Luma Cameras        │   │    │
│  │  │monitor.py     │  │  HTTP   │  │  (via HA proxy)      │   │    │
│  │  └───────────────┘  │         │  └──────────────────────┘   │    │
│  │  ┌───────────────┐  │         └──────────────────────────────┘    │
│  │  │ha_device_     │  │                                             │
│  │  │registry.py    │  │  ┌────────────────────────────────────┐    │
│  │  └───────────────┘  │  │  iMac Workers (OpenClaw agents)    │    │
│  │  ┌───────────────┐  │  │  • Security agent                  │    │
│  │  │ha_automations │  │  │  • Presence agent                  │    │
│  │  │.py            │  │  │  • AV control agent                │    │
│  │  └───────────────┘  │  │  • Network monitoring agent        │    │
│  └─────────────────────┘  └────────────────────────────────────┘    │
│                                                                       │
│  ──  Control4  ──  Lutron  ──  Araknis  ──  Sonos  ──  Luma NVR  ── │
└──────────────────────────────────────────────────────────────────────┘
```

### Communication Paths

| Path | Protocol | Purpose |
|------|----------|---------|
| Bob → Home Assistant | HTTP REST | Get states, call services, history, templates |
| Bob ↔ Home Assistant | WebSocket (`ws://PI_IP:8123/api/websocket`) | Real-time state_changed events |
| Bob ↔ Mosquitto | MQTT TCP | Vendor device events, Bob's heartbeat, commands |
| Bob → HA Camera Proxy | HTTP GET | Live camera snapshots, MJPEG streams |
| HA → Vendor Devices | HA integrations | Control4, Lutron, Sonos, Luma via native integrations |

---

## What Bob Can Do

### 1. Device Control (via `ha_bridge.py`)
```python
from ha_bridge import HAClient

async with HAClient.from_env() as ha:
    # Turn on living room lights at 70% warm white
    await ha.call_service("light", "turn_on", {
        "entity_id": "light.living_room",
        "brightness_pct": 70,
        "color_temp_kelvin": 3000,
    })

    # Lock all doors
    await ha.call_service("lock", "lock", {
        "entity_id": ["lock.front_door", "lock.back_door", "lock.garage"]
    })

    # Activate a scene
    await ha.call_service("scene", "turn_on", {
        "entity_id": "scene.welcome_home"
    })
```

### 2. Real-Time State Awareness
```python
# Get the current state of any entity
state = await ha.get_state("sensor.living_room_temperature")
print(f"Temperature: {state.state}°F")

# Get everything at once
all_states = await ha.get_states()
lights_on = [s for s in all_states if s.domain == "light" and s.state == "on"]
```

### 3. Camera Feeds (Luma via HA Proxy)
```python
from ha_camera_monitor import CameraMonitor

monitor = CameraMonitor(ha_client)
await monitor.start()

# Get a live snapshot (returns bytes, save as JPEG)
image_bytes = await ha.get_camera_snapshot("camera.luma_front_door")

# Get as base64 for vision model
b64_image = await ha.get_camera_snapshot_b64("camera.luma_front_door")

# Pass to GPT-4 Vision / Claude Vision
result = await vision_model.analyze(image=b64_image, prompt="Describe what you see")

# Get stream URL for continuous monitoring
stream_info = await monitor.get_stream_info("camera.luma_driveway")
print(stream_info["rtsp_url"])   # RTSP for NVR-quality stream
print(stream_info["mjpeg_url"])  # MJPEG for quick preview
```

### 4. MQTT Messaging (All Vendor Devices)
```python
from ha_mqtt_agent import MQTTAgent

agent = MQTTAgent.from_env()

# Register handler for Control4 events
async def handle_c4_event(msg, workflow):
    print(f"Control4: {msg.topic} → {msg.payload}")

await agent.add_subscription("control4/+/event", handle_c4_event)
await agent.start()

# Publish a command to any device
await agent.publish("lutron/master_bedroom_dimmer/set", {
    "level": 50,
    "fade_time": 2000
})
```

### 5. Automation Management
```python
from ha_automations import AutomationManager

manager = AutomationManager(ha_client)

# Create from natural language
auto_id = await manager.create_from_nl(
    "When client arrives home, turn on welcome scene"
)

# Create from Symphony template with custom variables
auto_id = await manager.create_from_template("morning_routine", variables={
    "wake_time": "06:30:00",
    "light_entities": ["light.master_bedroom", "light.hallway"],
    "shade_entities": ["cover.master_bedroom_shade"],
    "final_brightness": "90",
    "transition_minutes": "30",
})

# Trigger manually
await manager.trigger_automation(auto_id)

# Roll back if something goes wrong
await manager.rollback(auto_id)
```

### 6. Device Registry & Topology
```python
from ha_device_registry import DeviceRegistry

registry = DeviceRegistry(ha_client)
await registry.start()

# Find all Lutron devices in the master bedroom
bedroom_lights = registry.get_by_room("Master Bedroom")

# Get all cameras
cameras = registry.get_cameras()

# Full system topology report
topology = registry.generate_topology_report()
print(registry.generate_ascii_topology())

# Find entity by friendly name
entity_id = registry.friendly_to_entity("Front Door Lock")
```

### 7. History & Logbook
```python
from datetime import datetime, timedelta, timezone

# What did the front door do in the last 24 hours?
history = await ha.get_history("lock.front_door")

# Human-readable activity log
logbook = await ha.get_logbook(hours=48)
for entry in logbook:
    print(f"{entry['when']}: {entry['name']} — {entry['message']}")
```

### 8. Template Rendering
```python
# Count how many lights are currently on
lights_on = await ha.render_template(
    "{{ states.light | selectattr('state', 'eq', 'on') | list | count }}"
)

# Get formatted time
now_str = await ha.render_template(
    "{{ now().strftime('%A, %B %d at %I:%M %p') }}"
)
```

---

## Setup Prerequisites

### On the Raspberry Pi

1. **Home Assistant** running (Raspberry Pi OS or HassOS)
2. **Long-Lived Access Token** — generate at:
   `HA Profile → Long-lived access tokens → Create Token`
   Name it `bob-conductor` for easy identification.
3. **Mosquitto MQTT** add-on installed and running:
   - HA Settings → Add-ons → Mosquitto broker
   - Create credentials in the add-on configuration
4. **Static IP address** for the Pi (strongly recommended):
   - Set via your router's DHCP reservation
   - Or configure in HA: Settings → System → Network
5. **Camera entities** configured in Home Assistant (Luma integration or ONVIF)

### On Bob (Mac Mini M4)

```bash
# Install Python dependencies
pip install aiohttp asyncio-mqtt paho-mqtt python-dotenv

# Clone/copy the integration
cd /path/to/bob/integrations

# Configure environment
cp .env.example .env
nano .env  # Fill in PI_IP, HA_TOKEN, MQTT_PASSWORD
```

---

## Installation

```bash
# 1. Navigate to integration directory
cd /path/to/homeassistant_integration

# 2. Configure environment variables
cp .env.example .env
# Edit .env with your Pi's IP, HA token, and MQTT credentials

# 3. Run setup and smoke test
./setup_ha_integration.sh

# 4. Start with Docker (recommended for production)
docker compose -f docker-compose.ha.yml up -d

# Or run directly (development)
python ha_bridge.py        # Tests connectivity
python ha_mqtt_agent.py    # Runs MQTT agent
```

---

## File Reference

| File | Purpose |
|------|---------|
| `ha_bridge.py` | Core HAClient — REST + WebSocket, all HA methods |
| `ha_mqtt_agent.py` | MQTT agent — subscribes to all vendor topics, dispatches to OpenClaw |
| `ha_camera_monitor.py` | Camera polling, motion detection, snapshot management |
| `ha_automations.py` | Automation CRUD with Symphony templates and NL interface |
| `ha_device_registry.py` | Vendor-aware entity discovery and topology reporting |
| `openclaw_ha_tool.json` | OpenClaw tool definition (schema for all actions) |
| `ha_config.json` | Full configuration (MQTT topics, safety rules, room mappings) |
| `docker-compose.ha.yml` | Docker Compose overlay for the integration services |
| `setup_ha_integration.sh` | Installation, connectivity verification, and smoke test |
| `.env.example` | Environment variables template |

---

## API Reference — `ha_bridge.HAClient`

### States

| Method | Description |
|--------|-------------|
| `get_states()` | All entity states (cached 5s) |
| `get_state(entity_id)` | Single entity state (cached 5s, updates via WebSocket) |
| `set_state(entity_id, state, attributes)` | Set state directly (virtual/helper entities) |

### Services

| Method | Description |
|--------|-------------|
| `call_service(domain, service, data)` | Call any HA service |

### Cameras

| Method | Description |
|--------|-------------|
| `get_camera_snapshot(camera_entity)` | Returns raw JPEG bytes |
| `get_camera_snapshot_b64(camera_entity)` | Returns base64-encoded JPEG string |
| `get_camera_stream_url(camera_entity)` | Returns RTSP/stream URL |
| `get_camera_video_url(camera_entity)` | Returns HLS/MJPEG URL via HA proxy |

### Events

| Method | Description |
|--------|-------------|
| `subscribe_events(callback)` | Register callback for all HA events via WebSocket |

### MQTT

| Method | Description |
|--------|-------------|
| `publish_mqtt(topic, payload, retain, qos)` | Publish via HA's mqtt.publish service |
| `subscribe_mqtt(topic, callback)` | Subscribe via HA event bus |

### History & Logs

| Method | Description |
|--------|-------------|
| `get_history(entity_id, start, end)` | Historical state data |
| `get_logbook(entity_id, hours)` | Human-readable activity log |

### Templates & Config

| Method | Description |
|--------|-------------|
| `render_template(template_str)` | Render Jinja2 template |
| `get_config()` | HA configuration |
| `get_services()` | Available services by domain |
| `ping()` | Connectivity check |

### Automations

| Method | Description |
|--------|-------------|
| `create_automation(config)` | Create from raw config dict |
| `list_automations()` | All automation entries |
| `update_automation(id, config)` | Update existing automation |
| `delete_automation(id)` | Delete automation |
| `trigger_automation(id)` | Manually trigger |

---

## Symphony Automation Templates

Bob can create Home Assistant automations from these built-in templates:

| Template Name | Description | Key Variables |
|---------------|-------------|---------------|
| `welcome_scene` | Activate scene when resident arrives home | `person_entity`, `scene_entity` |
| `night_motion_alert` | Alert + record on camera motion after hours | `camera_entity`, `motion_sensor`, `start_time` |
| `network_device_offline` | MQTT alert when Araknis device goes offline | `device_entity`, `device_name` |
| `morning_routine` | Gradual light ramp + shade open on schedule | `wake_time`, `light_entities`, `final_brightness` |
| `av_scene_trigger` | AV scene + Sonos from keypad button | `trigger_entity`, `scene_entity`, `sonos_playlist` |
| `security_arm_departure` | Arm alarm + lock doors when all leave | `person_entities`, `alarm_entity`, `lock_entities` |
| `bob_command_relay` | Relay Bob's MQTT commands to HA actions | `mqtt_topic` |

---

## MQTT Topic Reference

### Bob Subscribes To

| Topic | Vendor | Event |
|-------|--------|-------|
| `homeassistant/#` | Home Assistant | All HA MQTT discovery and state |
| `luma/+/status` | Luma | Camera online/offline status |
| `luma/+/motion` | Luma | Motion detection events |
| `luma/+/recording` | Luma | Recording start/stop |
| `control4/+/event` | Control4 | Driver events (arrival, scene, etc.) |
| `control4/+/status` | Control4 | Device status updates |
| `lutron/+/state` | Lutron | Switch/dimmer/shade state changes |
| `lutron/+/event` | Lutron | Keypad button presses |
| `araknis/+/status` | Araknis | Network device status |
| `araknis/+/alert` | Araknis | Network alerts |
| `sonos/+/state` | Sonos | Player state (playing, paused, etc.) |
| `snapone/+/status` | Snap One | AV equipment status |
| `symphony/bob/commands` | Internal | Commands directed at Bob (QoS 1) |

### Bob Publishes To

| Topic | Frequency | Content |
|-------|-----------|---------|
| `symphony/bob/heartbeat` | Every 60s | Status, uptime, message count |
| `symphony/bob/status` | On change | Online/offline, current state |
| `symphony/bob/responses` | On demand | Responses to symphony/+/request |

---

## OpenClaw Integration

Add the `home_assistant` tool to your OpenClaw agent:

```python
# In your OpenClaw agent definition
tools = [
    "home_assistant",  # registered from openclaw_ha_tool.json
    # ... other tools
]

# Example agent usage
result = await call_tool("home_assistant", {
    "action": "get_state",
    "entity_id": "lock.front_door"
})

result = await call_tool("home_assistant", {
    "action": "camera_snapshot",
    "camera_entity": "camera.luma_front_door",
    "return_format": "base64"
})

result = await call_tool("home_assistant", {
    "action": "call_service",
    "domain": "scene",
    "service": "turn_on",
    "data": {"entity_id": "scene.welcome_home"}
})
```

---

## Security Considerations

### Actions Requiring Owner Approval
These services are **blocked** unless the owner explicitly confirms:
- `alarm_control_panel.disarm` — disarming the security system
- `alarm_control_panel.arm_away` / `arm_home` — changing alarm state
- `lock.unlock` — unlocking any door
- `homeassistant.restart` — restarting the HA instance

### Network Security
- The integration communicates **only on the local network** — no external services
- HA Long-Lived Access Token should have **minimum necessary scope**
- MQTT credentials should be unique to Bob (separate from HA's own MQTT user)
- Consider enabling TLS for MQTT (port 8883) in production

### Camera Data
- Snapshot data (base64 images) is **never written to agent logs**
- Motion-triggered snapshots are stored locally on Bob with configurable retention (default 30 days)
- Camera images should not be transmitted outside the local network without explicit owner consent

### Audit Trail
- All `call_service` invocations are logged with entity_id, service, and timestamp
- HA's own logbook provides an independent audit trail
- MQTT message history buffer retains the last 1000 messages in memory

---

## Troubleshooting

### "Cannot reach Home Assistant"
```bash
# Test connectivity manually
curl -H "Authorization: Bearer YOUR_TOKEN" http://PI_IP:8123/api/
# Expected: {"message":"API running."}
```

### "MQTT connection refused"
```bash
# Test MQTT without credentials (if broker allows)
mosquitto_pub -h PI_IP -p 1883 -t "test/ping" -m "hello"

# If using auth:
mosquitto_pub -h PI_IP -p 1883 -u homeassistant -P YOUR_PASSWORD -t "test/ping" -m "hello"
```

### "WebSocket disconnects frequently"
- Check HA logs for `websocket` errors
- Ensure the Pi isn't CPU-throttling (check `top` on Pi)
- Increase `WS_RECONNECT_DELAY` in `ha_bridge.py` if the Pi is under load

### "No camera entities found"
- Verify the Luma integration is installed in HA
- Check HA Settings → Integrations → confirm camera entities exist
- Run `./setup_ha_integration.sh` to re-discover entities

### "Rate limiting errors"
- The Pi's CPU is limited — don't exceed 10 REST requests/second
- Increase `DEFAULT_CACHE_TTL` in `ha_bridge.py` to reduce API calls
- Use the WebSocket event stream instead of polling for state changes

---

## Development Notes

### Adding a New Vendor

1. Add vendor signatures to `VENDOR_SIGNATURES` in `ha_device_registry.py`
2. Add MQTT topic subscriptions to `DEFAULT_SUBSCRIPTIONS` in `ha_mqtt_agent.py`
3. Add a handler in `MQTTAgent._register_default_routes()`
4. Update `ha_config.json` → `vendor_zones` with the new vendor details

### Adding an Automation Template

1. Add the template to `SYMPHONY_TEMPLATES` in `ha_automations.py`
2. Update `AutomationManager.parse_nl_to_template()` with keyword matching
3. Add the template name to `openclaw_ha_tool.json` → `create_automation.input.template_name.enum`

### Running Tests
```bash
# Connectivity smoke test
python ha_bridge.py

# MQTT agent test (runs forever, Ctrl+C to stop)
python ha_mqtt_agent.py

# Full setup verification
./setup_ha_integration.sh
```

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.0.0 | 2026-02-26 | Initial release — full HA integration for Bob the Conductor |

---

*Symphony Smart Homes — Bob the Conductor Home Assistant Integration*
*Built for the OpenClaw multi-agent framework on Mac Mini M4*
