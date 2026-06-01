"""Engine state resources exposed to the agent."""

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import UEClient


def register_engine_resources(mcp: FastMCP, client: UEClient) -> None:
    @mcp.resource("unreal://connection/status")
    async def connection_status() -> str:
        """Current connection status to the Unreal Editor."""
        result = await client.ping()
        return client.format_json(result)

    @mcp.resource("unreal://config")
    def server_config() -> str:
        """Non-secret server configuration (host, ports, mock mode)."""
        s = client.settings
        return client.format_json(
            {
                "host": s.ue_host,
                "http_port": s.ue_http_port,
                "ws_port": s.ue_ws_port,
                "mock_mode": s.ue_mock_mode,
                "project_path": s.ue_project_path,
            }
        )
