"""
Redis-backed unified context for Bob's Brain.

Each section maps to a Redis hash:
  bob:context:<section>

Values are JSON-encoded per field so heterogeneous types are preserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger("openclaw.context_engine")

DEFAULT_SECTIONS = (
    "portfolio",
    "email",
    "calendar",
    "project",
    "infrastructure",
    "intelligence",
    "owner",
)

EVENT_TO_CONTEXT: dict[str, Callable[[dict[str, Any]], tuple[str, str, Any] | None]] = {
    "trade_executed": lambda e: (
        "portfolio",
        "last_trade",
        (e.get("payload") or {}).get("timestamp") or e.get("timestamp"),
    ),
    "email_received": lambda e: ("email", "pending_count", "+1"),
    "proposal_sent": lambda e: ("project", "proposals_pending", "+1"),
    "payment_received": lambda e: ("project", "payments_pending", "-1"),
}


class ContextStore:
    """
    Redis hash per domain: bob:context:{domain}

    Can work with either redis.asyncio client or redis sync client.
    Prefer async methods inside running event loops.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        data_dir: str | Path | None = None,
    ):
        self._redis = redis_client
        self._redis_url = (
            redis_url
            or os.getenv("CONTEXT_REDIS_URL")
            or os.getenv("REDIS_URL")
            or "redis://172.18.0.100:6379"
        )
        self._data_dir = Path(data_dir or os.getenv("DATA_DIR", "/app/data"))
        self._snapshot_dir = self._data_dir / "context_snapshots"
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            except Exception as exc:
                logger.warning("[context-engine] redis init failed: %s", exc)
                self._redis = None

    @staticmethod
    def _split_path(path: str) -> tuple[str, str]:
        if "." not in path:
            raise ValueError("path must be section.key, got: %r" % path)
        section, key = path.split(".", 1)
        if not section or not key:
            raise ValueError("path must be section.key, got: %r" % path)
        return section, key

    @staticmethod
    def _key(section: str) -> str:
        return f"bob:context:{section}"

    async def _call(self, value: Any) -> Any:
        if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
            return await value
        return value

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), default=str)

    @staticmethod
    def _json_loads(value: str | None) -> Any:
        if value is None:
            return None
        try:
            return json.loads(value)
        except Exception:
            return value

    async def aget(self, path: str) -> Any:
        if not self._redis:
            return None
        section, key = self._split_path(path)
        raw = await self._call(self._redis.hget(self._key(section), key))
        return self._json_loads(raw)

    async def aset(self, path: str, value: Any, ttl_seconds: int = 300) -> None:
        if not self._redis:
            return
        section, key = self._split_path(path)
        hkey = self._key(section)
        await self._call(self._redis.hset(hkey, key, self._json_dumps(value)))
        await self._call(self._redis.expire(hkey, int(ttl_seconds)))

    async def aget_section(self, section: str) -> dict[str, Any]:
        if not self._redis:
            return {}
        data = await self._call(self._redis.hgetall(self._key(section)))
        out: dict[str, Any] = {}
        for key, val in (data or {}).items():
            out[key] = self._json_loads(val)
        return out

    async def aupdate_section(self, section: str, data: dict[str, Any], ttl_seconds: int = 300) -> None:
        if not self._redis or not data:
            return
        hkey = self._key(section)
        encoded = {k: self._json_dumps(v) for k, v in data.items()}
        await self._call(self._redis.hset(hkey, mapping=encoded))
        await self._call(self._redis.expire(hkey, int(ttl_seconds)))

    async def aincr(self, path: str, delta: int, ttl_seconds: int = 300) -> int:
        if not self._redis:
            return 0
        current = await self.aget(path)
        try:
            base = int(current or 0)
        except Exception:
            base = 0
        new_val = base + int(delta)
        await self.aset(path, new_val, ttl_seconds=ttl_seconds)
        return new_val

    async def get_snapshot(self, sections: tuple[str, ...] = DEFAULT_SECTIONS) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for section in sections:
            out[section] = await self.aget_section(section)
        return out

    async def handle_event(self, event: dict[str, Any]) -> None:
        """
        Ingest bus messages and direct service events.

        Supported shapes:
        - AgentBus envelope: {"from","to","type","payload","timestamp"}
        - Service event: {"service","event_type","payload","timestamp"}
        """
        try:
            event_type = event.get("event_type")
            payload = event.get("payload") or {}

            if not event_type and event.get("type") in {"request", "response", "alert"}:
                nested = payload if isinstance(payload, dict) else {}
                event_type = nested.get("event_type")
                payload = nested.get("payload") or nested

            if not event_type:
                return

            mapper = EVENT_TO_CONTEXT.get(event_type)
            if mapper:
                mapped = mapper({"payload": payload, "timestamp": event.get("timestamp"), "event_type": event_type})
                if mapped:
                    section, key, value = mapped
                    if isinstance(value, str) and value in {"+1", "-1"}:
                        await self.aincr(f"{section}.{key}", int(value))
                    else:
                        await self.aset(f"{section}.{key}", value)

            if event_type == "email_received":
                sender = (
                    payload.get("from")
                    or payload.get("sender")
                    or payload.get("email_from")
                    or ""
                )
                if sender:
                    await self.aset("email.last_sender", sender)
                subject = payload.get("subject", "")
                if subject:
                    await self.aset("email.last_subject", subject)
                await self.aset("email.last_checked", datetime.now(timezone.utc).isoformat())

            if event_type == "trade_executed":
                side = payload.get("side")
                if side:
                    await self.aset("portfolio.last_side", side)
                symbol = payload.get("symbol") or payload.get("market")
                if symbol:
                    await self.aset("portfolio.last_symbol", symbol)
        except Exception as exc:
            logger.warning("[context-engine] handle_event failed: %s", exc)

    async def snapshot_to_disk(self) -> Path:
        snapshot = await self.get_snapshot()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._snapshot_dir / f"context_{ts}.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": snapshot,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info("[context-engine] snapshot written: %s", path)

        # Keep latest 24
        files = sorted(self._snapshot_dir.glob("context_*.json"), reverse=True)
        for old in files[24:]:
            try:
                old.unlink()
            except Exception:
                pass
        return path

    async def update_context_md(
        self,
        path: str | Path = "CONTEXT.md",
        auto_git: bool = False,
    ) -> bool:
        snapshot = await self.get_snapshot()
        md = format_context_as_markdown(snapshot)
        out_path = Path(path)
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if md == current:
            return False
        out_path.write_text(md, encoding="utf-8")
        logger.info("[context-engine] CONTEXT.md updated")

        if auto_git:
            ts = datetime.now(timezone.utc).isoformat()
            try:
                subprocess.run(["git", "add", str(out_path)], check=False)
                subprocess.run(
                    ["git", "commit", "-m", f"auto: update CONTEXT.md {ts}"],
                    check=False,
                )
                subprocess.run(["git", "push"], check=False)
            except Exception as exc:
                logger.warning("[context-engine] git auto-update failed: %s", exc)
        return True

    # Optional sync wrappers for one-off scripts.
    def _run_sync(self, coro: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
            raise RuntimeError("Sync wrapper called in running event loop; use async methods")
        except RuntimeError as exc:
            if "no running event loop" in str(exc).lower():
                return asyncio.run(coro)
            raise

    def get(self, path: str) -> Any:
        return self._run_sync(self.aget(path))

    def set(self, path: str, value: Any, ttl_seconds: int = 300) -> None:
        self._run_sync(self.aset(path, value, ttl_seconds=ttl_seconds))

    def get_section(self, section: str) -> dict[str, Any]:
        return self._run_sync(self.aget_section(section))

    def update_section(self, section: str, data: dict[str, Any], ttl_seconds: int = 300) -> None:
        self._run_sync(self.aupdate_section(section, data, ttl_seconds=ttl_seconds))


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def format_context_as_markdown(snapshot: dict[str, Any]) -> str:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        "# Symphony Smart Homes - Active Context",
        f"## Last Updated: {now}",
        "",
    ]
    for section in DEFAULT_SECTIONS:
        lines.append(f"## {section.title()}")
        data = snapshot.get(section) or {}
        if not data:
            lines.append("- (no data)")
            lines.append("")
            continue
        for key in sorted(data.keys()):
            lines.append(f"- {key}: {_fmt(data[key])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
