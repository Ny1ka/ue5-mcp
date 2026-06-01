"""Editor and level tools — starting point for actor/level automation."""

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_editor_tools(mcp: FastMCP, client: UEClient) -> None:
    @mcp.tool()
    async def ue_ping() -> str:
        """Check connectivity to the Unreal Editor Remote Control API."""
        try:
            result = await client.ping()
            return client.format_json(result)
        except UEConnectionError as exc:
            return str(exc)

    @mcp.tool()
    async def ue_get_editor_info() -> str:
        """Return basic editor connection info (extend with level name, selection, PIE state)."""
        result = await client.ping()
        return client.format_json(result)
