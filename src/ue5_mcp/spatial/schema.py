"""Pydantic models for structured placement intent and result.

All spawn requests that flow through the spatial validation layer are
expressed as a PlacementIntent and produce a PlacementResult.  This
enforces a consistent contract between the LLM, the MCP tools, and the
UE bridge — replacing ad-hoc coordinate arguments with typed, validated
data that carries constraints, metadata, and a unique label all the way
through the pipeline.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Primitive vector types (lightweight, JSON-serialisable)
# ---------------------------------------------------------------------------


class Vector3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    def __iter__(self):  # type: ignore[override]
        yield self.x
        yield self.y
        yield self.z


class Rotation3(BaseModel):
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"pitch": self.pitch, "yaw": self.yaw, "roll": self.roll}


# ---------------------------------------------------------------------------
# World bounds helper
# ---------------------------------------------------------------------------


class WorldBounds(BaseModel):
    """Optional XY (and Z) extents that constrain placement search."""

    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    z_min: float | None = None
    z_max: float | None = None

    def contains_xy(self, x: float, y: float) -> bool:
        if self.x_min is not None and x < self.x_min:
            return False
        if self.x_max is not None and x > self.x_max:
            return False
        if self.y_min is not None and y < self.y_min:
            return False
        if self.y_max is not None and y > self.y_max:
            return False
        return True

    def contains_z(self, z: float) -> bool:
        if self.z_min is not None and z < self.z_min:
            return False
        if self.z_max is not None and z > self.z_max:
            return False
        return True


# ---------------------------------------------------------------------------
# Spatial constraints
# ---------------------------------------------------------------------------


class SpatialConstraints(BaseModel):
    """All validation rules that govern a single placement attempt."""

    # Clearance beyond the resolved asset extent (cm)
    min_spacing_cm: float = Field(default=50.0, ge=0.0)

    # Used as the asset extent when UE is unreachable (mock mode)
    fallback_extent_cm: float = Field(default=100.0, gt=0.0)

    # Whether to fire a downward line trace to find the real ground Z
    snap_to_surface: bool = True

    # Whether to tilt the actor to match the surface slope
    align_to_normal: bool = False

    # Reject placements on surfaces steeper than this angle (degrees)
    max_slope_deg: float = Field(default=45.0, ge=0.0, le=90.0)

    # Skip occupancy grid check entirely (use for overlapping VFX, decals, etc.)
    allow_overlap: bool = False

    # Use OBB collision instead of sphere (better for buildings, walls, roads)
    use_obb: bool = False

    # Z-axis placement bounds (cm)
    valid_z_min: float | None = None
    valid_z_max: float | None = None

    # XY-axis world bounds (cm) — prevents drift outside playable area
    valid_x_min: float | None = None
    valid_x_max: float | None = None
    valid_y_min: float | None = None
    valid_y_max: float | None = None

    # Reserved for the composition layer — raises NotImplementedError if set
    landscape_layer_filter: str | None = None

    @model_validator(mode="after")
    def _check_landscape_filter(self) -> "SpatialConstraints":
        if self.landscape_layer_filter is not None:
            raise NotImplementedError(
                "landscape_layer_filter is reserved for the composition layer "
                "(Layer 2) and is not yet implemented."
            )
        return self

    @model_validator(mode="after")
    def _check_z_order(self) -> "SpatialConstraints":
        if (
            self.valid_z_min is not None
            and self.valid_z_max is not None
            and self.valid_z_min > self.valid_z_max
        ):
            raise ValueError("valid_z_min must be <= valid_z_max")
        return self

    def to_world_bounds(self) -> WorldBounds:
        return WorldBounds(
            x_min=self.valid_x_min,
            x_max=self.valid_x_max,
            y_min=self.valid_y_min,
            y_max=self.valid_y_max,
            z_min=self.valid_z_min,
            z_max=self.valid_z_max,
        )


# ---------------------------------------------------------------------------
# Placement intent
# ---------------------------------------------------------------------------


class PlacementIntent(BaseModel):
    """Structured description of what to place, where, and under what rules.

    The LLM (or a higher-level tool) fills this in.  The SpawnValidator
    takes it, runs all checks, and returns a PlacementResult.
    """

    asset_path: str = Field(..., description="Full /Game/... path to the asset.")
    location: Vector3 = Field(default_factory=Vector3)
    rotation: Rotation3 | None = None
    scale: Vector3 = Field(default_factory=lambda: Vector3(x=1.0, y=1.0, z=1.0))
    constraints: SpatialConstraints = Field(default_factory=SpatialConstraints)

    # Human-readable tag; auto-generated by spawn_actor_safe if not provided.
    label: str | None = None

    @field_validator("asset_path")
    @classmethod
    def _validate_asset_path(cls, v: str) -> str:
        if not v.startswith("/Game/") and not v.startswith("/Script/"):
            raise ValueError(
                f"asset_path must start with '/Game/' or '/Script/', got: {v!r}"
            )
        return v


# ---------------------------------------------------------------------------
# Placement result
# ---------------------------------------------------------------------------


class PlacementResult(BaseModel):
    """Outcome of a SpawnValidator.validate() call.

    Contains the adjusted transform (after ground-snap), the resolved asset
    extent, slope measurement, and a structured list of any warnings or the
    rejection reason.  Grid side-effects are NOT recorded here — the grid is
    only updated after a confirmed UE spawn (see SpawnValidator.validate_and_mark).
    """

    success: bool

    # Final unique label (populated even on failure so callers can log it)
    label: str

    # Final world transform (may differ from intent after ground-snap)
    adjusted_location: Vector3 = Field(default_factory=Vector3)
    adjusted_rotation: Rotation3 = Field(default_factory=Rotation3)

    # Resolved asset extent × scale — the actual footprint used for checks
    asset_extent_cm: Vector3 = Field(default_factory=Vector3)

    # Measured surface slope after line trace (None if no trace was performed)
    slope_deg: float | None = None

    # Non-fatal issues (placement succeeded but with caveats)
    warnings: list[str] = Field(default_factory=list)

    # Set if success=False
    rejection_reason: str | None = None

    # Grid cell coordinates claimed by this placement (for debug)
    grid_cells_claimed: list[tuple[int, int]] = Field(default_factory=list)

    # Spawned actor name returned by UE (populated by validate_and_mark)
    spawned_actor: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """Compact representation suitable for LLM consumption."""
        d: dict[str, Any] = {
            "success": self.success,
            "label": self.label,
        }
        if self.success:
            d["location"] = self.adjusted_location.to_dict()
            d["rotation"] = self.adjusted_rotation.to_dict()
            d["extent_cm"] = self.asset_extent_cm.to_dict()
            if self.slope_deg is not None:
                d["slope_deg"] = round(self.slope_deg, 2)
            if self.warnings:
                d["warnings"] = self.warnings
            if self.spawned_actor:
                d["spawned_actor"] = self.spawned_actor
            d["grid_cells"] = len(self.grid_cells_claimed)
        else:
            d["rejection_reason"] = self.rejection_reason
            if self.slope_deg is not None:
                d["measured_slope_deg"] = round(self.slope_deg, 2)
        return d
