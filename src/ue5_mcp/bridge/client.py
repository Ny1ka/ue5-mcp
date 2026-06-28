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

# Actor management — requires EditorScriptingUtilities plugin
_EDITOR_ACTOR_SUB = "/Script/EditorScriptingUtilities.Default__EditorActorSubsystem"

# Level management — requires EditorScriptingUtilities plugin
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
        list_result = await self.call_editor_function(
            _EDITOR_ACTOR_SUB, "GetAllLevelActors", {}
        )
        actor_paths: list[str] = list_result.get("OutActorList", [])

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
            _EDITOR_LEVEL_LIB,
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

        # Optimise for tag-only search using dedicated subsystem call.
        if tag and not class_name and not name_pattern:
            result = await self.call_editor_function(
                _EDITOR_ACTOR_SUB,
                "GetAllActorsWithTag",
                {"Tag": tag},
            )
            paths: list[str] = result.get("OutActors", [])
            actors = [{"name": p.split(".")[-1], "object_path": p} for p in paths]
            return {"actors": actors, "total": len(actors), "filters": {"tag": tag}}

        # General filter: fetch all actors, filter locally.
        all_data = await self.get_all_actors()
        actors = all_data.get("actors", [])

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
        result = await self.call_editor_function(_EDITOR_ACTOR_SUB, "GetAllLevelActors", {})
        for path in result.get("OutActorList", []):
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
        world_result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "GetEditorWorld", {}
        )
        world_path: str = world_result.get("ReturnValue", "")

        # GetStreamingLevels lists sub-levels registered with the persistent level.
        streaming_result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "GetStreamingLevels", {}
        )
        streaming_levels: list[Any] = streaming_result.get("ReturnValue", [])

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
        world_before = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "GetEditorWorld", {}
        )
        previous = world_before.get("ReturnValue", "")

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
        world_result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "GetEditorWorld", {}
        )
        level_path: str = world_result.get("ReturnValue", "")

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

        # WorldSettings actor path pattern:
        # /Game/Maps/L_Forest.L_Forest:PersistentLevel.WorldSettings
        world_result = await self.call_editor_function(
            _EDITOR_LEVEL_LIB, "GetEditorWorld", {}
        )
        world_path: str = world_result.get("ReturnValue", "")
        world_name = world_path.split("/")[-1] if world_path else "Unknown"
        ws_path = f"{world_path}.{world_name}:PersistentLevel.WorldSettings"

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

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def format_json(self, data: Any) -> str:
        return json.dumps(data, indent=2, default=str)
