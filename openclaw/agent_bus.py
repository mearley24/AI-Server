"""
OpenClaw Multi-Agent Communication Bus
Redis pub/sub for agent-to-agent messaging.

Channel: agents:messages
Supports direct messages (to specific agent) and broadcasts (to all).
Falls back gracefully if Redis is unavailable.
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger("openclaw.agent_bus")


class AgentBus:
    """Redis pub/sub bus for inter-agent communication."""

    CHANNEL = "agents:messages"
    # In-memory buffer for recent messages (for query endpoint)
    MAX_BUFFER = 500

    def __init__(self, redis_url: str = ""):
        self._redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._subscribers: dict[str, list[Callable]] = {}
        self._message_buffer: deque[dict] = deque(maxlen=self.MAX_BUFFER)
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None

    async def start(self):
        """Connect to Redis and start listening."""
        if not self._redis_url:
            logger.warning("agent_bus: no REDIS_URL, running in local-only mode")
            return

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self.CHANNEL)
            self._running = True
            self._listen_task = asyncio.create_task(self._listen_loop())
            logger.info("agent_bus started on channel=%s", self.CHANNEL)
        except Exception as e:
            logger.warning("agent_bus: Redis unavailable, local-only mode: %s", e)
            self._redis = None

    async def _listen_loop(self):
        """Background task: read messages from Redis and dispatch to subscribers."""
        while self._running and self._pubsub:
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    self._message_buffer.append(data)

                    # Dispatch to subscribers
                    to_agent = data.get("to", "broadcast")
                    if to_agent == "broadcast":
                        for agent_id, callbacks in self._subscribers.items():
                            for cb in callbacks:
                                try:
                                    await cb(data)
                                except Exception as e:
                                    logger.error("agent_bus callback error agent=%s: %s", agent_id, e)
                    elif to_agent in self._subscribers:
                        for cb in self._subscribers[to_agent]:
                            try:
                                await cb(data)
                            except Exception as e:
                                logger.error("agent_bus callback error agent=%s: %s", to_agent, e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("agent_bus listen error: %s", e)
                await asyncio.sleep(1)

    async def publish(self, from_agent: str, to_agent: str, msg_type: str, payload: dict):
        """Send a message on the bus.

        Args:
            from_agent: sender agent ID
            to_agent: recipient agent ID or "broadcast"
            msg_type: "request", "response", or "alert"
            payload: arbitrary dict
        """
        message = {
            "from": from_agent,
            "to": to_agent,
            "type": msg_type,
            "payload": payload,
            "timestamp": time.time(),
        }

        # Always buffer locally
        self._message_buffer.append(message)

        # Publish to Redis if available
        if self._redis:
            try:
                await self._redis.publish(self.CHANNEL, json.dumps(message))
                logger.info("agent_bus_publish from=%s to=%s type=%s", from_agent, to_agent, msg_type)
            except Exception as e:
                logger.warning("agent_bus publish failed (buffered locally): %s", e)
        else:
            # No Redis — dispatch locally
            logger.info("agent_bus_local from=%s to=%s type=%s", from_agent, to_agent, msg_type)
            if to_agent == "broadcast":
                for agent_id, callbacks in self._subscribers.items():
                    for cb in callbacks:
                        try:
                            await cb(message)
                        except Exception as e:
                            logger.error("agent_bus local callback error: %s", e)
            elif to_agent in self._subscribers:
                for cb in self._subscribers[to_agent]:
                    try:
                        await cb(message)
                    except Exception as e:
                        logger.error("agent_bus local callback error: %s", e)

    def subscribe(self, agent_id: str, callback: Callable):
        """Register a callback for messages addressed to this agent or broadcast."""
        if agent_id not in self._subscribers:
            self._subscribers[agent_id] = []
        self._subscribers[agent_id].append(callback)
        logger.info("agent_bus_subscribe agent=%s", agent_id)

    def get_messages(self, agent_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Get recent messages, optionally filtered by agent_id (as sender or recipient)."""
        messages = list(self._message_buffer)
        if agent_id:
            messages = [
                m for m in messages
                if m.get("to") in (agent_id, "broadcast") or m.get("from") == agent_id
            ]
        return messages[-limit:]

    async def stop(self):
        """Shutdown the bus."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(self.CHANNEL)
                await self._pubsub.aclose()
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
        logger.info("agent_bus stopped")
