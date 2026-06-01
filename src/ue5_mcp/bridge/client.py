"""HTTP client for Unreal Engine's Remote Control API.

See: https://docs.unrealengine.com/en-US/remote-control-api-in-unreal-engine
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ue5_mcp.config import Settings


class UEConnectionError(Exception):
    """Raised when the editor is unreachable or returns an error."""


class UEClient:
    """Talks to UE via Remote Control HTTP endpoints.

    This is intentionally minimal — expand with preset calls, property get/set,
    and batch operations as you add tools.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._timeout = settings.ue_request_timeout_ms / 1000.0

    @property
    def is_mock(self) -> bool:
        return self.settings.ue_mock_mode

    async def ping(self) -> dict[str, Any]:
        """Check whether the Remote Control API is reachable."""
        if self.is_mock:
            return {
                "connected": True,
                "mock": True,
                "message": "Mock mode — no live editor required.",
            }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # Remote Control exposes info at the root; adjust as you discover your UE version's routes.
                response = await client.get(f"{self.settings.ue_http_base_url}/remote/info")
                response.raise_for_status()
                return {"connected": True, "mock": False, "info": response.json()}
        except httpx.HTTPError as exc:
            raise UEConnectionError(
                f"Cannot reach Unreal at {self.settings.ue_http_base_url}. "
                "Is the editor open with Remote Control API enabled?"
            ) from exc

    async def get(self, path: str) -> Any:
        if self.is_mock:
            return {"mock": True, "path": path, "data": []}

        url = f"{self.settings.ue_http_base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def put(self, path: str, body: dict[str, Any]) -> Any:
        if self.is_mock:
            return {"mock": True, "path": path, "accepted": body}

        url = f"{self.settings.ue_http_base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.put(url, json=body)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {"ok": True}

    def format_json(self, data: Any) -> str:
        return json.dumps(data, indent=2, default=str)
