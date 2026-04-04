"""Minimal structlog compatibility shim for environments without structlog.

If the real dependency is installed, Python will typically import it first from site-packages.
This fallback allows local smoke-import checks to run on bare systems.
"""

from __future__ import annotations

import logging
from typing import Any


class _ShimLogger:
    def __init__(self, name: str):
        self._log = logging.getLogger(name)

    def bind(self, **_: Any) -> "_ShimLogger":
        return self

    def _fmt(self, event: Any, kwargs: dict[str, Any]) -> str:
        if kwargs:
            return f"{event} " + " ".join(f"{k}={v}" for k, v in kwargs.items())
        return str(event)

    def debug(self, event: Any, **kwargs: Any) -> None:
        self._log.debug(self._fmt(event, kwargs))

    def info(self, event: Any, **kwargs: Any) -> None:
        self._log.info(self._fmt(event, kwargs))

    def warning(self, event: Any, **kwargs: Any) -> None:
        self._log.warning(self._fmt(event, kwargs))

    warn = warning

    def error(self, event: Any, **kwargs: Any) -> None:
        self._log.error(self._fmt(event, kwargs))

    def exception(self, event: Any, **kwargs: Any) -> None:
        self._log.exception(self._fmt(event, kwargs))


def get_logger(name: str | None = None) -> _ShimLogger:
    return _ShimLogger(name or "structlog-shim")
