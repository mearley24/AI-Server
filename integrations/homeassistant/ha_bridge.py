"""
ha_bridge.py — Symphony Smart Homes
Home Assistant Bridge for Bob the Conductor (OpenClaw multi-agent framework)

This is the primary interface between Bob (Mac Mini M4) and Home Assistant running
on the Raspberry Pi. Provides async access to all HA capabilities: states, services,
camera feeds, MQTT, WebSocket event streams, history, and template rendering.

Usage:
    from ha_bridge import HAClient, get_ha_client

    async with HAClient.from_env() as client:
        states = await client.get_states()
        await client.call_service("light", "turn_on", {"entity_id": "light.living_room"})
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlencode

import aiohttp
import asyncio_mqtt as aiomqtt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("symphony.ha_bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CACHE_TTL = 5          # seconds — entity state cache
WS_RECONNECT_DELAY = 5         # seconds — WebSocket reconnect backoff
MAX_RECONNECT_DELAY = 60       # seconds — reconnect ceiling
RATE_LIMIT_RPS = 10            # requests per second to the Pi REST API
REQUEST_TIMEOUT = 15           # seconds per HTTP request


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class HAState:
    entity_id: str
    state: str
    attributes: Dict[str, Any]
    last_changed: str
    last_updated: str
    context: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "HAState":
        return cls(
            entity_id=data["entity_id"],
            state=data["state"],
            attributes=data.get("attributes", {}),
            last_changed=data.get("last_changed", ""),
            last_updated=data.get("last_updated", ""),
            context=data.get("context", {}),
        )

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": self.attributes,
            "last_changed": self.last_changed,
            "last_updated": self.last_updated,
        }


@dataclass
class HAServiceResult:
    success: bool
    changed_states: List[dict] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter for REST API calls to the Pi."""

    def __init__(self, rps: float = RATE_LIMIT_RPS):
        self._rps = rps
        self._tokens = rps
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rps, self._tokens + elapsed * self._rps)
            self._last_refill = now
            if self._tokens < 1:
                sleep_for = (1 - self._tokens) / self._rps
                await asyncio.sleep(sleep_for)
                self._tokens = 0
            else:
                self._tokens -= 1


# ---------------------------------------------------------------------------
# State Cache
# ---------------------------------------------------------------------------

class StateCache:
    """Thread-safe TTL cache for entity states."""

    def __init__(self, ttl: float = DEFAULT_CACHE_TTL):
        self._ttl = ttl
        self._store: Dict[str, Tuple[HAState, float]] = {}
        self._all_states_ts: float = 0.0
        self._all_states: Optional[List[HAState]] = None

    def get(self, entity_id: str) -> Optional[HAState]:
        entry = self._store.get(entity_id)
        if entry and (time.monotonic() - entry[1]) < self._ttl:
            return entry[0]
        return None

    def set(self, state: HAState):
        self._store[state.entity_id] = (state, time.monotonic())

    def get_all(self) -> Optional[List[HAState]]:
        if self._all_states and (time.monotonic() - self._all_states_ts) < self._ttl:
            return self._all_states
        return None

    def set_all(self, states: List[HAState]):
        self._all_states = states
        self._all_states_ts = time.monotonic()
        for s in states:
            self._store[s.entity_id] = (s, self._all_states_ts)

    def invalidate(self, entity_id: str):
        self._store.pop(entity_id, None)

    def invalidate_all(self):
        self._store.clear()
        self._all_states = None
        self._all_states_ts = 0.0


# ---------------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------------

class HAWebSocketManager:
    """
    Manages a persistent WebSocket connection to Home Assistant for real-time events.
    Handles auth, subscription, and auto-reconnect.
    """

    def __init__(self, ws_url: str, token: str, state_cache: StateCache):
        self._url = ws_url
        self._token = token
        self._cache = state_cache
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._msg_id = 1
        self._subscriptions: Dict[int, Callable] = {}
        self._event_callbacks: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._reconnect_delay = WS_RECONNECT_DELAY

    def add_event_callback(self, callback: Callable):
        self._event_callbacks.append(callback)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _run_loop(self):
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                logger.warning(f"WebSocket error: {exc}. Reconnecting in {self._reconnect_delay}s")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
            else:
                self._reconnect_delay = WS_RECONNECT_DELAY

    async def _connect_and_listen(self):
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(self._url, heartbeat=30) as ws:
                self._ws = ws
                logger.info(f"WebSocket connected to {self._url}")
                self._reconnect_delay = WS_RECONNECT_DELAY

                # Auth handshake
                auth_required = await ws.receive_json()
                if auth_required.get("type") != "auth_required":
                    raise ValueError(f"Unexpected WS message: {auth_required}")
                await ws.send_json({"type": "auth", "access_token": self._token})
                auth_ok = await ws.receive_json()
                if auth_ok.get("type") != "auth_ok":
                    raise PermissionError(f"WebSocket auth failed: {auth_ok}")

                # Subscribe to all state_changed events
                sub_id = self._msg_id
                self._msg_id += 1
                await ws.send_json({
                    "id": sub_id,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                })

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        await self._handle_message(data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        finally:
            await session.close()

    async def _handle_message(self, data: dict):
        msg_type = data.get("type")
        if msg_type == "event":
            event = data.get("event", {})
            event_type = event.get("event_type")
            event_data = event.get("data", {})

            # Update cache on state_changed
            if event_type == "state_changed":
                new_state = event_data.get("new_state")
                if new_state:
                    self._cache.set(HAState.from_dict(new_state))

            # Dispatch to registered callbacks
            for cb in self._event_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(event_type, event_data))
                    else:
                        cb(event_type, event_data)
                except Exception as exc:
                    logger.error(f"Event callback error: {exc}")

    async def send(self, message: dict) -> int:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket not connected")
        msg_id = self._msg_id
        self._msg_id += 1
        message["id"] = msg_id
        await self._ws.send_json(message)
        return msg_id


# ---------------------------------------------------------------------------
# Main HA Client
# ---------------------------------------------------------------------------

class HAClient:
    """
    Async client for the Home Assistant REST and WebSocket APIs.
    Used by Bob the Conductor and all OpenClaw agents that need smart home access.

    Example:
        client = HAClient.from_env()
        await client.connect()
        states = await client.get_states()
        await client.call_service("light", "turn_on", {"entity_id": "light.living_room"})
        await client.disconnect()

    Or as async context manager:
        async with HAClient.from_env() as client:
            ...
    """

    def __init__(
        self,
        ha_url: str,
        token: str,
        ws_url: Optional[str] = None,
        mqtt_host: Optional[str] = None,
        mqtt_port: int = 1883,
        mqtt_user: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        rate_limit_rps: float = RATE_LIMIT_RPS,
    ):
        self._ha_url = ha_url.rstrip("/")
        self._token = token
        self._ws_url = ws_url or self._ha_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port
        self._mqtt_user = mqtt_user
        self._mqtt_password = mqtt_password

        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = StateCache(ttl=cache_ttl)
        self._rate_limiter = RateLimiter(rps=rate_limit_rps)
        self._ws_manager: Optional[HAWebSocketManager] = None
        self._mqtt_client: Optional[aiomqtt.Client] = None
        self._mqtt_task: Optional[asyncio.Task] = None
        self._mqtt_subscriptions: Dict[str, List[Callable]] = defaultdict(list)
        self._connected = False

    @classmethod
    def from_env(cls) -> "HAClient":
        """Create an HAClient from environment variables."""
        ha_url = os.environ.get("HA_URL", "http://homeassistant.local:8123")
        token = os.environ.get("HA_TOKEN", "")
        if not token:
            raise EnvironmentError("HA_TOKEN environment variable is required")
        return cls(
            ha_url=ha_url,
            token=token,
            ws_url=os.environ.get("HA_WEBSOCKET_URL"),
            mqtt_host=os.environ.get("MQTT_BROKER"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            mqtt_user=os.environ.get("MQTT_USER"),
            mqtt_password=os.environ.get("MQTT_PASSWORD"),
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        """Establish HTTP session and optional WebSocket + MQTT connections."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        connector = aiohttp.TCPConnector(limit=20)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        self._session = aiohttp.ClientSession(headers=headers, connector=connector, timeout=timeout)

        # Verify HA is reachable
        try:
            resp = await self._get("/api/")
            logger.info(f"Connected to Home Assistant {resp.get('version', 'unknown')} at {self._ha_url}")
        except Exception as exc:
            await self._session.close()
            raise ConnectionError(f"Cannot reach Home Assistant at {self._ha_url}: {exc}") from exc

        # Start WebSocket manager
        self._ws_manager = HAWebSocketManager(self._ws_url, self._token, self._cache)
        await self._ws_manager.start()

        self._connected = True

    async def disconnect(self):
        """Gracefully close all connections."""
        self._connected = False
        if self._ws_manager:
            await self._ws_manager.stop()
        if self._mqtt_task:
            self._mqtt_task.cancel()
        if self._session:
            await self._session.close()
        logger.info("HAClient disconnected")

    async def __aenter__(self) -> "HAClient":
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", path.lstrip("/"))
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, payload: Optional[dict] = None) -> Any:
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", path.lstrip("/"))
        async with self._session.post(url, json=payload or {}) as resp:
            resp.raise_for_status()
            ct = resp.content_type or ""
            if "json" in ct:
                return await resp.json()
            return await resp.read()

    async def _delete(self, path: str) -> Any:
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", path.lstrip("/"))
        async with self._session.delete(url) as resp:
            resp.raise_for_status()
            return await resp.json() if resp.content_length else {}

    async def _get_bytes(self, path: str) -> bytes:
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", path.lstrip("/"))
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    async def get_states(self) -> List[HAState]:
        """
        Fetch all entity states from Home Assistant.
        Results are cached for DEFAULT_CACHE_TTL seconds.
        """
        cached = self._cache.get_all()
        if cached:
            return cached
        data = await self._get("/api/states")
        states = [HAState.from_dict(s) for s in data]
        self._cache.set_all(states)
        logger.debug(f"Fetched {len(states)} entity states")
        return states

    async def get_state(self, entity_id: str) -> HAState:
        """
        Fetch the current state of a specific entity.
        Uses cache with 5-second TTL; real-time if WebSocket is connected.
        """
        cached = self._cache.get(entity_id)
        if cached:
            return cached
        data = await self._get(f"/api/states/{entity_id}")
        state = HAState.from_dict(data)
        self._cache.set(state)
        return state

    async def set_state(self, entity_id: str, state: str, attributes: Optional[dict] = None) -> HAState:
        """
        Set the state of an entity directly (bypasses service calls).
        Primarily for virtual/helper entities.
        """
        payload = {"state": state, "attributes": attributes or {}}
        data = await self._post(f"/api/states/{entity_id}", payload)
        result = HAState.from_dict(data)
        self._cache.set(result)
        return result

    # ------------------------------------------------------------------
    # Service calls
    # ------------------------------------------------------------------

    async def call_service(
        self,
        domain: str,
        service: str,
        data: Optional[dict] = None,
    ) -> HAServiceResult:
        """
        Call any Home Assistant service.

        Examples:
            await client.call_service("light", "turn_on", {
                "entity_id": "light.living_room",
                "brightness": 200,
                "color_temp": 3000,
            })
            await client.call_service("lock", "lock", {"entity_id": "lock.front_door"})
            await client.call_service("scene", "turn_on", {"entity_id": "scene.welcome"})
        """
        path = f"/api/services/{domain}/{service}"
        try:
            result = await self._post(path, data or {})
            # Invalidate cache for any entity_id in data
            if data and "entity_id" in data:
                eids = data["entity_id"]
                if isinstance(eids, str):
                    eids = [eids]
                for eid in eids:
                    self._cache.invalidate(eid)
            logger.info(f"Called service {domain}.{service} with {data}")
            return HAServiceResult(
                success=True,
                changed_states=result if isinstance(result, list) else [],
            )
        except aiohttp.ClientResponseError as exc:
            logger.error(f"Service call {domain}.{service} failed: {exc}")
            return HAServiceResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    async def get_camera_snapshot(self, camera_entity: str) -> bytes:
        """
        Download a JPEG snapshot from a camera entity.
        Returns raw bytes suitable for saving as a .jpg or passing to a vision model.

        Args:
            camera_entity: e.g. "camera.front_door" or "camera.luma_driveway"
        """
        path = f"/api/camera_proxy/{camera_entity}"
        image_bytes = await self._get_bytes(path)
        logger.debug(f"Got snapshot from {camera_entity}: {len(image_bytes)} bytes")
        return image_bytes

    async def get_camera_snapshot_b64(self, camera_entity: str) -> str:
        """Return a camera snapshot as a base64-encoded string (for LLM vision APIs)."""
        raw = await self.get_camera_snapshot(camera_entity)
        return base64.b64encode(raw).decode("utf-8")

    async def get_camera_stream_url(self, camera_entity: str) -> Optional[str]:
        """
        Get the stream URL for a camera entity (RTSP or MJPEG).
        Returns the stream URL string, or None if not available.
        """
        try:
            state = await self.get_state(camera_entity)
            # HA stores stream URL in attributes for supported cameras
            stream_url = state.attributes.get("stream_source") or state.attributes.get("entity_picture")
            if stream_url and not stream_url.startswith("http"):
                stream_url = self._ha_url + stream_url
            return stream_url
        except Exception as exc:
            logger.warning(f"Could not get stream URL for {camera_entity}: {exc}")
            return None

    async def get_camera_video_url(self, camera_entity: str) -> Optional[str]:
        """
        Initiate a camera stream and return the HLS/RTSP URL via HA Camera Proxy streaming endpoint.
        """
        try:
            result = await self._post(f"/api/camera_proxy_stream/{camera_entity}")
            if isinstance(result, dict):
                return result.get("url")
        except Exception:
            pass
        return f"{self._ha_url}/api/camera_proxy_stream/{camera_entity}?token={self._token}"

    # ------------------------------------------------------------------
    # WebSocket event subscription
    # ------------------------------------------------------------------

    async def subscribe_events(self, callback: Callable) -> None:
        """
        Register a callback for all real-time HA events.
        Callback signature: callback(event_type: str, event_data: dict)
        Events arrive via the persistent WebSocket connection.
        """
        if not self._ws_manager:
            raise RuntimeError("Client not connected. Call connect() first.")
        self._ws_manager.add_event_callback(callback)
        logger.info(f"Registered event callback: {callback.__name__}")

    # ------------------------------------------------------------------
    # History & Logbook
    # ------------------------------------------------------------------

    async def get_history(
        self,
        entity_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        minimal_response: bool = True,
    ) -> List[List[dict]]:
        """
        Fetch historical state data for an entity.

        Args:
            entity_id: The entity to query
            start: Start time (defaults to 24 hours ago)
            end: End time (defaults to now)
            minimal_response: Skip extra attributes for performance

        Returns:
            List of state history lists (one list per entity)
        """
        if not start:
            start = datetime.now(timezone.utc) - timedelta(hours=24)
        if not end:
            end = datetime.now(timezone.utc)

        iso_start = start.isoformat()
        iso_end = end.isoformat()
        params = {
            "filter_entity_id": entity_id,
            "end_time": iso_end,
        }
        if minimal_response:
            params["minimal_response"] = "true"

        path = f"/api/history/period/{iso_start}"
        data = await self._get(path, params=params)
        return data

    async def get_logbook(
        self,
        entity_id: Optional[str] = None,
        hours: int = 24,
    ) -> List[dict]:
        """
        Fetch the logbook (human-readable activity log).

        Args:
            entity_id: Optionally filter to a specific entity
            hours: How many hours back to look (default 24)

        Returns:
            List of logbook entries with time, name, message, entity_id
        """
        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        iso_start = start.isoformat()
        params: dict = {}
        if entity_id:
            params["entity"] = entity_id
        data = await self._get(f"/api/logbook/{iso_start}", params=params)
        return data

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------

    async def publish_mqtt(
        self,
        topic: str,
        payload: Any,
        retain: bool = False,
        qos: int = 0,
    ) -> None:
        """
        Publish a message to the MQTT broker via HA's mqtt.publish service.
        This routes through HA rather than a direct broker connection.

        Args:
            topic: MQTT topic string
            payload: String, dict (auto-serialized to JSON), or bytes
            retain: Whether the broker should retain this message
            qos: MQTT QoS level (0, 1, or 2)
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        elif isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        await self.call_service("mqtt", "publish", {
            "topic": topic,
            "payload": payload,
            "retain": retain,
            "qos": qos,
        })
        logger.debug(f"MQTT publish → {topic}: {str(payload)[:80]}")

    async def subscribe_mqtt(self, topic: str, callback: Callable) -> None:
        """
        Subscribe to an MQTT topic via HA event bus.
        Callback signature: callback(topic: str, payload: str)
        Note: For high-throughput MQTT, use HAMQTTAgent directly.
        """
        # Subscribe via HA's mqtt.subscribe service (creates an event subscription)
        async def _event_handler(event_type: str, event_data: dict):
            if event_type == "mqtt_message_received":
                msg_topic = event_data.get("topic", "")
                # Simple wildcard matching
                if self._topic_matches(topic, msg_topic):
                    await callback(msg_topic, event_data.get("payload", ""))

        await self.subscribe_events(_event_handler)

        # Also trigger HA to subscribe the topic via service
        try:
            await self._post("/api/services/mqtt/subscribe", {"topic": topic})
        except Exception:
            logger.debug(f"mqtt.subscribe service not available; relying on event stream for {topic}")

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """MQTT wildcard matching for + (single level) and # (multi level)."""
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        if pattern_parts[-1] == "#":
            return topic_parts[:len(pattern_parts) - 1] == pattern_parts[:-1]
        if len(pattern_parts) != len(topic_parts):
            return False
        return all(p == t or p == "+" for p, t in zip(pattern_parts, topic_parts))

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    async def render_template(self, template_str: str) -> str:
        """
        Render a Home Assistant Jinja2 template.

        Example:
            result = await client.render_template(
                "{{ states('sensor.living_room_temperature') }}°F"
            )
        """
        data = await self._post("/api/template", {"template": template_str})
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)

    # ------------------------------------------------------------------
    # Config / System
    # ------------------------------------------------------------------

    async def get_config(self) -> dict:
        """Get the Home Assistant configuration."""
        return await self._get("/api/config")

    async def get_services(self) -> dict:
        """Get all available services grouped by domain."""
        return await self._get("/api/services")

    async def get_components(self) -> List[str]:
        """Get list of loaded HA components/integrations."""
        return await self._get("/api/components")

    async def check_config(self) -> dict:
        """Trigger a HA config check and return the result."""
        return await self._post("/api/config/core/check_config")

    async def restart_ha(self) -> None:
        """Restart Home Assistant (use with caution!)."""
        await self._post("/api/services/homeassistant/restart")
        logger.warning("Home Assistant restart requested!")

    # ------------------------------------------------------------------
    # Automations (raw API helpers used by ha_automations.py)
    # ------------------------------------------------------------------

    async def get_automation_config(self, automation_id: str) -> dict:
        """Fetch a single automation config by ID."""
        return await self._get(f"/api/config/automation/config/{automation_id}")

    async def list_automations(self) -> List[dict]:
        """List all automation config entries."""
        return await self._get("/api/config/automation/config")

    async def create_automation(self, config: dict) -> dict:
        """Create a new automation from a config dict. Returns the created automation."""
        return await self._post("/api/config/automation/config", config)

    async def update_automation(self, automation_id: str, config: dict) -> dict:
        """Update an existing automation."""
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", f"api/config/automation/config/{automation_id}")
        async with self._session.put(url, json=config) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def delete_automation(self, automation_id: str) -> dict:
        """Delete an automation by ID."""
        return await self._delete(f"/api/config/automation/config/{automation_id}")

    async def trigger_automation(self, automation_id: str) -> HAServiceResult:
        """Manually trigger an automation."""
        return await self.call_service(
            "automation", "trigger",
            {"entity_id": f"automation.{automation_id}"}
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Returns True if Home Assistant is reachable and authenticated."""
        try:
            data = await self._get("/api/")
            return "message" in data or "version" in data
        except Exception:
            return False

    async def get_error_log(self) -> str:
        """Fetch the HA error log (plaintext)."""
        await self._rate_limiter.acquire()
        url = urljoin(self._ha_url + "/", "api/error_log")
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.text()


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

_default_client: Optional[HAClient] = None


async def get_ha_client() -> HAClient:
    """
    Get (or create) the global singleton HAClient.
    Recommended for use within OpenClaw agent tasks.
    """
    global _default_client
    if _default_client is None or not _default_client._connected:
        _default_client = HAClient.from_env()
        await _default_client.connect()
    return _default_client


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

async def _smoke_test():
    """Quick connectivity test — run with: python ha_bridge.py"""
    print("Symphony Smart Homes — HA Bridge Smoke Test")
    print("=" * 50)
    client = HAClient.from_env()
    async with client:
        # Ping
        ok = await client.ping()
        print(f"✓ HA reachable: {ok}")

        # States
        states = await client.get_states()
        print(f"✓ Entities loaded: {len(states)}")

        # Show a few interesting ones
        domains = {}
        for s in states:
            domain = s.entity_id.split(".")[0]
            domains[domain] = domains.get(domain, 0) + 1
        print("  Entity domains:")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1])[:10]:
            print(f"    {domain}: {count}")

        # Config
        config = await client.get_config()
        print(f"✓ HA version: {config.get('version', 'unknown')}")
        print(f"  Location: {config.get('location_name', 'unknown')}")

        # Template
        try:
            now = await client.render_template("{{ now().strftime('%Y-%m-%d %H:%M:%S') }}")
            print(f"✓ Template rendered: {now}")
        except Exception as e:
            print(f"  Template test skipped: {e}")

    print("\nSmoke test complete.")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
