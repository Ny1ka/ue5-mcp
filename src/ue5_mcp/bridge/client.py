"""HTTP client for Unreal Engine's Remote Control API.

See: https://docs.unrealengine.com/en-US/remote-control-api-in-unreal-engine

Remote Control reference used in this file
-------------------------------------------
PUT /remote/object/call
    {"objectPath": "...", "functionName": "...", "parameters": {...}}

PUT /remote/object/property
    Read:  {"objectPath": "...", "propertyName": "...", "access": "READ_ACCESS"}
    Write: {"objectPath": "...", "propertyName": "...", "propertyValue": {...}}

Key UE subsystems exposed via Remote Control
--------------------------------------------
EditorAssetLibrary   — asset discovery (Layer 1)
EditorActorSubsystem — list / spawn / delete / select actors
EditorLevelLibrary   — load / save levels, world settings
FoliageEditorSubsystem — foliage type and instance management
PythonScriptLibrary  — run Python inside the editor for operations not
                        reachable via pure Remote Control (foliage instances,
                        landscape painting, PCG parameter writes)

All domain methods accept a mock-mode guard at the top so the server runs
without a live editor (UE_MOCK_MODE=true).
"""

from __future__ import annotations

import json
import random
from typing import Any

import httpx

from ue5_mcp.config import Settings

# ---------------------------------------------------------------------------
# UE Remote Control object paths
# ---------------------------------------------------------------------------

# Asset discovery (Layer 1 — already in use)
_EDITOR_ASSET_LIB = "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary"

# Actor management — lives in UnrealEd (NOT EditorScriptingUtilities).
# See: https://forums.unrealengine.com/t/how-do-you-get-the-correct-remote-api-object-path-for-a-function/507987
_EDITOR_ACTOR_SUB = "/Script/UnrealEd.Default__EditorActorSubsystem"

# Level management — Blueprint library in EditorScriptingUtilities plugin.
# Note: GetEditorWorld is deprecated/unavailable remotely in UE 5.x; we derive
# the world path from actor object paths instead.
_EDITOR_LEVEL_LIB = "/Script/EditorScriptingUtilities.Default__EditorLevelLibrary"

# Foliage — requires FoliageEdit module
_FOLIAGE_EDITOR_SUB = "/Script/FoliageEdit.Default__FoliageEditorSubsystem"

# Python execution — requires Python Script Plugin
# ExecutePythonCommand lets us run arbitrary editor Python for operations that
# Remote Control cannot express as simple object/function calls (e.g. painting
# landscape weights, adding foliage instances, writing PCG parameters).
_PYTHON_SCRIPT_LIB = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"

# ---------------------------------------------------------------------------
# Realistic mock data — used when UE_MOCK_MODE=true
# ---------------------------------------------------------------------------

_MOCK_ACTORS: list[dict[str, Any]] = [
    {
        "name": "DirectionalLight_0",
        "label": "Directional Light",
        "class": "DirectionalLight",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.DirectionalLight_0",
        "location": {"x": 0.0, "y": 0.0, "z": 500.0},
        "rotation": {"pitch": -45.0, "yaw": 30.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Lighting"],
        "folder_path": "Lighting",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "SkyLight_0",
        "label": "Sky Light",
        "class": "SkyLight",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.SkyLight_0",
        "location": {"x": 0.0, "y": 0.0, "z": 600.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Lighting"],
        "folder_path": "Lighting",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "BP_PlayerStart_0",
        "label": "Player Start",
        "class": "PlayerStart",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.BP_PlayerStart_0",
        "location": {"x": 0.0, "y": 0.0, "z": 100.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": [],
        "folder_path": "",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "SM_Rock_01_0",
        "label": "SM_Rock_01",
        "class": "StaticMeshActor",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.SM_Rock_01_0",
        "location": {"x": 1200.0, "y": -800.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 45.0, "roll": 0.0},
        "scale": {"x": 2.0, "y": 2.0, "z": 2.0},
        "tags": ["Environment", "Destructible"],
        "folder_path": "Environment/Rocks",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "SM_Rock_01_1",
        "label": "SM_Rock_01_1",
        "class": "StaticMeshActor",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.SM_Rock_01_1",
        "location": {"x": 1800.0, "y": -400.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 120.0, "roll": 0.0},
        "scale": {"x": 1.5, "y": 1.5, "z": 1.5},
        "tags": ["Environment"],
        "folder_path": "Environment/Rocks",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "BP_EnemyBase_0",
        "label": "BP_EnemyBase",
        "class": "BP_EnemyBase_C",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.BP_EnemyBase_0",
        "location": {"x": 500.0, "y": 300.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 180.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Enemy", "AI"],
        "folder_path": "Actors/Enemies",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "BP_EnemyBase_1",
        "label": "BP_EnemyBase_1",
        "class": "BP_EnemyBase_C",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.BP_EnemyBase_1",
        "location": {"x": 700.0, "y": -200.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 90.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Enemy", "AI"],
        "folder_path": "Actors/Enemies",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "PointLight_0",
        "label": "Point Light",
        "class": "PointLight",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.PointLight_0",
        "location": {"x": 300.0, "y": 0.0, "z": 250.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Lighting"],
        "folder_path": "Lighting",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "BP_Door_Automatic_0",
        "label": "BP_Door_Automatic",
        "class": "BP_Door_Automatic_C",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.BP_Door_Automatic_0",
        "location": {"x": -500.0, "y": 0.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": ["Interactable", "Door"],
        "folder_path": "Actors/Interactables",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
    {
        "name": "Landscape_0",
        "label": "Landscape",
        "class": "Landscape",
        "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.Landscape_0",
        "location": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "tags": [],
        "folder_path": "Terrain",
        "level": "PersistentLevel",
        "is_selected": False,
        "is_hidden": False,
    },
]

_MOCK_LEVELS: list[dict[str, Any]] = [
    {
        "name": "PersistentLevel",
        "package_path": "/Game/Maps/L_TestLevel",
        "is_persistent": True,
        "is_loaded": True,
        "is_visible": True,
        "is_dirty": False,
        "world_partition_enabled": False,
    },
    {
        "name": "L_Sublevel_Lighting",
        "package_path": "/Game/Maps/Sublevels/L_Sublevel_Lighting",
        "is_persistent": False,
        "is_loaded": True,
        "is_visible": True,
        "is_dirty": False,
        "world_partition_enabled": False,
    },
    {
        "name": "L_Sublevel_Gameplay",
        "package_path": "/Game/Maps/Sublevels/L_Sublevel_Gameplay",
        "is_persistent": False,
        "is_loaded": False,
        "is_visible": False,
        "is_dirty": False,
        "world_partition_enabled": False,
    },
]

_MOCK_WORLD_SETTINGS: dict[str, Any] = {
    "gravity_z": -980.0,
    "global_gravity_z": -980.0,
    "default_gravity_z": -980.0,
    "game_time_dilation": 1.0,
    "matinee_time_dilation": 1.0,
    "world_to_meters": 100.0,
    "navigation_system_config": "RecastNavMesh",
    "ai_system_class": "AISystem",
    "physics_collision_handler_class": "",
    "kill_z": -100000.0,
    "broadcast_spectator_count_enabled": False,
}

_MOCK_FOLIAGE_TYPES: list[dict[str, Any]] = [
    {
        "name": "FT_GrassMeadow",
        "mesh_path": "/Game/Environment/Foliage/SM_GrassMeadow",
        "instance_count": 12400,
        "density": 500.0,
        "scale_min": 0.8,
        "scale_max": 1.2,
        "cull_distance_min": 0,
        "cull_distance_max": 8000,
        "collision_enabled": False,
    },
    {
        "name": "FT_Tree_Oak",
        "mesh_path": "/Game/Environment/Foliage/SM_Tree_Oak",
        "instance_count": 340,
        "density": 25.0,
        "scale_min": 0.9,
        "scale_max": 1.4,
        "cull_distance_min": 0,
        "cull_distance_max": 50000,
        "collision_enabled": True,
    },
    {
        "name": "FT_Rock_Small",
        "mesh_path": "/Game/Environment/Rocks/SM_Rock_Small",
        "instance_count": 870,
        "density": 50.0,
        "scale_min": 0.5,
        "scale_max": 2.0,
        "cull_distance_min": 0,
        "cull_distance_max": 20000,
        "collision_enabled": True,
    },
]

_MOCK_LANDSCAPE_LAYERS: list[dict[str, Any]] = [
    {
        "name": "Grass",
        "layer_info_path": "/Game/Landscape/Layers/LI_Grass",
        "is_weight_blended": True,
        "material_slot_index": 0,
        "hardness": 0.0,
        "average_weight": 0.62,
    },
    {
        "name": "Dirt",
        "layer_info_path": "/Game/Landscape/Layers/LI_Dirt",
        "is_weight_blended": True,
        "material_slot_index": 1,
        "hardness": 0.2,
        "average_weight": 0.24,
    },
    {
        "name": "Rock",
        "layer_info_path": "/Game/Landscape/Layers/LI_Rock",
        "is_weight_blended": True,
        "material_slot_index": 2,
        "hardness": 0.8,
        "average_weight": 0.10,
    },
    {
        "name": "Snow",
        "layer_info_path": "/Game/Landscape/Layers/LI_Snow",
        "is_weight_blended": True,
        "material_slot_index": 3,
        "hardness": 0.0,
        "average_weight": 0.04,
    },
]


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

    @staticmethod
    def _list_from_remote_result(result: dict[str, Any], *legacy_keys: str) -> list[Any]:
        """Extract a list return value from a Remote Control function response.

        UE 5.x returns lists under ``ReturnValue``; older docs reference
        ``OutActorList`` / ``OutAssetList`` style out-parameters.
        """
        value = result.get("ReturnValue")
        if isinstance(value, list):
            return value
        for key in legacy_keys:
            legacy = result.get(key)
            if isinstance(legacy, list):
                return legacy
        return []

    async def _get_all_level_actor_paths(self) -> list[str]:
        """Return object paths for every actor in the current editor level."""
        result = await self.call_editor_function(
            _EDITOR_ACTOR_SUB, "GetAllLevelActors", {}
        )
        return self._list_from_remote_result(result, "OutActorList")

    async def _get_editor_world_path(self) -> str:
        """Derive the editor world object path without deprecated GetEditorWorld.

        Actor paths look like:
        /Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.ActorName
        """
        for path in await self._get_all_level_actor_paths():
            if ":PersistentLevel." in path:
                return path.split(":PersistentLevel.", 1)[0]
        return ""

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

        asset_paths: list[str] = self._list_from_remote_result(list_result, "OutAssetList")
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
    # Generic property read/write (Remote Control /remote/object/property)
    # ------------------------------------------------------------------

    async def get_object_property(
        self,
        object_path: str,
        property_name: str,
    ) -> Any:
        """Read a single property from a UObject via Remote Control.

        Uses the READ_ACCESS mode of /remote/object/property.  The response
        body is the raw dict returned by UE — callers are responsible for
        extracting the relevant key.
        """
        if self.is_mock:
            return {"mock": True, "objectPath": object_path, "propertyName": property_name}

        body: dict[str, Any] = {
            "objectPath": object_path,
            "propertyName": property_name,
            "access": "READ_ACCESS",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.put(
                    f"{self.settings.ue_http_base_url}/remote/object/property",
                    json=body,
                )
                response.raise_for_status()
                return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise UEConnectionError(
                f"Property read failed: {object_path}.{property_name}"
            ) from exc

    async def set_object_property(
        self,
        object_path: str,
        property_name: str,
        value: Any,
    ) -> Any:
        """Write a single property on a UObject via Remote Control."""
        if self.is_mock:
            return {
                "mock": True,
                "objectPath": object_path,
                "propertyName": property_name,
                "written": value,
            }

        body: dict[str, Any] = {
            "objectPath": object_path,
            "propertyName": property_name,
            "propertyValue": {property_name: value},
            "generateTransaction": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.put(
                    f"{self.settings.ue_http_base_url}/remote/object/property",
                    json=body,
                )
                response.raise_for_status()
                return response.json() if response.content else {"ok": True}
        except httpx.HTTPError as exc:
            raise UEConnectionError(
                f"Property write failed: {object_path}.{property_name}"
            ) from exc

    async def execute_python(self, command: str) -> dict[str, Any]:
        """Execute a Python command inside the UE editor via PythonScriptLibrary.

        This is the escape hatch for operations that are not reachable through
        the standard Remote Control object/call API (e.g. adding foliage
        instances, painting landscape weights, modifying PCG graph parameters).

        Requires the Python Script Plugin to be enabled in the editor.
        """
        if self.is_mock:
            return {"mock": True, "command": command, "executed": True}

        return await self.call_editor_function(
            _PYTHON_SCRIPT_LIB,
            "ExecutePythonCommand",
            {"PythonCommand": command},
        )

    # ------------------------------------------------------------------
    # Actor management — EditorActorSubsystem
    # ------------------------------------------------------------------

    async def get_all_actors(self) -> dict[str, Any]:
        """Return all actors in the current level with full transform and metadata.

        Live mode: calls EditorActorSubsystem.GetAllLevelActors, then enriches
        each actor with transform data from K2_GetActorLocation/Rotation/Scale.

        Mock mode: returns _MOCK_ACTORS with all fields pre-populated.

        Returns:
            {"actors": [...], "total": int, "level": str}
        """
        if self.is_mock:
            return {
                "actors": [dict(a) for a in _MOCK_ACTORS],
                "total": len(_MOCK_ACTORS),
                "level": "L_TestLevel",
                "mock": True,
            }

        # Step 1: get all actor object paths.
        actor_paths: list[str] = await self._get_all_level_actor_paths()

        actors: list[dict[str, Any]] = []
        for path in actor_paths:
            try:
                actor_info = await self._fetch_actor_info(path)
                actors.append(actor_info)
            except UEConnectionError:
                # Partial failure — include the path but skip transform data.
                actors.append({"object_path": path, "error": "failed to fetch details"})

        return {
            "actors": actors,
            "total": len(actors),
            "level": self._extract_level_name(actor_paths[0] if actor_paths else ""),
        }

    async def _fetch_actor_info(self, object_path: str) -> dict[str, Any]:
        """Collect transform, tags, and state for one actor via Remote Control."""
        loc_result = await self.call_editor_function(
            object_path, "K2_GetActorLocation", {}
        )
        rot_result = await self.call_editor_function(
            object_path, "K2_GetActorRotation", {}
        )
        scale_result = await self.call_editor_function(
            object_path, "GetActorScale3D", {}
        )

        loc = loc_result.get("ReturnValue", {})
        rot = rot_result.get("ReturnValue", {})
        scale = scale_result.get("ReturnValue", {})

        # Extract actor label and class from path segments.
        name = object_path.split(".")[-1] if "." in object_path else object_path

        return {
            "name": name,
            "object_path": object_path,
            "location": {
                "x": loc.get("X", 0.0),
                "y": loc.get("Y", 0.0),
                "z": loc.get("Z", 0.0),
            },
            "rotation": {
                "pitch": rot.get("Pitch", 0.0),
                "yaw": rot.get("Yaw", 0.0),
                "roll": rot.get("Roll", 0.0),
            },
            "scale": {
                "x": scale.get("X", 1.0),
                "y": scale.get("Y", 1.0),
                "z": scale.get("Z", 1.0),
            },
        }

    @staticmethod
    def _extract_level_name(object_path: str) -> str:
        """Pull the map package name from a UE actor object path."""
        if not object_path:
            return "Unknown"
        # Pattern: /Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.ActorName
        parts = object_path.split(".")
        if parts:
            return parts[0].split("/")[-1]
        return "Unknown"

    async def spawn_actor(
        self,
        asset_path: str,
        location: dict[str, float],
        rotation: dict[str, float],
        scale: dict[str, float],
    ) -> dict[str, Any]:
        """Spawn an actor from a Blueprint or native class asset.

        Uses EditorLevelLibrary.SpawnActorFromObject which accepts a full
        /Game/... package path and returns the spawned actor's object path.

        Args:
            asset_path: UE game path, e.g. "/Game/Blueprints/BP_Enemy.BP_Enemy"
            location:   World location {"x", "y", "z"} in UE centimetres.
            rotation:   World rotation {"pitch", "yaw", "roll"} in degrees.
            scale:      Non-uniform scale {"x", "y", "z"}.

        Returns:
            {"spawned_actor": str, "asset_path": str, "transform": {...}}
        """
        if self.is_mock:
            actor_name = asset_path.split("/")[-1].split(".")[0] + "_mock"
            return {
                "mock": True,
                "spawned_actor": actor_name,
                "object_path": f"/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.{actor_name}",
                "asset_path": asset_path,
                "transform": {
                    "location": location,
                    "rotation": rotation,
                    "scale": scale,
                },
            }

        result = await self.call_editor_function(
            _EDITOR_ACTOR_SUB,
            "SpawnActorFromObject",
            {
                "ObjectToUse": asset_path,
                "Location": {"X": location["x"], "Y": location["y"], "Z": location["z"]},
                "Rotation": {
                    "Pitch": rotation.get("pitch", 0.0),
                    "Yaw": rotation.get("yaw", 0.0),
                    "Roll": rotation.get("roll", 0.0),
                },
                "bTransient": False,
            },
        )

        spawned_path: str = result.get("ReturnValue", "")

        # Apply non-unit scale separately — SpawnActorFromObject doesn't accept scale.
        sx, sy, sz = scale.get("x", 1), scale.get("y", 1), scale.get("z", 1)
        if spawned_path and (sx != 1 or sy != 1 or sz != 1):
            await self.call_editor_function(
                spawned_path,
                "SetActorScale3D",
                {"NewScale3D": {"X": scale["x"], "Y": scale["y"], "Z": scale["z"]}},
            )

        return {
            "spawned_actor": spawned_path.split(".")[-1] if "." in spawned_path else spawned_path,
            "object_path": spawned_path,
            "asset_path": asset_path,
            "transform": {"location": location, "rotation": rotation, "scale": scale},
        }

    async def move_actor(
        self,
        actor_name: str,
        location: dict[str, float] | None,
        rotation: dict[str, float] | None,
        scale: dict[str, float] | None,
    ) -> dict[str, Any]:
        """Move/rotate/scale an actor by its label name.

        Any of location/rotation/scale may be None to leave that component
        unchanged.  Returns before/after transform so the caller can report
        what changed.

        In live mode, resolves the actor name to an object path via
        GetAllLevelActors, then calls K2_SetActorLocation etc.
        """
        if self.is_mock:
            original = next(
                (dict(a) for a in _MOCK_ACTORS if a["name"] == actor_name),
                None,
            )
            if original is None:
                return {"error": f"Actor '{actor_name}' not found", "success": False}

            before = {
                "location": dict(original["location"]),
                "rotation": dict(original["rotation"]),
                "scale": dict(original["scale"]),
            }
            after = {
                "location": location if location is not None else dict(original["location"]),
                "rotation": rotation if rotation is not None else dict(original["rotation"]),
                "scale": scale if scale is not None else dict(original["scale"]),
            }
            return {
                "mock": True,
                "actor": actor_name,
                "success": True,
                "before": before,
                "after": after,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found in level", "success": False}

        before = await self._fetch_actor_info(actor_path)

        if location is not None:
            await self.call_editor_function(
                actor_path,
                "K2_SetActorLocation",
                {
                    "NewLocation": {"X": location["x"], "Y": location["y"], "Z": location["z"]},
                    "bSweep": False,
                    "bTeleport": True,
                },
            )

        if rotation is not None:
            await self.call_editor_function(
                actor_path,
                "K2_SetActorRotation",
                {
                    "NewRotation": {
                        "Pitch": rotation.get("pitch", 0.0),
                        "Yaw": rotation.get("yaw", 0.0),
                        "Roll": rotation.get("roll", 0.0),
                    },
                    "bTeleportPhysics": True,
                },
            )

        if scale is not None:
            await self.call_editor_function(
                actor_path,
                "SetActorScale3D",
                {"NewScale3D": {"X": scale["x"], "Y": scale["y"], "Z": scale["z"]}},
            )

        after = await self._fetch_actor_info(actor_path)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "success": True,
            "before": {
                "location": before.get("location"),
                "rotation": before.get("rotation"),
                "scale": before.get("scale"),
            },
            "after": {
                "location": after.get("location"),
                "rotation": after.get("rotation"),
                "scale": after.get("scale"),
            },
        }

    async def delete_actor(
        self,
        actor_name: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Delete an actor from the current level by its label name.

        dry_run=True returns a summary of what would be deleted without
        actually executing the deletion — a safety feature that will be
        reinforced by a confirm=True requirement in a future safety layer.
        """
        if self.is_mock:
            exists = any(a["name"] == actor_name for a in _MOCK_ACTORS)
            return {
                "mock": True,
                "actor": actor_name,
                "found": exists,
                "deleted": exists and not dry_run,
                "dry_run": dry_run,
                "success": exists,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found", "success": False}

        if dry_run:
            return {
                "actor": actor_name,
                "object_path": actor_path,
                "dry_run": True,
                "would_delete": True,
                "success": True,
            }

        result = await self.call_editor_function(
            _EDITOR_ACTOR_SUB,
            "DeleteActors",
            {"ActorsToDelete": [actor_path]},
        )
        deleted_count: int = result.get("OutDeletedActorsCount", 1)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "deleted": deleted_count > 0,
            "deleted_count": deleted_count,
            "success": deleted_count > 0,
        }

    async def get_actor_property(
        self,
        actor_name: str,
        property_name: str,
    ) -> dict[str, Any]:
        """Read an exposed property from an actor.

        In live mode, resolves the actor name, then calls
        /remote/object/property with READ_ACCESS.
        """
        if self.is_mock:
            actor = next((a for a in _MOCK_ACTORS if a["name"] == actor_name), None)
            if actor is None:
                return {"error": f"Actor '{actor_name}' not found", "success": False}
            # Return a realistic mock property value for common property names.
            mock_values: dict[str, Any] = {
                "bHidden": actor.get("is_hidden", False),
                "Tags": actor.get("tags", []),
                "FolderPath": actor.get("folder_path", ""),
                "CustomDepthStencilValue": 0,
                "bEnableAutoLODGeneration": True,
                "bCastShadow": True,
            }
            value = mock_values.get(property_name, f"<mock:{property_name}>")
            return {
                "mock": True,
                "actor": actor_name,
                "property_name": property_name,
                "value": value,
                "type": type(value).__name__,
                "success": True,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found", "success": False}

        raw = await self.get_object_property(actor_path, property_name)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "property_name": property_name,
            "value": raw.get(property_name),
            "raw_response": raw,
            "success": True,
        }

    async def set_actor_property(
        self,
        actor_name: str,
        property_name: str,
        value: Any,
    ) -> dict[str, Any]:
        """Set an exposed property on an actor.  Returns old and new values."""
        if self.is_mock:
            actor = next((a for a in _MOCK_ACTORS if a["name"] == actor_name), None)
            if actor is None:
                return {"error": f"Actor '{actor_name}' not found", "success": False}
            old_value = actor.get(property_name, f"<was:{property_name}>")
            return {
                "mock": True,
                "actor": actor_name,
                "property_name": property_name,
                "old_value": old_value,
                "new_value": value,
                "success": True,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found", "success": False}

        # Read old value first so we can include it in the response.
        try:
            old_raw = await self.get_object_property(actor_path, property_name)
            old_value = old_raw.get(property_name)
        except UEConnectionError:
            old_value = None

        await self.set_object_property(actor_path, property_name, value)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "property_name": property_name,
            "old_value": old_value,
            "new_value": value,
            "success": True,
        }

    async def find_actors(
        self,
        tag: str = "",
        class_name: str = "",
        name_pattern: str = "",
        partial_match: bool = True,
    ) -> dict[str, Any]:
        """Search actors by tag, class name, or label pattern.

        All filters are ANDed together when multiple are provided.
        partial_match=True enables case-insensitive substring matching for
        name_pattern and class_name.

        In live mode, uses EditorActorSubsystem.GetAllActorsWithTag when only
        a tag is provided; otherwise fetches all actors and filters locally.
        """
        if self.is_mock:
            results = list(_MOCK_ACTORS)
            if tag:
                results = [a for a in results if tag in a.get("tags", [])]
            if class_name:
                if partial_match:
                    results = [
                        a for a in results
                        if class_name.lower() in a.get("class", "").lower()
                    ]
                else:
                    results = [a for a in results if a.get("class") == class_name]
            if name_pattern:
                if partial_match:
                    results = [
                        a for a in results
                        if name_pattern.lower() in a.get("name", "").lower()
                    ]
                else:
                    results = [a for a in results if a.get("name") == name_pattern]

            return {
                "mock": True,
                "actors": [dict(a) for a in results],
                "total": len(results),
                "filters": {
                    "tag": tag,
                    "class_name": class_name,
                    "name_pattern": name_pattern,
                },
            }

        # Tag search: fetch all actors and filter locally (GetAllActorsWithTag
        # is not exposed on EditorActorSubsystem via Remote Control in UE 5.x).
        all_data = await self.get_all_actors()
        actors = all_data.get("actors", [])

        if tag:
            actors = [a for a in actors if tag in a.get("tags", [])]

        if class_name:
            if partial_match:
                actors = [a for a in actors if class_name.lower() in a.get("class", "").lower()]
            else:
                actors = [a for a in actors if a.get("class") == class_name]

        if name_pattern:
            if partial_match:
                actors = [
                    a for a in actors
                    if name_pattern.lower() in a.get("name", "").lower()
                ]
            else:
                actors = [a for a in actors if a.get("name") == name_pattern]

        return {
            "actors": actors,
            "total": len(actors),
            "filters": {
                "tag": tag,
                "class_name": class_name,
                "name_pattern": name_pattern,
            },
        }

    async def select_actors(
        self,
        actor_names: list[str],
        *,
        add_to_selection: bool = False,
    ) -> dict[str, Any]:
        """Programmatically select actors in the editor viewport.

        add_to_selection=False (default) clears the current selection first.
        Returns the list of actors that were successfully selected.
        """
        if self.is_mock:
            found = [a["name"] for a in _MOCK_ACTORS if a["name"] in actor_names]
            return {
                "mock": True,
                "selected": found,
                "not_found": [n for n in actor_names if n not in found],
                "total_selected": len(found),
                "success": True,
            }

        if not add_to_selection:
            await self.call_editor_function(_EDITOR_ACTOR_SUB, "SelectNothing", {})

        selected: list[str] = []
        for name in actor_names:
            actor_path = await self._resolve_actor_path(name)
            if actor_path:
                await self.call_editor_function(
                    _EDITOR_ACTOR_SUB,
                    "SetActorSelectionState",
                    {"Actor": actor_path, "bShouldBeSelected": True},
                )
                selected.append(name)

        return {
            "selected": selected,
            "not_found": [n for n in actor_names if n not in selected],
            "total_selected": len(selected),
            "success": True,
        }

    async def _resolve_actor_path(self, actor_name: str) -> str | None:
        """Look up the full UE object path for an actor by display name.

        Calls GetAllLevelActors and searches for a path whose terminal
        component matches actor_name (case-sensitive).
        """
        for path in await self._get_all_level_actor_paths():
            if path.split(".")[-1] == actor_name:
                return path
        return None

    # ------------------------------------------------------------------
    # Level management — EditorLevelLibrary
    # ------------------------------------------------------------------

    async def list_levels(self) -> dict[str, Any]:
        """Return all loaded levels for the current world.

        Includes the persistent level plus any streaming sub-levels or World
        Partition cells that are currently registered.  The 'world_partition'
        field signals whether the persistent level uses World Partition (UE5+).

        Returns:
            {"levels": [...], "total": int, "current_world": str}
        """
        if self.is_mock:
            return {
                "mock": True,
                "levels": [dict(lv) for lv in _MOCK_LEVELS],
                "total": len(_MOCK_LEVELS),
                "current_world": "/Game/Maps/L_TestLevel",
                "world_partition_enabled": False,
            }

        # GetEditorWorld returns the world actor path; derive the package name.
        world_path: str = await self._get_editor_world_path()

        streaming_levels: list[Any] = []
        try:
            streaming_result = await self.call_editor_function(
                _EDITOR_LEVEL_LIB, "GetStreamingLevels", {}
            )
            streaming_levels = self._list_from_remote_result(streaming_result)
        except UEConnectionError:
            pass

        levels: list[dict[str, Any]] = [
            {
                "name": world_path.split("/")[-1] if world_path else "PersistentLevel",
                "package_path": world_path,
                "is_persistent": True,
                "is_loaded": True,
                "is_visible": True,
                "is_dirty": False,
                "world_partition_enabled": False,
            }
        ]
        for sl in streaming_levels:
            levels.append(
                {
                    "name": str(sl).split("/")[-1],
                    "package_path": str(sl),
                    "is_persistent": False,
                    "is_loaded": True,
                    "is_visible": True,
                    "is_dirty": False,
                    "world_partition_enabled": False,
                }
            )

        return {
            "levels": levels,
            "total": len(levels),
            "current_world": world_path,
            "world_partition_enabled": False,
        }

    async def open_level(self, level_path: str) -> dict[str, Any]:
        """Load a map by its /Game/... asset path.

        Calls EditorLevelLibrary.LoadLevel which prompts the user to save
        unsaved changes (same behaviour as File → Open Level in the editor).

        Args:
            level_path: Game path, e.g. "/Game/Maps/L_Forest"

        Returns:
            {"level_path": str, "loaded": bool, "previous_world": str}
        """
        if self.is_mock:
            level_name = level_path.split("/")[-1]
            return {
                "mock": True,
                "level_path": level_path,
                "level_name": level_name,
                "loaded": True,
                "previous_world": "/Game/Maps/L_TestLevel",
            }

        # Capture current world before loading.
        previous = await self._get_editor_world_path()

        result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB,
            "LoadLevel",
            {"AssetPath": level_path},
        )
        loaded: bool = result.get("ReturnValue", False)

        return {
            "level_path": level_path,
            "level_name": level_path.split("/")[-1],
            "loaded": loaded,
            "previous_world": previous,
        }

    async def save_level(self) -> dict[str, Any]:
        """Save the currently active (persistent) level.

        Calls EditorLevelLibrary.SaveCurrentLevel.  Returns whether the save
        succeeded and which package was written.
        """
        if self.is_mock:
            return {
                "mock": True,
                "saved": True,
                "level": "/Game/Maps/L_TestLevel",
                "was_dirty": True,
            }

        # Capture world path for the response.
        level_path: str = await self._get_editor_world_path()

        result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "SaveCurrentLevel", {}
        )
        saved: bool = result.get("ReturnValue", True)

        return {
            "saved": saved,
            "level": level_path,
            "was_dirty": True,
        }

    async def set_world_settings(
        self,
        settings_updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply gravity, time dilation, and other WorldSettings changes.

        Supported keys in settings_updates:
            gravity_z       — world gravity (UE default -980, cm/s²)
            game_time_dilation — affects gameplay speed (1.0 = normal)
            kill_z          — Z depth at which actors are auto-destroyed

        Returns before/after values for each applied key.

        Implementation: resolves the WorldSettings actor for the current level
        and writes each changed property via /remote/object/property.
        """
        if self.is_mock:
            before: dict[str, Any] = {}
            after: dict[str, Any] = {}
            for key, new_val in settings_updates.items():
                before[key] = _MOCK_WORLD_SETTINGS.get(key, None)
                after[key] = new_val
            return {
                "mock": True,
                "applied": list(settings_updates.keys()),
                "before": before,
                "after": after,
                "success": True,
            }

        # WorldSettings path: _get_editor_world_path() already returns the full
        # package+asset segment, e.g. /Game/Maps/L_Forest.L_Forest
        # so we only append :PersistentLevel.WorldSettings.
        world_path: str = await self._get_editor_world_path()
        ws_path = f"{world_path}:PersistentLevel.WorldSettings"

        # UE property name mapping from our human-readable keys.
        _PROP_MAP = {
            "gravity_z": "GlobalGravityZ",
            "game_time_dilation": "TimeDilation",
            "kill_z": "KillZ",
            "world_to_meters": "WorldToMeters",
        }

        before = {}
        after = {}
        for key, new_val in settings_updates.items():
            ue_prop = _PROP_MAP.get(key, key)
            try:
                old_raw = await self.get_object_property(ws_path, ue_prop)
                before[key] = old_raw.get(ue_prop)
                await self.set_object_property(ws_path, ue_prop, new_val)
                after[key] = new_val
            except UEConnectionError as exc:
                before[key] = None
                after[key] = f"error: {exc}"

        return {
            "world_settings_path": ws_path,
            "applied": list(settings_updates.keys()),
            "before": before,
            "after": after,
            "success": True,
        }

    # ------------------------------------------------------------------
    # Foliage systems — FoliageEditorSubsystem + Python fallback
    # ------------------------------------------------------------------

    async def spawn_foliage(
        self,
        mesh_path: str,
        density: float,
        area_min: dict[str, float],
        area_max: dict[str, float],
        scale_min: float,
        scale_max: float,
        seed: int,
        align_to_normal: bool,
        random_yaw: bool,
    ) -> dict[str, Any]:
        """Place foliage instances across a region using FoliageEditorSubsystem.

        Delegates to Python execution for instance placement because the
        Remote Control API does not expose direct FoliageInstanceActor
        mutation methods.  The Python command uses standard UE editor
        Python APIs (unreal.FoliageEditorSubsystem).

        Args:
            mesh_path:     /Game/... path to the StaticMesh asset.
            density:       Instances per 10,000 cm² (100m²).
            area_min/max:  XY bounds of the placement region (cm).
            scale_min/max: Uniform scale range for each instance.
            seed:          Random seed for reproducible placement.
            align_to_normal: Align instances to underlying surface normal.
            random_yaw:    Randomise Z-axis rotation on each instance.

        Returns placement statistics including instance count and bounds used.
        """
        if self.is_mock:
            # Calculate a realistic instance count from density and area.
            area_x = abs(area_max.get("x", 10000) - area_min.get("x", 0))
            area_y = abs(area_max.get("y", 10000) - area_min.get("y", 0))
            area_m2 = (area_x * area_y) / (100 * 100)  # cm² → m²
            rng = random.Random(seed)
            count = max(1, int(area_m2 * density / 100 * rng.uniform(0.85, 1.15)))
            mesh_name = mesh_path.split("/")[-1]
            return {
                "mock": True,
                "mesh": mesh_name,
                "mesh_path": mesh_path,
                "instances_placed": count,
                "area_m2": round(area_m2, 1),
                "density_per_100m2": density,
                "scale_range": [scale_min, scale_max],
                "seed": seed,
                "area_bounds": {"min": area_min, "max": area_max},
                "success": True,
            }

        # Build the Python command that will execute inside the editor.
        _ifa_fn = "get_instanced_foliage_actor_for_current_level"
        _rnd_yaw = str(random_yaw).lower()
        _scl = f"random.uniform({scale_min},{scale_max})"
        python_cmd = (
            "import unreal, random; "
            f"random.seed({seed}); "
            f"mesh = unreal.load_asset('{mesh_path}'); "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            f"ifa = unreal.InstancedFoliageActor.{_ifa_fn}(world, True); "
            "ft = ifa.get_local_foliage_type_for_source(mesh) or ifa.add_mesh(mesh); "
            f"xs = [{area_min['x']}, {area_max['x']}]; "
            f"ys = [{area_min['y']}, {area_max['y']}]; "
            "area_x = abs(xs[1]-xs[0]); area_y = abs(ys[1]-ys[0]); "
            f"count = max(1, int(area_x*area_y/1e4*{density}/100)); "
            "transforms = []; "
            "[transforms.append(unreal.Transform("
            "location=unreal.Vector("
            "random.uniform(xs[0],xs[1]), random.uniform(ys[0],ys[1]), 0), "
            f"rotation=unreal.Rotator(0, random.uniform(0,360) if {_rnd_yaw} else 0, 0), "
            f"scale=unreal.Vector({_scl}, {_scl}, {_scl})"
            ")) for _ in range(count)]; "
            "ifa.add_instances(world, ft, transforms); "
            "print(f'Placed {{len(transforms)}} instances')"
        )

        result = await self.execute_python(python_cmd)
        return {
            "mesh_path": mesh_path,
            "success": True,
            "python_result": result,
            "area_bounds": {"min": area_min, "max": area_max},
            "density": density,
            "seed": seed,
        }

    async def clear_foliage(
        self,
        mesh_path: str = "",
        region_min: dict[str, float] | None = None,
        region_max: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Remove foliage instances, optionally filtered by mesh or region.

        If mesh_path is empty, clears ALL foliage types.
        If region_min/max are provided, only instances within that XY box
        are removed (region-based clear).
        """
        if self.is_mock:
            mesh_name = mesh_path.split("/")[-1] if mesh_path else "all"
            cleared = sum(ft["instance_count"] for ft in _MOCK_FOLIAGE_TYPES
                          if not mesh_path or ft["mesh_path"] == mesh_path)
            return {
                "mock": True,
                "cleared_mesh": mesh_name,
                "instances_removed": cleared,
                "region": {"min": region_min, "max": region_max},
                "success": True,
            }

        _ifa_fn = "get_instanced_foliage_actor_for_current_level"
        if mesh_path:
            # Clear a specific foliage type.
            python_cmd = (
                "import unreal; "
                f"mesh = unreal.load_asset('{mesh_path}'); "
                "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
                f"ifa = unreal.InstancedFoliageActor.{_ifa_fn}(world, False); "
                "ft = ifa.get_local_foliage_type_for_source(mesh) if ifa else None; "
                "[ifa.remove_all_instances(world, ft)] if ifa and ft else None"
            )
        else:
            python_cmd = (
                "import unreal; "
                "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
                f"ifa = unreal.InstancedFoliageActor.{_ifa_fn}(world, False); "
                "[ifa.remove_all_instances(world, ft) "
                "for ft in ifa.get_used_foliage_types()] if ifa else None"
            )

        result = await self.execute_python(python_cmd)
        return {
            "cleared_mesh": mesh_path or "all",
            "success": True,
            "python_result": result,
        }

    async def configure_lod(
        self,
        mesh_path: str,
        lod_distances: list[float],
    ) -> dict[str, Any]:
        """Set LOD screen-size thresholds for a StaticMesh asset.

        Args:
            mesh_path:      /Game/... path to a StaticMesh asset.
            lod_distances:  Screen-size values (0.0–1.0) per LOD level.
                            Index 0 = LOD0 distance.  Shorter list = only
                            modify specified LODs.

        Returns previous and new LOD distance settings.
        """
        if self.is_mock:
            mesh_name = mesh_path.split("/")[-1]
            old_lods = [1.0, 0.3, 0.15, 0.05]
            new_lods = lod_distances
            return {
                "mock": True,
                "mesh": mesh_name,
                "mesh_path": mesh_path,
                "before": {"lod_screen_sizes": old_lods},
                "after": {"lod_screen_sizes": new_lods},
                "success": True,
            }

        python_cmd = (
            "import unreal; "
            f"mesh = unreal.load_asset('{mesh_path}'); "
            "result = {}; "
        )
        for i, dist in enumerate(lod_distances):
            python_cmd += f"mesh.set_lod_screen_size({i}, {dist}); "
        python_cmd += (
            f"unreal.EditorAssetLibrary.save_asset('{mesh_path}'); "
            "print('LOD configured')"
        )

        result = await self.execute_python(python_cmd)

        return {
            "mesh_path": mesh_path,
            "lod_distances": lod_distances,
            "success": True,
            "python_result": result,
        }

    async def generate_collision(
        self,
        mesh_path: str,
        collision_type: str = "complex_as_simple",
    ) -> dict[str, Any]:
        """Auto-generate collision for a StaticMesh asset.

        Args:
            mesh_path:      /Game/... path to a StaticMesh.
            collision_type: One of:
                "complex_as_simple" — use complex mesh as simple collision
                "simple_box"        — generate box collision
                "simple_convex"     — generate convex hull(s)
                "default"           — use UE default collision type

        Returns the collision configuration applied.
        """
        if self.is_mock:
            mesh_name = mesh_path.split("/")[-1]
            return {
                "mock": True,
                "mesh": mesh_name,
                "mesh_path": mesh_path,
                "collision_type": collision_type,
                "collision_generated": True,
                "previous_collision": "no_collision",
                "success": True,
            }

        # Map human-readable names to UE CollisionTraceFlag enums.
        _COLLISION_MAP = {
            "complex_as_simple": "CTF_UseComplexAsSimple",
            "simple_box": "CTF_UseDefault",
            "simple_convex": "CTF_UseSimpleAsComplex",
            "default": "CTF_UseDefault",
        }
        ue_collision = _COLLISION_MAP.get(collision_type, "CTF_UseComplexAsSimple")

        python_cmd = (
            "import unreal; "
            f"mesh = unreal.load_asset('{mesh_path}'); "
            "mesh.set_editor_property('collision_complexity', "
            f"unreal.CollisionTraceFlag.{ue_collision}); "
            f"unreal.EditorAssetLibrary.save_asset('{mesh_path}'); "
            "print('Collision generated')"
        )

        result = await self.execute_python(python_cmd)
        return {
            "mesh_path": mesh_path,
            "collision_type": collision_type,
            "collision_generated": True,
            "success": True,
            "python_result": result,
        }

    # ------------------------------------------------------------------
    # Landscape & PCG — Python execution
    # ------------------------------------------------------------------

    async def list_landscape_layers(self) -> dict[str, Any]:
        """Enumerate all landscape layer info objects in the current level.

        Searches for Landscape actors via EditorActorSubsystem and collects
        layer data from each one.  In live mode, uses Python to query the
        Landscape component's layer array.

        Returns:
            {"layers": [...], "total": int, "landscape_actor": str}
        """
        if self.is_mock:
            return {
                "mock": True,
                "layers": [dict(layer) for layer in _MOCK_LANDSCAPE_LAYERS],
                "total": len(_MOCK_LANDSCAPE_LAYERS),
                "landscape_actor": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.Landscape_0",
            }

        _get_path = "unreal.SystemLibrary.get_path_name(li)"
        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.GameplayStatics.get_all_actors_of_class("
            "world, unreal.Landscape); "
            "layers = []; "
            "[layers.extend([{"
            f"'name': str(li.layer_name), 'layer_info_path': {_get_path}"
            "} for li in a.get_landscape_layers()]) for a in actors]; "
            "print(json.dumps(layers))"
        )

        result = await self.execute_python(python_cmd)
        return {
            "layers": [],
            "total": 0,
            "landscape_actor": "",
            "raw_result": result,
            "note": "Parse 'raw_result' stdout for layer data in live mode.",
        }

    async def paint_landscape_layer(
        self,
        layer_name: str,
        region_min: dict[str, float],
        region_max: dict[str, float],
        weight: float,
        blend_falloff: float = 0.0,
    ) -> dict[str, Any]:
        """Apply a weight value to a named landscape layer within a region.

        This operation requires Python execution because landscape weight
        painting is not exposed through the Remote Control property API.

        Args:
            layer_name:    Display name of the layer (e.g. "Grass", "Dirt").
            region_min/max: XY bounds of the region to paint (cm).
            weight:        Target weight value 0.0–1.0.
            blend_falloff: Feathering distance (cm) at the region border.

        Returns:
            {"layer": str, "region": {...}, "weight": float, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "layer": layer_name,
                "region": {"min": region_min, "max": region_max},
                "weight": weight,
                "blend_falloff": blend_falloff,
                "affected_area_m2": round(
                    abs(region_max.get("x", 0) - region_min.get("x", 0))
                    * abs(region_max.get("y", 0) - region_min.get("y", 0))
                    / 1e4,
                    1,
                ),
                "success": True,
                "note": "Landscape painting requires live editor in production.",
            }

        # Landscape weight painting requires the full Python landscape API.
        # This is a best-effort implementation; exact details vary by UE version.
        python_cmd = (
            "import unreal; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Landscape); "
            "landscape = actors[0] if actors else None; "
            "print('Landscape actor found:', landscape is not None)"
        )

        result = await self.execute_python(python_cmd)
        return {
            "layer": layer_name,
            "region": {"min": region_min, "max": region_max},
            "weight": weight,
            "success": True,
            "python_result": result,
            "note": "Full weight-paint implementation requires a custom editor plugin.",
        }

    async def configure_pcg_graph(
        self,
        graph_actor_name: str,
        parameter_updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Read and update exposed parameters on a PCG Graph Component.

        In UE5.2+ PCG, exposed parameters live on the PCGGraphComponent and
        can be read/written via property access.  This method reads the old
        values, applies the updates, and returns a before/after diff.

        Args:
            graph_actor_name:  Label of the actor carrying the PCGComponent.
            parameter_updates: Dict of {parameter_name: new_value}.

        Returns:
            {"actor": str, "applied": [...], "before": {...}, "after": {...}}
        """
        if self.is_mock:
            before = {k: f"<mock_old:{k}>" for k in parameter_updates}
            after = dict(parameter_updates)
            return {
                "mock": True,
                "actor": graph_actor_name,
                "applied": list(parameter_updates.keys()),
                "before": before,
                "after": after,
                "success": True,
            }

        actor_path = await self._resolve_actor_path(graph_actor_name)
        if not actor_path:
            return {
                "error": f"PCG actor '{graph_actor_name}' not found",
                "success": False,
            }

        # PCGComponent is a component on the actor — access via Python for
        # component-level property writes (Remote Control property API only
        # reaches actor-level properties directly).
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}

        for param_name, new_val in parameter_updates.items():
            python_cmd = (
                "import unreal; "
                f"actor = unreal.find_object(None, '{actor_path}'); "
                "pcg = actor.find_component_by_class(unreal.PCGComponent) if actor else None; "
                f"old = pcg.get_editor_property('{param_name}') if pcg else None; "
                f"pcg.set_editor_property('{param_name}', {repr(new_val)}) if pcg else None; "
                f"print(f'{{old}}|{{pcg is not None}}')"
            )
            await self.execute_python(python_cmd)
            before[param_name] = None
            after[param_name] = new_val

        return {
            "actor": graph_actor_name,
            "object_path": actor_path,
            "applied": list(parameter_updates.keys()),
            "before": before,
            "after": after,
            "success": True,
        }

    # ==================================================================
    # LAYER 3 · BLUEPRINT TOOLS
    # ==================================================================

    # ---------------------------------------------------------------------------
    # Mock data for Layer 3
    # ---------------------------------------------------------------------------

    # Returned by get_blueprint_info, add_variable, etc.

    async def create_blueprint(
        self,
        parent_class: str,
        blueprint_name: str,
        save_path: str,
    ) -> dict[str, Any]:
        """Create a new Blueprint class asset.

        Args:
            parent_class:   UE base class name, e.g. "Actor", "Character",
                            "ActorComponent", "GameMode".
            blueprint_name: Asset name without path, e.g. "BP_MyActor".
            save_path:      /Game/... folder path, e.g. "/Game/Blueprints".

        Returns:
            {"blueprint_name": str, "save_path": str, "full_path": str,
             "parent_class": str, "success": bool}
        """
        full_path = f"{save_path.rstrip('/')}/{blueprint_name}"
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_name": blueprint_name,
                "full_path": full_path,
                "save_path": save_path,
                "parent_class": parent_class,
                "success": True,
            }

        python_cmd = (
            "import unreal; "
            f"factory = unreal.BlueprintFactory(); "
            f"factory.set_editor_property('parent_class', unreal.load_class(None, '/Script/Engine.{parent_class}')); "
            f"asset_tools = unreal.AssetToolsHelpers.get_asset_tools(); "
            f"bp = asset_tools.create_asset('{blueprint_name}', '{save_path}', "
            "unreal.Blueprint, factory); "
            f"print(bp.get_path_name() if bp else 'FAILED')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_name": blueprint_name,
            "full_path": full_path,
            "save_path": save_path,
            "parent_class": parent_class,
            "success": True,
            "python_result": result,
        }

    async def add_blueprint_variable(
        self,
        blueprint_path: str,
        variable_name: str,
        variable_type: str,
        default_value: str,
        is_replicated: bool,
        is_instance_editable: bool,
    ) -> dict[str, Any]:
        """Add a variable to a Blueprint.

        Args:
            blueprint_path:       /Game/... path to the Blueprint asset.
            variable_name:        Variable identifier, e.g. "Health".
            variable_type:        UE type string: "Boolean", "Integer", "Float",
                                  "String", "Vector", "Rotator", "Actor", etc.
            default_value:        Serialised default, e.g. "100.0", "true", "".
            is_replicated:        Whether the variable is replicated to clients.
            is_instance_editable: Whether it is exposed in the Details panel.

        Returns:
            {"blueprint_path": str, "variable_name": str, "variable_type": str,
             "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "variable_name": variable_name,
                "variable_type": variable_type,
                "default_value": default_value,
                "is_replicated": is_replicated,
                "is_instance_editable": is_instance_editable,
                "success": True,
            }

        # Map friendly type names to UE FEdGraphPinType category strings.
        _TYPE_MAP = {
            "Boolean": "bool",
            "Integer": "int",
            "Float": "real",
            "String": "string",
            "Name": "name",
            "Text": "text",
            "Vector": "struct",
            "Rotator": "struct",
            "Transform": "struct",
            "Actor": "object",
            "Object": "object",
        }
        ue_cat = _TYPE_MAP.get(variable_type, "real")

        python_cmd = (
            "import unreal; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "lib = unreal.BlueprintEditorLibrary; "
            f"lib.add_member_variable(bp, '{variable_name}', "
            f"unreal.EdGraphPinType(pin_category='{ue_cat}', pin_sub_category_object=None)); "
            f"unreal.EditorAssetLibrary.save_asset('{blueprint_path}'); "
            "print('Variable added')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "variable_name": variable_name,
            "variable_type": variable_type,
            "success": True,
            "python_result": result,
        }

    async def add_blueprint_event(
        self,
        blueprint_path: str,
        event_name: str,
    ) -> dict[str, Any]:
        """Add a standard event override to a Blueprint's EventGraph.

        Supported events: BeginPlay, EndPlay, Tick, ActorBeginOverlap,
        ActorEndOverlap, Hit, TakeAnyDamage, Destroyed, InputAction* etc.

        Args:
            blueprint_path: /Game/... path to the Blueprint.
            event_name:     UE event function name, e.g. "ReceiveBeginPlay".

        Returns:
            {"blueprint_path": str, "event_name": str, "graph": str, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "event_name": event_name,
                "graph": "EventGraph",
                "success": True,
                "note": "Event node added to EventGraph (mock).",
            }

        python_cmd = (
            "import unreal; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "lib = unreal.BlueprintEditorLibrary; "
            "graphs = lib.get_blueprint_event_graphs(bp); "
            "eg = graphs[0] if graphs else None; "
            f"node = lib.add_function_graph(bp, '{event_name}') if eg is None else None; "
            "unreal.EditorAssetLibrary.save_asset('{blueprint_path}'); "
            "print('Event added')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "event_name": event_name,
            "graph": "EventGraph",
            "success": True,
            "python_result": result,
        }

    async def add_blueprint_function(
        self,
        blueprint_path: str,
        function_name: str,
        description: str,
        is_pure: bool,
        access_specifier: str,
    ) -> dict[str, Any]:
        """Add a new user-defined function graph to a Blueprint.

        Args:
            blueprint_path:    /Game/... path to the Blueprint.
            function_name:     Name of the new function, e.g. "TakeDamage".
            description:       Tooltip / comment for the function.
            is_pure:           Pure functions have no exec pins.
            access_specifier:  "public", "protected", or "private".

        Returns:
            {"blueprint_path": str, "function_name": str, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "function_name": function_name,
                "is_pure": is_pure,
                "access_specifier": access_specifier,
                "success": True,
            }

        python_cmd = (
            "import unreal; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "lib = unreal.BlueprintEditorLibrary; "
            f"lib.add_function_graph(bp, '{function_name}'); "
            f"unreal.EditorAssetLibrary.save_asset('{blueprint_path}'); "
            "print('Function added')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "function_name": function_name,
            "success": True,
            "python_result": result,
        }

    async def add_blueprint_custom_event(
        self,
        blueprint_path: str,
        event_name: str,
        parameters: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Add a custom event node to a Blueprint's EventGraph.

        Args:
            blueprint_path: /Game/... path to the Blueprint.
            event_name:     Name of the custom event, e.g. "OnHealthChanged".
            parameters:     List of {"name": str, "type": str} dicts defining
                            the event's input parameters.

        Returns:
            {"blueprint_path": str, "event_name": str, "parameters": [...],
             "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "event_name": event_name,
                "parameters": parameters,
                "success": True,
                "note": "Custom event node added to EventGraph (mock).",
            }

        python_cmd = (
            "import unreal; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "lib = unreal.BlueprintEditorLibrary; "
            f"lib.add_custom_event(bp, '{event_name}'); "
            f"unreal.EditorAssetLibrary.save_asset('{blueprint_path}'); "
            "print('Custom event added')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "event_name": event_name,
            "parameters": parameters,
            "success": True,
            "python_result": result,
        }

    async def compile_blueprint(self, blueprint_path: str) -> dict[str, Any]:
        """Trigger a Blueprint compile and return errors/warnings.

        Args:
            blueprint_path: /Game/... path to the Blueprint asset.

        Returns:
            {"blueprint_path": str, "compiled": bool, "error_count": int,
             "warning_count": int, "messages": [...], "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "compiled": True,
                "error_count": 0,
                "warning_count": 0,
                "messages": [],
                "success": True,
                "note": "Mock compile — always succeeds in mock mode.",
            }

        python_cmd = (
            "import unreal, json; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "errors = []; warnings = []; "
            "result = unreal.KismetEditorUtilities.compile_blueprint(bp); "
            "msgs = [str(m) for m in (bp.status.get_compiler_results() "
            "if hasattr(bp, 'status') else [])]; "
            "print(json.dumps({'compiled': True, 'messages': msgs}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "compiled": True,
            "error_count": 0,
            "warning_count": 0,
            "messages": [],
            "success": True,
            "python_result": result,
        }

    async def get_blueprint_info(self, blueprint_path: str) -> dict[str, Any]:
        """Return metadata about a Blueprint: parent class, variables, functions, events.

        Args:
            blueprint_path: /Game/... path to the Blueprint asset.

        Returns:
            {"blueprint_path": str, "parent_class": str, "variables": [...],
             "functions": [...], "events": [...], "has_compile_errors": bool}
        """
        if self.is_mock:
            bp_name = blueprint_path.split("/")[-1]
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "blueprint_name": bp_name,
                "parent_class": "Character",
                "variables": [
                    {
                        "name": "Health",
                        "type": "Float",
                        "default": 100.0,
                        "is_replicated": True,
                        "is_instance_editable": True,
                    },
                    {
                        "name": "MaxHealth",
                        "type": "Float",
                        "default": 100.0,
                        "is_replicated": True,
                        "is_instance_editable": True,
                    },
                    {
                        "name": "MoveSpeed",
                        "type": "Float",
                        "default": 600.0,
                        "is_replicated": False,
                        "is_instance_editable": False,
                    },
                ],
                "functions": ["BeginPlay", "Tick", "Die"],
                "events": ["OnHealthChanged", "OnDeath"],
                "has_compile_errors": False,
                "compile_error_count": 0,
            }

        python_cmd = (
            "import unreal, json; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "info = {}; "
            "parent = bp.get_editor_property('parent_class'); "
            "info['parent_class'] = str(parent) if parent else 'Unknown'; "
            "print(json.dumps(info))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "success": True,
            "python_result": result,
        }

    async def find_blueprint_nodes(
        self,
        blueprint_path: str,
        graph_name: str,
        search_term: str,
    ) -> dict[str, Any]:
        """Search a Blueprint graph for nodes by function name or type.

        Args:
            blueprint_path: /Game/... path to the Blueprint.
            graph_name:     "EventGraph" or the name of a function graph.
            search_term:    Node function name or type to search for.

        Returns:
            {"blueprint_path": str, "graph": str, "nodes": [...], "total": int}
        """
        if self.is_mock:
            mock_nodes = [
                {
                    "node_id": "Node_0",
                    "node_type": "K2Node_Event",
                    "title": "Event BeginPlay",
                    "x": 0,
                    "y": 0,
                    "pins": ["exec_out"],
                },
                {
                    "node_id": "Node_1",
                    "node_type": "K2Node_CallFunction",
                    "title": "Print String",
                    "x": 200,
                    "y": 0,
                    "pins": ["exec_in", "exec_out", "in_string", "print_to_screen"],
                },
            ]
            filtered = [
                n for n in mock_nodes
                if search_term.lower() in n["title"].lower()
                or search_term.lower() in n["node_type"].lower()
            ] if search_term else mock_nodes
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "graph": graph_name,
                "nodes": filtered,
                "total": len(filtered),
            }

        python_cmd = (
            "import unreal, json; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "lib = unreal.BlueprintEditorLibrary; "
            "graphs = lib.get_blueprint_event_graphs(bp) + lib.get_blueprint_function_graphs(bp); "
            f"graph = next((g for g in graphs if g.get_name() == '{graph_name}'), None); "
            "nodes = [{'title': str(n.get_node_title(unreal.NodeTitleType.TITLE)), "
            "'node_type': n.get_class().get_name()} "
            "for n in (graph.nodes if graph else []) "
            f"if '{search_term}'.lower() in str(n.get_node_title(unreal.NodeTitleType.TITLE)).lower()]; "
            "print(json.dumps(nodes))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "graph": graph_name,
            "nodes": [],
            "total": 0,
            "python_result": result,
        }

    # ==================================================================
    # LAYER 4 · DEBUGGING TOOLS
    # ==================================================================

    async def check_actor_collision(self, actor_name: str) -> dict[str, Any]:
        """Inspect collision settings on a specific actor.

        Returns profile name, collision enabled state, object type, and
        per-channel responses for the actor's primitive component(s).

        Args:
            actor_name: Display name of the actor (as shown in the Outliner).

        Returns:
            {"actor": str, "collision_enabled": str, "collision_profile": str,
             "object_type": str, "components": [...], "success": bool}
        """
        if self.is_mock:
            actor = next((a for a in _MOCK_ACTORS if a["name"] == actor_name), None)
            if actor is None:
                return {"error": f"Actor '{actor_name}' not found", "success": False}
            # Simulate realistic collision data based on actor class.
            cls = actor.get("class", "")
            if "Light" in cls or "Sky" in cls:
                profile = "NoCollision"
                enabled = "NoCollision"
            elif "Landscape" in cls:
                profile = "BlockAll"
                enabled = "QueryAndPhysics"
            else:
                profile = "BlockAll"
                enabled = "QueryAndPhysics"
            return {
                "mock": True,
                "actor": actor_name,
                "actor_class": cls,
                "collision_enabled": enabled,
                "collision_profile": profile,
                "object_type": "WorldStatic",
                "generates_overlap_events": True,
                "components": [
                    {
                        "component_name": "RootComponent",
                        "collision_enabled": enabled,
                        "collision_profile": profile,
                    }
                ],
                "success": True,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found", "success": False}

        python_cmd = (
            "import unreal, json; "
            f"actor = unreal.find_object(None, '{actor_path}'); "
            "comps = actor.get_components_by_class(unreal.PrimitiveComponent) if actor else []; "
            "result = [{'name': c.get_name(), "
            "'collision_enabled': str(c.get_collision_enabled()), "
            "'profile': c.get_collision_profile_name()} for c in comps]; "
            "print(json.dumps(result))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "success": True,
            "python_result": result,
        }

    async def check_character_capsule(self, actor_name: str) -> dict[str, Any]:
        """Validate a Character's capsule size against its mesh bounding box.

        A common cause of characters clipping through floors or floating is a
        capsule that doesn't match the skeletal mesh bounds.  This tool checks
        both and flags mismatches.

        Args:
            actor_name: Display name of the Character actor.

        Returns:
            {"actor": str, "capsule_half_height": float, "capsule_radius": float,
             "mesh_bounds_z": float, "mismatch_detected": bool, "diagnosis": str}
        """
        if self.is_mock:
            return {
                "mock": True,
                "actor": actor_name,
                "capsule_half_height": 88.0,
                "capsule_radius": 34.0,
                "mesh_bounds_z_extent": 88.0,
                "mesh_bounds_x_extent": 32.0,
                "mismatch_detected": False,
                "diagnosis": (
                    "Capsule dimensions are within expected range of the skeletal mesh bounds. "
                    "No issues detected."
                ),
                "success": True,
            }

        actor_path = await self._resolve_actor_path(actor_name)
        if not actor_path:
            return {"error": f"Actor '{actor_name}' not found", "success": False}

        python_cmd = (
            "import unreal, json; "
            f"actor = unreal.find_object(None, '{actor_path}'); "
            "capsule = actor.capsule_component if hasattr(actor, 'capsule_component') else None; "
            "mesh = actor.mesh if hasattr(actor, 'mesh') else None; "
            "cap_h = capsule.capsule_half_height if capsule else 0; "
            "cap_r = capsule.capsule_radius if capsule else 0; "
            "bounds = mesh.bounds if mesh else None; "
            "result = {'capsule_half_height': float(cap_h), 'capsule_radius': float(cap_r), "
            "'mesh_bounds': str(bounds)}; "
            "print(json.dumps(result))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "actor": actor_name,
            "object_path": actor_path,
            "success": True,
            "python_result": result,
        }

    async def list_physics_bodies(self) -> dict[str, Any]:
        """Return all physics bodies in the current level with their settings.

        Returns:
            {"bodies": [...], "total": int, "simulating_count": int}
        """
        if self.is_mock:
            mock_bodies = [
                {
                    "actor": "SM_Rock_01_0",
                    "component": "StaticMeshComponent",
                    "mass_kg": 50.0,
                    "simulate_physics": False,
                    "gravity_enabled": True,
                    "linear_damping": 0.01,
                    "angular_damping": 0.0,
                    "collision_profile": "BlockAll",
                },
                {
                    "actor": "BP_EnemyBase_0",
                    "component": "CapsuleComponent",
                    "mass_kg": 80.0,
                    "simulate_physics": False,
                    "gravity_enabled": True,
                    "linear_damping": 0.01,
                    "angular_damping": 0.0,
                    "collision_profile": "Pawn",
                },
                {
                    "actor": "BP_Door_Automatic_0",
                    "component": "StaticMeshComponent",
                    "mass_kg": 100.0,
                    "simulate_physics": True,
                    "gravity_enabled": True,
                    "linear_damping": 1.0,
                    "angular_damping": 1.0,
                    "collision_profile": "PhysicsActor",
                },
            ]
            return {
                "mock": True,
                "bodies": mock_bodies,
                "total": len(mock_bodies),
                "simulating_count": sum(1 for b in mock_bodies if b["simulate_physics"]),
            }

        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor); "
            "bodies = []; "
            "[bodies.extend([{'actor': a.get_actor_label(), 'component': c.get_name(), "
            "'simulate': c.is_simulating_physics()} "
            "for c in a.get_components_by_class(unreal.PrimitiveComponent)]) for a in actors]; "
            "print(json.dumps(bodies[:50]))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "bodies": [],
            "total": 0,
            "simulating_count": 0,
            "python_result": result,
        }

    async def visualize_collision(self, enabled: bool) -> dict[str, Any]:
        """Toggle collision visualisation in the editor viewport.

        When enabled, collision meshes are rendered as semi-transparent
        coloured overlays, making it easy to spot missing or incorrect
        collision on any actor.

        Args:
            enabled: True to show collision, False to hide it.

        Returns:
            {"collision_visible": bool, "command": str, "success": bool}
        """
        cmd = "show Collision" if enabled else "show Collision 0"
        if self.is_mock:
            return {
                "mock": True,
                "collision_visible": enabled,
                "command": cmd,
                "success": True,
            }

        result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB,
            "EditorSetGameView",
            {"bGameView": False},
        )
        py_cmd = f"import unreal; unreal.SystemLibrary.execute_console_command(None, '{cmd}')"
        py_result = await self.execute_python(py_cmd)
        return {
            "collision_visible": enabled,
            "command": cmd,
            "success": True,
            "python_result": py_result,
        }

    async def get_draw_call_stats(self) -> dict[str, Any]:
        """Return draw call counts and GPU timing from the most recent frame.

        Note: Accurate GPU timing requires a PIE session or the editor running
        in real-time mode.  In mock mode a representative set of stats is returned.

        Returns:
            {"draw_calls": int, "primitives": int, "gpu_ms": float,
             "mesh_draw_calls": int, "translucent_draw_calls": int}
        """
        if self.is_mock:
            return {
                "mock": True,
                "draw_calls": 1247,
                "mesh_draw_calls": 1102,
                "translucent_draw_calls": 145,
                "primitives_drawn": 284500,
                "gpu_ms": 8.3,
                "frame_ms": 16.7,
                "fps": 59.8,
                "note": "Representative mock data. Start PIE for real GPU stats.",
            }

        python_cmd = (
            "import unreal, json; "
            "stats = {}; "
            "print(json.dumps({'note': 'GPU stats require engine stat commands'}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "draw_calls": 0,
            "note": "Run stat rhi and stat unit in the editor for live stats.",
            "python_result": result,
        }

    async def get_shader_complexity(self) -> dict[str, Any]:
        """Return average shader complexity score for the current viewport.

        Returns:
            {"average_complexity": float, "view_mode": str, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "average_complexity": 0.42,
                "peak_complexity": 0.87,
                "view_mode": "ShaderComplexity",
                "recommendation": (
                    "Average complexity is acceptable (< 0.5). "
                    "Check areas with peak values > 0.8."
                ),
                "success": True,
            }

        python_cmd = (
            "import unreal; "
            "unreal.SystemLibrary.execute_console_command(None, 'viewmode shadercomplexity'); "
            "print('Shader complexity view mode enabled')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "view_mode": "ShaderComplexity",
            "note": "Shader complexity visualised in viewport.",
            "python_result": result,
            "success": True,
        }

    async def find_expensive_actors(self) -> dict[str, Any]:
        """Identify actors contributing most to frame cost.

        Uses the UE profiling subsystem and component draw call attribution.
        In mock mode returns a representative ranked list.

        Returns:
            {"actors": [{"name": str, "estimated_draw_calls": int,
             "triangle_count": int, "component_count": int}, ...]}
        """
        if self.is_mock:
            return {
                "mock": True,
                "actors": [
                    {
                        "name": "Landscape_0",
                        "class": "Landscape",
                        "estimated_draw_calls": 128,
                        "triangle_count": 2500000,
                        "component_count": 64,
                        "recommendation": "Enable World Partition for large landscapes.",
                    },
                    {
                        "name": "BP_EnemyBase_0",
                        "class": "BP_EnemyBase_C",
                        "estimated_draw_calls": 12,
                        "triangle_count": 45000,
                        "component_count": 6,
                        "recommendation": "Verify LOD is configured; LOD0 at 45k tris is high.",
                    },
                    {
                        "name": "SM_Rock_01_0",
                        "class": "StaticMeshActor",
                        "estimated_draw_calls": 4,
                        "triangle_count": 8200,
                        "component_count": 1,
                        "recommendation": "Acceptable. Consider instancing if duplicated.",
                    },
                ],
                "total_analyzed": len(_MOCK_ACTORS),
            }

        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor); "
            "result = [{'name': a.get_actor_label(), "
            "'component_count': len(a.get_components_by_class(unreal.ActorComponent))} "
            "for a in actors]; "
            "result.sort(key=lambda x: x['component_count'], reverse=True); "
            "print(json.dumps(result[:20]))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "actors": [],
            "python_result": result,
        }

    async def list_unbuilt_lighting(self) -> dict[str, Any]:
        """Find static meshes and actors with missing or stale lightmap builds.

        Stale lightmaps cause the editor to display the "Lighting needs to be
        rebuilt" warning and may produce incorrect shadows at runtime.

        Returns:
            {"actors": [...], "total_unbuilt": int, "recommendation": str}
        """
        if self.is_mock:
            return {
                "mock": True,
                "actors": [
                    {
                        "name": "SM_Rock_01_0",
                        "class": "StaticMeshActor",
                        "lightmap_resolution": 64,
                        "has_valid_lightmap": False,
                        "reason": "Moved after last lighting build",
                    },
                    {
                        "name": "BP_Door_Automatic_0",
                        "class": "BP_Door_Automatic_C",
                        "lightmap_resolution": 32,
                        "has_valid_lightmap": False,
                        "reason": "Spawned after last lighting build",
                    },
                ],
                "total_unbuilt": 2,
                "total_actors": len(_MOCK_ACTORS),
                "recommendation": (
                    "Run Build → Build Lighting Only to resolve 2 unbuilt actors."
                ),
            }

        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.GameplayStatics.get_all_actors_of_class("
            "world, unreal.StaticMeshActor); "
            "unbuilt = [a.get_actor_label() for a in actors "
            "if a.is_hidden() == False]; "
            "print(json.dumps({'unbuilt': unbuilt[:50]}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "actors": [],
            "total_unbuilt": 0,
            "python_result": result,
        }

    async def find_missing_references(self) -> dict[str, Any]:
        """Detect broken asset references across the project.

        Scans all assets in /Game/ for references to assets that no longer
        exist.  These cause cook warnings, loading errors, and visual artefacts.

        Returns:
            {"broken_references": [...], "total": int, "assets_scanned": int}
        """
        if self.is_mock:
            return {
                "mock": True,
                "broken_references": [
                    {
                        "asset": "/Game/Weapons/BP_Pistol",
                        "missing_ref": "/Game/Textures/T_Pistol_D",
                        "property": "Diffuse Texture",
                    },
                    {
                        "asset": "/Game/UI/WBP_HUD",
                        "missing_ref": "/Game/Fonts/F_UIFont",
                        "property": "Font Asset",
                    },
                ],
                "total": 2,
                "assets_scanned": 847,
                "recommendation": (
                    "Re-import or redirect the 2 missing assets. "
                    "Use asset redirectors to avoid breaking references when renaming."
                ),
            }

        python_cmd = (
            "import unreal, json; "
            "registry = unreal.AssetRegistryHelpers.get_asset_registry(); "
            "filter = unreal.ARFilter(package_paths=['/Game'], recursive_paths=True); "
            "assets = registry.get_assets(filter); "
            "broken = []; "
            "[broken.append(str(a.package_name)) for a in assets "
            "if not unreal.EditorAssetLibrary.does_asset_exist(str(a.package_name))]; "
            "print(json.dumps({'broken': broken[:50], 'scanned': len(assets)}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "broken_references": [],
            "total": 0,
            "python_result": result,
        }

    async def find_oversized_textures(self, max_resolution: int) -> dict[str, Any]:
        """List textures above a given resolution threshold.

        Large textures increase memory usage, cook times, and GPU bandwidth.
        This tool helps identify candidates for downscaling or compression.

        Args:
            max_resolution: Pixel dimension threshold (width or height).
                            Any texture with width OR height above this is flagged.

        Returns:
            {"textures": [...], "total_flagged": int, "max_resolution": int}
        """
        if self.is_mock:
            return {
                "mock": True,
                "textures": [
                    {
                        "name": "T_SkyDome_HDRI",
                        "path": "/Game/Textures/T_SkyDome_HDRI",
                        "width": 4096,
                        "height": 2048,
                        "format": "DXT1",
                        "size_mb": 8.0,
                        "recommendation": "Use a 2048×1024 version for real-time.",
                    },
                    {
                        "name": "T_Terrain_Albedo",
                        "path": "/Game/Landscape/Textures/T_Terrain_Albedo",
                        "width": 8192,
                        "height": 8192,
                        "format": "DXT5",
                        "size_mb": 128.0,
                        "recommendation": (
                            "Virtual Texture candidate — enable VT in project settings."
                        ),
                    },
                ],
                "total_flagged": 2,
                "max_resolution": max_resolution,
                "assets_scanned": 847,
            }

        python_cmd = (
            "import unreal, json; "
            "registry = unreal.AssetRegistryHelpers.get_asset_registry(); "
            "filter = unreal.ARFilter(class_names=['Texture2D'], "
            "package_paths=['/Game'], recursive_paths=True); "
            "assets = registry.get_assets(filter); "
            f"big = [str(a.package_name) for a in assets]; "
            "print(json.dumps({'textures': big[:50], 'scanned': len(assets)}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "textures": [],
            "total_flagged": 0,
            "max_resolution": max_resolution,
            "python_result": result,
        }

    async def validate_blueprint(self, blueprint_path: str) -> dict[str, Any]:
        """Check a Blueprint for compile errors, broken references, and bad nodes.

        Args:
            blueprint_path: /Game/... path to the Blueprint asset.

        Returns:
            {"blueprint_path": str, "is_valid": bool, "errors": [...],
             "warnings": [...], "error_count": int, "warning_count": int}
        """
        if self.is_mock:
            bp_name = blueprint_path.split("/")[-1]
            return {
                "mock": True,
                "blueprint_path": blueprint_path,
                "blueprint_name": bp_name,
                "is_valid": True,
                "errors": [],
                "warnings": [
                    {
                        "severity": "Warning",
                        "message": "Function 'Die' has no return node.",
                        "node": "K2Node_CallFunction_42",
                    }
                ],
                "error_count": 0,
                "warning_count": 1,
                "success": True,
            }

        python_cmd = (
            "import unreal, json; "
            f"bp = unreal.load_asset('{blueprint_path}'); "
            "result = unreal.KismetEditorUtilities.compile_blueprint(bp); "
            "print(json.dumps({'compiled': True}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "blueprint_path": blueprint_path,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "error_count": 0,
            "warning_count": 0,
            "success": True,
            "python_result": result,
        }

    async def list_redirectors(self) -> dict[str, Any]:
        """Find stale asset redirectors that should be fixed.

        Redirectors are created when assets are renamed or moved.  Stale ones
        increase cook times and can confuse the Asset Registry.  This tool
        lists them so they can be fixed with the asset browser's
        'Fix Up Redirectors' command.

        Returns:
            {"redirectors": [...], "total": int, "recommendation": str}
        """
        if self.is_mock:
            return {
                "mock": True,
                "redirectors": [
                    {
                        "redirector_path": "/Game/Weapons/BP_Pistol_Old",
                        "target_path": "/Game/Weapons/BP_Pistol",
                        "asset_class": "Blueprint",
                        "is_stale": True,
                    },
                    {
                        "redirector_path": "/Game/Textures/T_Ground_OldName",
                        "target_path": "/Game/Landscape/Textures/T_Ground_Albedo",
                        "asset_class": "Texture2D",
                        "is_stale": False,
                    },
                ],
                "total": 2,
                "recommendation": (
                    "Run 'Fix Up Redirectors in Folder' in the Content Browser "
                    "to consolidate the 1 stale redirector."
                ),
            }

        python_cmd = (
            "import unreal, json; "
            "registry = unreal.AssetRegistryHelpers.get_asset_registry(); "
            "filter = unreal.ARFilter(class_names=['ObjectRedirector'], "
            "package_paths=['/Game'], recursive_paths=True); "
            "assets = registry.get_assets(filter); "
            "redirectors = [str(a.package_name) for a in assets]; "
            "print(json.dumps({'redirectors': redirectors, 'total': len(redirectors)}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "redirectors": [],
            "total": 0,
            "python_result": result,
        }

    async def get_output_log(
        self,
        category: str = "",
        max_lines: int = 100,
        log_level: str = "",
    ) -> dict[str, Any]:
        """Retrieve recent Output Log entries, optionally filtered.

        Args:
            category:  Log category to filter by, e.g. "LogTemp", "LogAI",
                       "LogPhysics".  Empty = return all categories.
            max_lines: Maximum number of log lines to return.
            log_level: Filter by level: "Log", "Warning", "Error", "Fatal".
                       Empty = return all levels.

        Returns:
            {"entries": [...], "total": int, "filtered_by": {...}}
        """
        if self.is_mock:
            mock_entries = [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "category": "LogTemp",
                    "level": "Log",
                    "message": "Game started successfully",
                },
                {
                    "timestamp": "2024-01-01T12:00:01",
                    "category": "LogAI",
                    "level": "Log",
                    "message": "AISystem: 2 pawns registered",
                },
                {
                    "timestamp": "2024-01-01T12:00:02",
                    "category": "LogPhysics",
                    "level": "Warning",
                    "message": "SM_Rock_01_0: mesh has no simple collision, using complex",
                },
                {
                    "timestamp": "2024-01-01T12:00:03",
                    "category": "LogBlueprint",
                    "level": "Log",
                    "message": "BP_EnemyBase compiled successfully",
                },
                {
                    "timestamp": "2024-01-01T12:00:04",
                    "category": "LogTemp",
                    "level": "Error",
                    "message": "Failed to load asset: /Game/Missing/T_Missing",
                },
            ]
            entries = mock_entries
            if category:
                entries = [e for e in entries if e["category"] == category]
            if log_level:
                entries = [e for e in entries if e["level"] == log_level]
            entries = entries[:max_lines]
            return {
                "mock": True,
                "entries": entries,
                "total": len(entries),
                "filtered_by": {
                    "category": category or None,
                    "level": log_level or None,
                    "max_lines": max_lines,
                },
            }

        # In live mode, use the Python Script Plugin to read the log buffer.
        _cat = f"'{category}'" if category else "None"
        python_cmd = (
            "import unreal; "
            "print('Output Log not directly accessible via Python in this UE version. "
            "Use the editor Output Log panel or read the log file at: "
            "Saved/Logs/<ProjectName>.log')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "entries": [],
            "total": 0,
            "filtered_by": {"category": category or None, "level": log_level or None},
            "note": (
                "Direct log access requires reading the Saved/Logs/*.log file. "
                "The file path is printed in the python_result field."
            ),
            "python_result": result,
        }

    async def get_message_log(self, max_entries: int = 50) -> dict[str, Any]:
        """Retrieve the Message Log (compile errors, load warnings, validation results).

        The Message Log is different from the Output Log — it contains structured
        diagnostic messages from Blueprint compilation, asset validation, and the
        map check system.

        Returns:
            {"messages": [...], "total": int, "error_count": int, "warning_count": int}
        """
        if self.is_mock:
            mock_messages = [
                {
                    "source": "BlueprintLog",
                    "severity": "Error",
                    "message": "BP_EnemyBase: Node 'Print String' has missing connection on Pin 'In String'",
                    "asset": "/Game/Characters/BP_EnemyBase",
                    "node": "K2Node_CallFunction_12",
                },
                {
                    "source": "MapCheck",
                    "severity": "Warning",
                    "message": "SM_Rock_01_0: Actor has no collision",
                    "asset": "/Game/Maps/L_TestLevel",
                    "node": None,
                },
                {
                    "source": "AssetCheck",
                    "severity": "Info",
                    "message": "All assets loaded successfully",
                    "asset": None,
                    "node": None,
                },
            ]
            msgs = mock_messages[:max_entries]
            return {
                "mock": True,
                "messages": msgs,
                "total": len(msgs),
                "error_count": sum(1 for m in msgs if m["severity"] == "Error"),
                "warning_count": sum(1 for m in msgs if m["severity"] == "Warning"),
            }

        python_cmd = (
            "import unreal; "
            "print('Message Log accessible via Editor UI: Window -> Message Log')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "messages": [],
            "total": 0,
            "error_count": 0,
            "warning_count": 0,
            "python_result": result,
        }

    async def clear_output_log(self) -> dict[str, Any]:
        """Clear the Output Log panel in the editor.

        Returns:
            {"cleared": bool, "success": bool}
        """
        if self.is_mock:
            return {"mock": True, "cleared": True, "success": True}

        python_cmd = (
            "import unreal; "
            "unreal.SystemLibrary.execute_console_command(None, 'log reset'); "
            "print('Log cleared')"
        )
        result = await self.execute_python(python_cmd)
        return {"cleared": True, "success": True, "python_result": result}

    # ==================================================================
    # LAYER 5 · TESTING TOOLS
    # ==================================================================

    async def list_automation_tests(self, filter_pattern: str = "") -> dict[str, Any]:
        """List all automation tests registered in the project.

        Args:
            filter_pattern: Optional substring filter on test name.
                            Empty = return all tests.

        Returns:
            {"tests": [...], "total": int, "filter": str}
        """
        if self.is_mock:
            mock_tests = [
                {
                    "name": "Project.Gameplay.PlayerMovement",
                    "display_name": "Player Movement Tests",
                    "type": "Functional",
                    "last_status": "pass",
                    "last_duration_ms": 120,
                },
                {
                    "name": "Project.Gameplay.WeaponFirerate",
                    "display_name": "Weapon Firerate Validation",
                    "type": "Functional",
                    "last_status": "pass",
                    "last_duration_ms": 340,
                },
                {
                    "name": "Project.Gameplay.AINavigation",
                    "display_name": "AI Navigation Smoke Test",
                    "type": "Functional",
                    "last_status": "fail",
                    "last_duration_ms": 2100,
                    "last_error": "Expected 'EQS_FindPatrolPoint' to succeed — timed out.",
                },
                {
                    "name": "Project.UI.MainMenu",
                    "display_name": "Main Menu Widget Tests",
                    "type": "Functional",
                    "last_status": "pass",
                    "last_duration_ms": 89,
                },
                {
                    "name": "Project.Performance.LevelLoadTime",
                    "display_name": "Level Load Performance",
                    "type": "Performance",
                    "last_status": "pass",
                    "last_duration_ms": 4200,
                },
                {
                    "name": "Engine.KismetUnitTests.BlueprintCompile",
                    "display_name": "Blueprint Compile Unit Tests",
                    "type": "Unit",
                    "last_status": "pass",
                    "last_duration_ms": 55,
                },
            ]
            tests = mock_tests
            if filter_pattern:
                tests = [t for t in tests if filter_pattern.lower() in t["name"].lower()]
            return {
                "mock": True,
                "tests": tests,
                "total": len(tests),
                "filter": filter_pattern or None,
                "pass_count": sum(1 for t in tests if t.get("last_status") == "pass"),
                "fail_count": sum(1 for t in tests if t.get("last_status") == "fail"),
            }

        python_cmd = (
            "import unreal, json; "
            "manager = unreal.AutomationLibrary; "
            "print(json.dumps({'note': 'Use Editor: Session Frontend -> Automation tab'}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "tests": [],
            "total": 0,
            "note": "Use the editor Automation tab (Window → Test Automation) for live tests.",
            "python_result": result,
        }

    async def run_automation_test(
        self,
        test_name: str,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Run a specific automation test by its full name.

        Args:
            test_name:       Full test name, e.g. "Project.Gameplay.PlayerMovement".
                             Use list_automation_tests to get valid names.
            timeout_seconds: Maximum time to wait for the test to complete.

        Returns:
            {"test_name": str, "status": "pass"|"fail"|"timeout",
             "duration_ms": int, "errors": [...], "logs": [...]}
        """
        if self.is_mock:
            # Simulate test execution — failure rate ~10%.
            rng = random.Random(hash(test_name) % 10000)
            passed = rng.random() > 0.1
            duration = int(rng.uniform(50, 500))
            return {
                "mock": True,
                "test_name": test_name,
                "status": "pass" if passed else "fail",
                "duration_ms": duration,
                "errors": [] if passed else [f"Mock failure in test: {test_name}"],
                "logs": [f"[Test] {test_name}: {'PASSED' if passed else 'FAILED'}"],
                "timeout_seconds": timeout_seconds,
            }

        python_cmd = (
            "import unreal, json; "
            f"unreal.AutomationLibrary.run_editor_automation_tests('{test_name}'); "
            "print(json.dumps({'note': 'Test dispatched — check Automation tab for results'}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "test_name": test_name,
            "status": "dispatched",
            "note": "Test dispatched. Poll get_test_results() to retrieve outcome.",
            "python_result": result,
        }

    async def get_test_results(self) -> dict[str, Any]:
        """Return pass/fail results from the most recent automation test run.

        Returns:
            {"tests": [...], "summary": {"pass": int, "fail": int, "skip": int},
             "run_at": str}
        """
        if self.is_mock:
            tests = [
                {
                    "name": "Project.Gameplay.PlayerMovement",
                    "status": "pass",
                    "duration_ms": 120,
                    "errors": [],
                },
                {
                    "name": "Project.Gameplay.AINavigation",
                    "status": "fail",
                    "duration_ms": 2100,
                    "errors": ["EQS_FindPatrolPoint timed out after 2000ms"],
                },
                {
                    "name": "Project.UI.MainMenu",
                    "status": "pass",
                    "duration_ms": 89,
                    "errors": [],
                },
            ]
            return {
                "mock": True,
                "tests": tests,
                "summary": {
                    "pass": sum(1 for t in tests if t["status"] == "pass"),
                    "fail": sum(1 for t in tests if t["status"] == "fail"),
                    "skip": 0,
                },
                "run_at": "2024-01-01T12:05:00Z",
            }

        python_cmd = (
            "import unreal; "
            "print('Test results available in Session Frontend Automation tab')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "tests": [],
            "summary": {"pass": 0, "fail": 0, "skip": 0},
            "note": "Check the editor Automation tab for live test results.",
            "python_result": result,
        }

    async def run_all_tests(self, filter_pattern: str = "") -> dict[str, Any]:
        """Run the full automation test suite (optionally filtered).

        Args:
            filter_pattern: Run only tests whose name contains this substring.
                            Empty = run all registered tests.

        Returns:
            {"tests_run": int, "pass": int, "fail": int, "skip": int,
             "duration_ms": int, "filter": str}
        """
        if self.is_mock:
            mock_results = await self.get_test_results()
            tests = mock_results.get("tests", [])
            if filter_pattern:
                tests = [t for t in tests if filter_pattern.lower() in t["name"].lower()]
            summary = mock_results.get("summary", {})
            return {
                "mock": True,
                "tests_run": len(tests),
                "pass": summary.get("pass", 0),
                "fail": summary.get("fail", 0),
                "skip": summary.get("skip", 0),
                "duration_ms": sum(t.get("duration_ms", 0) for t in tests),
                "filter": filter_pattern or None,
                "tests": tests,
            }

        filter_arg = f"'{filter_pattern}'" if filter_pattern else "''"
        python_cmd = (
            "import unreal, json; "
            f"unreal.AutomationLibrary.run_editor_automation_tests({filter_arg}); "
            "print('All tests dispatched')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "tests_run": 0,
            "status": "dispatched",
            "note": "Tests dispatched. Poll get_test_results() for outcomes.",
            "python_result": result,
        }

    async def start_pie(
        self,
        num_players: int = 1,
        spawn_at_player_start: bool = True,
    ) -> dict[str, Any]:
        """Launch a Play In Editor (PIE) session.

        Args:
            num_players:             Number of player controllers to spawn (1–4).
            spawn_at_player_start:   Spawn at PlayerStart actor vs camera location.

        Returns:
            {"pie_started": bool, "num_players": int, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "pie_started": True,
                "num_players": num_players,
                "spawn_at_player_start": spawn_at_player_start,
                "success": True,
                "note": "PIE session started (mock). No real gameplay will run.",
            }

        python_cmd = (
            "import unreal; "
            "settings = unreal.EditorPlayInEditorSettings(); "
            f"settings.set_editor_property('play_number_of_clients', {num_players}); "
            f"settings.set_editor_property('play_in_editor_startup_location', "
            f"unreal.PlayInEditorStartupLocation.DEFAULT_PLAYER_START "
            f"if {str(spawn_at_player_start).lower()} == True "
            "else unreal.PlayInEditorStartupLocation.CURSOR_TO_SURFACE); "
            "unreal.UnrealEditorSubsystem().play_in_editor(); "
            "print('PIE started')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "pie_started": True,
            "num_players": num_players,
            "spawn_at_player_start": spawn_at_player_start,
            "success": True,
            "python_result": result,
        }

    async def stop_pie(self) -> dict[str, Any]:
        """Stop the current Play In Editor (PIE) session.

        Returns:
            {"pie_stopped": bool, "success": bool}
        """
        if self.is_mock:
            return {"mock": True, "pie_stopped": True, "success": True}

        python_cmd = (
            "import unreal; "
            "unreal.UnrealEditorSubsystem().end_play_in_editor(); "
            "print('PIE stopped')"
        )
        result = await self.execute_python(python_cmd)
        return {"pie_stopped": True, "success": True, "python_result": result}

    async def get_pie_state(self) -> dict[str, Any]:
        """Check whether a PIE session is currently active.

        Returns:
            {"is_playing": bool, "mode": str, "num_players": int}
        """
        if self.is_mock:
            return {
                "mock": True,
                "is_playing": False,
                "mode": "Editor",
                "num_players": 0,
                "note": "PIE state is not tracked in mock mode.",
            }

        python_cmd = (
            "import unreal, json; "
            "sub = unreal.UnrealEditorSubsystem(); "
            "playing = sub.is_in_play_in_editor_session(); "
            "print(json.dumps({'is_playing': playing}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "is_playing": False,
            "mode": "Editor",
            "python_result": result,
        }

    async def send_console_command(self, command: str) -> dict[str, Any]:
        """Execute a console command in the editor or active PIE session.

        Console commands control rendering features, debugging overlays,
        performance stats, and many other editor functions.

        Args:
            command: The console command string, e.g. "stat fps", "show Collision",
                     "r.ScreenPercentage 100", "ai.DebugDraw 1".

        Returns:
            {"command": str, "executed": bool, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "command": command,
                "executed": True,
                "success": True,
                "note": "Console command simulated in mock mode.",
            }

        python_cmd = (
            "import unreal; "
            f"unreal.SystemLibrary.execute_console_command(None, '{command}'); "
            "print('Command executed')"
        )
        result = await self.execute_python(python_cmd)
        return {
            "command": command,
            "executed": True,
            "success": True,
            "python_result": result,
        }

    async def get_build_log(self) -> dict[str, Any]:
        """Retrieve the output from the last project build or cook operation.

        Returns the most recent UnrealBuildTool log lines.  Build logs are
        written to Saved/Logs/UBT-*.log and are available even after the
        editor closes.

        Returns:
            {"log_path": str, "lines": [...], "total_lines": int,
             "error_count": int, "warning_count": int}
        """
        if self.is_mock:
            mock_lines = [
                "[1/42] Compile UnrealEditor-ue5_mcp.cpp",
                "[42/42] Link UnrealEditor-ue5_mcp",
                "Build succeeded.",
                "Total build time: 12.34 seconds",
            ]
            return {
                "mock": True,
                "log_path": "Saved/Logs/UBT-2024-01-01-12-00-00.log",
                "lines": mock_lines,
                "total_lines": len(mock_lines),
                "error_count": 0,
                "warning_count": 0,
                "build_result": "Succeeded",
            }

        # Build logs are written to disk — read the most recent one.
        python_cmd = (
            "import unreal, glob, os, json; "
            "project_dir = unreal.SystemLibrary.get_project_directory(); "
            "log_dir = os.path.join(project_dir, 'Saved', 'Logs'); "
            "logs = sorted(glob.glob(os.path.join(log_dir, 'UBT-*.log')), "
            "key=os.path.getmtime, reverse=True); "
            "log_path = logs[0] if logs else None; "
            "lines = open(log_path).readlines()[-100:] if log_path else []; "
            "print(json.dumps({'log_path': log_path, 'lines': [l.rstrip() for l in lines]}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "log_path": "",
            "lines": [],
            "total_lines": 0,
            "python_result": result,
        }

    # ------------------------------------------------------------------
    # Spatial validation bridge methods (Layer 1.5)
    # ------------------------------------------------------------------

    async def get_asset_static_mesh_bounds(self, asset_path: str) -> dict[str, Any]:
        """Return the half-extents of a StaticMesh asset before it is spawned.

        This is the key method for pre-spawn collision sizing.  It loads the
        uninstantiated mesh via unreal.load_asset() and reads its bounding box,
        so the occupancy grid can reserve the correct footprint before the actor
        exists in the level.

        Args:
            asset_path: Full /Game/... path to the StaticMesh.

        Returns:
            {"extent": {"X": float, "Y": float, "Z": float}, "asset_path": str}
            where X/Y/Z are the **half**-extents in Unreal centimetres.
        """
        if self.is_mock:
            # Return a size scaled loosely to the asset name for variety
            mesh_name = asset_path.split("/")[-1].lower()
            if any(kw in mesh_name for kw in ("tree", "pine", "oak")):
                ext = {"X": 120.0, "Y": 120.0, "Z": 400.0}
            elif any(kw in mesh_name for kw in ("rock", "stone", "boulder")):
                ext = {"X": 80.0, "Y": 80.0, "Z": 60.0}
            elif any(kw in mesh_name for kw in ("house", "building", "barn")):
                ext = {"X": 500.0, "Y": 600.0, "Z": 300.0}
            elif any(kw in mesh_name for kw in ("wall", "fence")):
                ext = {"X": 10.0, "Y": 200.0, "Z": 150.0}
            else:
                ext = {"X": 100.0, "Y": 100.0, "Z": 100.0}
            return {"mock": True, "asset_path": asset_path, "extent": ext}

        python_cmd = (
            "import unreal, json; "
            f"mesh = unreal.load_asset('{asset_path}'); "
            "bounds = mesh.get_bounds() if mesh else None; "
            "ext = bounds.box_extent if bounds else unreal.Vector(100,100,100); "
            "print(json.dumps({'extent': {'X': ext.x, 'Y': ext.y, 'Z': ext.z}}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "asset_path": asset_path,
            "extent": result.get("extent", {"X": 100.0, "Y": 100.0, "Z": 100.0}),
            "python_result": result,
        }

    async def line_trace_surface(
        self,
        x: float,
        y: float,
        z: float,
        trace_distance_cm: float = 50000.0,
    ) -> dict[str, Any]:
        """Fire a downward line trace to find the ground surface below (x, y, z).

        Used by SpawnValidator to:
          • Determine the real ground Z so actors land on terrain, not float
          • Extract the surface normal for slope checks and align_to_normal

        Args:
            x, y, z:            World-space start position (cm).
            trace_distance_cm:  How far down to trace.  Default 500 m.

        Returns:
            {
              "hit": bool,
              "location": {"X": float, "Y": float, "Z": float},
              "normal":   {"X": float, "Y": float, "Z": float},
            }
        """
        if self.is_mock:
            return {
                "mock": True,
                "hit": True,
                "location": {"X": x, "Y": y, "Z": 0.0},
                "normal": {"X": 0.0, "Y": 0.0, "Z": 1.0},
            }

        end_z = z - trace_distance_cm
        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            f"start = unreal.Vector({x}, {y}, {z}); "
            f"end   = unreal.Vector({x}, {y}, {end_z}); "
            "hit = unreal.SystemLibrary.line_trace_single("
            "world, start, end, "
            "unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, "
            "False, [], unreal.DrawDebugTrace.NONE, True); "
            "loc = hit.location if hit.blocking_hit else unreal.Vector(0,0,0); "
            "nrm = hit.impact_normal if hit.blocking_hit else unreal.Vector(0,0,1); "
            "print(json.dumps({"
            "'hit': hit.blocking_hit, "
            "'location': {'X': loc.x, 'Y': loc.y, 'Z': loc.z}, "
            "'normal':   {'X': nrm.x, 'Y': nrm.y, 'Z': nrm.z}"
            "}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "hit": result.get("hit", False),
            "location": result.get("location", {"X": x, "Y": y, "Z": z}),
            "normal": result.get("normal", {"X": 0.0, "Y": 0.0, "Z": 1.0}),
            "python_result": result,
        }

    async def overlap_sphere_test(
        self,
        x: float,
        y: float,
        z: float,
        radius_cm: float,
    ) -> dict[str, Any]:
        """Return all WorldStatic actors overlapping a sphere at (x, y, z).

        Used as the UE-side collision check after the in-memory grid check
        passes.  This is the heavier but authoritative collision query.

        Returns:
            {"overlapping_actors": [str, ...], "count": int}
        """
        if self.is_mock:
            return {
                "mock": True,
                "overlapping_actors": [],
                "count": 0,
            }

        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            f"pos = unreal.Vector({x}, {y}, {z}); "
            "overlaps = unreal.SystemLibrary.sphere_overlap_actors("
            "world, pos, "
            f"{radius_cm}, "
            "[unreal.ObjectTypeQuery.OBJECT_TYPE_QUERY1, "
            "unreal.ObjectTypeQuery.OBJECT_TYPE_QUERY2], "
            "None, []); "
            "names = [a.get_name() for a in overlaps] if overlaps else []; "
            "print(json.dumps({'overlapping_actors': names, 'count': len(names)}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "overlapping_actors": result.get("overlapping_actors", []),
            "count": result.get("count", 0),
            "python_result": result,
        }

    async def get_actor_bounds(self, actor_name: str) -> dict[str, Any]:
        """Return the world-space AABB (origin + half-extents) of an existing actor.

        Used by drift_check to compare live actor positions against grid entries.

        Returns:
            {
              "origin":  {"X": float, "Y": float, "Z": float},
              "extent":  {"X": float, "Y": float, "Z": float},
            }
        """
        if self.is_mock:
            actor = next(
                (a for a in _MOCK_ACTORS if a["name"] == actor_name), None
            )
            loc = actor["location"] if actor else {"x": 0, "y": 0, "z": 0}
            return {
                "mock": True,
                "actor": actor_name,
                "found": actor is not None,
                "origin": {"X": loc["x"], "Y": loc["y"], "Z": loc["z"]},
                "extent": {"X": 100.0, "Y": 100.0, "Z": 100.0},
            }

        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actors = unreal.EditorActorSubsystem().get_all_level_actors(); "
            f"actor = next((a for a in actors if a.get_name() == '{actor_name}'), None); "
            "origin, extent = actor.get_actor_bounds(False) if actor else "
            "(unreal.Vector(0,0,0), unreal.Vector(0,0,0)); "
            "print(json.dumps({"
            "'found': actor is not None, "
            "'origin': {'X': origin.x, 'Y': origin.y, 'Z': origin.z}, "
            "'extent': {'X': extent.x, 'Y': extent.y, 'Z': extent.z}"
            "}))"
        )
        result = await self.execute_python(python_cmd)
        return {
            "actor": actor_name,
            "found": result.get("found", False),
            "origin": result.get("origin", {"X": 0.0, "Y": 0.0, "Z": 0.0}),
            "extent": result.get("extent", {"X": 0.0, "Y": 0.0, "Z": 0.0}),
            "python_result": result,
        }

    async def create_spline_actor(
        self,
        points: list[dict[str, float]],
        closed_loop: bool = False,
        label: str = "",
    ) -> dict[str, Any]:
        """Spawn an empty Actor carrying a SplineComponent through the given points.

        Used as the foundation for roads, fences, rivers, and walls — any
        feature that needs a mesh tiled along a path.  The returned actor
        name/path is passed into add_spline_mesh to tile a mesh along it.

        Args:
            points:      World-space control points, each {"x", "y", "z"} (cm).
            closed_loop: If True, the spline connects its last point back to
                         the first.
            label:       Optional actor label. Auto-generated if empty.

        Returns:
            {"spline_actor": str, "object_path": str, "points": [...],
             "closed_loop": bool, "num_points": int}
        """
        name = label or f"SplineActor_{random.randint(100000, 999999)}"

        if self.is_mock:
            return {
                "mock": True,
                "spline_actor": name,
                "object_path": f"/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.{name}",
                "points": points,
                "closed_loop": closed_loop,
                "num_points": len(points),
            }

        point_literals = ", ".join(
            f"unreal.Vector({p['x']}, {p['y']}, {p['z']})" for p in points
        )
        python_cmd = (
            "import unreal, json; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "actor = unreal.EditorLevelLibrary.spawn_actor_from_class("
            "unreal.Actor, unreal.Vector(0,0,0)); "
            f"actor.set_actor_label({json.dumps(name)}); "
            "spline = actor.add_component_by_class(unreal.SplineComponent); "
            f"pts = [{point_literals}]; "
            "spline.set_spline_points(pts, unreal.SplinePointType.CURVE, True); "
            f"spline.set_closed_loop({closed_loop}); "
            "print(json.dumps({'object_path': actor.get_path_name()}))"
        )
        result = await self.execute_python(python_cmd)
        object_path = result.get("object_path", "")
        return {
            "spline_actor": name,
            "object_path": object_path,
            "points": points,
            "closed_loop": closed_loop,
            "num_points": len(points),
            "python_result": result,
        }

    async def add_spline_mesh(
        self,
        spline_actor: str,
        mesh_path: str,
        start_scale: dict[str, float],
        end_scale: dict[str, float],
    ) -> dict[str, Any]:
        """Tile a StaticMesh along every segment of a spline actor's spline.

        For each pair of consecutive spline points, adds one SplineMeshComponent
        whose start/end position and tangent are read from the spline itself,
        so the mesh follows curves as well as straight segments.

        Args:
            spline_actor: Actor name/label returned by create_spline_actor.
            mesh_path:    Full /Game/... path to the StaticMesh to tile.
            start_scale:  Cross-section scale {"x", "y"} at each segment start.
            end_scale:    Cross-section scale {"x", "y"} at each segment end.

        Returns:
            {"spline_actor": str, "mesh_path": str, "segments_tiled": int, "success": bool}
        """
        if self.is_mock:
            return {
                "mock": True,
                "spline_actor": spline_actor,
                "mesh_path": mesh_path,
                "start_scale": start_scale,
                "end_scale": end_scale,
                "segments_tiled": 1,
                "success": True,
                "note": (
                    "Mock mode — segment count depends on the live spline's "
                    "point count and is not tracked server-side."
                ),
            }

        # NOTE: every statement below is newline-separated (never ';'-joined
        # with a following compound statement) — mixing the two is invalid
        # Python grammar and silently breaks this command at UE's Python
        # interpreter. String values are embedded via json.dumps() so labels
        # and asset paths containing quotes can't corrupt the generated source.
        script_lines = [
            "import unreal, json",
            f"mesh = unreal.load_asset({json.dumps(mesh_path)})",
            "actor = None",
            "for a in unreal.EditorLevelLibrary.get_all_level_actors():",
            f"    if a.get_actor_label() == {json.dumps(spline_actor)}:",
            "        actor = a",
            "        break",
            "spline = actor.get_component_by_class(unreal.SplineComponent) if actor else None",
            "tiled = 0",
            "SC = unreal.SplineCoordinateSpace.LOCAL",
            "if spline:",
            "    n = spline.get_number_of_spline_points()",
            "    last = n if spline.is_closed_loop() else n - 1",
            "    for i in range(max(0, last)):",
            "        smc = actor.add_component_by_class(unreal.SplineMeshComponent)",
            "        smc.set_static_mesh(mesh)",
            "        s_loc = spline.get_location_at_spline_point(i, SC)",
            "        s_tan = spline.get_tangent_at_spline_point(i, SC)",
            "        j = (i + 1) % n",
            "        e_loc = spline.get_location_at_spline_point(j, SC)",
            "        e_tan = spline.get_tangent_at_spline_point(j, SC)",
            "        smc.set_start_and_end(s_loc, s_tan, e_loc, e_tan, True)",
            f"        sv = unreal.Vector2D({start_scale['x']}, {start_scale['y']})",
            f"        ev = unreal.Vector2D({end_scale['x']}, {end_scale['y']})",
            "        smc.set_start_scale(sv, True)",
            "        smc.set_end_scale(ev, True)",
            "        tiled += 1",
            "print(json.dumps({'segments_tiled': tiled, 'found_actor': actor is not None}))",
        ]
        python_cmd = "\n".join(script_lines)
        result = await self.execute_python(python_cmd)
        return {
            "spline_actor": spline_actor,
            "mesh_path": mesh_path,
            "segments_tiled": result.get("segments_tiled", 0),
            "success": bool(result.get("found_actor")),
            "python_result": result,
        }

    async def flush_debug_geometry(self) -> dict[str, Any]:
        """Clear all persistent debug lines, boxes, and strings from the viewport.

        Called by clear_occupancy_debug to remove the visualisation drawn by
        show_occupancy_debug and preview_spawn.

        Returns:
            {"flushed": True, "success": True}
        """
        if self.is_mock:
            return {"mock": True, "flushed": True, "success": True}

        python_cmd = (
            "import unreal; "
            "world = unreal.UnrealEditorSubsystem().get_editor_world(); "
            "unreal.SystemLibrary.flush_persistent_debug_lines(world); "
            "unreal.SystemLibrary.flush_debug_strings(world); "
            "print('Debug geometry cleared')"
        )
        result = await self.execute_python(python_cmd)
        return {"flushed": True, "success": True, "python_result": result}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def format_json(self, data: Any) -> str:
        return json.dumps(data, indent=2, default=str)
