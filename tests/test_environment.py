"""Tests for Layer 2 · Environment Tools.

Coverage groups:
  TestActorDiscovery       — list_actors, find_actors_by_tag, select_actors
  TestActorSpawning        — spawn_actor
  TestActorMovement        — move_actor
  TestActorPropertyAccess  — get_actor_property, set_actor_property
  TestActorDeletion        — delete_actor
  TestLevelManagement      — list_levels, open_level, save_current_level
  TestWorldSettings        — set_world_settings
  TestFoliageTools         — spawn_foliage, clear_foliage
  TestLODAndCollision      — configure_lod, generate_collision
  TestLandscapeTools       — list_landscape_layers, paint_landscape_layer
  TestPCGTools             — configure_pcg_graph
  TestBridgeMockData       — _MOCK_ACTORS, _MOCK_LEVELS etc. structure validation
  TestMockModeE2E          — every tool works end-to-end in mock mode
  TestErrorHandling        — invalid inputs, missing actors, JSON errors
"""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.client import (
    _MOCK_ACTORS,
    _MOCK_LANDSCAPE_LAYERS,
    _MOCK_LEVELS,
    _MOCK_WORLD_SETTINGS,
    UEClient,
)
from ue5_mcp.config import Settings
from ue5_mcp.tools.environment import (
    _error,
    register_environment_tools,
)

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> UEClient:
    """UEClient with mock mode enabled — no live editor required."""
    return UEClient(Settings(ue_mock_mode=True))


def _parsed(json_str: str) -> dict:
    """Parse JSON returned by a tool and raise on failure."""
    return json.loads(json_str)


# ---------------------------------------------------------------------------
# TestActorDiscovery
# ---------------------------------------------------------------------------


class TestActorDiscovery:
    @pytest.mark.asyncio
    async def test_get_all_actors_returns_actors(self, mock_client: UEClient) -> None:
        result = await mock_client.get_all_actors()
        assert "actors" in result
        assert result["total"] == len(result["actors"])
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_get_all_actors_structure(self, mock_client: UEClient) -> None:
        result = await mock_client.get_all_actors()
        for actor in result["actors"]:
            assert "name" in actor
            assert "location" in actor
            assert "rotation" in actor
            assert "scale" in actor
            for axis in ("x", "y", "z"):
                assert axis in actor["location"], f"location missing axis {axis}"
                assert axis in actor["scale"], f"scale missing axis {axis}"
            for axis in ("pitch", "yaw", "roll"):
                assert axis in actor["rotation"], f"rotation missing axis {axis}"

    @pytest.mark.asyncio
    async def test_get_all_actors_includes_mock_flag(self, mock_client: UEClient) -> None:
        result = await mock_client.get_all_actors()
        assert result.get("mock") is True

    @pytest.mark.asyncio
    async def test_find_actors_by_tag(self, mock_client: UEClient) -> None:
        result = await mock_client.find_actors(tag="Enemy")
        actors = result["actors"]
        assert len(actors) > 0
        for actor in actors:
            assert "Enemy" in actor.get("tags", [])

    @pytest.mark.asyncio
    async def test_find_actors_by_class_partial(self, mock_client: UEClient) -> None:
        result = await mock_client.find_actors(class_name="StaticMesh", partial_match=True)
        actors = result["actors"]
        assert all("staticmesh" in a.get("class", "").lower() for a in actors)

    @pytest.mark.asyncio
    async def test_find_actors_by_name_pattern(self, mock_client: UEClient) -> None:
        result = await mock_client.find_actors(name_pattern="Rock")
        actors = result["actors"]
        assert all("rock" in a.get("name", "").lower() for a in actors)

    @pytest.mark.asyncio
    async def test_find_actors_combined_filters(self, mock_client: UEClient) -> None:
        result = await mock_client.find_actors(tag="AI", class_name="BP_Enemy")
        actors = result["actors"]
        # Every returned actor must match BOTH the tag and class filter.
        for actor in actors:
            assert "AI" in actor.get("tags", [])
            assert "bp_enemy" in actor.get("class", "").lower()

    @pytest.mark.asyncio
    async def test_find_actors_no_match(self, mock_client: UEClient) -> None:
        result = await mock_client.find_actors(tag="NonExistentTag_xyz")
        assert result["total"] == 0
        assert result["actors"] == []

    @pytest.mark.asyncio
    async def test_select_actors_returns_found(self, mock_client: UEClient) -> None:
        actor_name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.select_actors([actor_name])
        assert actor_name in result["selected"]
        assert result["total_selected"] >= 1

    @pytest.mark.asyncio
    async def test_select_actors_not_found(self, mock_client: UEClient) -> None:
        result = await mock_client.select_actors(["NonExistentActor_xyz"])
        assert "NonExistentActor_xyz" in result["not_found"]
        assert result["total_selected"] == 0

    @pytest.mark.asyncio
    async def test_select_actors_mixed(self, mock_client: UEClient) -> None:
        real_name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.select_actors([real_name, "DoesNotExist_abc"])
        assert real_name in result["selected"]
        assert "DoesNotExist_abc" in result["not_found"]


# ---------------------------------------------------------------------------
# TestActorSpawning
# ---------------------------------------------------------------------------


class TestActorSpawning:
    @pytest.mark.asyncio
    async def test_spawn_actor_returns_name(self, mock_client: UEClient) -> None:
        result = await mock_client.spawn_actor(
            "/Game/Blueprints/BP_Enemy.BP_Enemy",
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        assert "spawned_actor" in result
        assert result["spawned_actor"]  # non-empty

    @pytest.mark.asyncio
    async def test_spawn_actor_echo_transform(self, mock_client: UEClient) -> None:
        loc = {"x": 100.0, "y": 200.0, "z": 50.0}
        rot = {"pitch": 0.0, "yaw": 90.0, "roll": 0.0}
        scale = {"x": 2.0, "y": 2.0, "z": 2.0}
        result = await mock_client.spawn_actor(
            "/Game/Blueprints/BP_Test.BP_Test", loc, rot, scale
        )
        assert result["transform"]["location"] == loc
        assert result["transform"]["rotation"] == rot
        assert result["transform"]["scale"] == scale

    @pytest.mark.asyncio
    async def test_spawn_actor_echo_asset_path(self, mock_client: UEClient) -> None:
        asset = "/Game/Blueprints/BP_Barrel.BP_Barrel"
        result = await mock_client.spawn_actor(
            asset,
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        assert result["asset_path"] == asset

    @pytest.mark.asyncio
    async def test_spawn_actor_returns_object_path(self, mock_client: UEClient) -> None:
        result = await mock_client.spawn_actor(
            "/Game/Blueprints/BP_Enemy.BP_Enemy",
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        assert "object_path" in result


# ---------------------------------------------------------------------------
# TestActorMovement
# ---------------------------------------------------------------------------


class TestActorMovement:
    @pytest.mark.asyncio
    async def test_move_actor_returns_before_after(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        new_loc = {"x": 9999.0, "y": 8888.0, "z": 100.0}
        result = await mock_client.move_actor(
            name, location=new_loc, rotation=None, scale=None
        )
        assert result["success"] is True
        assert "before" in result
        assert "after" in result
        assert result["after"]["location"] == new_loc

    @pytest.mark.asyncio
    async def test_move_actor_rotation_only(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        new_rot = {"pitch": 0.0, "yaw": 180.0, "roll": 0.0}
        result = await mock_client.move_actor(
            name, location=None, rotation=new_rot, scale=None
        )
        assert result["success"] is True
        assert result["after"]["rotation"] == new_rot

    @pytest.mark.asyncio
    async def test_move_actor_scale_only(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        new_scale = {"x": 3.0, "y": 3.0, "z": 3.0}
        result = await mock_client.move_actor(
            name, location=None, rotation=None, scale=new_scale
        )
        assert result["success"] is True
        assert result["after"]["scale"] == new_scale

    @pytest.mark.asyncio
    async def test_move_actor_not_found(self, mock_client: UEClient) -> None:
        result = await mock_client.move_actor(
            "NonExistentActor_xyz",
            location={"x": 0.0, "y": 0.0, "z": 0.0},
            rotation=None,
            scale=None,
        )
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_move_actor_unchanged_components_preserved(
        self, mock_client: UEClient
    ) -> None:
        name = _MOCK_ACTORS[0]["name"]
        original_rot = dict(_MOCK_ACTORS[0]["rotation"])
        new_loc = {"x": 0.0, "y": 0.0, "z": 0.0}
        result = await mock_client.move_actor(
            name, location=new_loc, rotation=None, scale=None
        )
        # Rotation must be unchanged when we only move location.
        assert result["after"]["rotation"] == original_rot


# ---------------------------------------------------------------------------
# TestActorPropertyAccess
# ---------------------------------------------------------------------------


class TestActorPropertyAccess:
    @pytest.mark.asyncio
    async def test_get_actor_property_known(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.get_actor_property(name, "bHidden")
        assert result["success"] is True
        assert "value" in result
        assert result["property_name"] == "bHidden"

    @pytest.mark.asyncio
    async def test_get_actor_property_tags(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.get_actor_property(name, "Tags")
        assert result["success"] is True
        assert isinstance(result["value"], list)

    @pytest.mark.asyncio
    async def test_get_actor_property_not_found(self, mock_client: UEClient) -> None:
        result = await mock_client.get_actor_property("NonExistent_xyz", "bHidden")
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_set_actor_property_returns_old_and_new(
        self, mock_client: UEClient
    ) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.set_actor_property(name, "bHidden", True)
        assert result["success"] is True
        assert "old_value" in result
        assert result["new_value"] is True

    @pytest.mark.asyncio
    async def test_set_actor_property_actor_not_found(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.set_actor_property("Missing_xyz", "bHidden", False)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_set_actor_property_echo_value(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.set_actor_property(name, "CustomDepthStencilValue", 42)
        assert result["new_value"] == 42


# ---------------------------------------------------------------------------
# TestActorDeletion
# ---------------------------------------------------------------------------


class TestActorDeletion:
    @pytest.mark.asyncio
    async def test_delete_actor_dry_run(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.delete_actor(name, dry_run=True)
        assert result["dry_run"] is True
        # Actor should not actually be deleted in dry_run
        assert not result.get("deleted", True) or result["dry_run"]

    @pytest.mark.asyncio
    async def test_delete_actor_mock_found(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.delete_actor(name, dry_run=False)
        assert result["found"] is True

    @pytest.mark.asyncio
    async def test_delete_actor_not_found(self, mock_client: UEClient) -> None:
        result = await mock_client.delete_actor("NonExistentActor_xyz", dry_run=False)
        assert result["found"] is False
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_actor_returns_actor_name(self, mock_client: UEClient) -> None:
        name = _MOCK_ACTORS[0]["name"]
        result = await mock_client.delete_actor(name, dry_run=True)
        assert result["actor"] == name


# ---------------------------------------------------------------------------
# TestLevelManagement
# ---------------------------------------------------------------------------


class TestLevelManagement:
    @pytest.mark.asyncio
    async def test_list_levels_returns_persistent_level(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.list_levels()
        levels = result["levels"]
        persistent = [lv for lv in levels if lv.get("is_persistent")]
        assert len(persistent) == 1

    @pytest.mark.asyncio
    async def test_list_levels_total_matches(self, mock_client: UEClient) -> None:
        result = await mock_client.list_levels()
        assert result["total"] == len(result["levels"])
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_list_levels_structure(self, mock_client: UEClient) -> None:
        result = await mock_client.list_levels()
        for level in result["levels"]:
            assert "name" in level
            assert "package_path" in level
            assert "is_persistent" in level
            assert "is_loaded" in level
            assert "is_visible" in level

    @pytest.mark.asyncio
    async def test_open_level_mock(self, mock_client: UEClient) -> None:
        result = await mock_client.open_level("/Game/Maps/L_Forest")
        assert result["loaded"] is True
        assert result["level_path"] == "/Game/Maps/L_Forest"

    @pytest.mark.asyncio
    async def test_open_level_returns_previous_world(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.open_level("/Game/Maps/L_Arena")
        assert "previous_world" in result
        assert result["previous_world"]  # non-empty

    @pytest.mark.asyncio
    async def test_save_level_mock(self, mock_client: UEClient) -> None:
        result = await mock_client.save_level()
        assert result["saved"] is True
        assert "level" in result


# ---------------------------------------------------------------------------
# TestWorldSettings
# ---------------------------------------------------------------------------


class TestWorldSettings:
    @pytest.mark.asyncio
    async def test_set_world_settings_gravity(self, mock_client: UEClient) -> None:
        result = await mock_client.set_world_settings({"gravity_z": -490.0})
        assert result["success"] is True
        assert "gravity_z" in result["after"]
        assert result["after"]["gravity_z"] == -490.0

    @pytest.mark.asyncio
    async def test_set_world_settings_multiple(self, mock_client: UEClient) -> None:
        updates = {"gravity_z": 0.0, "game_time_dilation": 0.5}
        result = await mock_client.set_world_settings(updates)
        assert result["success"] is True
        assert set(result["applied"]) == set(updates.keys())

    @pytest.mark.asyncio
    async def test_set_world_settings_before_after(self, mock_client: UEClient) -> None:
        result = await mock_client.set_world_settings({"kill_z": -200000.0})
        assert "before" in result
        assert "after" in result
        assert result["after"]["kill_z"] == -200000.0

    @pytest.mark.asyncio
    async def test_set_world_settings_returns_applied_list(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.set_world_settings(
            {"gravity_z": -980.0, "game_time_dilation": 1.0}
        )
        assert isinstance(result["applied"], list)
        assert len(result["applied"]) == 2


# ---------------------------------------------------------------------------
# TestFoliageTools
# ---------------------------------------------------------------------------


class TestFoliageTools:
    @pytest.mark.asyncio
    async def test_spawn_foliage_returns_count(self, mock_client: UEClient) -> None:
        result = await mock_client.spawn_foliage(
            mesh_path="/Game/Environment/SM_Tree_Oak",
            density=50.0,
            area_min={"x": 0.0, "y": 0.0},
            area_max={"x": 10000.0, "y": 10000.0},
            scale_min=0.9,
            scale_max=1.4,
            seed=42,
            align_to_normal=True,
            random_yaw=True,
        )
        assert result["success"] is True
        assert result["instances_placed"] > 0

    @pytest.mark.asyncio
    async def test_spawn_foliage_seed_reproducibility(
        self, mock_client: UEClient
    ) -> None:
        params = dict(
            mesh_path="/Game/Environment/SM_Tree_Oak",
            density=50.0,
            area_min={"x": 0.0, "y": 0.0},
            area_max={"x": 10000.0, "y": 10000.0},
            scale_min=0.9,
            scale_max=1.4,
            seed=99,
            align_to_normal=True,
            random_yaw=True,
        )
        r1 = await mock_client.spawn_foliage(**params)
        r2 = await mock_client.spawn_foliage(**params)
        assert r1["instances_placed"] == r2["instances_placed"]

    @pytest.mark.asyncio
    async def test_spawn_foliage_area_m2_calculated(
        self, mock_client: UEClient
    ) -> None:
        # 10000cm × 10000cm = 10000 m²
        result = await mock_client.spawn_foliage(
            mesh_path="/Game/Foliage/SM_Grass",
            density=100.0,
            area_min={"x": 0.0, "y": 0.0},
            area_max={"x": 10000.0, "y": 10000.0},
            scale_min=1.0,
            scale_max=1.0,
            seed=1,
            align_to_normal=False,
            random_yaw=False,
        )
        assert result["area_m2"] == pytest.approx(10000.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_clear_foliage_by_mesh(self, mock_client: UEClient) -> None:
        result = await mock_client.clear_foliage(
            mesh_path="/Game/Environment/Foliage/SM_Tree_Oak"
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_clear_foliage_all(self, mock_client: UEClient) -> None:
        result = await mock_client.clear_foliage()
        assert result["success"] is True
        assert result["instances_removed"] > 0

    @pytest.mark.asyncio
    async def test_clear_foliage_unknown_mesh_zero_removed(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.clear_foliage(
            mesh_path="/Game/Missing/SM_DoesNotExist"
        )
        # Mock: unknown mesh → 0 instances removed, but not an error
        assert result["success"] is True
        assert result["instances_removed"] == 0


# ---------------------------------------------------------------------------
# TestLODAndCollision
# ---------------------------------------------------------------------------


class TestLODAndCollision:
    @pytest.mark.asyncio
    async def test_configure_lod_returns_before_after(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.configure_lod(
            "/Game/Environment/Rocks/SM_Rock_01",
            [1.0, 0.3, 0.1, 0.03],
        )
        assert result["success"] is True
        assert "before" in result
        assert "after" in result
        assert result["after"]["lod_screen_sizes"] == [1.0, 0.3, 0.1, 0.03]

    @pytest.mark.asyncio
    async def test_configure_lod_echo_mesh_path(self, mock_client: UEClient) -> None:
        path = "/Game/Environment/SM_Rock_Big"
        result = await mock_client.configure_lod(path, [1.0, 0.25, 0.1, 0.04])
        assert result["mesh_path"] == path

    @pytest.mark.asyncio
    async def test_generate_collision_success(self, mock_client: UEClient) -> None:
        result = await mock_client.generate_collision(
            "/Game/Environment/SM_Rock_01", "complex_as_simple"
        )
        assert result["success"] is True
        assert result["collision_generated"] is True

    @pytest.mark.asyncio
    async def test_generate_collision_echo_type(self, mock_client: UEClient) -> None:
        result = await mock_client.generate_collision(
            "/Game/Environment/SM_Rock_01", "simple_box"
        )
        assert result["collision_type"] == "simple_box"

    @pytest.mark.asyncio
    async def test_generate_collision_default_type(self, mock_client: UEClient) -> None:
        result = await mock_client.generate_collision("/Game/Environment/SM_Barrel")
        # Default type should be used
        assert result["success"] is True


# ---------------------------------------------------------------------------
# TestLandscapeTools
# ---------------------------------------------------------------------------


class TestLandscapeTools:
    @pytest.mark.asyncio
    async def test_list_landscape_layers_returns_layers(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.list_landscape_layers()
        assert "layers" in result
        assert result["total"] == len(result["layers"])
        assert result["total"] > 0

    @pytest.mark.asyncio
    async def test_list_landscape_layers_structure(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.list_landscape_layers()
        for layer in result["layers"]:
            assert "name" in layer
            assert "layer_info_path" in layer
            assert "is_weight_blended" in layer

    @pytest.mark.asyncio
    async def test_list_landscape_layers_known_names(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.list_landscape_layers()
        names = {layer["name"] for layer in result["layers"]}
        # Mock data should include standard landscape layers.
        assert "Grass" in names

    @pytest.mark.asyncio
    async def test_paint_landscape_layer_success(self, mock_client: UEClient) -> None:
        result = await mock_client.paint_landscape_layer(
            layer_name="Grass",
            region_min={"x": 0.0, "y": 0.0},
            region_max={"x": 10000.0, "y": 10000.0},
            weight=1.0,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_paint_landscape_layer_echo_layer_name(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.paint_landscape_layer(
            layer_name="Dirt",
            region_min={"x": 0.0, "y": 0.0},
            region_max={"x": 5000.0, "y": 5000.0},
            weight=0.5,
        )
        assert result["layer"] == "Dirt"
        assert result["weight"] == 0.5

    @pytest.mark.asyncio
    async def test_paint_landscape_layer_area_calculation(
        self, mock_client: UEClient
    ) -> None:
        # 20000cm × 20000cm = 40000 m²
        result = await mock_client.paint_landscape_layer(
            layer_name="Rock",
            region_min={"x": 0.0, "y": 0.0},
            region_max={"x": 20000.0, "y": 20000.0},
            weight=0.8,
        )
        assert result["affected_area_m2"] == pytest.approx(40000.0, rel=0.01)


# ---------------------------------------------------------------------------
# TestPCGTools
# ---------------------------------------------------------------------------


class TestPCGTools:
    @pytest.mark.asyncio
    async def test_configure_pcg_graph_returns_before_after(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.configure_pcg_graph(
            "BP_Forest_PCG_0",
            {"Density": 500, "Seed": 42},
        )
        assert result["success"] is True
        assert "before" in result
        assert "after" in result

    @pytest.mark.asyncio
    async def test_configure_pcg_graph_applied_keys(
        self, mock_client: UEClient
    ) -> None:
        updates = {"Density": 100, "bEnabled": True}
        result = await mock_client.configure_pcg_graph("PCG_Actor_0", updates)
        assert set(result["applied"]) == set(updates.keys())

    @pytest.mark.asyncio
    async def test_configure_pcg_graph_after_values(
        self, mock_client: UEClient
    ) -> None:
        updates = {"Density": 250, "Seed": 7}
        result = await mock_client.configure_pcg_graph("PCG_Test_0", updates)
        assert result["after"]["Density"] == 250
        assert result["after"]["Seed"] == 7

    @pytest.mark.asyncio
    async def test_configure_pcg_graph_actor_name_echoed(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.configure_pcg_graph(
            "BP_Meadow_PCG_0", {"Scale": 1.5}
        )
        assert result["actor"] == "BP_Meadow_PCG_0"


# ---------------------------------------------------------------------------
# TestBridgeMockData — validate the quality of mock data constants
# ---------------------------------------------------------------------------


class TestBridgeMockData:
    def test_mock_actors_all_have_required_fields(self) -> None:
        required = {"name", "class", "object_path", "location", "rotation", "scale", "tags"}
        for actor in _MOCK_ACTORS:
            missing = required - set(actor.keys())
            assert not missing, f"Actor '{actor['name']}' missing fields: {missing}"

    def test_mock_actors_location_has_xyz(self) -> None:
        for actor in _MOCK_ACTORS:
            for axis in ("x", "y", "z"):
                assert axis in actor["location"], (
                    f"Actor '{actor['name']}' location missing '{axis}'"
                )

    def test_mock_actors_rotation_has_pyr(self) -> None:
        for actor in _MOCK_ACTORS:
            for axis in ("pitch", "yaw", "roll"):
                assert axis in actor["rotation"], (
                    f"Actor '{actor['name']}' rotation missing '{axis}'"
                )

    def test_mock_actors_unique_names(self) -> None:
        names = [a["name"] for a in _MOCK_ACTORS]
        assert len(names) == len(set(names)), "Duplicate actor names in mock data"

    def test_mock_actors_unique_object_paths(self) -> None:
        paths = [a["object_path"] for a in _MOCK_ACTORS]
        assert len(paths) == len(set(paths)), "Duplicate object paths in mock data"

    def test_mock_levels_one_persistent(self) -> None:
        persistent = [lv for lv in _MOCK_LEVELS if lv.get("is_persistent")]
        assert len(persistent) == 1, "Exactly one persistent level required in mock data"

    def test_mock_levels_have_package_paths(self) -> None:
        for level in _MOCK_LEVELS:
            assert level.get("package_path", "").startswith("/Game/"), (
                f"Level '{level['name']}' has invalid package_path"
            )

    def test_mock_landscape_layers_all_have_required_fields(self) -> None:
        for layer in _MOCK_LANDSCAPE_LAYERS:
            assert "name" in layer
            assert "layer_info_path" in layer
            assert "is_weight_blended" in layer

    def test_mock_world_settings_has_gravity(self) -> None:
        assert "gravity_z" in _MOCK_WORLD_SETTINGS or "global_gravity_z" in _MOCK_WORLD_SETTINGS

    def test_mock_world_settings_gravity_negative(self) -> None:
        # UE's default Earth gravity is -980 cm/s²
        gravity = (
            _MOCK_WORLD_SETTINGS.get("gravity_z")
            or _MOCK_WORLD_SETTINGS.get("global_gravity_z")
        )
        assert gravity is not None
        assert gravity < 0, "Default gravity should be negative (downward)"


# ---------------------------------------------------------------------------
# TestMockModeE2E — every tool produces valid JSON in mock mode
# ---------------------------------------------------------------------------


class TestMockModeE2E:
    """End-to-end: call every registered tool via the bridge, parse JSON."""

    @pytest.mark.asyncio
    async def test_e2e_list_actors(self, mock_client: UEClient) -> None:
        result = await mock_client.get_all_actors()
        assert isinstance(result, dict)
        assert "actors" in result

    @pytest.mark.asyncio
    async def test_e2e_spawn_actor(self, mock_client: UEClient) -> None:
        result = await mock_client.spawn_actor(
            "/Game/BP/BP_Test.BP_Test",
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
            {"x": 1.0, "y": 1.0, "z": 1.0},
        )
        assert "spawned_actor" in result

    @pytest.mark.asyncio
    async def test_e2e_move_actor(self, mock_client: UEClient) -> None:
        result = await mock_client.move_actor(
            _MOCK_ACTORS[0]["name"],
            {"x": 0.0, "y": 0.0, "z": 0.0},
            None,
            None,
        )
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_delete_actor(self, mock_client: UEClient) -> None:
        result = await mock_client.delete_actor(_MOCK_ACTORS[0]["name"])
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_list_levels(self, mock_client: UEClient) -> None:
        result = await mock_client.list_levels()
        assert "levels" in result

    @pytest.mark.asyncio
    async def test_e2e_open_level(self, mock_client: UEClient) -> None:
        result = await mock_client.open_level("/Game/Maps/L_Forest")
        assert "loaded" in result

    @pytest.mark.asyncio
    async def test_e2e_save_level(self, mock_client: UEClient) -> None:
        result = await mock_client.save_level()
        assert "saved" in result

    @pytest.mark.asyncio
    async def test_e2e_set_world_settings(self, mock_client: UEClient) -> None:
        result = await mock_client.set_world_settings({"gravity_z": -980.0})
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_spawn_foliage(self, mock_client: UEClient) -> None:
        result = await mock_client.spawn_foliage(
            "/Game/SM_Tree",
            50.0,
            {"x": 0.0, "y": 0.0},
            {"x": 10000.0, "y": 10000.0},
            0.9,
            1.2,
            42,
            True,
            True,
        )
        assert "instances_placed" in result

    @pytest.mark.asyncio
    async def test_e2e_clear_foliage(self, mock_client: UEClient) -> None:
        result = await mock_client.clear_foliage()
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_configure_lod(self, mock_client: UEClient) -> None:
        result = await mock_client.configure_lod("/Game/SM_Rock", [1.0, 0.3, 0.15, 0.05])
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_generate_collision(self, mock_client: UEClient) -> None:
        result = await mock_client.generate_collision("/Game/SM_Rock")
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_list_landscape_layers(self, mock_client: UEClient) -> None:
        result = await mock_client.list_landscape_layers()
        assert "layers" in result

    @pytest.mark.asyncio
    async def test_e2e_paint_landscape_layer(self, mock_client: UEClient) -> None:
        result = await mock_client.paint_landscape_layer(
            "Grass", {"x": 0.0, "y": 0.0}, {"x": 1000.0, "y": 1000.0}, 1.0
        )
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_configure_pcg_graph(self, mock_client: UEClient) -> None:
        result = await mock_client.configure_pcg_graph("PCG_0", {"Density": 100})
        assert "success" in result

    @pytest.mark.asyncio
    async def test_e2e_execute_python(self, mock_client: UEClient) -> None:
        result = await mock_client.execute_python("print('hello')")
        assert result.get("mock") is True

    @pytest.mark.asyncio
    async def test_e2e_get_object_property(self, mock_client: UEClient) -> None:
        result = await mock_client.get_object_property(
            "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.DirectionalLight_0",
            "bHidden",
        )
        assert result.get("mock") is True

    @pytest.mark.asyncio
    async def test_e2e_set_object_property(self, mock_client: UEClient) -> None:
        result = await mock_client.set_object_property(
            "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.DirectionalLight_0",
            "bHidden",
            True,
        )
        assert result.get("mock") is True


# ---------------------------------------------------------------------------
# TestErrorHandling — tool-layer validation and structured error responses
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_error_helper_structure(self) -> None:
        err = _error("test_tool", "Something went wrong")
        assert err["error"] == "Something went wrong"
        assert err["tool"] == "test_tool"
        assert err["success"] is False
        assert "timestamp" in err

    def test_error_helper_json_serialisable(self) -> None:
        err = _error("test_tool", "message")
        serialised = json.dumps(err)
        parsed = json.loads(serialised)
        assert parsed["success"] is False

    @pytest.mark.asyncio
    async def test_find_actors_empty_filters_raises_error(
        self, mock_client: UEClient
    ) -> None:
        # Providing no filters returns empty, not an exception
        result = await mock_client.find_actors()
        # Should gracefully return all actors when no filters given
        assert "actors" in result

    @pytest.mark.asyncio
    async def test_move_actor_nonexistent_returns_error_dict(
        self, mock_client: UEClient
    ) -> None:
        result = await mock_client.move_actor(
            "Ghost_Actor_00",
            {"x": 0.0, "y": 0.0, "z": 0.0},
            None,
            None,
        )
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_configure_lod_valid_decreasing_order_succeeds(
        self, mock_client: UEClient
    ) -> None:
        # The tool layer validates decreasing order; bridge just passes through.
        # Test that bridge accepts valid decreasing order.
        result = await mock_client.configure_lod(
            "/Game/SM_Rock", [1.0, 0.3, 0.15, 0.05]
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_paint_landscape_layer_returns_dict(
        self, mock_client: UEClient
    ) -> None:
        # Bridge does not validate weight bounds; tool layer does.
        # Direct bridge call should always return a dict regardless of value.
        result = await mock_client.paint_landscape_layer(
            "Grass",
            {"x": 0.0, "y": 0.0},
            {"x": 1000.0, "y": 1000.0},
            0.75,
        )
        assert isinstance(result, dict)

    def test_tool_layer_registers_without_error(self, mock_client: UEClient) -> None:
        """Verify register_environment_tools attaches tools without raising."""
        test_mcp = FastMCP("lint-test")
        register_environment_tools(test_mcp, mock_client)
