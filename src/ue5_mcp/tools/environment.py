"""Environment tools — Layer 2 of the Unreal MCP platform.

This module implements all tools that let an AI agent place, query, configure,
and remove things inside an Unreal Engine 5 world.  The tools are organised
into four functional groups that mirror the Layer 2 roadmap:

  Phase 1 · Actor Management
    list_actors, spawn_actor, move_actor, delete_actor,
    set_actor_property, get_actor_property, find_actors_by_tag, select_actors

  Phase 2 · Level Management
    list_levels, open_level, save_current_level, set_world_settings

  Phase 3 · Foliage Systems
    spawn_foliage, clear_foliage, configure_lod, generate_collision

  Phase 4 · Landscape & PCG Foundation
    list_landscape_layers, paint_landscape_layer, configure_pcg_graph

Every tool:
  • Works in mock mode (UE_MOCK_MODE=true) — no live editor required
  • Returns structured, JSON-serialisable data via client.format_json()
  • Handles UEConnectionError gracefully and returns an error payload
  • Follows the exact same registration pattern as register_asset_tools()

Bridge communication lives in bridge/client.py.  This file contains only
MCP-layer business logic: argument validation, response shaping, and the
@mcp.tool() decorators.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_environment_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all Layer 2 environment tools on the MCP server."""

    # ==================================================================
    # PHASE 1 · ACTOR MANAGEMENT
    # ==================================================================

    @mcp.tool()
    async def list_actors(
        class_filter: Annotated[
            str,
            "Optional actor class name to filter by (e.g. 'StaticMeshActor', "
            "'BP_EnemyBase_C'). Leave empty to return all actors.",
        ] = "",
        folder_filter: Annotated[
            str,
            "Optional editor folder path prefix to filter by "
            "(e.g. 'Lighting', 'Environment/Rocks').",
        ] = "",
        include_hidden: Annotated[
            bool,
            "Include actors that are hidden in the editor. Default true.",
        ] = True,
    ) -> str:
        """Return all actors in the current level with full transform and metadata.

        Each actor entry contains:
          • name / label / class
          • World location, rotation, scale
          • Editor tags
          • Editor folder path
          • Level name (persistent vs sub-level)
          • is_selected / is_hidden state

        Use this before any actor manipulation to discover what exists and
        obtain the correct actor names for subsequent tool calls.
        """
        try:
            result = await client.get_all_actors()
            actors: list[dict[str, Any]] = result.get("actors", [])

            # Apply optional filters
            if class_filter:
                actors = [
                    a for a in actors
                    if class_filter.lower() in a.get("class", "").lower()
                ]
            if folder_filter:
                actors = [
                    a for a in actors
                    if a.get("folder_path", "").startswith(folder_filter)
                ]
            if not include_hidden:
                actors = [a for a in actors if not a.get("is_hidden", False)]

            payload: dict[str, Any] = {
                "actors": actors,
                "total": len(actors),
                "level": result.get("level", "Unknown"),
                "filters_applied": {
                    "class": class_filter or None,
                    "folder": folder_filter or None,
                    "include_hidden": include_hidden,
                },
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["mock"] = True
                payload["note"] = (
                    "Mock data — set UE_MOCK_MODE=false with a running editor for real results."
                )
            return client.format_json(payload)

        except UEConnectionError as exc:
            return client.format_json(_error("list_actors", str(exc)))

    @mcp.tool()
    async def spawn_actor(
        asset_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint or native asset to spawn. "
            "Example: '/Game/Blueprints/BP_Enemy.BP_Enemy'. "
            "Use list_project_assets first to verify the asset exists.",
        ],
        location_x: Annotated[float, "World X location in Unreal centimetres."] = 0.0,
        location_y: Annotated[float, "World Y location in Unreal centimetres."] = 0.0,
        location_z: Annotated[float, "World Z location in Unreal centimetres."] = 0.0,
        rotation_pitch: Annotated[float, "Pitch rotation in degrees."] = 0.0,
        rotation_yaw: Annotated[float, "Yaw rotation in degrees."] = 0.0,
        rotation_roll: Annotated[float, "Roll rotation in degrees."] = 0.0,
        scale_x: Annotated[float, "X scale factor. 1.0 = default size."] = 1.0,
        scale_y: Annotated[float, "Y scale factor."] = 1.0,
        scale_z: Annotated[float, "Z scale factor."] = 1.0,
    ) -> str:
        """Spawn a Blueprint or native actor in the current level.

        The actor is placed at the given world transform.  Returns the spawned
        actor's name and full object path so subsequent tools (move_actor,
        set_actor_property) can reference it immediately.

        Requires: EditorScriptingUtilities plugin enabled in the editor.
        """
        location = {"x": location_x, "y": location_y, "z": location_z}
        rotation = {"pitch": rotation_pitch, "yaw": rotation_yaw, "roll": rotation_roll}
        scale = {"x": scale_x, "y": scale_y, "z": scale_z}

        try:
            result = await client.spawn_actor(asset_path, location, rotation, scale)
            payload: dict[str, Any] = {
                **result,
                "spawned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("spawn_actor", str(exc)))

    @mcp.tool()
    async def move_actor(
        actor_name: Annotated[
            str,
            "Display name of the actor to move (as shown in the Outliner). "
            "Use list_actors first to get the correct name.",
        ],
        location_x: Annotated[
            float | None,
            "New world X location (cm). Omit or set to null to leave unchanged.",
        ] = None,
        location_y: Annotated[float | None, "New world Y location (cm)."] = None,
        location_z: Annotated[float | None, "New world Z location (cm)."] = None,
        rotation_pitch: Annotated[float | None, "New pitch (degrees)."] = None,
        rotation_yaw: Annotated[float | None, "New yaw (degrees)."] = None,
        rotation_roll: Annotated[float | None, "New roll (degrees)."] = None,
        scale_x: Annotated[float | None, "New X scale."] = None,
        scale_y: Annotated[float | None, "New Y scale."] = None,
        scale_z: Annotated[float | None, "New Z scale."] = None,
    ) -> str:
        """Move, rotate, or scale an actor by its display name.

        Only components with all three axes provided are updated — for example,
        passing only location_x/y/z updates position while leaving rotation and
        scale untouched.

        Returns before and after transforms so the AI can confirm the change.
        """
        # Only construct component dicts when all three axes are provided
        location: dict[str, float] | None = None
        rotation: dict[str, float] | None = None
        scale: dict[str, float] | None = None

        if location_x is not None and location_y is not None and location_z is not None:
            location = {"x": location_x, "y": location_y, "z": location_z}
        if rotation_pitch is not None and rotation_yaw is not None and rotation_roll is not None:
            rotation = {"pitch": rotation_pitch, "yaw": rotation_yaw, "roll": rotation_roll}
        if scale_x is not None and scale_y is not None and scale_z is not None:
            scale = {"x": scale_x, "y": scale_y, "z": scale_z}

        if location is None and rotation is None and scale is None:
            return client.format_json(
                _error(
                    "move_actor",
                    "No transform components specified. Provide location, rotation, "
                    "or scale (all three axes of each component required).",
                )
            )

        try:
            result = await client.move_actor(actor_name, location, rotation, scale)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("move_actor", str(exc)))

    @mcp.tool()
    async def delete_actor(
        actor_name: Annotated[
            str,
            "Display name of the actor to delete (as shown in the Outliner). "
            "Use list_actors first to verify the correct name.",
        ],
        dry_run: Annotated[
            bool,
            "If true, return a description of what would be deleted without "
            "actually deleting it. Recommended before destructive operations.",
        ] = False,
    ) -> str:
        """Delete an actor from the current level.

        This is a destructive operation.  Use dry_run=true first to confirm
        you have the correct actor.  A future confirm=true parameter will be
        added as part of the safety layer to prevent accidental deletions.

        Returns a deletion summary including the actor name and whether the
        operation succeeded.
        """
        try:
            result = await client.delete_actor(actor_name, dry_run=dry_run)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("delete_actor", str(exc)))

    @mcp.tool()
    async def set_actor_property(
        actor_name: Annotated[
            str,
            "Display name of the actor (as shown in the Outliner).",
        ],
        property_name: Annotated[
            str,
            "UE property name on the actor, exactly as it appears in the C++ "
            "class or Blueprint variable list. "
            "Examples: 'bHidden', 'Tags', 'CustomDepthStencilValue', 'bCastShadow'.",
        ],
        property_value: Annotated[
            str,
            "New value as a JSON-encoded string. "
            "Examples: 'true', '42', '\"MyTag\"', '[\"TagA\", \"TagB\"]'.",
        ],
    ) -> str:
        """Set an exposed property on an actor.

        Targets any UE property that is exposed to the Remote Control API.
        Returns the old and new values so the AI can confirm the change.

        Common use cases:
          • Toggle visibility: property_name='bHidden', value='true'
          • Set custom depth: property_name='CustomDepthStencilValue', value='1'
          • Add tags:         property_name='Tags', value='["Enemy","Boss"]'

        Note: The property must be accessible via the Remote Control API.
        Blueprint-only variables require Blueprint-specific handling.
        """
        import json as _json

        try:
            parsed_value: Any = _json.loads(property_value)
        except _json.JSONDecodeError:
            # If the value isn't valid JSON, treat it as a plain string
            parsed_value = property_value

        try:
            result = await client.set_actor_property(actor_name, property_name, parsed_value)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("set_actor_property", str(exc)))

    @mcp.tool()
    async def get_actor_property(
        actor_name: Annotated[
            str,
            "Display name of the actor (as shown in the Outliner).",
        ],
        property_name: Annotated[
            str,
            "UE property name to read. "
            "Examples: 'bHidden', 'Tags', 'FolderPath', 'CustomDepthStencilValue'.",
        ],
    ) -> str:
        """Read an exposed property from an actor.

        Returns the current value and its Python type name.  Use this to
        inspect actor state before deciding whether to change it.

        Common use cases:
          • Check visibility:     property_name='bHidden'
          • Read actor tags:      property_name='Tags'
          • Get folder location:  property_name='FolderPath'
        """
        try:
            result = await client.get_actor_property(actor_name, property_name)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("get_actor_property", str(exc)))

    @mcp.tool()
    async def find_actors_by_tag(
        tag: Annotated[
            str,
            "Actor tag to search for (exact match). "
            "Examples: 'Enemy', 'Interactable', 'Lighting'.",
        ] = "",
        class_name: Annotated[
            str,
            "Actor class name to filter by. Supports partial match. "
            "Examples: 'PointLight', 'BP_Enemy', 'StaticMeshActor'.",
        ] = "",
        name_pattern: Annotated[
            str,
            "Substring to match against actor display names. "
            "Example: 'Rock' matches 'SM_Rock_01', 'SM_Rock_02', etc.",
        ] = "",
        partial_match: Annotated[
            bool,
            "Use substring matching for class_name and name_pattern. "
            "Set to false for exact-only matches. Default true.",
        ] = True,
    ) -> str:
        """Search actors by tag, class name, or display name pattern.

        All provided filters are ANDed together.  Leave unused filters empty.
        Returns the matching actors with their transforms — the same shape as
        list_actors but pre-filtered.

        Examples:
          • Find all lights:   class_name='Light'
          • Find tagged enemies: tag='Enemy'
          • Find all rocks:    name_pattern='Rock'
          • Find a specific BP: class_name='BP_Door_Automatic_C', partial_match=false
        """
        if not tag and not class_name and not name_pattern:
            return client.format_json(
                _error(
                    "find_actors_by_tag",
                    "At least one filter must be provided: tag, class_name, or name_pattern.",
                )
            )

        try:
            result = await client.find_actors(
                tag=tag,
                class_name=class_name,
                name_pattern=name_pattern,
                partial_match=partial_match,
            )
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("find_actors_by_tag", str(exc)))

    @mcp.tool()
    async def select_actors(
        actor_names: Annotated[
            str,
            "Comma-separated list of actor display names to select in the editor. "
            "Example: 'SM_Rock_01_0, BP_EnemyBase_0, PointLight_0'.",
        ],
        add_to_selection: Annotated[
            bool,
            "If true, add to the existing editor selection. "
            "If false (default), clear selection first.",
        ] = False,
    ) -> str:
        """Programmatically select actors in the editor viewport.

        Updates the editor's current selection state, which means the
        selected actors will appear highlighted in the viewport and their
        properties will appear in the Details panel.

        Use cases:
          • Select all enemies before batch-moving them
          • Highlight specific actors to show the user where they are
          • Prepare a selection for a subsequent delete_actor call

        Returns the list of actors that were successfully selected and any
        names that could not be found.
        """
        names = [n.strip() for n in actor_names.split(",") if n.strip()]
        if not names:
            return client.format_json(
                _error("select_actors", "actor_names must not be empty.")
            )

        try:
            result = await client.select_actors(names, add_to_selection=add_to_selection)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("select_actors", str(exc)))

    # ==================================================================
    # PHASE 2 · LEVEL MANAGEMENT
    # ==================================================================

    @mcp.tool()
    async def list_levels(
    ) -> str:
        """Return all levels registered with the current world.

        Includes:
          • The persistent level
          • Streaming sub-levels (loaded and unloaded)
          • World Partition awareness flag

        Use this before open_level to confirm the correct game path, and
        after save_current_level to verify the dirty flag cleared.
        """
        try:
            result = await client.list_levels()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock data — connect a live editor for real level data."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_levels", str(exc)))

    @mcp.tool()
    async def open_level(
        level_path: Annotated[
            str,
            "Full /Game/... game path to the map asset. "
            "Example: '/Game/Maps/L_OpenWorld'. "
            "Use list_levels or list_project_assets to find valid paths.",
        ],
    ) -> str:
        """Open a map by its /Game/... asset path.

        This behaves identically to File → Open Level in the editor.  If there
        are unsaved changes in the current level, the editor will prompt to save
        them (same behaviour as manual file open).

        The response includes the previous world path so the caller knows what
        was open before the switch.
        """
        if not level_path.startswith("/Game/"):
            return client.format_json(
                _error(
                    "open_level",
                    f"Invalid level_path '{level_path}'. Must start with '/Game/'.",
                )
            )

        try:
            result = await client.open_level(level_path)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("open_level", str(exc)))

    @mcp.tool()
    async def save_current_level(
    ) -> str:
        """Save the currently active (persistent) level.

        Equivalent to Ctrl+S in the editor.  Returns the level package path
        and whether the save was successful.  If the level was not dirty
        (no unsaved changes), the operation still succeeds.

        Use this after any batch operation that modifies the level to ensure
        changes are persisted to disk.
        """
        try:
            result = await client.save_level()
            payload: dict[str, Any] = {
                **result,
                "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("save_current_level", str(exc)))

    @mcp.tool()
    async def set_world_settings(
        gravity_z: Annotated[
            float | None,
            "Override world gravity Z component (cm/s²). "
            "UE default is -980 (Earth gravity). "
            "Use 0 for zero-gravity, positive for reversed gravity.",
        ] = None,
        game_time_dilation: Annotated[
            float | None,
            "World time dilation multiplier. 1.0 = normal speed, "
            "0.5 = half speed, 2.0 = double speed.",
        ] = None,
        kill_z: Annotated[
            float | None,
            "Z depth below which actors are automatically destroyed. "
            "Default is -100000 cm (1km below origin).",
        ] = None,
    ) -> str:
        """Configure gravity, time dilation, and kill-Z for the current world.

        All parameters are optional — provide only the settings you want to
        change.  Returns before/after values for every setting that was updated.

        Future parameters (extensible design):
          world_to_meters, navigation_system, ai_system, physics_handler
        """
        updates: dict[str, Any] = {}
        if gravity_z is not None:
            updates["gravity_z"] = gravity_z
        if game_time_dilation is not None:
            updates["game_time_dilation"] = game_time_dilation
        if kill_z is not None:
            updates["kill_z"] = kill_z

        if not updates:
            return client.format_json(
                _error(
                    "set_world_settings",
                    "No settings provided. Specify at least one of: "
                    "gravity_z, game_time_dilation, kill_z.",
                )
            )

        try:
            result = await client.set_world_settings(updates)
            payload: dict[str, Any] = {
                **result,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("set_world_settings", str(exc)))

    # ==================================================================
    # PHASE 3 · FOLIAGE SYSTEMS
    # ==================================================================

    @mcp.tool()
    async def spawn_foliage(
        mesh_path: Annotated[
            str,
            "Full /Game/... path to the StaticMesh asset to use as foliage. "
            "Example: '/Game/Environment/Foliage/SM_Tree_Oak'. "
            "Use list_project_assets(category_filter='static_meshes') to find valid paths.",
        ],
        density: Annotated[
            float,
            "Number of instances per 100 m² (10,000 cm²). "
            "Example: 50 = 50 trees per 100m². Adjust for desired coverage.",
        ] = 50.0,
        area_min_x: Annotated[float, "Minimum X bound of the placement area (cm)."] = 0.0,
        area_min_y: Annotated[float, "Minimum Y bound of the placement area (cm)."] = 0.0,
        area_max_x: Annotated[float, "Maximum X bound of the placement area (cm)."] = 10000.0,
        area_max_y: Annotated[float, "Maximum Y bound of the placement area (cm)."] = 10000.0,
        scale_min: Annotated[
            float,
            "Minimum uniform scale factor for each instance. Default 0.9.",
        ] = 0.9,
        scale_max: Annotated[
            float,
            "Maximum uniform scale factor for each instance. Default 1.2.",
        ] = 1.2,
        seed: Annotated[
            int,
            "Random seed for reproducible placement. Same seed + same parameters "
            "always produces the same distribution.",
        ] = 42,
        align_to_normal: Annotated[
            bool,
            "Align each instance to the surface normal below it (for slopes). "
            "Default true.",
        ] = True,
        random_yaw: Annotated[
            bool,
            "Randomise Z-axis (yaw) rotation for each instance. Default true.",
        ] = True,
    ) -> str:
        """Place foliage instances across a region of the world.

        This is the primary tool for populating environments with trees, rocks,
        grass, or any StaticMesh asset.  Density and area bounds determine how
        many instances are placed and where.

        Example: place 500 pine trees across a 200×200m forest:
          mesh_path='/Game/Environment/SM_PineTree'
          density=50, area 0–20000 in both axes, scale_min=0.8, scale_max=1.4

        Placement statistics are returned so the AI can report exactly how
        many instances were created.

        Requires: FoliageEdit module enabled.  Python Script Plugin for live mode.
        """
        try:
            result = await client.spawn_foliage(
                mesh_path=mesh_path,
                density=density,
                area_min={"x": area_min_x, "y": area_min_y},
                area_max={"x": area_max_x, "y": area_max_y},
                scale_min=scale_min,
                scale_max=scale_max,
                seed=seed,
                align_to_normal=align_to_normal,
                random_yaw=random_yaw,
            )
            payload: dict[str, Any] = {
                **result,
                "placed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("spawn_foliage", str(exc)))

    @mcp.tool()
    async def clear_foliage(
        mesh_path: Annotated[
            str,
            "Full /Game/... path to the StaticMesh whose instances should be cleared. "
            "Leave empty to clear ALL foliage types.",
        ] = "",
        region_min_x: Annotated[
            float | None,
            "Minimum X of the region to clear (cm). "
            "Leave empty to clear across the entire world.",
        ] = None,
        region_min_y: Annotated[float | None, "Minimum Y of the region to clear (cm)."] = None,
        region_max_x: Annotated[float | None, "Maximum X of the region to clear (cm)."] = None,
        region_max_y: Annotated[float | None, "Maximum Y of the region to clear (cm)."] = None,
    ) -> str:
        """Remove foliage instances, optionally scoped to a mesh type or region.

        Combinations:
          • Provide mesh_path only → clear all instances of that mesh type
          • Provide region_* only → clear all foliage within that XY box
          • Provide both → clear a specific mesh type within a region
          • Provide neither → clear ALL foliage (use with caution)

        This is a destructive operation — use dry-run or inspect the existing
        foliage with list_project_assets before calling.
        """
        region_min: dict[str, float] | None = None
        region_max: dict[str, float] | None = None

        if region_min_x is not None and region_min_y is not None:
            region_min = {"x": region_min_x, "y": region_min_y}
        if region_max_x is not None and region_max_y is not None:
            region_max = {"x": region_max_x, "y": region_max_y}

        try:
            result = await client.clear_foliage(
                mesh_path=mesh_path,
                region_min=region_min,
                region_max=region_max,
            )
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("clear_foliage", str(exc)))

    @mcp.tool()
    async def configure_lod(
        mesh_path: Annotated[
            str,
            "Full /Game/... path to the StaticMesh asset. "
            "Example: '/Game/Environment/Rocks/SM_Rock_01'. "
            "Use list_project_assets(category_filter='static_meshes') to find valid paths.",
        ],
        lod0_screen_size: Annotated[
            float,
            "Screen-size threshold for LOD0 (full detail). Range 0.0–1.0. "
            "Typical value: 1.0 (show LOD0 when mesh fills most of screen).",
        ] = 1.0,
        lod1_screen_size: Annotated[
            float,
            "Screen-size threshold for LOD1. Range 0.0–1.0. Typical: 0.3.",
        ] = 0.3,
        lod2_screen_size: Annotated[
            float,
            "Screen-size threshold for LOD2. Range 0.0–1.0. Typical: 0.15.",
        ] = 0.15,
        lod3_screen_size: Annotated[
            float,
            "Screen-size threshold for LOD3 (lowest detail). Range 0.0–1.0. Typical: 0.05.",
        ] = 0.05,
    ) -> str:
        """Set LOD screen-size thresholds for a StaticMesh asset.

        Lower screen-size values mean a LOD switches in only when the mesh is
        very small on screen (far away), keeping higher-detail LODs visible
        for longer.  The values must be decreasing from LOD0 to LOD3.

        Returns the previous LOD settings alongside the new ones so the AI can
        confirm or revert the change.

        Requires: Python Script Plugin enabled in the editor (live mode).
        """
        lod_distances = [
            lod0_screen_size,
            lod1_screen_size,
            lod2_screen_size,
            lod3_screen_size,
        ]

        # Validate decreasing order
        for i in range(len(lod_distances) - 1):
            if lod_distances[i] < lod_distances[i + 1]:
                return client.format_json(
                    _error(
                        "configure_lod",
                        f"LOD screen sizes must be in decreasing order. "
                        f"LOD{i} ({lod_distances[i]}) < LOD{i+1} ({lod_distances[i+1]}).",
                    )
                )

        try:
            result = await client.configure_lod(mesh_path, lod_distances)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("configure_lod", str(exc)))

    @mcp.tool()
    async def generate_collision(
        mesh_path: Annotated[
            str,
            "Full /Game/... path to the StaticMesh asset. "
            "Example: '/Game/Environment/Rocks/SM_Rock_01'.",
        ],
        collision_type: Annotated[
            str,
            "Collision generation method. Options:\n"
            "  'complex_as_simple' — use the render mesh as collision (accurate, expensive)\n"
            "  'simple_box'        — generate a simple box collision (fast)\n"
            "  'simple_convex'     — generate a convex hull approximation\n"
            "  'default'           — use UE default collision settings",
        ] = "complex_as_simple",
    ) -> str:
        """Auto-generate collision geometry for a StaticMesh asset.

        This is required for any mesh that should block characters, projectiles,
        or other physics objects in the world.  Without collision, actors will
        pass through the mesh even if it is visible.

        Returns the previous collision setting and the new one.  Save the
        asset after calling this to persist the change.

        Requires: Python Script Plugin enabled in the editor (live mode).
        """
        valid_types = {"complex_as_simple", "simple_box", "simple_convex", "default"}
        if collision_type not in valid_types:
            return client.format_json(
                _error(
                    "generate_collision",
                    f"Invalid collision_type '{collision_type}'. "
                    f"Valid options: {', '.join(sorted(valid_types))}.",
                )
            )

        try:
            result = await client.generate_collision(mesh_path, collision_type)
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("generate_collision", str(exc)))

    # ==================================================================
    # PHASE 4 · LANDSCAPE & PCG FOUNDATION
    # ==================================================================

    @mcp.tool()
    async def list_landscape_layers(
    ) -> str:
        """Return all layer info objects defined on the Landscape actor.

        Each layer entry contains:
          • name — display name (e.g. "Grass", "Dirt", "Rock")
          • layer_info_path — the /Game/... path to the LandscapeLayerInfoObject
          • is_weight_blended — whether the layer participates in weight blending
          • material_slot_index — its index in the landscape material
          • average_weight — estimated coverage across the landscape (mock only)

        Use this before paint_landscape_layer to confirm layer names and paths.
        """
        try:
            result = await client.list_landscape_layers()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock data — connect a live editor with a Landscape actor "
                    "in the level for real layer data."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_landscape_layers", str(exc)))

    @mcp.tool()
    async def paint_landscape_layer(
        layer_name: Annotated[
            str,
            "Name of the landscape layer to paint. "
            "Use list_landscape_layers to get valid layer names.",
        ],
        region_min_x: Annotated[
            float,
            "Minimum X of the painting region (cm). 0 = landscape origin.",
        ] = 0.0,
        region_min_y: Annotated[float, "Minimum Y of the painting region (cm)."] = 0.0,
        region_max_x: Annotated[float, "Maximum X of the painting region (cm)."] = 10000.0,
        region_max_y: Annotated[float, "Maximum Y of the painting region (cm)."] = 10000.0,
        weight: Annotated[
            float,
            "Target layer weight. 0.0 = paint nothing, 1.0 = full coverage. "
            "Other weight-blended layers will be reduced proportionally.",
        ] = 1.0,
        blend_falloff: Annotated[
            float,
            "Feathering/falloff distance in cm at the region border. "
            "0 = hard edge, positive values create a smooth blend.",
        ] = 0.0,
    ) -> str:
        """Apply a layer weight to a landscape region.

        This is a foundational tool for terrain painting — for example,
        painting "Grass" across the valley floor and "Rock" on steep slopes.

        Note: Full weight-paint implementation in live mode requires either:
          a) Python Script Plugin + landscape Python API (partial support)
          b) A custom C++ editor plugin for precise paint control

        The tool returns the affected area and weight applied so the AI can
        confirm the operation before committing.
        """
        if not 0.0 <= weight <= 1.0:
            return client.format_json(
                _error(
                    "paint_landscape_layer",
                    f"Weight must be between 0.0 and 1.0, got {weight}.",
                )
            )
        if blend_falloff < 0:
            return client.format_json(
                _error(
                    "paint_landscape_layer",
                    f"blend_falloff must be >= 0, got {blend_falloff}.",
                )
            )

        try:
            result = await client.paint_landscape_layer(
                layer_name=layer_name,
                region_min={"x": region_min_x, "y": region_min_y},
                region_max={"x": region_max_x, "y": region_max_y},
                weight=weight,
                blend_falloff=blend_falloff,
            )
            return client.format_json(result)
        except UEConnectionError as exc:
            return client.format_json(_error("paint_landscape_layer", str(exc)))

    @mcp.tool()
    async def configure_pcg_graph(
        graph_actor_name: Annotated[
            str,
            "Display name of the actor carrying the PCGComponent (as shown "
            "in the Outliner). Use list_actors or find_actors_by_tag to locate it.",
        ],
        parameter_updates: Annotated[
            str,
            "JSON object mapping parameter names to new values. "
            "Example: '{\"Density\": 500, \"Seed\": 42, \"bEnabled\": true}'. "
            "Parameter names must match the exposed variable names in the PCG graph.",
        ],
    ) -> str:
        """Read and update exposed parameters on a PCG Graph Component.

        PCG (Procedural Content Generation) graphs expose parameters that
        control procedural generation — things like density, seed, scale
        ranges, and enabled/disabled sub-graphs.

        This tool reads the current values, applies the updates, and returns a
        before/after diff so the AI can confirm what changed.

        Requires: PCG Plugin enabled.  Python Script Plugin for live mode.
        """
        import json as _json

        try:
            updates: dict[str, Any] = _json.loads(parameter_updates)
        except _json.JSONDecodeError as exc:
            return client.format_json(
                _error(
                    "configure_pcg_graph",
                    f"parameter_updates is not valid JSON: {exc}",
                )
            )

        if not isinstance(updates, dict) or not updates:
            return client.format_json(
                _error(
                    "configure_pcg_graph",
                    "parameter_updates must be a non-empty JSON object.",
                )
            )

        try:
            result = await client.configure_pcg_graph(graph_actor_name, updates)
            payload: dict[str, Any] = {
                **result,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("configure_pcg_graph", str(exc)))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error(tool: str, message: str) -> dict[str, Any]:
    """Construct a structured error payload that is safe to return to the AI."""
    return {
        "error": message,
        "tool": tool,
        "success": False,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
