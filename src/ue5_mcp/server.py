"""MCP server entry point — wires tools, resources, and prompts together."""

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient
from ue5_mcp.config import get_settings
from ue5_mcp.prompts import register_workflow_prompts
from ue5_mcp.resources import register_engine_resources
from ue5_mcp.tools import (
    register_asset_tools,
    register_blueprint_tools,
    register_debugging_tools,
    register_editor_tools,
    register_environment_tools,
    register_spatial_tools,
    register_testing_tools,
)

# FastMCP instance — name appears in MCP client UI
mcp = FastMCP(
    "ue5-mcp",
    instructions=(
        "MCP server for Unreal Engine 5. Use tools to query and control the editor "
        "when connected. Enable mock mode (UE_MOCK_MODE=true) for development without UE. "
        "Always call list_project_assets first to understand what exists in the project "
        "before generating Blueprints, placing assets, or diagnosing issues. "
        "For debugging issues, start with check_actor_collision or get_output_log. "
        "For testing, use list_automation_tests then run_automation_test. "
        "When building environments: call sync_occupancy_grid at session start, then use "
        "spawn_actor_safe (not spawn_actor) for all actor placement — it validates "
        "occupancy, snaps to ground, checks slope, and tracks every actor so nothing "
        "overlaps. Use validate_spawn for a dry-run check before committing. "
        "Use show_occupancy_debug to visualise occupied cells and preview_spawn to "
        "preview placement without spawning. "
        "For assembled structures (cabins, houses, warehouses, towers), call "
        "list_structure_templates then build_structure instead of spawning "
        "components one at a time. For roads, fences, or rivers, use "
        "create_road_segment or create_spline_actor + add_spline_mesh."
    ),
)


def create_app() -> FastMCP:
    """Register all MCP primitives on the shared FastMCP instance."""
    settings = get_settings()
    client = UEClient(settings)

    # Layer 1 — Project Knowledge
    register_editor_tools(mcp, client)
    register_asset_tools(mcp, client)

    # Layer 2 — Environment Tools
    register_environment_tools(mcp, client)

    # Layer 1.5 — Spatial Validation
    register_spatial_tools(mcp, client)

    # Layer 3 — Blueprint Tools
    register_blueprint_tools(mcp, client)

    # Layer 4 — Debugging Tools
    register_debugging_tools(mcp, client)

    # Layer 5 — Testing Tools
    register_testing_tools(mcp, client)

    # Resources and Prompts
    register_engine_resources(mcp, client)
    register_workflow_prompts(mcp)

    return mcp


def main() -> None:
    create_app()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
