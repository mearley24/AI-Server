"""
ha_mqtt_agent.py — Symphony Smart Homes
MQTT Agent for Bob the Conductor

Connects directly to the Mosquitto broker on the Raspberry Pi and handles:
- Topic subscriptions for all vendor-specific devices (Control4, Lutron, Araknis, Luma)
- Bob's heartbeat publishing
- Event dispatching to OpenClaw agents/workflows
- Message history ring buffer (last 1000 messages)
- Smart home event routing

This agent runs as a persistent background service on Bob (Mac Mini M4).

Usage:
    agent = MQTTAgent.from_env()
    await agent.start()
    # ... runs indefinitely
    await agent.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("symphony.ha_mqtt_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL = 60       # seconds between Bob's heartbeat publishes
RECONNECT_DELAY = 5           # initial reconnect delay (seconds)
MAX_RECONNECT_DELAY = 120     # maximum reconnect delay
MESSAGE_HISTORY_SIZE = 1000   # ring buffer capacity
BOB_HEARTBEAT_TOPIC = "symphony/bob/heartbeat"
BOB_STATUS_TOPIC = "symphony/bob/status"
BOB_COMMANDS_TOPIC = "symphony/bob/commands"

# Topics Bob subscribes to
DEFAULT_SUBSCRIPTIONS = [
    ("homeassistant/#", 0),          # All HA MQTT discovery + events
    ("luma/+/status", 0),            # Luma camera status
    ("luma/+/motion", 0),            # Luma camera motion alerts
    ("luma/+/recording", 0),         # Luma recording events
    ("control4/+/event", 0),         # Control4 driver events
    ("control4/+/status", 0),        # Control4 status updates
    ("lutron/+/state", 0),           # Lutron switch/dimmer/shade states
    ("lutron/+/event", 0),           # Lutron button events
    ("araknis/+/status", 0),         # Araknis network device status
    ("araknis/+/alert", 0),          # Araknis network alerts
    ("sonos/+/state", 0),            # Sonos player states
    ("sonos/+/event", 0),            # Sonos events
    ("snapone/+/status", 0),         # Snap One/Triad status
    ("symphony/bob/commands", 1),    # Commands directed at Bob (QoS 1)
    ("symphony/+/request", 1),       # Service requests from any agent
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class MQTTMessage:
    topic: str
    payload: str
    qos: int
    retain: bool
    timestamp: float = field(default_factory=time.time)

    def payload_json(self) -> Optional[Any]:
        """Try to parse payload as JSON; return None if not valid JSON."""
        try:
            return json.loads(self.payload)
        except (json.JSONDecodeError, TypeError):
            return None

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "qos": self.qos,
            "retain": self.retain,
            "timestamp": self.timestamp,
            "iso_time": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
        }


@dataclass
class EventRoute:
    """Maps a topic pattern to a handler and optional OpenClaw workflow."""
    topic_pattern: str
    handler: Callable
    openclaw_workflow: Optional[str] = None
    description: str = ""


# ---------------------------------------------------------------------------
# Topic Classifier — maps MQTT topics to vendor/category
# ---------------------------------------------------------------------------

class TopicClassifier:
    """Classifies incoming MQTT topics to vendor/device category for routing."""

    VENDOR_MAP = {
        "homeassistant": "home_assistant",
        "luma": "luma_camera",
        "control4": "control4",
        "lutron": "lutron",
        "araknis": "araknis_network",
        "sonos": "sonos_audio",
        "snapone": "snap_one",
        "triad": "triad_audio",
        "symphony": "symphony_internal",
    }

    ACTION_MAP = {
        "status": "status_update",
        "state": "state_change",
        "event": "event",
        "alert": "alert",
        "motion": "motion_detected",
        "recording": "recording_event",
        "commands": "command",
        "request": "request",
        "heartbeat": "heartbeat",
        "discovery": "discovery",
    }

    @classmethod
    def classify(cls, topic: str) -> dict:
        parts = topic.split("/")
        vendor = cls.VENDOR_MAP.get(parts[0], "unknown")
        device_id = parts[1] if len(parts) > 1 else None
        action_raw = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else None)
        action = cls.ACTION_MAP.get(action_raw, action_raw) if action_raw else None
        return {
            "vendor": vendor,
            "device_id": device_id,
            "action": action,
            "parts": parts,
        }

    @classmethod
    def is_safety_critical(cls, topic: str) -> bool:
        """Returns True if the message may involve a safety-critical device."""
        critical_keywords = ["lock", "alarm", "security", "garage", "door", "gate", "camera"]
        return any(kw in topic.lower() for kw in critical_keywords)


# ---------------------------------------------------------------------------
# Message History Buffer
# ---------------------------------------------------------------------------

class MessageHistory:
    """Ring buffer of the last N MQTT messages for inspection and replay."""

    def __init__(self, maxlen: int = MESSAGE_HISTORY_SIZE):
        self._buffer: Deque[MQTTMessage] = deque(maxlen=maxlen)

    def add(self, msg: MQTTMessage):
        self._buffer.append(msg)

    def get_all(self) -> List[MQTTMessage]:
        return list(self._buffer)

    def get_by_topic_prefix(self, prefix: str) -> List[MQTTMessage]:
        return [m for m in self._buffer if m.topic.startswith(prefix)]

    def get_recent(self, seconds: float = 60) -> List[MQTTMessage]:
        cutoff = time.time() - seconds
        return [m for m in self._buffer if m.timestamp >= cutoff]

    def get_by_vendor(self, vendor: str) -> List[MQTTMessage]:
        return [m for m in self._buffer if m.topic.split("/")[0] == vendor]

    def summary(self) -> dict:
        msgs = list(self._buffer)
        if not msgs:
            return {"total": 0, "by_vendor": {}}
        vendor_counts: Dict[str, int] = {}
        for m in msgs:
            v = m.topic.split("/")[0]
            vendor_counts[v] = vendor_counts.get(v, 0) + 1
        return {
            "total": len(msgs),
            "oldest": msgs[0].iso_time if msgs else None,
            "newest": msgs[-1].iso_time if msgs else None,
            "by_vendor": vendor_counts,
        }

    @property
    def iso_time(self):
        pass


# ---------------------------------------------------------------------------
# Event Dispatcher
# ---------------------------------------------------------------------------

class EventDispatcher:
    """
    Routes MQTT messages to registered handlers based on topic patterns.
    Supports wildcards: + (single level), # (multi level).
    """

    def __init__(self):
        self._routes: List[EventRoute] = []
        self._default_handler: Optional[Callable] = None

    def register(
        self,
        topic_pattern: str,
        handler: Callable,
        openclaw_workflow: Optional[str] = None,
        description: str = "",
    ):
        """Register a handler for a topic pattern."""
        self._routes.append(EventRoute(
            topic_pattern=topic_pattern,
            handler=handler,
            openclaw_workflow=openclaw_workflow,
            description=description,
        ))
        logger.debug(f"Registered handler for topic pattern: {topic_pattern}")

    def set_default_handler(self, handler: Callable):
        self._default_handler = handler

    async def dispatch(self, msg: MQTTMessage):
        """Dispatch a message to all matching handlers."""
        dispatched = False
        for route in self._routes:
            if self._matches(route.topic_pattern, msg.topic):
                try:
                    if asyncio.iscoroutinefunction(route.handler):
                        await route.handler(msg, route.openclaw_workflow)
                    else:
                        route.handler(msg, route.openclaw_workflow)
                    dispatched = True
                except Exception as exc:
                    logger.error(f"Handler error for {msg.topic}: {exc}")

        if not dispatched and self._default_handler:
            try:
                if asyncio.iscoroutinefunction(self._default_handler):
                    await self._default_handler(msg, None)
                else:
                    self._default_handler(msg, None)
            except Exception as exc:
                logger.error(f"Default handler error: {exc}")

    @staticmethod
    def _matches(pattern: str, topic: str) -> bool:
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        if pattern_parts[-1] == "#":
            return topic_parts[:len(pattern_parts) - 1] == pattern_parts[:-1]
        if len(pattern_parts) != len(topic_parts):
            return False
        return all(p == t or p == "+" for p, t in zip(pattern_parts, topic_parts))


# ---------------------------------------------------------------------------
# MQTT Agent
# ---------------------------------------------------------------------------

class MQTTAgent:
    """
    Persistent MQTT agent running on Bob.

    Maintains a direct connection to the Mosquitto broker on the Pi,
    handles all vendor-specific topic subscriptions, dispatches events
    to OpenClaw agents, and publishes Bob's heartbeat.
    """

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: str = "bob-conductor",
        subscriptions: Optional[List[tuple]] = None,
    ):
        self._host = broker_host
        self._port = broker_port
        self._username = username
        self._password = password
        self._client_id = client_id
        self._subscriptions = subscriptions or DEFAULT_SUBSCRIPTIONS
        self._history = MessageHistory(maxlen=MESSAGE_HISTORY_SIZE)
        self._dispatcher = EventDispatcher()
        self._running = False
        self._client = None
        self._reconnect_delay = RECONNECT_DELAY
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._main_task: Optional[asyncio.Task] = None
        self._openclaw_trigger_callbacks: List[Callable] = []

        # Register built-in handlers
        self._register_default_routes()

    @classmethod
    def from_env(cls) -> "MQTTAgent":
        """Create an MQTTAgent from environment variables."""
        host = os.environ.get("MQTT_BROKER", "")
        if not host:
            raise EnvironmentError("MQTT_BROKER environment variable is required")
        return cls(
            broker_host=host,
            broker_port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USER"),
            password=os.environ.get("MQTT_PASSWORD"),
        )

    def _register_default_routes(self):
        """Register built-in handlers for known vendor topics."""
        d = self._dispatcher
        d.register("luma/+/motion", self._handle_luma_motion,
                   openclaw_workflow="security_alert",
                   description="Luma camera motion detection")
        d.register("luma/+/status", self._handle_device_status,
                   description="Luma camera online/offline")
        d.register("control4/+/event", self._handle_control4_event,
                   description="Control4 driver events")
        d.register("lutron/+/state", self._handle_lutron_state,
                   description="Lutron switch/dimmer state changes")
        d.register("araknis/+/alert", self._handle_network_alert,
                   openclaw_workflow="network_alert",
                   description="Araknis network device alerts")
        d.register("symphony/bob/commands", self._handle_bob_command,
                   description="Commands directed at Bob")
        d.register("homeassistant/#", self._handle_ha_discovery,
                   description="Home Assistant MQTT discovery")
        d.set_default_handler(self._handle_default)

    async def start(self):
        self._running = True
        self._main_task = asyncio.create_task(self._run_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"MQTT Agent started (broker: {self._host}:{self._port})")

    async def stop(self):
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._main_task:
            self._main_task.cancel()
        logger.info("MQTT Agent stopped")

    async def run_forever(self):
        await self.start()
        try:
            await asyncio.gather(self._main_task, self._heartbeat_task)
        except asyncio.CancelledError:
            pass

    async def _run_loop(self):
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                logger.warning(f"MQTT connection lost: {exc}. Reconnecting in {self._reconnect_delay}s")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, MAX_RECONNECT_DELAY)
            else:
                self._reconnect_delay = RECONNECT_DELAY

    async def _connect_and_listen(self):
        try:
            import asyncio_mqtt as aiomqtt
        except ImportError:
            logger.error("asyncio_mqtt not installed. Install with: pip install asyncio-mqtt")
            raise
        connect_kwargs = {
            "hostname": self._host,
            "port": self._port,
            "client_id": self._client_id,
            "keepalive": 60,
        }
        if self._username:
            connect_kwargs["username"] = self._username
        if self._password:
            connect_kwargs["password"] = self._password
        async with aiomqtt.Client(**connect_kwargs) as client:
            self._client = client
            logger.info(f"MQTT connected to {self._host}:{self._port} as {self._client_id}")
            self._reconnect_delay = RECONNECT_DELAY
            for topic, qos in self._subscriptions:
                await client.subscribe(topic, qos=qos)
            await self._publish_status("online")
            async for message in client.messages:
                if not self._running:
                    break
                msg = MQTTMessage(
                    topic=str(message.topic),
                    payload=message.payload.decode("utf-8", errors="replace") if message.payload else "",
                    qos=message.qos,
                    retain=message.retain,
                )
                self._history.add(msg)
                await self._dispatcher.dispatch(msg)

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await self.publish(BOB_HEARTBEAT_TOPIC, {
                    "status": "online",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agent": "bob-conductor",
                    "message_count": len(self._history.get_all()),
                    "uptime_seconds": time.time() - self._start_time,
                }, retain=True)
            except Exception as exc:
                logger.warning(f"Heartbeat publish failed: {exc}")

    async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> None:
        if self._client is None:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        elif not isinstance(payload, (str, bytes)):
            payload = str(payload)
        await self._client.publish(topic, payload, qos=qos, retain=retain)

    async def _publish_status(self, status: str):
        await self.publish(BOB_STATUS_TOPIC, {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, retain=True)

    async def _handle_luma_motion(self, msg: MQTTMessage, workflow: Optional[str]):
        classification = TopicClassifier.classify(msg.topic)
        camera_id = classification.get("device_id", "unknown")
        payload = msg.payload_json() or {"raw": msg.payload}
        logger.info(f"MOTION DETECTED: Luma camera {camera_id} — {payload}")
        await self._trigger_openclaw_workflow(workflow, {
            "event": "motion_detected", "vendor": "luma",
            "camera_id": camera_id, "payload": payload, "timestamp": msg.timestamp,
        })

    async def _handle_device_status(self, msg: MQTTMessage, workflow: Optional[str]):
        classification = TopicClassifier.classify(msg.topic)
        device_id = classification.get("device_id", "unknown")
        payload = msg.payload_json() or msg.payload
        online_status = payload.get("status", "unknown") if isinstance(payload, dict) else str(payload)
        logger.info(f"Device status: {classification['vendor']} {device_id} → {online_status}")

    async def _handle_control4_event(self, msg: MQTTMessage, workflow: Optional[str]):
        classification = TopicClassifier.classify(msg.topic)
        driver_id = classification.get("device_id", "unknown")
        payload = msg.payload_json() or {"raw": msg.payload}
        event_type = payload.get("event_type", "unknown") if isinstance(payload, dict) else "unknown"
        logger.info(f"Control4 event: driver={driver_id} type={event_type}")
        if event_type in ("arrival", "departure", "presence"):
            await self._trigger_openclaw_workflow("client_presence_workflow", {
                "event": event_type, "driver_id": driver_id,
                "payload": payload, "timestamp": msg.timestamp,
            })

    async def _handle_lutron_state(self, msg: MQTTMessage, workflow: Optional[str]):
        classification = TopicClassifier.classify(msg.topic)
        device_id = classification.get("device_id", "unknown")
        payload = msg.payload_json() or msg.payload
        logger.debug(f"Lutron state: {device_id} → {payload}")

    async def _handle_network_alert(self, msg: MQTTMessage, workflow: Optional[str]):
        classification = TopicClassifier.classify(msg.topic)
        device_id = classification.get("device_id", "unknown")
        payload = msg.payload_json() or {"raw": msg.payload}
        severity = payload.get("severity", "unknown") if isinstance(payload, dict) else "unknown"
        logger.warning(f"Network alert: Araknis {device_id} — severity={severity}")
        await self._trigger_openclaw_workflow(workflow, {
            "event": "network_alert", "vendor": "araknis",
            "device_id": device_id, "severity": severity,
            "payload": payload, "timestamp": msg.timestamp,
        })

    async def _handle_bob_command(self, msg: MQTTMessage, workflow: Optional[str]):
        payload = msg.payload_json()
        if not payload:
            logger.warning(f"Received non-JSON command on {msg.topic}: {msg.payload}")
            return
        command = payload.get("command", "")
        args = payload.get("args", {})
        request_id = payload.get("request_id")
        logger.info(f"Received Bob command: {command} (request_id={request_id})")
        await self._trigger_openclaw_workflow("command_handler", {
            "command": command, "args": args,
            "request_id": request_id, "source": "mqtt", "timestamp": msg.timestamp,
        })

    async def _handle_ha_discovery(self, msg: MQTTMessage, workflow: Optional[str]):
        parts = msg.topic.split("/")
        if len(parts) >= 4 and parts[-1] == "config":
            logger.debug(f"HA Discovery: {msg.topic}")

    async def _handle_default(self, msg: MQTTMessage, workflow: Optional[str]):
        logger.debug(f"MQTT [{msg.topic}]: {msg.payload[:100]}")

    def add_openclaw_trigger(self, callback: Callable):
        self._openclaw_trigger_callbacks.append(callback)

    async def _trigger_openclaw_workflow(self, workflow: Optional[str], context: dict):
        if not workflow:
            return
        for cb in self._openclaw_trigger_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(workflow, context))
                else:
                    cb(workflow, context)
            except Exception as exc:
                logger.error(f"OpenClaw trigger error (workflow={workflow}): {exc}")

    async def add_subscription(self, topic: str, handler: Callable, qos: int = 0):
        self._dispatcher.register(topic, handler)
        if self._client:
            await self._client.subscribe(topic, qos=qos)
        else:
            self._subscriptions.append((topic, qos))

    def get_history(self) -> MessageHistory:
        return self._history

    def get_recent_messages(self, seconds: float = 60) -> List[MQTTMessage]:
        return self._history.get_recent(seconds)

    def get_messages_by_vendor(self, vendor: str) -> List[MQTTMessage]:
        return self._history.get_by_vendor(vendor)

    def history_summary(self) -> dict:
        return self._history.summary()

    @property
    def _start_time(self):
        if not hasattr(self, "_agent_start_time"):
            self._agent_start_time = time.time()
        return self._agent_start_time


async def _main():
    logging.basicConfig(level=logging.INFO)
    agent = MQTTAgent.from_env()
    async def openclaw_handler(workflow: str, context: dict):
        logger.info(f"[OpenClaw] Trigger → workflow={workflow}, context={context}")
    agent.add_openclaw_trigger(openclaw_handler)
    print("Starting Symphony MQTT Agent (Bob the Conductor)")
    print(f"Connecting to broker: {agent._host}:{agent._port}")
    print(f"Subscriptions: {len(agent._subscriptions)} topics")
    print("Press Ctrl+C to stop.\n")
    try:
        await agent.run_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(_main())
