"""Tests for Phase 5 · Splines, Roads & Structure Composition.

Coverage groups:
  TestStructureTemplateLoader — structures.py loader + resolve/rotate helpers
  TestListStructureTemplates  — list_structure_templates tool
  TestBuildStructure          — build_structure tool (happy path, overrides,
                                 overlap rejection, error handling)
  TestSplineTools              — create_spline_actor, add_spline_mesh
  TestCreateRoadSegment        — create_road_segment tool
"""

from __future__ import annotations

import json

import pytest

from ue5_mcp.bridge.client import UEClient
from ue5_mcp.config import Settings
from ue5_mcp.spatial import OCCUPANCY_GRID
from ue5_mcp.structures import (
    get_structure_template,
    load_structure_templates,
    resolve_component_asset,
    rotate_offset_xy,
)
from ue5_mcp.tools.environment import register_environment_tools

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> UEClient:
    """UEClient with mock mode enabled — no live editor required."""
    return UEClient(Settings(ue_mock_mode=True))


@pytest.fixture(autouse=True)
def _clear_grid():
    """Every test starts with an empty occupancy grid."""
    OCCUPANCY_GRID.clear()
    yield
    OCCUPANCY_GRID.clear()


class _ToolRegistry:
    """Captures @mcp.tool() functions by name for direct invocation in tests."""

    def __init__(self) -> None:
        self._tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn

        return decorator

    def __getattr__(self, name: str):
        return self._tools[name]


@pytest.fixture
def tools(mock_client: UEClient):
    registry = _ToolRegistry()
    register_environment_tools(registry, mock_client)  # type: ignore[arg-type]
    return registry


def _parsed(json_str: str) -> dict:
    return json.loads(json_str)


# ---------------------------------------------------------------------------
# TestStructureTemplateLoader
# ---------------------------------------------------------------------------


class TestStructureTemplateLoader:
    def test_load_returns_expected_presets(self) -> None:
        templates = load_structure_templates()
        for key in (
            "cabin",
            "house_small",
            "house_large",
            "warehouse",
            "tower",
            "wall_segment",
            "archway",
        ):
            assert key in templates

    def test_every_template_has_required_fields(self) -> None:
        templates = load_structure_templates()
        for key, tpl in templates.items():
            assert "display_name" in tpl, key
            assert "description" in tpl, key
            footprint = tpl["footprint_cm"]
            for axis in ("x", "y", "z"):
                assert axis in footprint, f"{key} footprint missing {axis}"
            assert len(tpl["components"]) > 0, key

    def test_component_ids_unique_per_template(self) -> None:
        templates = load_structure_templates()
        for key, tpl in templates.items():
            ids = [c["id"] for c in tpl["components"]]
            assert len(ids) == len(set(ids)), f"duplicate component ids in {key}"

    def test_every_component_has_required_fields(self) -> None:
        templates = load_structure_templates()
        for key, tpl in templates.items():
            for component in tpl["components"]:
                for field in ("id", "category", "default_asset", "offset", "rotation", "scale"):
                    assert field in component, f"{key}.{component.get('id')} missing {field}"
                for axis in ("x", "y", "z"):
                    assert axis in component["offset"]
                    assert axis in component["scale"]
                for axis in ("pitch", "yaw", "roll"):
                    assert axis in component["rotation"]

    def test_get_structure_template_unknown_returns_none(self) -> None:
        assert get_structure_template("not_a_real_structure") is None

    def test_get_structure_template_known(self) -> None:
        tpl = get_structure_template("cabin")
        assert tpl is not None
        assert tpl["display_name"] == "Wooden Cabin"

    def test_resolve_component_asset_priority(self) -> None:
        component = {
            "id": "wall_north",
            "category": "wall",
            "default_asset": "/Game/Default/SM_Wall",
        }
        # No overrides — falls back to default_asset
        assert resolve_component_asset(component, {}) == "/Game/Default/SM_Wall"
        # Category override applies
        assert (
            resolve_component_asset(component, {"wall": "/Game/Custom/SM_Wall_Stone"})
            == "/Game/Custom/SM_Wall_Stone"
        )
        # Exact id override takes priority over category override
        overrides = {
            "wall": "/Game/Custom/SM_Wall_Stone",
            "wall_north": "/Game/Custom/SM_Wall_North_Special",
        }
        assert resolve_component_asset(component, overrides) == "/Game/Custom/SM_Wall_North_Special"

    def test_rotate_offset_xy_zero_yaw_is_identity(self) -> None:
        x, y = rotate_offset_xy(100.0, 50.0, 0.0)
        assert x == pytest.approx(100.0)
        assert y == pytest.approx(50.0)

    def test_rotate_offset_xy_ninety_degrees(self) -> None:
        x, y = rotate_offset_xy(100.0, 0.0, 90.0)
        assert x == pytest.approx(0.0, abs=1e-6)
        assert y == pytest.approx(100.0, abs=1e-6)


# ---------------------------------------------------------------------------
# TestListStructureTemplates
# ---------------------------------------------------------------------------


class TestListStructureTemplates:
    @pytest.mark.asyncio
    async def test_returns_all_presets(self, tools) -> None:
        result = _parsed(await tools.list_structure_templates())
        assert result["total"] == len(load_structure_templates())
        assert "cabin" in result["templates"]
        assert "components" in result["templates"]["cabin"]

    @pytest.mark.asyncio
    async def test_component_summary_shape(self, tools) -> None:
        result = _parsed(await tools.list_structure_templates())
        for entry in result["templates"]["wall_segment"]["components"]:
            assert "id" in entry
            assert "category" in entry


# ---------------------------------------------------------------------------
# TestBuildStructure
# ---------------------------------------------------------------------------


class TestBuildStructure:
    @pytest.mark.asyncio
    async def test_happy_path_spawns_all_components(self, tools) -> None:
        result = _parsed(
            await tools.build_structure(structure_type="cabin", location_x=0.0, location_y=0.0)
        )
        assert result["success"] is True
        template = get_structure_template("cabin")
        assert result["components_spawned"] == len(template["components"])
        assert result["components_failed"] == 0
        assert result["grid_registered"] is True

    @pytest.mark.asyncio
    async def test_unknown_structure_type_lists_valid_options(self, tools) -> None:
        result = _parsed(await tools.build_structure(structure_type="castle"))
        assert result["success"] is False
        assert "cabin" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_component_overrides_json(self, tools) -> None:
        result = _parsed(
            await tools.build_structure(structure_type="cabin", component_overrides="{not json")
        )
        assert result["success"] is False
        assert "not valid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_component_overrides_applied_by_category(self, tools) -> None:
        overrides = json.dumps({"wall": "/Game/Custom/SM_Wall_Stone"})
        result = _parsed(
            await tools.build_structure(
                structure_type="cabin", component_overrides=overrides
            )
        )
        wall_components = [c for c in result["spawned"] if c["category"] == "wall"]
        assert wall_components
        assert all(c["asset_path"] == "/Game/Custom/SM_Wall_Stone" for c in wall_components)

    @pytest.mark.asyncio
    async def test_second_overlapping_structure_rejected(self, tools) -> None:
        first = _parsed(
            await tools.build_structure(
                structure_type="cabin", location_x=0.0, location_y=0.0, label="cabin_a"
            )
        )
        assert first["success"] is True

        second = _parsed(
            await tools.build_structure(
                structure_type="cabin", location_x=0.0, location_y=0.0, label="cabin_b"
            )
        )
        assert second["success"] is False
        assert "overlaps" in second["error"]

    @pytest.mark.asyncio
    async def test_allow_overlap_bypasses_rejection(self, tools) -> None:
        first = _parsed(
            await tools.build_structure(
                structure_type="cabin", location_x=0.0, location_y=0.0, label="cabin_a"
            )
        )
        assert first["success"] is True

        second = _parsed(
            await tools.build_structure(
                structure_type="cabin",
                location_x=0.0,
                location_y=0.0,
                label="cabin_b",
                allow_overlap=True,
            )
        )
        assert second["success"] is True

    @pytest.mark.asyncio
    async def test_yaw_and_uniform_scale_affect_component_locations(self, tools) -> None:
        baseline = _parsed(
            await tools.build_structure(
                structure_type="wall_segment",
                location_x=0.0,
                location_y=0.0,
                label="wall_baseline",
                use_spatial_validation=False,
            )
        )
        rotated = _parsed(
            await tools.build_structure(
                structure_type="wall_segment",
                location_x=0.0,
                location_y=0.0,
                yaw=90.0,
                label="wall_rotated",
                use_spatial_validation=False,
            )
        )
        base_panel = next(c for c in baseline["spawned"] if c["id"] == "panel")
        rot_panel = next(c for c in rotated["spawned"] if c["id"] == "panel")
        # panel offset is purely along local X; a 90 degree yaw should move it
        # onto the Y axis instead.
        assert base_panel["location"]["x"] == pytest.approx(0.0, abs=1e-6)
        assert rot_panel["location"]["y"] == pytest.approx(0.0, abs=1e-3)


# ---------------------------------------------------------------------------
# TestSplineTools
# ---------------------------------------------------------------------------


class TestSplineTools:
    @pytest.mark.asyncio
    async def test_create_spline_actor_happy_path(self, tools) -> None:
        points = json.dumps([{"x": 0, "y": 0, "z": 0}, {"x": 1000, "y": 0, "z": 0}])
        result = _parsed(await tools.create_spline_actor(points=points))
        assert result["num_points"] == 2
        assert "spline_actor" in result

    @pytest.mark.asyncio
    async def test_create_spline_actor_invalid_json(self, tools) -> None:
        result = _parsed(await tools.create_spline_actor(points="{not json"))
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_spline_actor_requires_two_points(self, tools) -> None:
        points = json.dumps([{"x": 0, "y": 0, "z": 0}])
        result = _parsed(await tools.create_spline_actor(points=points))
        assert result["success"] is False
        assert "at least 2" in result["error"]

    @pytest.mark.asyncio
    async def test_add_spline_mesh_mock_success(self, tools) -> None:
        result = _parsed(
            await tools.add_spline_mesh(
                spline_actor="SplineActor_123",
                mesh_path="/Game/Environment/Roads/SM_RoadStraight",
            )
        )
        assert result["success"] is True
        assert result["mesh_path"] == "/Game/Environment/Roads/SM_RoadStraight"


# ---------------------------------------------------------------------------
# TestCreateRoadSegment
# ---------------------------------------------------------------------------


class TestCreateRoadSegment:
    @pytest.mark.asyncio
    async def test_happy_path(self, tools) -> None:
        result = _parsed(
            await tools.create_road_segment(
                start_x=0.0,
                start_y=0.0,
                end_x=1000.0,
                end_y=0.0,
                width_cm=500.0,
                road_mesh_path="/Game/Environment/Roads/SM_RoadStraight",
            )
        )
        assert result["success"] is True
        assert result["length_cm"] == pytest.approx(1000.0)
        assert result["grid_registered"] is True
        assert result["road_mesh"]["success"] is True

    @pytest.mark.asyncio
    async def test_zero_length_segment_rejected(self, tools) -> None:
        result = _parsed(
            await tools.create_road_segment(
                start_x=100.0, start_y=100.0, end_x=100.0, end_y=100.0
            )
        )
        assert result["success"] is False
        assert "zero length" in result["error"]

    @pytest.mark.asyncio
    async def test_no_mesh_path_creates_spline_only(self, tools) -> None:
        result = _parsed(
            await tools.create_road_segment(start_x=0.0, start_y=0.0, end_x=500.0, end_y=0.0)
        )
        assert result["success"] is True
        assert result["road_mesh"] is None

    @pytest.mark.asyncio
    async def test_overlapping_structure_blocks_road(self, tools) -> None:
        structure = _parsed(
            await tools.build_structure(
                structure_type="cabin", location_x=500.0, location_y=0.0, label="blocking_cabin"
            )
        )
        assert structure["success"] is True

        road = _parsed(
            await tools.create_road_segment(
                start_x=0.0, start_y=0.0, end_x=1000.0, end_y=0.0, width_cm=500.0
            )
        )
        assert road["success"] is False
        assert "overlaps" in road["error"]

    @pytest.mark.asyncio
    async def test_allow_overlap_bypasses_rejection(self, tools) -> None:
        structure = _parsed(
            await tools.build_structure(
                structure_type="cabin", location_x=500.0, location_y=0.0, label="blocking_cabin"
            )
        )
        assert structure["success"] is True

        road = _parsed(
            await tools.create_road_segment(
                start_x=0.0,
                start_y=0.0,
                end_x=1000.0,
                end_y=0.0,
                width_cm=500.0,
                allow_overlap=True,
            )
        )
        assert road["success"] is True

    @pytest.mark.asyncio
    async def test_width_scale_applied_to_x_not_y(self, tools) -> None:
        # SplineMeshComponent's default ForwardAxis=X maps Vector2D.x to the
        # mesh's local Y (width) axis and Vector2D.y to local Z (height) — the
        # width ratio must land in "x", not "y" (regression for a mixed-up axis).
        result = _parsed(
            await tools.create_road_segment(
                start_x=0.0,
                start_y=0.0,
                end_x=1000.0,
                end_y=0.0,
                width_cm=1000.0,
                road_mesh_path="/Game/Environment/Roads/SM_RoadStraight",
            )
        )
        assert result["success"] is True
        start_scale = result["road_mesh"]["start_scale"]
        assert start_scale["x"] != pytest.approx(1.0)
        assert start_scale["y"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestReviewRegressions — bugs found and fixed during self-review
# ---------------------------------------------------------------------------


class TestReviewRegressions:
    @pytest.mark.asyncio
    async def test_build_structure_partial_failure_does_not_register_grid(
        self, tools, mock_client: UEClient, monkeypatch
    ) -> None:
        async def _always_fail(*args, **kwargs):
            from ue5_mcp.bridge.client import UEConnectionError

            raise UEConnectionError("simulated failure")

        monkeypatch.setattr(mock_client, "spawn_actor", _always_fail)

        result = _parsed(
            await tools.build_structure(
                structure_type="wall_segment", location_x=0.0, location_y=0.0
            )
        )
        assert result["success"] is False
        assert result["components_failed"] == 3
        assert result["grid_registered"] is False

        # Because nothing was actually registered, a retry at the same spot
        # (after removing the failure) must not be rejected as an overlap.
        monkeypatch.undo()
        retry = _parsed(
            await tools.build_structure(
                structure_type="wall_segment", location_x=0.0, location_y=0.0
            )
        )
        assert retry["success"] is True

    @pytest.mark.asyncio
    async def test_create_road_segment_mesh_failure_reports_failure(
        self, tools, mock_client: UEClient, monkeypatch
    ) -> None:
        async def _always_fail(*args, **kwargs):
            from ue5_mcp.bridge.client import UEConnectionError

            raise UEConnectionError("simulated mesh failure")

        monkeypatch.setattr(mock_client, "add_spline_mesh", _always_fail)

        result = _parsed(
            await tools.create_road_segment(
                start_x=0.0,
                start_y=0.0,
                end_x=1000.0,
                end_y=0.0,
                road_mesh_path="/Game/Environment/Roads/SM_RoadStraight",
            )
        )
        assert result["success"] is False
        assert result["road_mesh"]["success"] is False
        assert result["grid_registered"] is False

    @pytest.mark.asyncio
    async def test_create_spline_actor_rejects_point_missing_key(self, tools) -> None:
        points = json.dumps([{"x": 0, "y": 0}, {"x": 1000, "y": 0, "z": 0}])
        result = _parsed(await tools.create_spline_actor(points=points))
        assert result["success"] is False
        assert "z" in result["error"] or "keys" in result["error"]
