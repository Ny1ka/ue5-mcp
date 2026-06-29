"""Tests for the ue5-mcp server, bridge, and tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ue5_mcp.bridge.asset_registry import (
    ASSET_CATEGORIES,
    classify_by_class,
    classify_by_path,
)
from ue5_mcp.bridge.asset_scanner import (
    find_content_directory,
    scan_content_directory,
    scan_result_to_dict,
)
from ue5_mcp.bridge.client import UEClient
from ue5_mcp.config import Settings
from starlette.testclient import TestClient

from ue5_mcp.server import create_app
from ue5_mcp.tools.assets import _build_mock_result, _discover_assets
from ue5_mcp.ui.server import app as ui_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> UEClient:
    return UEClient(Settings(ue_mock_mode=True))


@pytest.fixture
def mock_client_with_path(tmp_path: Path) -> UEClient:
    """Mock client that also has a project path pointing to a temp directory."""
    content = tmp_path / "Content"
    content.mkdir()
    return UEClient(Settings(ue_mock_mode=True, ue_project_path=str(tmp_path)))


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Minimal fake UE project structure for filesystem scanner tests."""
    content = tmp_path / "Content"
    (content / "Maps").mkdir(parents=True)
    (content / "Blueprints" / "Characters").mkdir(parents=True)
    (content / "Blueprints" / "Weapons").mkdir(parents=True)
    (content / "Materials").mkdir(parents=True)
    (content / "Textures").mkdir(parents=True)
    (content / "Meshes").mkdir(parents=True)
    (content / "Effects").mkdir(parents=True)
    (content / "Audio" / "SFX").mkdir(parents=True)

    # Maps
    (content / "Maps" / "MainMenu.umap").touch()
    (content / "Maps" / "L_Forest.umap").touch()

    # Blueprints
    (content / "Blueprints" / "Characters" / "BP_Hero.uasset").touch()
    (content / "Blueprints" / "Weapons" / "BP_Rifle.uasset").touch()
    (content / "Blueprints" / "Weapons" / "ABP_Rifle.uasset").touch()

    # Materials
    (content / "Materials" / "M_Rock.uasset").touch()
    (content / "Materials" / "MI_Rock_Wet.uasset").touch()

    # Textures
    (content / "Textures" / "T_Rock_D.uasset").touch()

    # Static meshes
    (content / "Meshes" / "SM_Rock_01.uasset").touch()

    # Niagara
    (content / "Effects" / "NS_Smoke.uasset").touch()

    # Sounds
    (content / "Audio" / "SFX" / "SW_Shot.uasset").touch()
    (content / "Audio" / "SFX" / "SC_Weapon.uasset").touch()

    # Write a dummy .uproject
    (tmp_path / "FakeGame.uproject").write_text('{"FileVersion": 3}')

    return tmp_path


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_mock_mode(mock_client: UEClient) -> None:
    result = await mock_client.ping()
    assert result["connected"] is True
    assert result["mock"] is True


def test_create_app_registers_primitives() -> None:
    app = create_app()
    assert app.name == "ue5-mcp"


def test_ui_dashboard_endpoints() -> None:
    client = TestClient(ui_app)

    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["server"] == "ue5-mcp"
    assert "project" in payload
    assert "mode" in payload
    assert "config" in payload

    tools = client.get("/api/tools")
    assert tools.status_code == 200
    tool_payload = tools.json()
    assert tool_payload["total"] >= 4
    assert all("name" in t and "description" in t for t in tool_payload["tools"])

    page = client.get("/")
    assert page.status_code == 200
    assert "UE5" in page.text


def test_format_json(mock_client: UEClient) -> None:
    payload = mock_client.format_json({"ok": True})
    assert json.loads(payload) == {"ok": True}


# ---------------------------------------------------------------------------
# Asset registry — classification engine
# ---------------------------------------------------------------------------


class TestAssetRegistry:
    def test_all_categories_have_keys(self) -> None:
        for key, cat in ASSET_CATEGORIES.items():
            assert cat.key == key, f"Category key mismatch: {key} vs {cat.key}"

    def test_classify_by_known_class(self) -> None:
        assert classify_by_class("StaticMesh") == "static_meshes"
        assert classify_by_class("Blueprint") == "blueprints"
        assert classify_by_class("AnimBlueprint") == "anim_blueprints"
        assert classify_by_class("NiagaraSystem") == "niagara_systems"
        assert classify_by_class("World") == "maps"
        assert classify_by_class("WidgetBlueprint") == "widget_blueprints"

    def test_classify_unknown_class_returns_none(self) -> None:
        assert classify_by_class("NonExistentClass") is None

    def test_classify_by_prefix_static_mesh(self) -> None:
        assert classify_by_path("SM_Rock", [], ".uasset") == "static_meshes"

    def test_classify_by_prefix_blueprint(self) -> None:
        assert classify_by_path("BP_Hero", [], ".uasset") == "blueprints"

    def test_classify_by_prefix_material_instance(self) -> None:
        # MI_ must win over M_ (longer prefix)
        assert classify_by_path("MI_Rock_Wet", [], ".uasset") == "material_instances"

    def test_classify_umap_extension(self) -> None:
        assert classify_by_path("MainMenu", [], ".umap") == "maps"

    def test_classify_by_folder_hint(self) -> None:
        # No prefix → falls back to folder hint
        result = classify_by_path("MyTexture", ["Textures"], ".uasset")
        assert result == "textures"

    def test_classify_fallback_uncategorized(self) -> None:
        result = classify_by_path("SomethingRandom", [], ".uasset")
        assert result == "uncategorized"

    def test_no_duplicate_class_names_across_categories(self) -> None:
        seen: dict[str, str] = {}
        for cat in ASSET_CATEGORIES.values():
            for cls in cat.ue_class_names:
                assert cls not in seen, (
                    f"Class '{cls}' registered in both '{seen[cls]}' and '{cat.key}'"
                )
                seen[cls] = cat.key


# ---------------------------------------------------------------------------
# Asset scanner — filesystem
# ---------------------------------------------------------------------------


class TestAssetScanner:
    def test_find_content_directory_from_uproject(self, fake_project: Path) -> None:
        uproject = fake_project / "FakeGame.uproject"
        result = find_content_directory(str(uproject))
        assert result == fake_project / "Content"

    def test_find_content_directory_from_root(self, fake_project: Path) -> None:
        result = find_content_directory(str(fake_project))
        assert result == fake_project / "Content"

    def test_find_content_directory_not_found(self, tmp_path: Path) -> None:
        result = find_content_directory(str(tmp_path / "nonexistent"))
        assert result is None

    def test_scan_returns_expected_categories(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project))
        assert result.total > 0
        assert "maps" in result.categories
        assert "blueprints" in result.categories
        assert "materials" in result.categories
        assert "material_instances" in result.categories
        assert "textures" in result.categories
        assert "static_meshes" in result.categories

    def test_scan_maps_count(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project))
        assert len(result.categories["maps"]) == 2

    def test_scan_blueprints_and_abp_split(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project))
        bp_names = [a.name for a in result.categories["blueprints"]]
        abp_names = [a.name for a in result.categories.get("anim_blueprints", [])]
        assert "BP_Hero" in bp_names
        assert "BP_Rifle" in bp_names
        assert "ABP_Rifle" in abp_names

    def test_scan_project_name_derived(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project))
        assert result.project_name == "FakeGame"

    def test_scan_result_to_dict_structure(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project))
        d = scan_result_to_dict(result)
        assert "categories" in d
        assert "total_assets" in d
        assert "discovery_method" in d
        assert d["discovery_method"] == "filesystem"
        for _key, cat in d["categories"].items():
            assert "display_name" in cat
            assert "count" in cat
            assert "assets" in cat
            assert cat["count"] == len(cat["assets"])

    def test_scan_nonrecursive(self, fake_project: Path) -> None:
        result = scan_content_directory(str(fake_project), recursive=False)
        # Non-recursive at content root: no sub-directory assets
        assert result.total == 0

    def test_scan_raises_for_missing_content(self) -> None:
        with pytest.raises(FileNotFoundError):
            scan_content_directory("/nonexistent/path/that/does/not/exist")


# ---------------------------------------------------------------------------
# Tool orchestration — mock mode
# ---------------------------------------------------------------------------


class TestListProjectAssetsTool:
    @pytest.mark.asyncio
    async def test_mock_result_structure(self, mock_client: UEClient) -> None:
        result = await _discover_assets(
            mock_client, directory="/Game", recursive=True, include_sizes=True
        )
        assert result["discovery_method"] == "mock"
        assert result["total_assets"] > 0
        assert "categories" in result
        assert "blueprints" in result["categories"]
        assert "maps" in result["categories"]

    @pytest.mark.asyncio
    async def test_mock_categories_have_required_fields(self, mock_client: UEClient) -> None:
        result = await _discover_assets(
            mock_client, directory="/Game", recursive=True, include_sizes=False
        )
        for key, cat in result["categories"].items():
            assert "display_name" in cat, f"Missing display_name in {key}"
            assert "count" in cat, f"Missing count in {key}"
            assert "assets" in cat, f"Missing assets in {key}"

    @pytest.mark.asyncio
    async def test_filesystem_fallback_with_project_path(self, fake_project: Path) -> None:
        client = UEClient(
            Settings(ue_mock_mode=False, ue_project_path=str(fake_project))
        )
        result = await _discover_assets(
            client, directory="/Game", recursive=True, include_sizes=False
        )
        # Will fall back to filesystem since no live editor
        assert result["discovery_method"] in ("filesystem", "filesystem_error")

    @pytest.mark.asyncio
    async def test_filesystem_error_graceful(self) -> None:
        client = UEClient(
            Settings(ue_mock_mode=False, ue_project_path="/bad/path/to/nowhere")
        )
        result = await _discover_assets(
            client, directory="/Game", recursive=True, include_sizes=False
        )
        assert result["discovery_method"] == "filesystem_error"
        assert "error" in result

    def test_build_mock_result_completeness(self) -> None:
        result = _build_mock_result()
        assert result["total_assets"] > 0
        assert result["discovery_method"] == "mock"
        # All mock assets must point to known categories
        for key in result["categories"]:
            assert key in ASSET_CATEGORIES, f"Mock uses unknown category key: {key}"
