"""MCP server entry point — wires tools, resources, and prompts together."""

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient
from ue5_mcp.config import get_settings
from ue5_mcp.prompts import register_workflow_prompts
from ue5_mcp.resources import register_engine_resources
from ue5_mcp.tools import register_editor_tools

# FastMCP instance — name appears in MCP client UI
mcp = FastMCP(
    "ue5-mcp",
    instructions=(
        "MCP server for Unreal Engine 5. Use tools to query and control the editor "
        "when connected. Enable mock mode (UE_MOCK_MODE=true) for development without UE."
    ),
)


def create_app() -> FastMCP:
    """Register all MCP primitives on the shared FastMCP instance."""
    settings = get_settings()
    client = UEClient(settings)

    register_editor_tools(mcp, client)
    register_engine_resources(mcp, client)
    register_workflow_prompts(mcp)

    return mcp


def main() -> None:
    create_app()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
