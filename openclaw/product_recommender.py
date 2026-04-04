"""Lightweight product hints from hardware JSON catalogs + graph validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from design_validator import DesignValidator


def _hardware_dir() -> Path:
    env = os.environ.get("HARDWARE_DIR")
    if env:
        return Path(env)
    docker = Path("/app/knowledge/hardware")
    if docker.exists():
        return docker
    return Path(__file__).resolve().parent.parent / "knowledge" / "hardware"


def _load_tv_catalog() -> list[dict[str, Any]]:
    p = _hardware_dir() / "tvs.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return data.get("components", [])


def recommend_tv_room(
    budget_usd_max: float,
    size_inches_min: float = 55,
    room: str = "",
) -> list[dict[str, Any]]:
    """Return up to 5 TV candidates from tvs.json under budget."""
    tvs = _load_tv_catalog()
    out: list[dict[str, Any]] = []
    for c in tvs:
        specs = c.get("specs", {})
        price = float(specs.get("msrp", specs.get("price", 999999)) or 999999)
        diag = float(specs.get("diagonal_in", 0) or 0)
        if price <= budget_usd_max and diag >= size_inches_min:
            out.append(
                {
                    "manufacturer": c.get("manufacturer"),
                    "model": c.get("model"),
                    "diagonal_in": diag,
                    "price": price,
                    "room": room,
                }
            )
    out.sort(key=lambda x: x["price"])
    return out[:5]


def validate_stack(components: list[dict[str, Any]]) -> dict[str, Any]:
    dv = DesignValidator()
    return dv.validate_components(components)
