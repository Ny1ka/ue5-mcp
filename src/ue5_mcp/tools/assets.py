"""Asset discovery tools — Layer 1 of the Unreal MCP platform.

list_project_assets
    Returns every asset in the current project, grouped by category.
    Drives all downstream tools (Blueprint generation, debugging, foliage
    placement, etc.) by giving the AI an accurate map of what exists so it
    never hallucinates missing or wrong asset paths.

Discovery strategy (tried in order, first success wins):
  1. Remote Control API  — live editor with EditorScriptingUtilities plugin.
                           Gives exact UE class names → perfect categorisation.
  2. Filesystem scan     — UE_PROJECT_PATH set in .env / environment.
                           Heuristic prefix + folder classification; no editor needed.
  3. Mock data           — UE_MOCK_MODE=true or both paths unavailable.
                           Returns representative stub assets for development.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge.asset_registry import (
    ASSET_CATEGORIES,
    MOCK_ASSETS,
    classify_by_class,
    classify_by_path,
)
from ue5_mcp.bridge.asset_scanner import (
    AssetEntry,
    ScanResult,
    scan_content_directory,
    scan_result_to_dict,
)
from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_asset_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all asset-related MCP tools on the server."""

    @mcp.tool()
    async def list_project_assets(
        directory: Annotated[
            str,
            "Virtual game path to scan (e.g. '/Game', '/Game/Weapons'). "
            "Default scans the entire project.",
        ] = "/Game",
        recursive: Annotated[
            bool,
            "Whether to descend into sub-folders. Default true.",
        ] = True,
        category_filter: Annotated[
            str,
            "Comma-separated list of category keys to include "
            "(e.g. 'blueprints,static_meshes,maps'). "
            "Omit or leave empty to return all categories.",
        ] = "",
        include_sizes: Annotated[
            bool,
            "Include file size in KB for each asset (filesystem mode only). "
            "Slightly slower on large projects.",
        ] = True,
    ) -> str:
        """Return all assets in the Unreal project, grouped by category.

        Categories include: Static Meshes, Skeletal Meshes, Materials,
        Material Instances, Textures, Blueprints, Maps, Niagara Systems,
        Sound Waves, Sound Cues, MetaSounds, Animations, Anim Blueprints,
        Widget Blueprints, Physics Assets, Data Tables, Data Assets,
        Level Sequences, Enhanced Input, and more.

        Use this as the first call before any asset placement, Blueprint
        generation, or debugging task so the AI knows exactly what exists
        in the project.
        """
        filters = {f.strip() for f in category_filter.split(",") if f.strip()}

        result = await _discover_assets(
            client,
            directory=directory,
            recursive=recursive,
            include_sizes=include_sizes,
        )

        payload = _build_response(result, filters)
        return client.format_json(payload)

    # ------------------------------------------------------------------
    # Bonus tool: list available category keys so the AI can use them as
    # filters without guessing.
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_asset_categories() -> str:
        """Return all supported asset category keys and their display names.

        Use the 'key' values as the category_filter argument to
        list_project_assets to narrow results.
        """
        categories = [
            {
                "key": cat.key,
                "display_name": cat.display_name,
                "ue_classes": sorted(cat.ue_class_names),
                "name_prefixes": list(cat.name_prefixes),
            }
            for cat in sorted(ASSET_CATEGORIES.values(), key=lambda c: c.sort_order)
        ]
        return client.format_json({"categories": categories, "total": len(categories)})


# ---------------------------------------------------------------------------
# Discovery orchestration
# ---------------------------------------------------------------------------


async def _discover_assets(
    client: UEClient,
    *,
    directory: str,
    recursive: bool,
    include_sizes: bool,
) -> dict:
    """Run the three-tier discovery chain and return a serialisable dict."""

    # ── Tier 1: Remote Control API (live editor) ──────────────────────────
    if not client.is_mock:
        try:
            remote_result = await client.list_assets_remote(
                directory, recursive=recursive
            )
            if remote_result.get("asset_data"):
                return _build_from_remote(remote_result, client)
        except UEConnectionError:
            pass  # Fall through to filesystem / mock

    # ── Tier 2: Filesystem scan ───────────────────────────────────────────
    project_path = client.settings.ue_project_path
    if project_path:
        try:
            scan = scan_content_directory(
                project_path,
                directory_filter=directory,
                recursive=recursive,
                include_sizes=include_sizes,
            )
            return scan_result_to_dict(scan)
        except FileNotFoundError as exc:
            # Return a graceful error payload instead of crashing the tool.
            return {
                "error": str(exc),
                "hint": "Set UE_PROJECT_PATH=/path/to/MyGame in .env to enable filesystem scanning.",
                "discovery_method": "filesystem_error",
                "total_assets": 0,
                "categories": {},
            }

    # ── Tier 3: Mock data ─────────────────────────────────────────────────
    return _build_mock_result()


def _build_from_remote(remote_result: dict, client: UEClient) -> dict:
    """Convert Remote Control API asset data into the standard response shape."""
    from pathlib import PurePosixPath

    categories: dict[str, list[dict]] = {}

    for entry in remote_result.get("asset_data", []):
        path: str = entry.get("path", "")
        ue_class: str = entry.get("class", "")

        # Prefer exact class lookup; fall back to heuristic.
        if ue_class:
            cat_key = classify_by_class(ue_class) or _heuristic_from_path(path)
        else:
            cat_key = _heuristic_from_path(path)

        asset_name = PurePosixPath(path).name
        categories.setdefault(cat_key, []).append(
            {
                "name": asset_name,
                "game_path": path,
                **({"ue_class": ue_class} if ue_class else {}),
            }
        )

    # Sort by name within each category.
    ordered: dict[str, dict] = {}
    for key in sorted(
        categories,
        key=lambda k: ASSET_CATEGORIES[k].sort_order if k in ASSET_CATEGORIES else 999,
    ):
        assets = sorted(categories[key], key=lambda a: a["name"].lower())
        cat_meta = ASSET_CATEGORIES.get(key)
        ordered[key] = {
            "display_name": cat_meta.display_name if cat_meta else key.replace("_", " ").title(),
            "count": len(assets),
            "assets": assets,
        }

    total = sum(v["count"] for v in ordered.values())
    return {
        "discovery_method": "remote_control",
        "total_assets": total,
        "categories": ordered,
    }


def _heuristic_from_path(game_path: str) -> str:
    from pathlib import PurePosixPath

    p = PurePosixPath(game_path)
    ext = p.suffix.lower() or ".uasset"
    parts = list(p.parts[:-1])
    return classify_by_path(p.name, parts, ext)


def _build_mock_result() -> dict:
    """Assemble the rich mock dataset into the standard response shape."""
    categories: dict[str, dict] = {}

    for key, assets in MOCK_ASSETS.items():
        cat_meta = ASSET_CATEGORIES.get(key)
        categories[key] = {
            "display_name": cat_meta.display_name if cat_meta else key.replace("_", " ").title(),
            "count": len(assets),
            "assets": assets,
        }

    total = sum(v["count"] for v in categories.values())
    return {
        "project": "MockGame",
        "discovery_method": "mock",
        "note": (
            "Mock data — set UE_MOCK_MODE=false and provide "
            "UE_PROJECT_PATH or a running editor for real results."
        ),
        "total_assets": total,
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# Response post-processing
# ---------------------------------------------------------------------------


def _build_response(raw: dict, filters: set[str]) -> dict:
    """Add metadata and apply optional category filter to the raw discovery result."""
    out = {
        **raw,
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if filters:
        all_cats: dict = out.get("categories", {})
        filtered = {k: v for k, v in all_cats.items() if k in filters}
        out["categories"] = filtered
        out["total_assets"] = sum(v["count"] for v in filtered.values())
        out["filter_applied"] = sorted(filters)

    return out
