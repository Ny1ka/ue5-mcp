"""MCP tools — actions the agent can invoke (spawn actors, run commands, etc.)."""

from ue5_mcp.tools.assets import register_asset_tools
from ue5_mcp.tools.blueprints import register_blueprint_tools
from ue5_mcp.tools.debugging import register_debugging_tools
from ue5_mcp.tools.editor import register_editor_tools
from ue5_mcp.tools.environment import register_environment_tools
from ue5_mcp.tools.testing import register_testing_tools

__all__ = [
    "register_editor_tools",
    "register_asset_tools",
    "register_environment_tools",
    "register_blueprint_tools",
    "register_debugging_tools",
    "register_testing_tools",
]
