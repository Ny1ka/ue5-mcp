"""HTTP client for Unreal Engine's Remote Control API.

See: https://docs.unrealengine.com/en-US/remote-control-api-in-unreal-engine

Remote Control object/call reference
-------------------------------------
PUT /remote/object/call
{
    "objectPath": "<UE object path>",
    "functionName": "<function>",
    "parameters": { ... }
}

The asset listing flow uses EditorAssetLibrary (requires the
EditorScriptingUtilities plugin in the editor).  Results are enriched by
calling FindAssetData per path to obtain the real UE class name, enabling
exact category mapping instead of heuristic prefix/folder matching.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ue5_mcp.config import Settings

# UE Remote Control object path for EditorAssetLibrary
_EDITOR_ASSET_LIB = (
    "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary"
)


class UEConnectionError(Exception):
    """Raised when the editor is unreachable or returns an error."""


class UEClient:
    """Talks to UE via Remote Control HTTP endpoints.

    Expand with new domain-specific async methods as you add tools.
    All methods accept mock-mode guard at the top so no live editor is needed
    during development (UE_MOCK_MODE=true).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._timeout = settings.ue_request_timeout_ms / 1000.0

    @property
    def is_mock(self) -> bool:
        return self.settings.ue_mock_mode

    # ------------------------------------------------------------------
    # Low-level primitives
    # ------------------------------------------------------------------

    async def ping(self) -> dict[str, Any]:
        """Check whether the Remote Control API is reachable."""
        if self.is_mock:
            return {
                "connected": True,
                "mock": True,
                "message": "Mock mode — no live editor required.",
            }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.get(f"{self.settings.ue_http_base_url}/remote/info")
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
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.get(url)
            response.raise_for_status()
            return response.json()

    async def put(self, path: str, body: dict[str, Any]) -> Any:
        if self.is_mock:
            return {"mock": True, "path": path, "accepted": body}

        url = f"{self.settings.ue_http_base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.put(url, json=body)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {"ok": True}

    # ------------------------------------------------------------------
    # Remote Control object/call helpers
    # ------------------------------------------------------------------

    async def call_editor_function(
        self,
        object_path: str,
        function_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> Any:
        """Call an arbitrary UE function via Remote Control /remote/object/call.

        Returns the parsed response body.  Raises UEConnectionError on HTTP
        or connection failure.  Does NOT guard mock mode — callers decide.
        """
        body: dict[str, Any] = {
            "objectPath": object_path,
            "functionName": function_name,
            "parameters": parameters or {},
            "generateTransaction": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.put(
                    f"{self.settings.ue_http_base_url}/remote/object/call",
                    json=body,
                )
                response.raise_for_status()
                return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise UEConnectionError(
                f"Remote function call failed: {object_path}.{function_name}"
            ) from exc

    # ------------------------------------------------------------------
    # Asset discovery via Remote Control (EditorAssetLibrary)
    # ------------------------------------------------------------------

    async def list_assets_remote(
        self,
        directory: str = "/Game",
        *,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Enumerate project assets through the editor's Asset Registry.

        Requires the EditorScriptingUtilities plugin (enabled by default in
        UE5 editor builds).  Returns a dict with:
          {
            "asset_paths": ["/Game/Weapons/BP_Pistol", ...],
            "asset_data":  [{"path": ..., "class": ..., "package": ...}, ...]
          }

        Asset class names in asset_data drive exact category mapping; fall back
        to heuristic classification when this call is unavailable.
        """
        if self.is_mock:
            return {"asset_paths": [], "asset_data": [], "mock": True}

        # Step 1 — list all asset paths under the directory.
        list_result = await self.call_editor_function(
            _EDITOR_ASSET_LIB,
            "ListAssets",
            {
                "DirectoryPath": directory,
                "Recursive": recursive,
                "IncludeOnlyOnDiskAssets": False,
            },
        )

        asset_paths: list[str] = list_result.get("OutAssetList", [])
        if not asset_paths:
            return {"asset_paths": [], "asset_data": []}

        # Step 2 — bulk fetch asset metadata to get UE class names.
        # Batching avoids one HTTP round-trip per asset on large projects.
        asset_data: list[dict[str, Any]] = []

        # Process in batches of 100 to stay within Remote Control limits.
        batch_size = 100
        for i in range(0, len(asset_paths), batch_size):
            batch = asset_paths[i : i + batch_size]
            for path in batch:
                try:
                    data_result = await self.call_editor_function(
                        _EDITOR_ASSET_LIB,
                        "FindAssetData",
                        {"AssetPath": path},
                    )
                    out_data = data_result.get("OutAssetData", {})
                    asset_data.append(
                        {
                            "path": path,
                            "class": out_data.get("AssetClass", ""),
                            "package": out_data.get("PackageName", ""),
                        }
                    )
                except UEConnectionError:
                    # Non-fatal; asset will fall back to heuristic classification.
                    asset_data.append({"path": path, "class": "", "package": ""})

        return {"asset_paths": asset_paths, "asset_data": asset_data}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def format_json(self, data: Any) -> str:
        return json.dumps(data, indent=2, default=str)
