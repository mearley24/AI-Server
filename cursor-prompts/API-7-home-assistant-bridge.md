# API-7: Home Assistant Bridge — Wire Into Docker Stack and OpenClaw

## The Problem

Five Home Assistant integration files exist in `integrations/homeassistant/` — `ha_bridge.py`, `ha_automations.py`, `ha_camera_monitor.py`, `ha_device_registry.py`, and `ha_mqtt_agent.py` — along with `ha_config.json`. These files have been written but are not verified to import cleanly, are not wired into the Docker stack, are not registered as a tool Bob can use, and have never been tested against a real or mock HA instance. The goal is to make this integration production-ready: fix imports, externalize config, wire ha_bridge.py as the main entry point, register it in OpenClaw's agent registry, add a health check, and create a docker-compose snippet for when a client has Home Assistant.

## Context Files to Read First

- `integrations/homeassistant/ha_bridge.py` (the main entry point — read fully before touching anything)
- `integrations/homeassistant/ha_automations.py` (automation trigger/registration logic)
- `integrations/homeassistant/ha_camera_monitor.py` (camera event monitor)
- `integrations/homeassistant/ha_device_registry.py` (device catalog and state tracking)
- `integrations/homeassistant/ha_mqtt_agent.py` (MQTT communication layer)
- `integrations/homeassistant/ha_config.json` (config schema — understand all fields)
- `agents/agent_registry.yml` (Bob's agent registry — where new tools get registered)
- `openclaw/orchestrator.py` (how OpenClaw calls registered agents)

## Prompt

Read the existing code first — read all five Python files and the config JSON before making any changes. Understand the integration architecture: how ha_bridge.py coordinates the other modules, what ha_mqtt_agent.py connects to, what ha_device_registry.py tracks, and what ha_automations.py can trigger. Do not rewrite working logic. Fix, wire, and harden what exists.

### 1. Verify All Imports Resolve

Run a dry-run import check on each file:

```bash
cd /path/to/project
python -c "from integrations.homeassistant.ha_bridge import HABridge; print('bridge OK')"
python -c "from integrations.homeassistant.ha_mqtt_agent import HAMQTTAgent; print('mqtt OK')"
python -c "from integrations.homeassistant.ha_device_registry import HADeviceRegistry; print('registry OK')"
python -c "from integrations.homeassistant.ha_automations import HAAutomations; print('automations OK')"
python -c "from integrations.homeassistant.ha_camera_monitor import HACameraMonitor; print('camera OK')"
```

For each ImportError:
- If it is a missing third-party package: add it to `requirements.txt` (or the correct requirements file for this integration)
- If it is a missing local import: fix the import path
- If a referenced class or function was renamed: update the reference

Do not restructure the module layout to fix imports — fix the import paths or the dependency.

### 2. Externalize All Config to Environment Variables

Read `ha_config.json` — it likely contains HA URL, token, MQTT host, and credentials. These must not live in a JSON file in production. Move them to environment variables:

In every HA module, replace hardcoded config reads with `os.getenv`:

```python
import os

HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")  # long-lived access token
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
```

Add these variables to `.env.example` with placeholder values and a comment:

```env
# Home Assistant Bridge
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your-long-lived-access-token-here
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USER=
MQTT_PASSWORD=
```

If `ha_config.json` is already used at runtime to load other non-secret configuration (device lists, automation templates), that is fine — keep it for non-secret config only.

### 3. Add Graceful Startup Behavior

In `ha_bridge.py`, wrap the HA connection in retry logic so the entire Docker stack does not crash if HA is unreachable:

```python
async def connect_with_retry(self, max_attempts: int = None):
    """
    Try to connect to HA. If unreachable, log a warning and retry every 60s.
    Never raise — always keep the bridge alive in a degraded state.
    """
    attempt = 0
    while True:
        try:
            await self._connect()
            logger.info(f"Home Assistant bridge connected to {self.ha_url}")
            self.connected = True
            return
        except Exception as e:
            attempt += 1
            logger.warning(f"HA bridge connection failed (attempt {attempt}): {e}. Retrying in 60s...")
            self.connected = False
            await asyncio.sleep(60)
```

All public methods on HABridge should check `self.connected` and return a degraded response if not connected:

```python
async def get_device_states(self) -> dict:
    if not self.connected:
        return {"error": "HA bridge not connected", "connected": False}
    # ... existing implementation
```

### 4. Add Health Check Endpoint

In `ha_bridge.py`, add a health check method that OpenClaw and Mission Control can call:

```python
async def health_check(self) -> dict:
    return {
        "connected": self.connected,
        "ha_url": self.ha_url,
        "mqtt_connected": self.mqtt_agent.connected if self.mqtt_agent else False,
        "devices_registered": len(self.device_registry.devices) if self.device_registry else 0,
        "last_event": self.last_event_timestamp,
        "status": "healthy" if self.connected else "degraded",
    }
```

Register this as an HTTP endpoint if ha_bridge.py runs as a service:

```python
@app.get("/health")
async def health():
    return await bridge.health_check()
```

### 5. Wire ha_bridge.py as the Single Entry Point

Read the five files and confirm ha_bridge.py initializes the other four modules. If it does not yet, add initialization:

```python
class HABridge:
    def __init__(self):
        self.ha_url = HA_URL
        self.ha_token = HA_TOKEN
        self.connected = False
        self.last_event_timestamp = None
        
        # Initialize sub-modules — use their existing __init__ signatures
        self.device_registry = HADeviceRegistry()
        self.mqtt_agent = HAMQTTAgent(
            host=MQTT_HOST,
            port=MQTT_PORT,
            username=MQTT_USER,
            password=MQTT_PASSWORD,
        )
        self.automations = HAAutomations(bridge=self)
        self.camera_monitor = HACameraMonitor(bridge=self)
    
    async def start(self):
        await self.connect_with_retry()
        await asyncio.gather(
            self.mqtt_agent.start(),
            self.camera_monitor.start(),
        )
```

Adjust constructor arguments to match what each class already accepts — read their `__init__` methods.

### 6. Register in OpenClaw Agent Registry

In `agents/agent_registry.yml`, add the HA bridge as a tool Bob can call:

```yaml
agents:
  # ... existing agents ...
  
  home_assistant:
    name: "Home Assistant Bridge"
    description: "Query and control smart home devices via Home Assistant"
    entry_point: "integrations.homeassistant.ha_bridge.HABridge"
    enabled: false  # Set to true when a client has HA — off by default
    capabilities:
      - query_device_states
      - trigger_automation
      - monitor_cameras
      - list_devices
    tools:
      - name: query_device
        description: "Get the current state of a specific HA device"
        parameters:
          entity_id: string
      - name: trigger_automation
        description: "Trigger a named HA automation"
        parameters:
          automation_id: string
      - name: get_camera_snapshot
        description: "Get the latest camera image for a named camera"
        parameters:
          camera_entity_id: string
```

In `openclaw/orchestrator.py`, if agent_registry.yml is already loaded dynamically, the HA bridge will be available automatically when `enabled: true`. If the orchestrator hardcodes agent imports, add a conditional import:

```python
if agent_registry.get("home_assistant", {}).get("enabled"):
    from integrations.homeassistant.ha_bridge import HABridge
    ha_bridge = HABridge()
```

### 7. Create Docker Compose Snippet

Create `integrations/homeassistant/docker-compose.ha.yml` — a self-contained snippet that can be merged into the main `docker-compose.yml` when deploying for a client with HA:

```yaml
# docker-compose.ha.yml
# Merge with main docker-compose.yml for clients with Home Assistant
# Usage: docker-compose -f docker-compose.yml -f integrations/homeassistant/docker-compose.ha.yml up

version: "3.8"

services:
  ha-bridge:
    build:
      context: .
      dockerfile: integrations/homeassistant/Dockerfile.ha
    container_name: ha-bridge
    restart: unless-stopped
    environment:
      - HA_URL=${HA_URL}
      - HA_TOKEN=${HA_TOKEN}
      - MQTT_HOST=${MQTT_HOST}
      - MQTT_PORT=${MQTT_PORT:-1883}
      - MQTT_USER=${MQTT_USER}
      - MQTT_PASSWORD=${MQTT_PASSWORD}
      - REDIS_URL=redis://172.18.0.100:6379
    ports:
      - "8105:8105"  # Health check / query API
    networks:
      - bob-network
    depends_on:
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8105/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Also create `integrations/homeassistant/Dockerfile.ha`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "integrations.homeassistant.ha_bridge"]
```

Add a `if __name__ == "__main__":` block to `ha_bridge.py` to make it runnable as a module:

```python
if __name__ == "__main__":
    import asyncio
    import uvicorn
    
    bridge = HABridge()
    # If using FastAPI for the health endpoint:
    asyncio.run(bridge.start())
```

### 8. Test With Mock Home Assistant

Create a minimal mock test at `tests/test_ha_bridge.py`:

```python
"""
Test HA bridge with a mock HA server.
Does not require a real Home Assistant instance.
"""
import asyncio
from unittest.mock import AsyncMock, patch

async def test_ha_bridge_imports():
    """Verify all HA modules import cleanly."""
    from integrations.homeassistant.ha_bridge import HABridge
    from integrations.homeassistant.ha_device_registry import HADeviceRegistry
    from integrations.homeassistant.ha_mqtt_agent import HAMQTTAgent
    print("All imports OK")

async def test_ha_bridge_degraded_mode():
    """HA bridge should handle unreachable HA gracefully."""
    from integrations.homeassistant.ha_bridge import HABridge
    
    bridge = HABridge()
    bridge.connected = False  # simulate unreachable HA
    
    result = await bridge.get_device_states()
    assert result.get("connected") is False or result.get("error") is not None
    print("Degraded mode OK:", result)

async def test_health_check():
    from integrations.homeassistant.ha_bridge import HABridge
    bridge = HABridge()
    health = await bridge.health_check()
    assert "connected" in health
    assert "status" in health
    print("Health check OK:", health)

if __name__ == "__main__":
    asyncio.run(test_ha_bridge_imports())
    asyncio.run(test_ha_bridge_degraded_mode())
    asyncio.run(test_health_check())
    print("All HA bridge tests passed.")
```

Run `python tests/test_ha_bridge.py`. All three tests must pass without a real HA instance. If any test fails due to a missing method that should exist, add it to ha_bridge.py. If it fails due to missing env vars, the graceful handling from step 3 should prevent crashes.
