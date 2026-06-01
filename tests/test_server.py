"""Basic tests — expand as you add tools and bridge methods."""

import json

import pytest

from ue5_mcp.bridge.client import UEClient
from ue5_mcp.config import Settings
from ue5_mcp.server import create_app


@pytest.fixture
def mock_client() -> UEClient:
    return UEClient(Settings(ue_mock_mode=True))


@pytest.mark.asyncio
async def test_ping_mock_mode(mock_client: UEClient) -> None:
    result = await mock_client.ping()
    assert result["connected"] is True
    assert result["mock"] is True


def test_create_app_registers_primitives() -> None:
    app = create_app()
    assert app.name == "ue5-mcp"


def test_format_json(mock_client: UEClient) -> None:
    payload = mock_client.format_json({"ok": True})
    assert json.loads(payload) == {"ok": True}
