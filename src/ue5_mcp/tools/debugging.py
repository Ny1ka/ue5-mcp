"""Debugging tools — Layer 4 of the Unreal MCP platform.

This module gives the AI the ability to diagnose real problems in a UE5 project:
collision issues that cause characters to fall through floors, performance hotspots,
broken asset references, stale lightmaps, and more.

Tools are organised into four functional groups:

  Group 1 · Collision & Physics
    check_actor_collision, check_character_capsule,
    list_physics_bodies, visualize_collision

  Group 2 · Performance
    get_draw_call_stats, get_shader_complexity,
    find_expensive_actors, list_unbuilt_lighting

  Group 3 · Asset Validation
    find_missing_references, find_oversized_textures,
    validate_blueprint, list_redirectors

  Group 4 · Log Analysis
    get_output_log, get_message_log, clear_output_log

All tools:
  • Work in mock mode (UE_MOCK_MODE=true)
  • Return structured JSON via client.format_json()
  • Handle UEConnectionError gracefully
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_debugging_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all Layer 4 debugging tools on the MCP server."""

    # ==================================================================
    # GROUP 1 · COLLISION & PHYSICS
    # ==================================================================

    @mcp.tool()
    async def check_actor_collision(
        actor_name: Annotated[
            str,
            "Display name of the actor to inspect (as shown in the Outliner). "
            "Use list_actors first to confirm the exact name.",
        ],
    ) -> str:
        """Inspect collision settings on a specific actor.

        Returns the collision profile, enabled state, object type, and
        per-component collision configuration.

        This is the first tool to call when diagnosing 'my character falls through
        the floor' or 'projectiles pass through walls' issues.

        Example diagnosis workflow:
          1. check_actor_collision('SM_Floor_01')
          2. If collision_enabled='NoCollision' → use set_actor_property to fix
          3. If profile='OverlapAll' → change to 'BlockAll' for solid objects
        """
        try:
            result = await client.check_actor_collision(actor_name)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock collision data. Connect a live editor for real collision info."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("check_actor_collision", str(exc)))

    @mcp.tool()
    async def check_character_capsule(
        actor_name: Annotated[
            str,
            "Display name of the Character or Pawn actor. "
            "Use list_actors or find_actors_by_tag(class_name='Character') "
            "to find Character actors.",
        ],
    ) -> str:
        """Validate a Character's capsule size against its mesh bounding box.

        A common cause of characters clipping through geometry or floating
        above the ground is a CapsuleComponent that doesn't match the
        SkeletalMesh's bounds.

        This tool measures both and flags mismatches with a plain-language
        diagnosis so the AI can recommend the correct capsule dimensions.

        Common findings:
          • Capsule too tall — character floats above ground
          • Capsule too short — character clips into the floor
          • Capsule too narrow — character clips through walls
          • Capsule too wide — character gets stuck in narrow passages
        """
        try:
            result = await client.check_character_capsule(actor_name)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("check_character_capsule", str(exc)))

    @mcp.tool()
    async def list_physics_bodies(
    ) -> str:
        """Return all physics bodies in the current level with their settings.

        Reports each PrimitiveComponent that has collision enabled, along with:
          • simulate_physics — whether the body is physics-simulated
          • mass_kg — body mass in kilograms
          • damping — linear and angular drag
          • collision_profile — the named profile in use

        Use this to find physics bodies that are unexpectedly simulating,
        or bodies missing mass/damping values that affect gameplay.
        """
        try:
            result = await client.list_physics_bodies()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock physics data — connect a live editor for real physics body info."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_physics_bodies", str(exc)))

    @mcp.tool()
    async def visualize_collision(
        enabled: Annotated[
            bool,
            "True to enable collision visualisation overlay in the viewport, "
            "False to disable it and return to normal rendering.",
        ] = True,
    ) -> str:
        """Toggle collision geometry visualisation in the editor viewport.

        When enabled, all collision shapes are rendered as coloured
        semi-transparent overlays:
          • Green  = simple collision (BlockAll)
          • Blue   = complex collision
          • Yellow = no collision / query-only

        This makes it easy to spot missing collision on any actor without
        inspecting properties individually.

        Use check_actor_collision for per-actor details after identifying
        which actors have unexpected collision shapes in this view.
        """
        try:
            result = await client.visualize_collision(enabled)
            payload: dict[str, Any] = {
                **result,
                "toggled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("visualize_collision", str(exc)))

    # ==================================================================
    # GROUP 2 · PERFORMANCE
    # ==================================================================

    @mcp.tool()
    async def get_draw_call_stats(
    ) -> str:
        """Return draw call counts and GPU timing from the most recent frame.

        High draw call counts (> 2000 on mid-range hardware) are a common
        performance bottleneck.  This tool provides:
          • draw_calls — total GPU draw calls in the last frame
          • mesh_draw_calls — draw calls attributed to StaticMesh / SkeletalMesh
          • translucent_draw_calls — draw calls for translucent materials
          • gpu_ms — time the GPU spent rendering the frame
          • fps — frames per second

        Note: Accurate timing requires a PIE session or real-time editor mode.
        Mock mode returns representative values for a mid-complexity scene.
        """
        try:
            result = await client.get_draw_call_stats()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Representative mock stats. Start a PIE session for real GPU timing."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_draw_call_stats", str(exc)))

    @mcp.tool()
    async def get_shader_complexity(
    ) -> str:
        """Enable shader complexity view mode and return average complexity scores.

        Shader complexity measures how expensive materials are to render,
        expressed as a 0–1 score (higher = more expensive):
          • 0.0–0.3  — cheap (simple materials, minimal instructions)
          • 0.3–0.6  — moderate (normal maps, layered materials)
          • 0.6–0.8  — expensive (many texture samples, complex math)
          • 0.8–1.0  — very expensive (consider simplifying or LOD-ing)

        In live mode this command enables the 'viewmode shadercomplexity'
        console command in the viewport.
        """
        try:
            result = await client.get_shader_complexity()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_shader_complexity", str(exc)))

    @mcp.tool()
    async def find_expensive_actors(
    ) -> str:
        """Identify actors contributing most to frame cost.

        Ranks actors by estimated draw call contribution and triangle count.
        Each result includes a human-readable recommendation.

        Common findings:
          • Landscape with many components — enable World Partition
          • High-poly characters without LOD — configure LOD via configure_lod
          • Overdrawing translucent particles — reduce emitter spawn rate
          • Many small static meshes — merge with HLOD or instancing
        """
        try:
            result = await client.find_expensive_actors()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Estimated mock data. Live mode uses real draw call attribution."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("find_expensive_actors", str(exc)))

    @mcp.tool()
    async def list_unbuilt_lighting(
    ) -> str:
        """Find static meshes and actors with missing or stale lightmap builds.

        UE displays a 'Lighting needs to be rebuilt' warning when any actor
        has been moved, spawned, or modified since the last lighting build.

        Returns each unbuilt actor with its lightmap resolution and the reason
        its lightmap is considered stale, plus a recommended build command.

        Actors with unbuilt lighting will render with an incorrect/preview
        shadow at runtime — always build lighting before shipping.
        """
        try:
            result = await client.list_unbuilt_lighting()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock lighting data — run Build → Build Lighting in the editor "
                    "to resolve stale lightmaps."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_unbuilt_lighting", str(exc)))

    # ==================================================================
    # GROUP 3 · ASSET VALIDATION
    # ==================================================================

    @mcp.tool()
    async def find_missing_references(
    ) -> str:
        """Detect broken asset references across the /Game/ folder.

        Broken references occur when an asset that another asset depends on
        has been deleted, renamed without a redirector, or moved to a path
        that no longer exists.

        Broken references cause:
          • Visual artefacts (missing textures, meshes)
          • Cook warnings and potential cook failures
          • Runtime loading errors

        Returns each broken reference with the asset that contains it and
        the missing dependency path.
        """
        try:
            result = await client.find_missing_references()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock missing references. Connect a live editor with a project "
                    "to scan for real broken dependencies."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("find_missing_references", str(exc)))

    @mcp.tool()
    async def find_oversized_textures(
        max_resolution: Annotated[
            int,
            "Pixel dimension threshold. Textures where width OR height exceeds this "
            "value will be flagged. Common values: 2048, 4096. Default 4096.",
        ] = 4096,
    ) -> str:
        """List textures above a given resolution threshold.

        Large textures (8K+) consume significant memory and increase cook times.
        This tool helps identify candidates for:
          • Downscaling to a lower resolution
          • Converting to a Virtual Texture (for large tiling textures)
          • Updating texture compression settings

        Each flagged texture includes its dimensions, disk size, and a
        specific recommendation based on its likely use case.
        """
        if max_resolution < 64:
            return client.format_json(
                _error(
                    "find_oversized_textures",
                    f"max_resolution must be at least 64, got {max_resolution}.",
                )
            )

        try:
            result = await client.find_oversized_textures(max_resolution)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("find_oversized_textures", str(exc)))

    @mcp.tool()
    async def validate_blueprint(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset to validate. "
            "Example: '/Game/Characters/BP_EnemyBase'.",
        ],
    ) -> str:
        """Check a Blueprint for compile errors, broken references, and bad nodes.

        Runs a compile check and inspects the Blueprint graph for:
          • Nodes with missing connections (red error nodes)
          • References to deleted assets or removed functions
          • Pure function cycles (infinite loops)
          • Missing parent function implementations

        Returns a structured list of errors and warnings with the node
        identifier so you can locate and fix each issue.

        Use compile_blueprint after fixing errors to confirm the resolution.
        """
        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error("validate_blueprint", "blueprint_path must start with '/Game/'.")
            )

        try:
            result = await client.validate_blueprint(blueprint_path)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("validate_blueprint", str(exc)))

    @mcp.tool()
    async def list_redirectors(
    ) -> str:
        """Find stale asset redirectors that should be fixed.

        Redirectors are automatically created when you rename or move an asset.
        They ensure existing references still resolve to the new location.
        Over time, stale redirectors accumulate and cause:
          • Increased cook times (each redirector is a separate cook step)
          • Asset Registry clutter
          • Potential reference confusion when multiple redirectors chain

        Returns each redirector with its source and target paths, and flags
        stale ones (redirectors pointing to an asset that no longer exists
        at the target).

        Fix all redirectors by right-clicking a folder in the Content Browser
        and selecting 'Fix Up Redirectors in Folder'.
        """
        try:
            result = await client.list_redirectors()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock redirector list. Run 'Fix Up Redirectors in Folder' in "
                    "the Content Browser to resolve stale redirectors."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_redirectors", str(exc)))

    # ==================================================================
    # GROUP 4 · LOG ANALYSIS
    # ==================================================================

    @mcp.tool()
    async def get_output_log(
        category: Annotated[
            str,
            "Log category to filter by. Examples: 'LogTemp', 'LogAI', "
            "'LogPhysics', 'LogBlueprint', 'LogNet'. "
            "Leave empty to return entries from all categories.",
        ] = "",
        max_lines: Annotated[
            int,
            "Maximum number of log lines to return. Default 100.",
        ] = 100,
        log_level: Annotated[
            str,
            "Filter by severity: 'Log', 'Warning', 'Error', 'Fatal'. "
            "Leave empty to return all levels.",
        ] = "",
    ) -> str:
        """Retrieve recent Output Log entries, optionally filtered.

        The Output Log is the primary diagnostic stream in UE — it captures
        blueprint prints, AI decisions, physics warnings, network events, and
        more.  Use this to gather context before diagnosing a bug.

        Filtering by log_level='Error' is especially useful for surfacing
        critical failures without noise from informational messages.

        In live mode, the Output Log is read from the most recent
        Saved/Logs/<Project>.log file.
        """
        if max_lines < 1:
            return client.format_json(
                _error("get_output_log", "max_lines must be at least 1.")
            )
        if max_lines > 5000:
            return client.format_json(
                _error("get_output_log", "max_lines must be 5000 or less.")
            )

        valid_levels = {"", "Log", "Warning", "Error", "Fatal"}
        if log_level not in valid_levels:
            return client.format_json(
                _error(
                    "get_output_log",
                    "log_level must be one of: "
                    + ", ".join(repr(lv) for lv in sorted(valid_levels)) + ".",
                )
            )

        try:
            result = await client.get_output_log(category, max_lines, log_level)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock log data. Connect a live editor for real Output Log entries."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_output_log", str(exc)))

    @mcp.tool()
    async def get_message_log(
        max_entries: Annotated[
            int,
            "Maximum number of message log entries to return. Default 50.",
        ] = 50,
    ) -> str:
        """Retrieve the Message Log (compile errors, map check warnings, validation).

        The Message Log is separate from the Output Log — it contains structured
        diagnostic messages from:
          • Blueprint compilation (syntax errors, missing connections)
          • Map Check (missing lightmaps, missing BSP brushes, scale warnings)
          • Asset validation (cook errors, missing dependencies)
          • Build and cook pipelines

        Each entry has a severity (Error / Warning / Info), the source system,
        and a clickable link to the affected asset or node.

        Use this alongside get_output_log when diagnosing build failures or
        Blueprint compile issues.
        """
        if max_entries < 1:
            return client.format_json(
                _error("get_message_log", "max_entries must be at least 1.")
            )

        try:
            result = await client.get_message_log(max_entries)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_message_log", str(exc)))

    @mcp.tool()
    async def clear_output_log(
    ) -> str:
        """Clear the Output Log to make new messages easier to spot.

        Use before triggering a specific action (Blueprint compile, level load,
        gameplay test) so the log only contains messages from that action.

        Equivalent to right-clicking in the Output Log panel and selecting
        'Clear Log'.

        The audit log is NOT cleared by this command — only the editor's
        in-memory output buffer.
        """
        try:
            result = await client.clear_output_log()
            payload: dict[str, Any] = {
                **result,
                "cleared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("clear_output_log", str(exc)))


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
