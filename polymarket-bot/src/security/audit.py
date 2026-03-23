"""Audit trail — structured JSON logging for every trade and API call.

Writes rotating daily JSON log files to /data/audit/ with configurable
retention (default 90 days).  Provides a query interface used by the
GET /audit REST endpoint.
"""

from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AuditTrail:
    """Append-only audit log for trade decisions and API interactions.

    Each day gets its own JSON-lines file:
        /data/audit/2026-03-23.jsonl

    Old files are pruned according to retention_days on each write.
    """

    def __init__(
        self,
        audit_dir: str | Path = "/data/audit",
        retention_days: int = 90,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._retention_days = retention_days
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._current_date = ""
        self._current_file: Any = None

        logger.info(
            "audit_trail_initialized",
            path=str(self._audit_dir),
            retention_days=retention_days,
        )

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_file(self) -> Any:
        """Get the current day's log file handle, rotating if needed."""
        today = self._today()
        if today != self._current_date:
            if self._current_file is not None:
                self._current_file.close()
            self._current_date = today
            path = self._audit_dir / f"{today}.jsonl"
            self._current_file = open(path, "a", encoding="utf-8")
            self._prune_old_files()
        return self._current_file

    def _prune_old_files(self) -> None:
        """Remove audit files older than retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        for filepath in sorted(self._audit_dir.glob("*.jsonl")):
            date_part = filepath.stem  # e.g. "2026-01-01"
            if date_part < cutoff_str:
                try:
                    filepath.unlink()
                    logger.info("audit_file_pruned", file=str(filepath))
                except OSError as exc:
                    logger.error("audit_prune_error", file=str(filepath), error=str(exc))

    def _write_entry(self, entry: dict[str, Any]) -> None:
        """Write a single audit entry as a JSON line."""
        entry["_ts"] = datetime.now(timezone.utc).isoformat()
        f = self._get_file()
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()

    def log_trade_decision(
        self,
        strategy: str,
        market: str,
        side: str,
        size: float,
        price: float,
        order_id: str = "",
        fill_status: str = "",
        debate_result: dict[str, Any] | None = None,
        latency_signal: dict[str, Any] | None = None,
        order_flow_signal: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a trade decision with full context."""
        entry: dict[str, Any] = {
            "type": "trade_decision",
            "strategy": strategy,
            "market": market,
            "side": side,
            "size": size,
            "price": price,
            "order_id": order_id,
            "fill_status": fill_status,
        }
        if debate_result is not None:
            entry["debate_result"] = debate_result
        if latency_signal is not None:
            entry["latency_signal"] = latency_signal
        if order_flow_signal is not None:
            entry["order_flow_signal"] = order_flow_signal
        if metadata:
            entry["metadata"] = metadata

        self._write_entry(entry)

    def log_api_call(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log an outbound API call (no secrets)."""
        entry: dict[str, Any] = {
            "type": "api_call",
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 1),
        }
        if metadata:
            entry["metadata"] = metadata
        self._write_entry(entry)

    def log_security_event(
        self,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a security-relevant event (kill switch, rate limit, etc.)."""
        entry: dict[str, Any] = {
            "type": "security_event",
            "event": event,
        }
        if details:
            entry["details"] = details
        self._write_entry(entry)

    def query(
        self,
        date: str | None = None,
        strategy: str | None = None,
        entry_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query the audit trail with optional filters.

        Parameters:
            date: ISO date string (e.g. "2026-03-23"). Defaults to today.
            strategy: Filter by strategy name.
            entry_type: Filter by entry type ("trade_decision", "api_call", "security_event").
            limit: Maximum entries to return.
        """
        target_date = date or self._today()
        filepath = self._audit_dir / f"{target_date}.jsonl"

        if not filepath.exists():
            return []

        results: list[dict[str, Any]] = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Apply filters
                if strategy and entry.get("strategy") != strategy:
                    continue
                if entry_type and entry.get("type") != entry_type:
                    continue

                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def get_available_dates(self) -> list[str]:
        """Return list of dates that have audit data."""
        dates = []
        for filepath in sorted(self._audit_dir.glob("*.jsonl")):
            dates.append(filepath.stem)
        return dates

    def close(self) -> None:
        """Close any open file handles."""
        if self._current_file is not None:
            self._current_file.close()
            self._current_file = None
