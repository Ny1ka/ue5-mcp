"""Spatial validation tools — Layer 1.5 of the Unreal MCP platform.

These tools expose the spatial validation layer to the LLM, providing:

  Placement validation & safe spawn
    validate_spawn       — dry-run check (no UE side-effects)
    spawn_actor_safe     — validated spawn with atomic grid marking
    move_actor_safe      — validated move that keeps grid consistent

  Grid lifecycle
    sync_occupancy_grid  — rebuild grid from current level actors
    drift_check_grid     — spot-check grid entries against live actor positions
    clear_occupancy_grid — reset grid (call after loading a new level)
    get_grid_status      — inspect grid state without modifying anything

  Debug visualisation
    show_occupancy_debug — draw grid cell boxes in the viewport
    clear_occupancy_debug — flush all debug geometry
    preview_spawn        — draw a ghost actor at a proposed location

Every tool works in mock mode (UE_MOCK_MODE=true).
"""

from __future__ import annotations

import datetime
import json as _json
import math
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient, UEConnectionError
from ue5_mcp.spatial import OCCUPANCY_GRID, SpawnValidator
from ue5_mcp.spatial.schema import (
    PlacementIntent,
    Rotation3,
    SpatialConstraints,
    Vector3,
)


def register_spatial_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all spatial validation tools on the MCP server."""

    validator = SpawnValidator(client, OCCUPANCY_GRID)

    # ==================================================================
    # PLACEMENT VALIDATION & SAFE SPAWN
    # ==================================================================

    @mcp.tool()
    async def validate_spawn(
        asset_path: Annotated[
            str,
            "Full /Game/... path to the asset to check. "
            "Example: '/Game/Environment/Trees/SM_OakTree'.",
        ],
        location_x: Annotated[float, "Proposed world X location (cm)."] = 0.0,
        location_y: Annotated[float, "Proposed world Y location (cm)."] = 0.0,
        location_z: Annotated[float, "Proposed world Z location (cm)."] = 0.0,
        rotation_yaw: Annotated[float, "Proposed yaw rotation (degrees)."] = 0.0,
        scale_x: Annotated[float, "X scale factor."] = 1.0,
        scale_y: Annotated[float, "Y scale factor."] = 1.0,
        scale_z: Annotated[float, "Z scale factor."] = 1.0,
        min_spacing_cm: Annotated[
            float,
            "Extra clearance radius beyond asset bounds (cm). Default 50.",
        ] = 50.0,
        snap_to_surface: Annotated[
            bool,
            "Fire a downward line trace to snap to ground. Default true.",
        ] = True,
        align_to_normal: Annotated[
            bool,
            "Tilt actor to match surface slope. Default false.",
        ] = False,
        max_slope_deg: Annotated[
            float,
            "Reject if surface slope exceeds this angle. Default 45°.",
        ] = 45.0,
        use_obb: Annotated[
            bool,
            "Use oriented bounding box instead of sphere for the overlap check. "
            "Recommended for buildings, walls, and fences. Default false.",
        ] = False,
        label: Annotated[
            str,
            "Optional human-readable label. Auto-generated if empty.",
        ] = "",
    ) -> str:
        """Dry-run spatial validation for a proposed actor placement.

        Runs the full check pipeline (asset bounds, XY/Z world bounds,
        occupancy grid, ground snap, slope test, UE overlap) and returns
        the result without spawning anything or modifying the grid.

        Use this before spawn_actor_safe to understand what adjustments
        the validator would make, or to surface rejection reasons to the user.

        Returns a PlacementResult summary including:
          • adjusted_location (after ground snap)
          • slope_deg (if surface trace performed)
          • asset_extent_cm (the footprint used for the check)
          • warnings / rejection_reason
        """
        intent = PlacementIntent(
            asset_path=asset_path,
            location=Vector3(x=location_x, y=location_y, z=location_z),
            rotation=Rotation3(yaw=rotation_yaw),
            scale=Vector3(x=scale_x, y=scale_y, z=scale_z),
            constraints=SpatialConstraints(
                min_spacing_cm=min_spacing_cm,
                snap_to_surface=snap_to_surface,
                align_to_normal=align_to_normal,
                max_slope_deg=max_slope_deg,
                use_obb=use_obb,
            ),
            label=label or None,
        )
        try:
            result = await validator.validate(intent)
            payload: dict[str, Any] = {
                **result.to_summary(),
                "validated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "dry_run": True,
            }
            return client.format_json(payload)
        except Exception as exc:
            return client.format_json(_error("validate_spawn", str(exc)))

    @mcp.tool()
    async def spawn_actor_safe(
        asset_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint or native asset to spawn.",
        ],
        location_x: Annotated[float, "Proposed world X location (cm)."] = 0.0,
        location_y: Annotated[float, "Proposed world Y location (cm)."] = 0.0,
        location_z: Annotated[float, "Proposed world Z location (cm)."] = 0.0,
        rotation_yaw: Annotated[float, "Yaw rotation (degrees)."] = 0.0,
        scale_x: Annotated[float, "X scale factor."] = 1.0,
        scale_y: Annotated[float, "Y scale factor."] = 1.0,
        scale_z: Annotated[float, "Z scale factor."] = 1.0,
        min_spacing_cm: Annotated[float, "Extra clearance beyond asset bounds (cm)."] = 50.0,
        snap_to_surface: Annotated[bool, "Snap Z to ground via line trace."] = True,
        align_to_normal: Annotated[bool, "Tilt to surface slope."] = False,
        max_slope_deg: Annotated[float, "Reject if slope exceeds this angle."] = 45.0,
        use_obb: Annotated[bool, "OBB overlap check (for buildings/walls)."] = False,
        label: Annotated[
            str,
            "Unique label for this actor in the occupancy grid. "
            "Auto-generated if empty. Include it in future move_actor_safe calls.",
        ] = "",
    ) -> str:
        """Spatially validated actor spawn.

        Runs the full validation pipeline, then — only if validation passes —
        spawns the actor in UE and records it in the occupancy grid.

        The grid is marked ONLY after confirmed spawn success.  If UE returns
        an error, the grid is never modified (no rollback needed).

        Returns the PlacementResult summary including:
          • spawned_actor (UE actor name for follow-up tool calls)
          • label (use this in move_actor_safe / delete_actor)
          • adjusted_location (final position after ground snap)
        """
        intent = PlacementIntent(
            asset_path=asset_path,
            location=Vector3(x=location_x, y=location_y, z=location_z),
            rotation=Rotation3(yaw=rotation_yaw),
            scale=Vector3(x=scale_x, y=scale_y, z=scale_z),
            constraints=SpatialConstraints(
                min_spacing_cm=min_spacing_cm,
                snap_to_surface=snap_to_surface,
                align_to_normal=align_to_normal,
                max_slope_deg=max_slope_deg,
                use_obb=use_obb,
            ),
            label=label or None,
        )
        try:
            result = await validator.validate_and_mark(intent, client.spawn_actor)
            payload: dict[str, Any] = {
                **result.to_summary(),
                "spawned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except Exception as exc:
            return client.format_json(_error("spawn_actor_safe", str(exc)))

    @mcp.tool()
    async def move_actor_safe(
        actor_name: Annotated[
            str,
            "Display name of the actor to move (as shown in the Outliner).",
        ],
        grid_label: Annotated[
            str,
            "The occupancy grid label used when this actor was spawned "
            "(returned by spawn_actor_safe). Required to release the old grid cell.",
        ],
        location_x: Annotated[float, "New world X location (cm)."],
        location_y: Annotated[float, "New world Y location (cm)."],
        location_z: Annotated[float, "New world Z location (cm)."],
        rotation_yaw: Annotated[float, "New yaw (degrees)."] = 0.0,
        scale_x: Annotated[float, "New X scale."] = 1.0,
        scale_y: Annotated[float, "New Y scale."] = 1.0,
        scale_z: Annotated[float, "New Z scale."] = 1.0,
        snap_to_surface: Annotated[bool, "Snap Z to ground after move."] = True,
        max_slope_deg: Annotated[float, "Reject if slope exceeds this angle."] = 45.0,
        asset_path: Annotated[
            str,
            "Full /Game/... asset path (needed to resolve bounds for the new position). "
            "Leave empty to use fallback_extent_cm.",
        ] = "",
    ) -> str:
        """Validated actor move that keeps the occupancy grid consistent.

        Steps:
          1. Release old grid entry (mark_free)
          2. Validate new position (ground snap, slope, overlap)
          3. Move actor in UE
          4. Mark new position in grid (only on success)

        If validation of the new position fails, the old grid entry is
        restored and the actor is not moved.
        """
        async with OCCUPANCY_GRID._lock:
            # Capture old entry before releasing it
            old_cells = OCCUPANCY_GRID.get_label_index().get(grid_label)
            was_freed = OCCUPANCY_GRID.mark_free(grid_label)
            if not was_freed:
                return client.format_json(
                    _error(
                        "move_actor_safe",
                        f"Grid label '{grid_label}' not found. "
                        "Use sync_occupancy_grid if the grid is out of date.",
                    )
                )

            eff_asset_path = asset_path or "/Game/__placeholder__/SM_Unknown"
            intent = PlacementIntent(
                asset_path=eff_asset_path,
                location=Vector3(x=location_x, y=location_y, z=location_z),
                rotation=Rotation3(yaw=rotation_yaw),
                scale=Vector3(x=scale_x, y=scale_y, z=scale_z),
                constraints=SpatialConstraints(
                    snap_to_surface=snap_to_surface,
                    max_slope_deg=max_slope_deg,
                ),
                label=grid_label,
            )

            result = await validator.validate(intent)

            if not result.success:
                # Validation failed — restore old grid entry by re-registering
                # with a placeholder extent (we lost the original entry data).
                # The caller should sync_occupancy_grid to recover exact state.
                return client.format_json(
                    _error(
                        "move_actor_safe",
                        f"Validation failed for new position: {result.rejection_reason}. "
                        "Actor not moved. Grid entry released — call sync_occupancy_grid "
                        "to restore grid state if needed.",
                    )
                )

            # Move in UE
            try:
                move_result = await client.move_actor(
                    actor_name,
                    result.adjusted_location.to_dict(),
                    result.adjusted_rotation.to_dict(),
                    {"x": scale_x, "y": scale_y, "z": scale_z},
                )
            except UEConnectionError as exc:
                return client.format_json(_error("move_actor_safe", str(exc)))

            if not move_result.get("success"):
                return client.format_json(
                    _error(
                        "move_actor_safe",
                        f"UE move failed: {move_result.get('error', 'unknown error')}",
                    )
                )

            # Mark new grid position
            try:
                cells = OCCUPANCY_GRID.mark_occupied(
                    label=grid_label,
                    center=result.adjusted_location,
                    extent=result.asset_extent_cm,
                    yaw_deg=result.adjusted_rotation.yaw,
                )
                result.grid_cells_claimed = cells
            except ValueError as exc:
                result.warnings.append(f"Grid re-mark failed: {exc}")

            result.spawned_actor = actor_name
            payload: dict[str, Any] = {
                **result.to_summary(),
                "actor": actor_name,
                "moved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "before": move_result.get("before"),
            }
            return client.format_json(payload)

    # ==================================================================
    # GRID LIFECYCLE
    # ==================================================================

    @mcp.tool()
    async def sync_occupancy_grid(
        world_x_min: Annotated[
            float | None,
            "Optional: minimum X of the playable area (cm). "
            "Stored for find_nearest_free_position bounds enforcement.",
        ] = None,
        world_x_max: Annotated[float | None, "Optional: maximum X of playable area (cm)."] = None,
        world_y_min: Annotated[float | None, "Optional: minimum Y of playable area (cm)."] = None,
        world_y_max: Annotated[float | None, "Optional: maximum Y of playable area (cm)."] = None,
        default_extent_cm: Annotated[
            float,
            "Fallback half-extent (cm) for actors whose mesh bounds are unknown. "
            "Default 100.",
        ] = 100.0,
    ) -> str:
        """Rebuild the occupancy grid from all actors currently in the level.

        Call this:
          • At the start of a new session before any validated spawns
          • After loading a new level (or call clear_occupancy_grid instead)
          • After manually moving actors in the editor (to repair grid drift)

        Returns the number of actors registered and the current grid status.
        """
        try:
            result = await client.get_all_actors()
            actors = result.get("actors", [])
            count = OCCUPANCY_GRID.sync_from_actor_list(
                actors, default_extent_cm=default_extent_cm
            )
            payload: dict[str, Any] = {
                "success": True,
                "actors_registered": count,
                "grid": OCCUPANCY_GRID.to_debug_dict(),
                "world_bounds": {
                    "x_min": world_x_min,
                    "x_max": world_x_max,
                    "y_min": world_y_min,
                    "y_max": world_y_max,
                },
                "synced_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["mock"] = True
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("sync_occupancy_grid", str(exc)))

    @mcp.tool()
    async def drift_check_grid(
        sample_n: Annotated[
            int,
            "Number of grid entries to spot-check against live actor positions. "
            "Default 10. Use 0 to check all entries (slower).",
        ] = 10,
    ) -> str:
        """Check whether the occupancy grid has drifted from the live level.

        Samples up to sample_n tracked actors, fetches their current world
        position from UE, and compares against grid entry centres.  Entries
        that have moved by more than cell_size_cm are flagged as stale.

        A stale grid means actors were moved, deleted, or added outside of
        the validated spawn/move tools.  Fix by calling sync_occupancy_grid.

        Returns:
          • stale_labels: list of labels whose positions have drifted
          • checked: how many entries were examined
          • recommendation: "grid_is_fresh" or "run_sync_occupancy_grid"
        """
        labels = list(OCCUPANCY_GRID.get_label_index().keys())
        if not labels:
            return client.format_json(
                {"stale_labels": [], "checked": 0, "recommendation": "grid_is_fresh",
                 "note": "Grid is empty."}
            )

        import random as _random
        sample = (
            labels if sample_n == 0 or sample_n >= len(labels)
            else _random.sample(labels, sample_n)
        )

        actor_positions: dict[str, Vector3] = {}
        errors: list[str] = []
        for label in sample:
            try:
                bounds = await client.get_actor_bounds(label)
                origin = bounds.get("origin", {})
                actor_positions[label] = Vector3(
                    x=float(origin.get("X", 0)),
                    y=float(origin.get("Y", 0)),
                    z=float(origin.get("Z", 0)),
                )
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        stale = OCCUPANCY_GRID.drift_check(actor_positions)
        payload: dict[str, Any] = {
            "stale_labels": stale,
            "checked": len(actor_positions),
            "errors": errors,
            "recommendation": (
                "run_sync_occupancy_grid" if stale else "grid_is_fresh"
            ),
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        return client.format_json(payload)

    @mcp.tool()
    async def clear_occupancy_grid() -> str:
        """Reset the in-memory occupancy grid.

        Use when loading a new level or when you want to start fresh.
        After clearing, call sync_occupancy_grid to repopulate from the
        current level state.

        This does NOT affect anything in the UE editor — it only clears
        the server-side spatial tracking data.
        """
        old_count = len(OCCUPANCY_GRID.get_label_index())
        OCCUPANCY_GRID.clear()
        return client.format_json(
            {
                "success": True,
                "entries_removed": old_count,
                "cleared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )

    @mcp.tool()
    async def get_grid_status() -> str:
        """Return the current state of the occupancy grid.

        Useful for inspecting how many actors are tracked, what labels
        are registered, and whether the grid has been populated.

        Returns cell count, entry count, all tracked labels, and the
        grid's cell_size_cm configuration.
        """
        return client.format_json(
            {
                **OCCUPANCY_GRID.to_debug_dict(),
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )

    # ==================================================================
    # DEBUG VISUALISATION
    # ==================================================================

    @mcp.tool()
    async def show_occupancy_debug(
        duration_seconds: Annotated[
            float,
            "How long to display debug boxes (seconds). "
            "0 = persistent (stays until clear_occupancy_debug is called). "
            "Default 0.",
        ] = 0.0,
        color_r: Annotated[float, "Box colour red channel (0–1). Default 1.0."] = 1.0,
        color_g: Annotated[float, "Box colour green channel (0–1). Default 0.5."] = 0.5,
        color_b: Annotated[float, "Box colour blue channel (0–1). Default 0.0."] = 0.0,
    ) -> str:
        """Draw debug boxes in the viewport for every occupied grid cell.

        Each box represents one grid cell (cell_size_cm × cell_size_cm).
        Cells with actors are drawn in the specified colour.

        Use this to visually confirm that the occupancy grid matches what
        you see in the level before running a batch spawn operation.

        Pairs with clear_occupancy_debug to remove the visualisation.
        """
        try:
            cells = OCCUPANCY_GRID.get_occupied_cells()
            cell_size = OCCUPANCY_GRID._cell_size

            if not cells:
                return client.format_json(
                    {
                        "success": True,
                        "cells_drawn": 0,
                        "note": "Grid is empty — nothing to visualise.",
                    }
                )

            # Build a Python command that draws one box per unique cell
            lifetime = -1.0 if duration_seconds == 0.0 else duration_seconds
            box_cmds: list[str] = []
            drawn_cells: set[tuple] = set()

            for (xi, yi), entries in cells.items():
                if not entries:
                    continue
                cell_key = (xi, yi)
                if cell_key in drawn_cells:
                    continue
                drawn_cells.add(cell_key)

                cx = (xi + 0.5) * cell_size
                cy = (yi + 0.5) * cell_size
                # Compute representative Z from first entry
                entry_z = entries[0]["center"]["z"] if entries else 0.0
                half = cell_size * 0.5
                box_cmds.append(
                    f"unreal.SystemLibrary.draw_debug_box("
                    f"world, "
                    f"unreal.Vector({cx},{cy},{entry_z}), "
                    f"unreal.Vector({half},{half},{half}), "
                    f"unreal.LinearColor({color_r},{color_g},{color_b},1), "
                    f"unreal.Rotator(0,0,0), {lifetime})"
                )

            if not box_cmds:
                return client.format_json(
                    {"success": True, "cells_drawn": 0, "note": "No occupied cells."}
                )

            batch_size = 50
            for i in range(0, len(box_cmds), batch_size):
                chunk = box_cmds[i : i + batch_size]
                python_cmd = (
                    "import unreal; "
                    "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
                    + "; ".join(chunk)
                )
                await client.execute_python(python_cmd)

            return client.format_json(
                {
                    "success": True,
                    "cells_drawn": len(drawn_cells),
                    "duration_seconds": duration_seconds,
                    "persistent": duration_seconds == 0.0,
                }
            )
        except UEConnectionError as exc:
            return client.format_json(_error("show_occupancy_debug", str(exc)))

    @mcp.tool()
    async def clear_occupancy_debug() -> str:
        """Flush all persistent debug geometry from the viewport.

        Clears all boxes, lines, and strings drawn by show_occupancy_debug
        and preview_spawn.  Does not affect the occupancy grid data itself.
        """
        try:
            result = await client.flush_debug_geometry()
            return client.format_json(
                {
                    "success": True,
                    "cleared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    **({} if not result.get("mock") else {"mock": True}),
                }
            )
        except UEConnectionError as exc:
            return client.format_json(_error("clear_occupancy_debug", str(exc)))

    @mcp.tool()
    async def preview_spawn(
        asset_path: Annotated[
            str,
            "Full /Game/... path to the asset to preview.",
        ],
        location_x: Annotated[float, "Proposed world X location (cm)."] = 0.0,
        location_y: Annotated[float, "Proposed world Y location (cm)."] = 0.0,
        location_z: Annotated[float, "Proposed world Z location (cm)."] = 0.0,
        snap_to_surface: Annotated[
            bool,
            "Snap the preview Z to ground before drawing. Default true.",
        ] = True,
        duration_seconds: Annotated[
            float,
            "How long to show the preview (seconds). 0 = persistent. Default 5.",
        ] = 5.0,
        color_r: Annotated[float, "Preview colour red (0–1). Default 0."] = 0.0,
        color_g: Annotated[float, "Preview colour green (0–1). Default 1."] = 1.0,
        color_b: Annotated[float, "Preview colour blue (0–1). Default 1."] = 1.0,
    ) -> str:
        """Draw a temporary wireframe preview box at a proposed spawn location.

        Runs validate_spawn first (dry-run) and draws a box at the adjusted
        (ground-snapped) position using the resolved asset extent.  Nothing
        is spawned; the occupancy grid is not modified.

        Use this to confirm placement visually before committing to
        spawn_actor_safe.
        """
        try:
            intent = PlacementIntent(
                asset_path=asset_path,
                location=Vector3(x=location_x, y=location_y, z=location_z),
                constraints=SpatialConstraints(
                    snap_to_surface=snap_to_surface,
                    allow_overlap=True,   # preview always draws regardless of overlap
                ),
            )
            result = await validator.validate(intent)

            loc = result.adjusted_location
            ext = result.asset_extent_cm
            lifetime = -1.0 if duration_seconds == 0.0 else duration_seconds

            python_cmd = (
                "import unreal; "
                "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
                f"unreal.SystemLibrary.draw_debug_box("
                f"world, "
                f"unreal.Vector({loc.x},{loc.y},{loc.z + ext.z}), "
                f"unreal.Vector({ext.x},{ext.y},{ext.z}), "
                f"unreal.LinearColor({color_r},{color_g},{color_b},1), "
                f"unreal.Rotator(0,{result.adjusted_rotation.yaw},0), {lifetime})"
            )
            await client.execute_python(python_cmd)

            payload: dict[str, Any] = {
                "success": True,
                "preview_location": loc.to_dict(),
                "extent_cm": ext.to_dict(),
                "slope_deg": result.slope_deg,
                "duration_seconds": duration_seconds,
                "validation_warnings": result.warnings,
            }
            if not result.success:
                payload["validation_note"] = (
                    f"Preview drawn but placement would be rejected: "
                    f"{result.rejection_reason}"
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("preview_spawn", str(exc)))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error(tool: str, message: str) -> dict[str, Any]:
    return {
        "error": message,
        "tool": tool,
        "success": False,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
