"""Filesystem-based Unreal Engine content directory scanner.

Walks a project's Content folder and classifies each .uasset / .umap file
using the asset_registry heuristics (folder hints + naming prefix).

This is the offline/fallback discovery path.  The live path (Remote Control
API) may enrich results with exact UE class names, but this scanner works
with no editor running.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ue5_mcp.bridge.asset_registry import (
    ASSET_CATEGORIES,
    classify_by_path,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AssetEntry:
    """A single discovered asset."""

    name: str
    game_path: str
    file_path: str
    category: str
    extension: str
    # Populated by the Remote Control enrichment pass if available.
    ue_class: str | None = None
    size_kb: int | None = None


@dataclass
class ScanResult:
    """Aggregated output of a content directory scan."""

    project_name: str
    content_root: str
    discovery_method: str
    categories: dict[str, list[AssetEntry]] = field(default_factory=dict)
    uncategorized: list[AssetEntry] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.categories.values()) + len(self.uncategorized)


# ---------------------------------------------------------------------------
# Content directory resolution helpers
# ---------------------------------------------------------------------------


def find_content_directory(project_path: str) -> Path | None:
    """Locate the Content directory from a .uproject path or project root.

    Accepts any of:
      - /path/to/MyGame/MyGame.uproject
      - /path/to/MyGame
      - /path/to/MyGame/Content
    """
    p = Path(project_path)

    if p.suffix == ".uproject":
        candidate = p.parent / "Content"
    elif p.name.lower() == "content" and p.is_dir():
        candidate = p
    else:
        candidate = p / "Content"

    return candidate if candidate.is_dir() else None


def _derive_project_name(project_path: str) -> str:
    p = Path(project_path)
    if p.suffix == ".uproject":
        return p.stem
    # Walk up looking for a .uproject file
    for parent in [p, p.parent, p.parent.parent]:
        matches = list(parent.glob("*.uproject"))
        if matches:
            return matches[0].stem
    return p.name


# ---------------------------------------------------------------------------
# Iterator over asset files
# ---------------------------------------------------------------------------


def _iter_asset_files(content_dir: Path) -> Iterator[Path]:
    """Yield all .uasset and .umap paths under content_dir."""
    for root, dirs, files in os.walk(content_dir):
        # Skip Developers folder (per-user temp content)
        dirs[:] = [d for d in dirs if d not in ("Developers", "__pycache__")]
        for fname in files:
            if fname.endswith((".uasset", ".umap")):
                yield Path(root) / fname


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------


def scan_content_directory(
    project_path: str,
    *,
    directory_filter: str = "/Game",
    recursive: bool = True,
    include_sizes: bool = True,
) -> ScanResult:
    """Scan a project's Content folder and return categorised assets.

    Args:
        project_path: Path to .uproject file or the project root.
        directory_filter: Virtual game path prefix to restrict scanning
                          (e.g. "/Game/Weapons"). Default scans everything.
        recursive: Whether to descend into sub-directories.
        include_sizes: Whether to stat each file for its size.

    Returns:
        ScanResult with assets grouped by category key.

    Raises:
        FileNotFoundError: When the Content directory cannot be located.
    """
    content_dir = find_content_directory(project_path)
    if content_dir is None:
        raise FileNotFoundError(
            f"Could not locate a Content directory at or under '{project_path}'. "
            "Check UE_PROJECT_PATH in your .env file."
        )

    project_name = _derive_project_name(project_path)

    # Resolve optional sub-directory filter.
    # "/Game/Weapons" → <content_dir>/Weapons
    sub_path: Path | None = None
    if directory_filter and directory_filter not in ("/Game", "/game"):
        relative = directory_filter.lstrip("/").removeprefix("Game").lstrip("/")
        if relative:
            sub_path = content_dir / relative
            if not sub_path.is_dir():
                sub_path = None  # filter path doesn't exist; scan everything

    scan_root = sub_path if sub_path else content_dir

    result = ScanResult(
        project_name=project_name,
        content_root=str(content_dir),
        discovery_method="filesystem",
    )

    file_iter: Iterator[Path]
    if recursive:
        file_iter = _iter_asset_files(scan_root)
    else:
        file_iter = (
            scan_root / f
            for f in os.listdir(scan_root)
            if f.endswith((".uasset", ".umap"))
        )

    for asset_path in file_iter:
        entry = _build_entry(asset_path, content_dir, include_sizes)
        if entry.category == "uncategorized":
            result.uncategorized.append(entry)
        else:
            result.categories.setdefault(entry.category, []).append(entry)

    # Sort assets within each category by name
    for assets in result.categories.values():
        assets.sort(key=lambda a: a.name.lower())
    result.uncategorized.sort(key=lambda a: a.name.lower())

    return result


def _build_entry(asset_path: Path, content_dir: Path, include_sizes: bool) -> AssetEntry:
    ext = asset_path.suffix.lower()
    name = asset_path.stem

    # Build path parts relative to content dir for folder-hint matching.
    try:
        relative = asset_path.relative_to(content_dir)
    except ValueError:
        relative = asset_path

    path_parts = list(relative.parts[:-1])  # exclude filename

    category = classify_by_path(name, path_parts, ext)

    # Build the /Game/... virtual path.
    game_rel = "/".join([*path_parts, name])
    game_path = f"/Game/{game_rel}"

    size_kb: int | None = None
    if include_sizes:
        try:
            size_kb = max(1, asset_path.stat().st_size // 1024)
        except OSError:
            pass

    return AssetEntry(
        name=name,
        game_path=game_path,
        file_path=str(asset_path),
        category=category,
        extension=ext,
        size_kb=size_kb,
    )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def scan_result_to_dict(result: ScanResult) -> dict:
    """Convert a ScanResult to a JSON-serialisable dict for MCP output."""
    categories_out: dict[str, dict] = {}

    # Sort categories by their sort_order, then key name for uncategorized
    ordered_keys = sorted(
        result.categories.keys(),
        key=lambda k: ASSET_CATEGORIES[k].sort_order if k in ASSET_CATEGORIES else 999,
    )

    for key in ordered_keys:
        assets = result.categories[key]
        cat_meta = ASSET_CATEGORIES.get(key)
        categories_out[key] = {
            "display_name": cat_meta.display_name if cat_meta else key.replace("_", " ").title(),
            "count": len(assets),
            "assets": [_entry_to_dict(a) for a in assets],
        }

    out: dict = {
        "project": result.project_name,
        "content_root": result.content_root,
        "discovery_method": result.discovery_method,
        "total_assets": result.total,
        "categories": categories_out,
    }

    if result.uncategorized:
        out["uncategorized"] = {
            "display_name": "Uncategorized",
            "count": len(result.uncategorized),
            "assets": [_entry_to_dict(a) for a in result.uncategorized],
        }

    return out


def _entry_to_dict(entry: AssetEntry) -> dict:
    d: dict = {
        "name": entry.name,
        "game_path": entry.game_path,
    }
    if entry.ue_class:
        d["ue_class"] = entry.ue_class
    if entry.size_kb is not None:
        d["size_kb"] = entry.size_kb
    return d
