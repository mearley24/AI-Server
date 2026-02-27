"""
ha_camera_monitor.py — Symphony Smart Homes
Camera Monitoring Module for Bob the Conductor

Manages camera feeds from Luma cameras via Home Assistant:
- Configurable polling for periodic snapshots
- On-demand snapshot capture and storage
- Motion detection event handling (from HA WebSocket events)
- Auto-save on motion with configurable retention policy
- Camera status dashboard data aggregation
- RTSP proxy information for direct access from Bob's network
- Luma NVR recording queries via HA

Usage:
    monitor = CameraMonitor(ha_client, snapshot_dir="./snapshots")
    await monitor.start()
    snapshot_path = await monitor.capture_snapshot("camera.luma_front_door")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("symphony.ha_camera_monitor")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SNAPSHOT_DIR = "./snapshots"
DEFAULT_POLL_INTERVAL = 30          # seconds between routine polling
MOTION_SNAPSHOT_BURST = 3          # snapshots on motion event
MOTION_SNAPSHOT_INTERVAL = 2.0     # seconds between burst snapshots
MAX_SNAPSHOT_AGE_DAYS = 30         # auto-delete snapshots older than this
SNAPSHOT_FILENAME_FORMAT = "{camera}_{timestamp}.jpg"
CAMERA_TIMEOUT = 10                 # seconds for camera HTTP request


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class CameraInfo:
    entity_id: str
    friendly_name: str
    state: str                          # "idle", "recording", "streaming", "unavailable"
    stream_url: Optional[str] = None
    last_snapshot_path: Optional[str] = None
    last_snapshot_time: Optional[float] = None
    motion_detected: bool = False
    is_luma: bool = False
    location: Optional[str] = None
    nvr_channel: Optional[int] = None
    attributes: dict = field(default_factory=dict)

    def is_online(self) -> bool:
        return self.state not in ("unavailable", "unknown")

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "friendly_name": self.friendly_name,
            "state": self.state,
            "stream_url": self.stream_url,
            "last_snapshot_path": self.last_snapshot_path,
            "last_snapshot_time": self.last_snapshot_time,
            "motion_detected": self.motion_detected,
            "is_luma": self.is_luma,
            "location": self.location,
            "nvr_channel": self.nvr_channel,
            "online": self.is_online(),
        }


@dataclass
class MotionEvent:
    camera_entity: str
    timestamp: float
    snapshot_paths: List[str] = field(default_factory=list)
    confidence: float = 0.0
    zone: Optional[str] = None
    raw_event: dict = field(default_factory=dict)


@dataclass
class SnapshotRecord:
    path: str
    camera_entity: str
    timestamp: float
    triggered_by: str          # "motion", "poll", "on_demand"
    size_bytes: int = 0

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Camera Monitor
# ---------------------------------------------------------------------------

class CameraMonitor:
    """
    Manages camera feeds, snapshots, and motion events for all Luma cameras
    visible through Home Assistant.
    """

    def __init__(
        self,
        ha_client,                         # HAClient instance
        snapshot_dir: str = DEFAULT_SNAPSHOT_DIR,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        camera_entities: Optional[List[str]] = None,
        motion_snapshot_burst: int = MOTION_SNAPSHOT_BURST,
        max_snapshot_age_days: int = MAX_SNAPSHOT_AGE_DAYS,
    ):
        self._ha = ha_client
        self._snapshot_dir = Path(snapshot_dir)
        self._poll_interval = poll_interval
        self._camera_entities = camera_entities or []   # empty = auto-discover
        self._motion_burst = motion_snapshot_burst
        self._max_age_days = max_snapshot_age_days

        self._cameras: Dict[str, CameraInfo] = {}
        self._snapshot_records: List[SnapshotRecord] = []
        self._motion_events: List[MotionEvent] = []
        self._motion_callbacks: List[Callable] = []
        self._poll_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Ensure snapshot directory exists
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the camera monitor (background polling + event subscription)."""
        self._running = True

        # Auto-discover cameras if no list was provided
        if not self._camera_entities:
            await self._discover_cameras()
        else:
            # Initialize from the provided list
            for entity_id in self._camera_entities:
                await self._refresh_camera_info(entity_id)

        # Subscribe to HA events for motion detection
        await self._ha.subscribe_events(self._on_ha_event)

        # Start polling loop
        self._poll_task = asyncio.create_task(self._poll_loop())

        # Start cleanup loop
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(f"Camera monitor started: {len(self._cameras)} cameras, "
                    f"poll={self._poll_interval}s, snapshot_dir={self._snapshot_dir}")

    async def stop(self):
        """Stop the camera monitor."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Camera monitor stopped")

    # ------------------------------------------------------------------
    # Camera discovery
    # ------------------------------------------------------------------

    async def _discover_cameras(self):
        """Auto-discover camera entities from Home Assistant."""
        states = await self._ha.get_states()
        camera_states = [s for s in states if s.entity_id.startswith("camera.")]

        for state in camera_states:
            await self._refresh_camera_info(state.entity_id)

        logger.info(f"Discovered {len(self._cameras)} camera(s): "
                    f"{', '.join(sorted(self._cameras.keys()))}")

    async def _refresh_camera_info(self, entity_id: str):
        """Refresh CameraInfo for a single entity."""
        try:
            state = await self._ha.get_state(entity_id)
            attrs = state.attributes
            friendly_name = attrs.get("friendly_name", entity_id)
            is_luma = (
                "luma" in entity_id.lower()
                or "luma" in friendly_name.lower()
                or attrs.get("brand", "").lower() == "luma"
            )
            location = self._infer_location(entity_id, friendly_name)

            # Update or create
            if entity_id in self._cameras:
                cam = self._cameras[entity_id]
                cam.state = state.state
                cam.attributes = attrs
                cam.friendly_name = friendly_name
            else:
                self._cameras[entity_id] = CameraInfo(
                    entity_id=entity_id,
                    friendly_name=friendly_name,
                    state=state.state,
                    is_luma=is_luma,
                    location=location,
                    attributes=attrs,
                    nvr_channel=attrs.get("channel"),
                )
        except Exception as exc:
            logger.warning(f"Could not fetch camera info for {entity_id}: {exc}")

    @staticmethod
    def _infer_location(entity_id: str, friendly_name: str) -> Optional[str]:
        """Infer room/location from entity ID or friendly name."""
        location_keywords = [
            "front", "back", "rear", "side", "driveway", "garage", "door",
            "yard", "patio", "pool", "gate", "entry", "foyer", "living",
            "kitchen", "bedroom", "office", "basement", "attic",
        ]
        combined = (entity_id + " " + friendly_name).lower()
        for kw in location_keywords:
            if kw in combined:
                return kw.title()
        return None

    # ------------------------------------------------------------------
    # Snapshot capture
    # ------------------------------------------------------------------

    async def capture_snapshot(
        self,
        camera_entity: str,
        triggered_by: str = "on_demand",
        label: Optional[str] = None,
    ) -> Optional[str]:
        """
        Capture and save a snapshot from a camera.

        Args:
            camera_entity: HA entity ID (e.g. "camera.luma_front_door")
            triggered_by: "motion", "poll", or "on_demand"
            label: Optional suffix for the filename

        Returns:
            Absolute path to the saved JPEG, or None on failure.
        """
        try:
            image_bytes = await self._ha.get_camera_snapshot(camera_entity)
        except Exception as exc:
            logger.warning(f"Snapshot failed for {camera_entity}: {exc}")
            return None

        # Build filename
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        cam_slug = camera_entity.replace("camera.", "").replace("/", "_")
        suffix = f"_{label}" if label else ""
        filename = f"{cam_slug}_{ts_str}{suffix}.jpg"

        # Organize by date
        date_dir = self._snapshot_dir / ts.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        filepath = date_dir / filename

        filepath.write_bytes(image_bytes)
        logger.info(f"Snapshot saved: {filepath} ({len(image_bytes):,} bytes)")

        # Record
        record = SnapshotRecord(
            path=str(filepath),
            camera_entity=camera_entity,
            timestamp=ts.timestamp(),
            triggered_by=triggered_by,
            size_bytes=len(image_bytes),
        )
        self._snapshot_records.append(record)

        # Update camera info
        if camera_entity in self._cameras:
            cam = self._cameras[camera_entity]
            cam.last_snapshot_path = str(filepath)
            cam.last_snapshot_time = record.timestamp

        return str(filepath)

    async def capture_burst(
        self,
        camera_entity: str,
        count: int = MOTION_SNAPSHOT_BURST,
        interval: float = MOTION_SNAPSHOT_INTERVAL,
        label: str = "burst",
    ) -> List[str]:
        """
        Capture a rapid burst of snapshots (used for motion events).

        Returns:
            List of saved file paths.
        """
        paths = []
        for i in range(count):
            path = await self.capture_snapshot(camera_entity, triggered_by="motion", label=f"{label}_{i+1}")
            if path:
                paths.append(path)
            if i < count - 1:
                await asyncio.sleep(interval)
        return paths

    # ------------------------------------------------------------------
    # Motion detection
    # ------------------------------------------------------------------

    def add_motion_callback(self, callback: Callable):
        """
        Register a callback for motion events.
        Callback signature: callback(event: MotionEvent)
        """
        self._motion_callbacks.append(callback)

    async def _on_ha_event(self, event_type: str, event_data: dict):
        """Handle HA events — specifically state_changed events for cameras."""
        if event_type == "state_changed":
            entity_id = event_data.get("entity_id", "")
            if entity_id.startswith("camera."):
                await self._handle_camera_state_change(entity_id, event_data)

        # Handle HA's built-in motion events
        elif event_type in ("motion_detected", "image_processing_found_face"):
            await self._handle_ha_motion_event(event_data)

        # Handle MQTT-based motion from Luma
        elif event_type == "mqtt_message_received":
            topic = event_data.get("topic", "")
            if "motion" in topic and "luma" in topic:
                camera_slug = topic.split("/")[1] if "/" in topic else ""
                entity_id = f"camera.{camera_slug}"
                await self._handle_motion_detected(entity_id, event_data)

    async def _handle_camera_state_change(self, entity_id: str, event_data: dict):
        """Handle camera entity state changes."""
        new_state = event_data.get("new_state", {})
        state_value = new_state.get("state", "") if new_state else ""

        if entity_id in self._cameras:
            self._cameras[entity_id].state = state_value

        # Detect when a camera comes back online
        old_state = event_data.get("old_state", {})
        old_value = old_state.get("state", "") if old_state else ""
        if old_value == "unavailable" and state_value not in ("unavailable", "unknown"):
            logger.info(f"Camera back online: {entity_id}")

    async def _handle_ha_motion_event(self, event_data: dict):
        """Handle built-in HA motion detection events."""
        entity_id = event_data.get("entity_id", "")
        if not entity_id or not entity_id.startswith("camera."):
            return
        await self._handle_motion_detected(entity_id, event_data)

    async def _handle_motion_detected(self, entity_id: str, raw_event: dict):
        """Core motion detection handler — captures burst and fires callbacks."""
        logger.info(f"Motion detected: {entity_id}")

        if entity_id in self._cameras:
            self._cameras[entity_id].motion_detected = True

        # Capture burst snapshots
        snapshot_paths = await self.capture_burst(entity_id, count=self._motion_burst)

        # Build motion event record
        event = MotionEvent(
            camera_entity=entity_id,
            timestamp=time.time(),
            snapshot_paths=snapshot_paths,
            zone=raw_event.get("zone"),
            raw_event=raw_event,
        )
        self._motion_events.append(event)

        # Fire registered callbacks
        for cb in self._motion_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(event))
                else:
                    cb(event)
            except Exception as exc:
                logger.error(f"Motion callback error: {exc}")

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        """Periodically refresh camera states and take routine snapshots."""
        while self._running:
            await asyncio.sleep(self._poll_interval)
            for entity_id in list(self._cameras.keys()):
                await self._refresh_camera_info(entity_id)

    # ------------------------------------------------------------------
    # Snapshot cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self):
        """Delete old snapshots beyond the retention window."""
        while self._running:
            await asyncio.sleep(3600)  # run hourly
            await self._cleanup_old_snapshots()

    async def _cleanup_old_snapshots(self):
        """Remove snapshots older than max_snapshot_age_days."""
        cutoff = datetime.now() - timedelta(days=self._max_age_days)
        deleted = 0
        for snapshot_dir in self._snapshot_dir.iterdir():
            if snapshot_dir.is_dir():
                try:
                    dir_date = datetime.strptime(snapshot_dir.name, "%Y-%m-%d")
                    if dir_date < cutoff:
                        for f in snapshot_dir.iterdir():
                            if f.is_file():
                                f.unlink()
                                deleted += 1
                        snapshot_dir.rmdir()
                except ValueError:
                    pass  # Not a date directory
        if deleted:
            logger.info(f"Cleaned up {deleted} old snapshots")

    # ------------------------------------------------------------------
    # RTSP proxy info
    # ------------------------------------------------------------------

    async def get_stream_info(self, entity_id: str) -> dict:
        """
        Get RTSP/stream information for a camera.
        Returns URLs and stream metadata for direct access from Bob's network.
        """
        cam = self._cameras.get(entity_id)
        if not cam:
            await self._refresh_camera_info(entity_id)
            cam = self._cameras.get(entity_id)
        if not cam:
            return {"error": f"Camera {entity_id} not found"}

        # Fetch fresh stream URL
        stream_url = await self._ha.get_camera_stream_url(entity_id)
        mjpeg_url = await self._ha.get_camera_video_url(entity_id)

        return {
            "entity_id": entity_id,
            "friendly_name": cam.friendly_name,
            "state": cam.state,
            "rtsp_url": stream_url,
            "mjpeg_url": mjpeg_url,
            "proxy_url": f"{self._ha._ha_url}/api/camera_proxy_stream/{entity_id}",
            "snapshot_url": f"{self._ha._ha_url}/api/camera_proxy/{entity_id}",
            "is_online": cam.is_online(),
            "nvr_channel": cam.nvr_channel,
        }

    # ------------------------------------------------------------------
    # Dashboard & reporting
    # ------------------------------------------------------------------

    def get_dashboard_data(self) -> dict:
        """
        Return camera status data for a dashboard view.
        Used by Bob to display current camera health.
        """
        cameras = [cam.to_dict() for cam in self._cameras.values()]
        online = sum(1 for c in self._cameras.values() if c.is_online())
        motion_active = sum(1 for c in self._cameras.values() if c.motion_detected)
        recent_snapshots = sorted(
            self._snapshot_records,
            key=lambda r: r.timestamp,
            reverse=True,
        )[:10]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_cameras": len(cameras),
                "online": online,
                "offline": len(cameras) - online,
                "motion_active": motion_active,
                "total_snapshots": len(self._snapshot_records),
                "total_motion_events": len(self._motion_events),
            },
            "cameras": cameras,
            "recent_snapshots": [
                {
                    "camera": r.camera_entity,
                    "path": r.path,
                    "time": r.iso_time,
                    "triggered_by": r.triggered_by,
                    "size_kb": r.size_bytes // 1024,
                }
                for r in recent_snapshots
            ],
            "recent_motion_events": [
                {
                    "camera": e.camera_entity,
                    "time": datetime.fromtimestamp(e.timestamp, tz=timezone.utc).isoformat(),
                    "snapshots": len(e.snapshot_paths),
                    "zone": e.zone,
                }
                for e in sorted(self._motion_events, key=lambda e: e.timestamp, reverse=True)[:5]
            ],
        }

    def get_cameras(self) -> Dict[str, CameraInfo]:
        """Return all known cameras."""
        return dict(self._cameras)

    def get_motion_events(self, last_n: int = 20) -> List[MotionEvent]:
        """Return the N most recent motion events."""
        return sorted(self._motion_events, key=lambda e: e.timestamp, reverse=True)[:last_n]

    # ------------------------------------------------------------------
    # Luma NVR query helpers
    # ------------------------------------------------------------------

    async def query_nvr_recordings(
        self,
        camera_entity: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Query Luma NVR for recorded footage via Home Assistant history.
        Returns a list of recording events for the given time window.

        Note: Full NVR API access requires the Luma integration or direct API access.
        This method uses HA history as a proxy for recording events.
        """
        start = start or datetime.now(timezone.utc) - timedelta(hours=24)
        end = end or datetime.now(timezone.utc)

        try:
            history = await self._ha.get_history(camera_entity, start=start, end=end)
            recordings = []
            for state_list in history:
                for state in state_list:
                    if state.get("state") == "recording":
                        recordings.append({
                            "camera": camera_entity,
                            "start_time": state.get("last_changed"),
                            "state": "recording",
                        })
            return recordings
        except Exception as exc:
            logger.warning(f"NVR query failed for {camera_entity}: {exc}")
            return []

    async def get_nvr_snapshot_url(
        self,
        camera_entity: str,
        timestamp: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Get a URL for a historical NVR snapshot (if Luma supports it via HA).
        Returns current snapshot URL if no timestamp specified.
        """
        if timestamp:
            # Historical snapshots require NVR direct API; return HA proxy as fallback
            logger.debug(f"Historical NVR snapshot requested for {camera_entity} at {timestamp}")
        return f"{self._ha._ha_url}/api/camera_proxy/{camera_entity}"


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_camera_monitor(ha_client, config: Optional[dict] = None) -> CameraMonitor:
    """
    Create a CameraMonitor from a config dict (as loaded from ha_config.json).
    """
    cfg = config or {}
    return CameraMonitor(
        ha_client=ha_client,
        snapshot_dir=os.environ.get("CAMERA_SNAPSHOT_DIR", cfg.get("snapshot_dir", DEFAULT_SNAPSHOT_DIR)),
        poll_interval=cfg.get("camera_poll_interval", DEFAULT_POLL_INTERVAL),
        camera_entities=cfg.get("camera_entities", []),
        motion_snapshot_burst=cfg.get("motion_snapshot_burst", MOTION_SNAPSHOT_BURST),
        max_snapshot_age_days=cfg.get("max_snapshot_age_days", MAX_SNAPSHOT_AGE_DAYS),
    )


# ---------------------------------------------------------------------------
# Optional type annotation (avoid hard import of ha_bridge)
# ---------------------------------------------------------------------------
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ha_bridge import HAClient
