"""SpawnValidator — orchestrates all pre-spawn spatial checks.

Validation pipeline (in order):
  1. Resolve asset extent via get_asset_static_mesh_bounds (or fallback)
  2. Compute effective collision radius = max(extent × scale) + min_spacing
  3. XY world-bounds check
  4. Z constraint check on suggested location
  5. Fast in-memory grid check (is_region_free / is_obb_free)
  6. If snap_to_surface: line_trace_surface → adjusted Z
  7. Slope check vs max_slope_deg (reject or extract surface rotation)
  8. Re-check grid at adjusted position (post-snap)
  9. Optional UE overlap_sphere_test at final position
 10. Return PlacementResult (no grid side-effects — grid updated by caller
     only after confirmed UE spawn success)

validate_and_mark() wraps step 10 with an asyncio.Lock so validate + UE spawn
+ mark_occupied is atomic from the grid's perspective.
"""

from __future__ import annotations

import math
from uuid import uuid4
from typing import TYPE_CHECKING, Callable, Awaitable, Any

from ue5_mcp.spatial.schema import (
    PlacementIntent,
    PlacementResult,
    Rotation3,
    Vector3,
)

if TYPE_CHECKING:
    from ue5_mcp.bridge.client import UEClient
    from ue5_mcp.spatial.grid import OccupancyGrid


def _make_label(asset_path: str) -> str:
    mesh_name = asset_path.split("/")[-1].split(".")[0]
    return f"{mesh_name}_{uuid4().hex[:6]}"


def _surface_normal_to_rotation(normal: dict[str, float], base_yaw: float) -> Rotation3:
    """Convert a UE surface normal vector to a Pitch/Roll/Yaw rotator.

    The surface normal is (NX, NY, NZ).  We decompose it into:
      • Pitch = arctan2(-NZ_lateral, NZ_up) — forward tilt
      • Roll  = arctan2(NY cross component, 1) — side tilt
      • Yaw   = preserved from intent

    This is an approximation suitable for foliage / prop placement.
    """
    nx = normal.get("X", 0.0)
    ny = normal.get("Y", 0.0)
    nz = normal.get("Z", 1.0)

    # Slope angle from world up
    slope = math.degrees(math.acos(max(-1.0, min(1.0, nz))))

    # Pitch: project normal onto XZ plane
    pitch = math.degrees(math.atan2(-nx, nz))
    # Roll: project normal onto YZ plane
    roll = math.degrees(math.atan2(-ny, nz))

    return Rotation3(pitch=pitch, yaw=base_yaw, roll=roll), slope  # type: ignore[return-value]


class SpawnValidator:
    """Runs the full spatial validation pipeline for a PlacementIntent."""

    def __init__(self, client: "UEClient", grid: "OccupancyGrid") -> None:
        self._client = client
        self._grid = grid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(self, intent: PlacementIntent) -> PlacementResult:
        """Run all checks; return a PlacementResult with no side-effects.

        The grid is NOT modified here.  Call validate_and_mark() when you
        also want to spawn in UE and record the result atomically.
        """
        label = intent.label or _make_label(intent.asset_path)
        constraints = intent.constraints
        scale = intent.scale
        warnings: list[str] = []

        # ------------------------------------------------------------------
        # Step 1 — Resolve asset extent
        # ------------------------------------------------------------------
        try:
            bounds_raw = await self._client.get_asset_static_mesh_bounds(intent.asset_path)
            raw_ext = bounds_raw.get("extent", {})
            asset_extent = Vector3(
                x=float(raw_ext.get("X", constraints.fallback_extent_cm)),
                y=float(raw_ext.get("Y", constraints.fallback_extent_cm)),
                z=float(raw_ext.get("Z", constraints.fallback_extent_cm)),
            )
        except Exception:
            asset_extent = Vector3(
                x=constraints.fallback_extent_cm,
                y=constraints.fallback_extent_cm,
                z=constraints.fallback_extent_cm,
            )
            warnings.append(
                "Could not resolve asset bounds from UE — using fallback_extent_cm."
            )

        # Scale the extent
        scaled_extent = Vector3(
            x=asset_extent.x * scale.x,
            y=asset_extent.y * scale.y,
            z=asset_extent.z * scale.z,
        )

        # Effective collision radius (sphere fast-path)
        eff_radius = max(scaled_extent.x, scaled_extent.y) + constraints.min_spacing_cm

        # ------------------------------------------------------------------
        # Step 2 — XY world-bounds check
        # ------------------------------------------------------------------
        wb = constraints.to_world_bounds()
        if not wb.contains_xy(intent.location.x, intent.location.y):
            return self._reject(
                label, scaled_extent,
                f"Location ({intent.location.x:.0f}, {intent.location.y:.0f}) is outside "
                f"the valid XY world bounds.",
                warnings=warnings,
            )

        # ------------------------------------------------------------------
        # Step 3 — Z constraint check (pre-snap)
        # ------------------------------------------------------------------
        if not wb.contains_z(intent.location.z):
            return self._reject(
                label, scaled_extent,
                f"Location Z={intent.location.z:.0f} is outside "
                f"valid_z range [{wb.z_min}, {wb.z_max}].",
                warnings=warnings,
            )

        # ------------------------------------------------------------------
        # Step 4 — Fast grid check at proposed location
        # ------------------------------------------------------------------
        if not constraints.allow_overlap:
            if constraints.use_obb:
                base_yaw = (intent.rotation.yaw if intent.rotation else 0.0)
                clear = self._grid.is_obb_free(
                    intent.location, scaled_extent, base_yaw
                )
            else:
                clear = self._grid.is_region_free(intent.location, eff_radius)

            if not clear:
                return self._reject(
                    label, scaled_extent,
                    f"Proposed location ({intent.location.x:.0f}, "
                    f"{intent.location.y:.0f}, {intent.location.z:.0f}) "
                    f"overlaps an existing actor in the occupancy grid.",
                    warnings=warnings,
                )

        # ------------------------------------------------------------------
        # Step 5 — Ground snap (line trace)
        # ------------------------------------------------------------------
        adjusted_loc = Vector3(
            x=intent.location.x,
            y=intent.location.y,
            z=intent.location.z,
        )
        base_yaw = intent.rotation.yaw if intent.rotation else 0.0
        adjusted_rot = Rotation3(
            pitch=intent.rotation.pitch if intent.rotation else 0.0,
            yaw=base_yaw,
            roll=intent.rotation.roll if intent.rotation else 0.0,
        )
        slope_deg: float | None = None

        if constraints.snap_to_surface:
            try:
                trace = await self._client.line_trace_surface(
                    intent.location.x,
                    intent.location.y,
                    intent.location.z,
                )
                if trace.get("hit"):
                    hit_loc = trace.get("location", {})
                    adjusted_loc = Vector3(
                        x=hit_loc.get("X", intent.location.x),
                        y=hit_loc.get("Y", intent.location.y),
                        z=hit_loc.get("Z", intent.location.z),
                    )

                    # Slope check
                    normal = trace.get("normal", {"X": 0, "Y": 0, "Z": 1})
                    nz = normal.get("Z", 1.0)
                    slope_deg = math.degrees(math.acos(max(-1.0, min(1.0, nz))))

                    if slope_deg > constraints.max_slope_deg:
                        return self._reject(
                            label, scaled_extent,
                            f"Surface slope {slope_deg:.1f}° exceeds max_slope_deg "
                            f"{constraints.max_slope_deg}°. Choose a flatter location.",
                            slope_deg=slope_deg,
                            warnings=warnings,
                        )

                    # Apply surface normal to rotation if requested
                    if constraints.align_to_normal:
                        adjusted_rot, _ = _surface_normal_to_rotation(normal, base_yaw)

                    # Z constraint re-check after snap
                    if not wb.contains_z(adjusted_loc.z):
                        return self._reject(
                            label, scaled_extent,
                            f"Ground-snapped Z={adjusted_loc.z:.0f} is outside "
                            f"valid_z range [{wb.z_min}, {wb.z_max}].",
                            slope_deg=slope_deg,
                            warnings=warnings,
                        )
                else:
                    warnings.append(
                        "line_trace_surface found no surface hit — using original Z."
                    )
            except Exception as exc:
                warnings.append(f"Ground snap failed ({exc}) — using original Z.")

        # ------------------------------------------------------------------
        # Step 6 — Grid re-check at adjusted (post-snap) position
        # ------------------------------------------------------------------
        if not constraints.allow_overlap and constraints.snap_to_surface:
            if constraints.use_obb:
                clear = self._grid.is_obb_free(adjusted_loc, scaled_extent, adjusted_rot.yaw)
            else:
                clear = self._grid.is_region_free(adjusted_loc, eff_radius)

            if not clear:
                return self._reject(
                    label, scaled_extent,
                    f"Ground-snapped location ({adjusted_loc.x:.0f}, "
                    f"{adjusted_loc.y:.0f}, {adjusted_loc.z:.0f}) "
                    f"overlaps an existing actor after surface snap.",
                    slope_deg=slope_deg,
                    warnings=warnings,
                )

        # ------------------------------------------------------------------
        # Step 7 — UE overlap sphere test (optional, heavier)
        # ------------------------------------------------------------------
        try:
            overlaps = await self._client.overlap_sphere_test(
                adjusted_loc.x, adjusted_loc.y, adjusted_loc.z, eff_radius
            )
            overlap_actors = overlaps.get("overlapping_actors", [])
            if overlap_actors and not constraints.allow_overlap:
                return self._reject(
                    label, scaled_extent,
                    f"UE overlap test found {len(overlap_actors)} actor(s) at the "
                    f"proposed location: {', '.join(overlap_actors[:5])}.",
                    slope_deg=slope_deg,
                    warnings=warnings,
                )
        except Exception as exc:
            warnings.append(f"UE overlap test skipped ({exc}).")

        # ------------------------------------------------------------------
        # Success — return PlacementResult (no grid writes here)
        # ------------------------------------------------------------------
        return PlacementResult(
            success=True,
            label=label,
            adjusted_location=adjusted_loc,
            adjusted_rotation=adjusted_rot,
            asset_extent_cm=scaled_extent,
            slope_deg=slope_deg,
            warnings=warnings,
        )

    async def validate_and_mark(
        self,
        intent: PlacementIntent,
        spawn_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> PlacementResult:
        """Atomic validate → spawn → mark_occupied under asyncio.Lock.

        The grid lock is held for the full critical section so concurrent
        calls cannot both pass is_region_free before either marks occupied.

        Args:
            intent:   PlacementIntent describing the asset and constraints.
            spawn_fn: Async callable that performs the actual UE spawn.
                      Called only if validation succeeds.
                      Receives (asset_path, location_dict, rotation_dict, scale_dict).

        Returns:
            PlacementResult with spawned_actor populated on success.
        """
        async with self._grid._lock:
            result = await self.validate(intent)
            if not result.success:
                return result

            # Call UE — grid is NOT touched until this succeeds
            try:
                spawn_result = await spawn_fn(
                    intent.asset_path,
                    result.adjusted_location.to_dict(),
                    result.adjusted_rotation.to_dict(),
                    intent.scale.to_dict(),
                )
            except Exception as exc:
                result.success = False
                result.rejection_reason = f"UE spawn failed: {exc}"
                return result

            if not spawn_result.get("spawned_actor") and not spawn_result.get("mock"):
                result.success = False
                result.rejection_reason = (
                    f"UE spawn returned no actor: {spawn_result}"
                )
                return result

            # Mark grid only after confirmed spawn
            constraints = intent.constraints
            try:
                cells = self._grid.mark_occupied(
                    label=result.label,
                    center=result.adjusted_location,
                    extent=result.asset_extent_cm,
                    yaw_deg=result.adjusted_rotation.yaw,
                    z_min=(
                        result.adjusted_location.z
                        if result.asset_extent_cm.z < math.inf
                        else None
                    ),
                    z_max=(
                        result.adjusted_location.z + result.asset_extent_cm.z * 2
                        if result.asset_extent_cm.z < math.inf
                        else None
                    ),
                    use_obb=constraints.use_obb,
                )
                result.grid_cells_claimed = cells
            except ValueError as exc:
                result.warnings.append(f"Grid mark skipped: {exc}")

            result.spawned_actor = spawn_result.get("spawned_actor")
            return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reject(
        label: str,
        extent: Vector3,
        reason: str,
        slope_deg: float | None = None,
        warnings: list[str] | None = None,
    ) -> PlacementResult:
        return PlacementResult(
            success=False,
            label=label,
            asset_extent_cm=extent,
            slope_deg=slope_deg,
            rejection_reason=reason,
            warnings=warnings or [],
        )
