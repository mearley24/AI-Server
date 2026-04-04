"""Validate D-Tools / manual component lists using knowledge/hardware system graph."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("openclaw.design_validator")

_graph_module: Any = None


def _load_graph_module():
    global _graph_module
    if _graph_module is not None:
        return _graph_module
    default = Path("/app/knowledge/hardware/system_graph.py")
    if not default.exists():
        default = Path(__file__).resolve().parent.parent / "knowledge" / "hardware" / "system_graph.py"
    path = os.environ.get("SYSTEM_GRAPH_PATH", str(default))
    spec = importlib.util.spec_from_file_location("symphony_system_graph", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load system graph from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _graph_module = mod
    return mod


class DesignValidator:
    """Runs CompatibilityEngine.validate_system on component dicts."""

    def __init__(self) -> None:
        self._mod = _load_graph_module()
        self._engine = self._mod.CompatibilityEngine()

    def validate_components(self, components: list[dict[str, Any]]) -> dict[str, Any]:
        comp_objs = []
        for row in components:
            comp_objs.append(self._mod._component_from_dict(row))
        report = self._engine.validate_system(comp_objs)
        return {
            "passes": report.passes,
            "warnings": report.warnings,
            "failures": report.failures,
            "suggestions": report.suggestions,
            "summary": f"{len(report.passes)} pass, {len(report.warnings)} warn, {len(report.failures)} fail",
        }
