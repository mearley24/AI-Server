# API-7: Home Assistant Bridge — Connect Bob to the Physical World

## Context Files to Read First
- integrations/homeassistant/README.md (full architecture and API reference)
- integrations/homeassistant/ha_bridge.py
- integrations/homeassistant/ha_mqtt_agent.py
- integrations/homeassistant/ha_camera_monitor.py
- integrations/homeassistant/ha_device_registry.py
- integrations/homeassistant/ha_automations.py
- integrations/homeassistant/docker-compose.ha.yml

## Prompt

The Home Assistant integration code is written but needs to be deployed and connected to a real HA instance. Make it production-ready:

1. **Environment setup**:
   - Add HA env vars to `.env.example`: `HA_URL`, `HA_TOKEN`, `MQTT_HOST`, `MQTT_USER`, `MQTT_PASSWORD`
   - Make all HA modules gracefully handle missing env vars (log warning, disable feature, don't crash)
   - If HA is unreachable at startup, retry every 60s instead of crashing

2. **Docker integration**:
   - Merge `docker-compose.ha.yml` overlay into the main `docker-compose.yml` as an optional profile (`--profile homeassistant`)
   - Services: `ha-bridge` (REST/WebSocket client), `ha-mqtt-agent` (MQTT subscriber)
   - Both depend on Redis (healthy)

3. **Wire into Bob's brain**:
   - Add HA commands to the iMessage bridge: "lights on in [room]", "lock all doors", "camera snapshot [location]"
   - Parse natural language commands in `scripts/imessage-server.py` and route to `ha_bridge.py`
   - Camera snapshots: fetch via HA proxy, send as MMS through iMessage bridge

4. **Automation templates**:
   - Verify the 7 Symphony templates in `ha_automations.py` work with HA's automation format
   - Add CLI: `python3 ha_automations.py --create morning_routine --vars '{"wake_time":"06:30"}'`
   - Add iMessage command: "create automation [template_name]"

5. **Security**:
   - Enforce the approval list: lock/unlock, alarm arm/disarm, HA restart require owner confirmation via iMessage before executing
   - Log all service calls with timestamp and source

6. **Health monitoring**:
   - Add HA connectivity status to Mission Control dashboard (API-5)
   - If HA goes offline, send iMessage alert to Matt

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
