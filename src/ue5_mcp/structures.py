"""Structure template loading — Composition layer (Session 3 of the roadmap).

Templates describe how to assemble a named structure (cabin, house, warehouse,
tower, wall segment, archway, ...) from a list of relatively-offset mesh
components.  The curated data lives in templates/structure_templates.json —
see that file's `default_asset` fields for placeholder paths meant to be
overridden per-project via build_structure's component_overrides argument.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATES_PATH = Path(__file__).parent / "templates" / "structure_templates.json"


@lru_cache(maxsize=1)
def load_structure_templates() -> dict[str, Any]:
    """Load and cache the structure template catalogue from disk."""
    with _TEMPLATES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_structure_template(structure_type: str) -> dict[str, Any] | None:
    """Return the raw template dict for a structure type, or None if unknown."""
    return load_structure_templates().get(structure_type)


def resolve_component_asset(
    component: dict[str, Any],
    overrides: dict[str, str],
) -> str:
    """Resolve the asset path for a component, honouring caller overrides.

    Priority: exact component id override > category override > default_asset
    baked into the template.
    """
    comp_id = component["id"]
    category = component["category"]
    if comp_id in overrides:
        return overrides[comp_id]
    if category in overrides:
        return overrides[category]
    return component["default_asset"]


def rotate_offset_xy(offset_x: float, offset_y: float, yaw_deg: float) -> tuple[float, float]:
    """Rotate a local (x, y) offset around world +Z by yaw_deg degrees."""
    yaw_rad = math.radians(yaw_deg)
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)
    world_x = cos_y * offset_x - sin_y * offset_y
    world_y = sin_y * offset_x + cos_y * offset_y
    return world_x, world_y
