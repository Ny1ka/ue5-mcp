"""In-memory spatial hash grid for actor occupancy tracking.

Design choices:
  • Module-level singleton (OCCUPANCY_GRID) persists across MCP tool calls
    within a server session.
  • Cell size is configurable (default 100 cm = 1 UE unit).
  • Each cell stores a list of OccupancyEntry values, so multiple thin/tall
    actors at the same XY position but different Z ranges can coexist
    (walkway under a bridge, basement under a building).
  • Sphere is the fast-path collision shape; OBB (oriented bounding box) is
    opt-in for architectural elements via use_obb=True in SpatialConstraints.
  • An asyncio.Lock gates all writes so concurrent spawn_actor_safe calls
    cannot both pass is_region_free before either has marked occupied.
  • Label uniqueness is enforced: mark_occupied raises ValueError on duplicate.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any

from ue5_mcp.spatial.schema import Vector3, WorldBounds


# ---------------------------------------------------------------------------
# OBB record (stored when use_obb=True)
# ---------------------------------------------------------------------------


@dataclass
class OBBRecord:
    """Oriented bounding box stored per entry."""

    center: Vector3
    half_x: float          # half-extent along local X (after scale)
    half_y: float          # half-extent along local Y
    half_z: float          # half-extent along local Z
    yaw_deg: float = 0.0   # rotation around world-up only


# ---------------------------------------------------------------------------
# Occupancy entry (one actor → one or more grid cells)
# ---------------------------------------------------------------------------


@dataclass
class OccupancyEntry:
    """One actor's footprint record stored inside a grid cell."""

    actor_label: str
    center: Vector3
    radius_cm: float                      # sphere fast-path
    obb: OBBRecord | None = None          # set when use_obb=True
    z_min: float = field(default=-math.inf)
    z_max: float = field(default=math.inf)


# ---------------------------------------------------------------------------
# SAT helper for OBB-vs-sphere and OBB-vs-OBB tests
# ---------------------------------------------------------------------------


def _obb_overlaps_sphere(obb: OBBRecord, center: Vector3, radius: float) -> bool:
    """AABB-vs-sphere test in OBB local space (ignores Z for speed)."""
    yaw_rad = math.radians(obb.yaw_deg)
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)

    dx = center.x - obb.center.x
    dy = center.y - obb.center.y

    # Rotate sphere centre into OBB local space
    local_x = cos_y * dx + sin_y * dy
    local_y = -sin_y * dx + cos_y * dy

    # Clamp to OBB extents
    clamped_x = max(-obb.half_x, min(obb.half_x, local_x))
    clamped_y = max(-obb.half_y, min(obb.half_y, local_y))

    dist_sq = (local_x - clamped_x) ** 2 + (local_y - clamped_y) ** 2
    return dist_sq <= radius ** 2


def _obbs_overlap(a: OBBRecord, b: OBBRecord) -> bool:
    """2-D SAT test (yaw only) between two OBBs."""
    # Project both boxes onto 4 axes: 2 from A, 2 from B
    def _project(obb: OBBRecord, axis_x: float, axis_y: float) -> tuple[float, float]:
        corners = [
            ( obb.half_x,  obb.half_y),
            (-obb.half_x,  obb.half_y),
            ( obb.half_x, -obb.half_y),
            (-obb.half_x, -obb.half_y),
        ]
        yaw_rad = math.radians(obb.yaw_deg)
        cos_o = math.cos(yaw_rad)
        sin_o = math.sin(yaw_rad)
        projs = []
        for (lx, ly) in corners:
            wx = obb.center.x + cos_o * lx - sin_o * ly
            wy = obb.center.y + sin_o * lx + cos_o * ly
            projs.append(wx * axis_x + wy * axis_y)
        return min(projs), max(projs)

    def _gap_on_axis(axis_x: float, axis_y: float) -> bool:
        lo_a, hi_a = _project(a, axis_x, axis_y)
        lo_b, hi_b = _project(b, axis_x, axis_y)
        return hi_a < lo_b or hi_b < lo_a

    for obb in (a, b):
        yaw_rad = math.radians(obb.yaw_deg)
        cos_o = math.cos(yaw_rad)
        sin_o = math.sin(yaw_rad)
        if _gap_on_axis(cos_o, sin_o):
            return False
        if _gap_on_axis(-sin_o, cos_o):
            return False
    return True


# ---------------------------------------------------------------------------
# OccupancyGrid
# ---------------------------------------------------------------------------


class OccupancyGrid:
    """Spatial hash grid that records all placed actors.

    Cells are identified by integer (xi, yi) coordinates derived by dividing
    world X/Y by cell_size_cm.  Each cell holds a list of OccupancyEntry
    objects (multiple actors can share a cell; overlap is checked by
    sphere/OBB geometry, not cell membership alone).
    """

    def __init__(self, cell_size_cm: float = 100.0) -> None:
        if cell_size_cm <= 0:
            raise ValueError("cell_size_cm must be > 0")
        self._cell_size = cell_size_cm
        self._lock = asyncio.Lock()

        # (xi, yi) → list of OccupancyEntry
        self._cells: dict[tuple[int, int], list[OccupancyEntry]] = {}

        # label → list of cell coords it touches (for fast removal)
        self._label_index: dict[str, list[tuple[int, int]]] = {}

    # ------------------------------------------------------------------
    # Cell coordinate helpers
    # ------------------------------------------------------------------

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return int(math.floor(x / self._cell_size)), int(math.floor(y / self._cell_size))

    def _cells_for_radius(
        self, center: Vector3, radius_cm: float
    ) -> list[tuple[int, int]]:
        """Return all grid cells that a circle (center, radius) touches."""
        r = radius_cm
        x0, y0 = center.x - r, center.y - r
        x1, y1 = center.x + r, center.y + r
        xi_min, yi_min = self._cell(x0, y0)
        xi_max, yi_max = self._cell(x1, y1)
        return [
            (xi, yi)
            for xi in range(xi_min, xi_max + 1)
            for yi in range(yi_min, yi_max + 1)
        ]

    def _cells_for_obb(self, obb: OBBRecord) -> list[tuple[int, int]]:
        """Return all cells that an OBB's AABB (rotated) touches."""
        diag = math.hypot(obb.half_x, obb.half_y)
        return self._cells_for_radius(obb.center, diag)

    # ------------------------------------------------------------------
    # Z-range overlap
    # ------------------------------------------------------------------

    @staticmethod
    def _z_ranges_overlap(
        a_min: float, a_max: float, b_min: float, b_max: float
    ) -> bool:
        return a_min < b_max and b_min < a_max

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def mark_occupied(
        self,
        label: str,
        center: Vector3,
        extent: Vector3,
        yaw_deg: float = 0.0,
        z_min: float | None = None,
        z_max: float | None = None,
        use_obb: bool = False,
    ) -> list[tuple[int, int]]:
        """Record an actor as occupying space in the grid.

        Args:
            label:    Unique actor label.  Raises ValueError if already present.
            center:   World centre of the actor (post-spawn location).
            extent:   Half-extents of the mesh bounding box (already × scale).
            yaw_deg:  Actor yaw — used for OBB orientation.
            z_min/max: World-space Z range.  If None, defaults to ±inf
                       (2-D-only behaviour for callers that don't supply Z).
            use_obb:  Store an OBB instead of sphere for overlap tests.

        Returns:
            List of (xi, yi) cells marked.
        """
        if label in self._label_index:
            raise ValueError(
                f"Label '{label}' already exists in the occupancy grid. "
                "Call mark_free(label) first or use a unique label."
            )

        eff_z_min = z_min if z_min is not None else -math.inf
        eff_z_max = z_max if z_max is not None else math.inf

        # Sphere radius = largest XY extent component
        radius_cm = max(extent.x, extent.y)

        obb: OBBRecord | None = None
        if use_obb:
            obb = OBBRecord(
                center=center,
                half_x=extent.x,
                half_y=extent.y,
                half_z=extent.z,
                yaw_deg=yaw_deg,
            )

        entry = OccupancyEntry(
            actor_label=label,
            center=center,
            radius_cm=radius_cm,
            obb=obb,
            z_min=eff_z_min,
            z_max=eff_z_max,
        )

        if use_obb and obb is not None:
            cells = self._cells_for_obb(obb)
        else:
            cells = self._cells_for_radius(center, radius_cm)

        for cell in cells:
            self._cells.setdefault(cell, []).append(entry)

        self._label_index[label] = cells
        return cells

    def mark_free(self, label: str) -> bool:
        """Remove an actor from the grid by label.

        Returns True if found and removed, False if the label was not present.
        """
        cells = self._label_index.pop(label, None)
        if cells is None:
            return False

        for cell in cells:
            entries = self._cells.get(cell, [])
            self._cells[cell] = [e for e in entries if e.actor_label != label]
            if not self._cells[cell]:
                del self._cells[cell]
        return True

    # ------------------------------------------------------------------
    # Public read API (lock-free — safe for concurrent reads)
    # ------------------------------------------------------------------

    def is_region_free(
        self,
        center: Vector3,
        radius_cm: float,
        z_min: float | None = None,
        z_max: float | None = None,
    ) -> bool:
        """Return True if no recorded actor overlaps the sphere (center, radius).

        Optionally restricts the Z check: only entries whose Z-range
        overlaps [z_min, z_max] are considered.
        """
        eff_z_min = z_min if z_min is not None else -math.inf
        eff_z_max = z_max if z_max is not None else math.inf

        for cell in self._cells_for_radius(center, radius_cm):
            for entry in self._cells.get(cell, []):
                # Z-range gate
                if not self._z_ranges_overlap(
                    eff_z_min, eff_z_max, entry.z_min, entry.z_max
                ):
                    continue

                # Shape test
                if entry.obb is not None:
                    if _obb_overlaps_sphere(entry.obb, center, radius_cm):
                        return False
                else:
                    dx = entry.center.x - center.x
                    dy = entry.center.y - center.y
                    combined = entry.radius_cm + radius_cm
                    if dx * dx + dy * dy <= combined * combined:
                        return False
        return True

    def is_obb_free(
        self,
        center: Vector3,
        half_extents: Vector3,
        yaw_deg: float,
        z_min: float | None = None,
        z_max: float | None = None,
    ) -> bool:
        """Return True if the given OBB does not overlap any recorded entry."""
        candidate = OBBRecord(
            center=center,
            half_x=half_extents.x,
            half_y=half_extents.y,
            half_z=half_extents.z,
            yaw_deg=yaw_deg,
        )
        eff_z_min = z_min if z_min is not None else -math.inf
        eff_z_max = z_max if z_max is not None else math.inf

        for cell in self._cells_for_obb(candidate):
            for entry in self._cells.get(cell, []):
                if not self._z_ranges_overlap(
                    eff_z_min, eff_z_max, entry.z_min, entry.z_max
                ):
                    continue

                if entry.obb is not None:
                    if _obbs_overlap(candidate, entry.obb):
                        return False
                else:
                    if _obb_overlaps_sphere(candidate, entry.center, entry.radius_cm):
                        return False
        return True

    def find_nearest_free_position(
        self,
        center: Vector3,
        radius_cm: float,
        search_radius_cm: float = 1000.0,
        bounds: WorldBounds | None = None,
    ) -> Vector3 | None:
        """Search outward from center for the nearest unoccupied position.

        Samples candidate positions in expanding concentric rings.  Returns
        None if no free position is found within search_radius_cm.

        Respects world bounds if provided — will not return a position outside
        valid_x/y ranges.
        """
        step = max(radius_cm * 0.5, self._cell_size)
        rings = int(math.ceil(search_radius_cm / step))

        for ring in range(rings + 1):
            if ring == 0:
                candidates = [center]
            else:
                # Sample 8 × ring points on a ring of radius ring×step
                n_pts = max(8, ring * 8)
                r = ring * step
                candidates = [
                    Vector3(
                        x=center.x + r * math.cos(2 * math.pi * i / n_pts),
                        y=center.y + r * math.sin(2 * math.pi * i / n_pts),
                        z=center.z,
                    )
                    for i in range(n_pts)
                ]

            for candidate in candidates:
                if bounds is not None and not bounds.contains_xy(candidate.x, candidate.y):
                    continue
                if self.is_region_free(candidate, radius_cm):
                    return candidate

        return None

    def drift_check(
        self,
        actor_positions: dict[str, Vector3],
        tolerance_cm: float | None = None,
    ) -> list[str]:
        """Compare grid entries against live actor positions.

        Args:
            actor_positions: Mapping of actor_label → current world position
                             (obtained from UE via get_actor_bounds or list_actors).
            tolerance_cm:    Distance threshold; defaults to cell_size_cm.

        Returns:
            List of labels whose grid centre has drifted more than tolerance_cm
            from the provided live position.  Empty list means the grid is fresh.
        """
        tol = tolerance_cm if tolerance_cm is not None else self._cell_size
        stale: list[str] = []

        for label, live_pos in actor_positions.items():
            cells = self._label_index.get(label)
            if cells is None:
                stale.append(label)
                continue

            # Find the entry in the first cell
            entry: OccupancyEntry | None = None
            for cell in cells:
                for e in self._cells.get(cell, []):
                    if e.actor_label == label:
                        entry = e
                        break
                if entry is not None:
                    break

            if entry is None:
                stale.append(label)
                continue

            dx = entry.center.x - live_pos.x
            dy = entry.center.y - live_pos.y
            dz = entry.center.z - live_pos.z
            if math.sqrt(dx * dx + dy * dy + dz * dz) > tol:
                stale.append(label)

        return stale

    def sync_from_actor_list(
        self,
        actors: list[dict],
        default_extent_cm: float = 100.0,
    ) -> int:
        """Rebuild the grid from a list of actor dicts (from list_actors / UE).

        Clears the existing grid first.  Each actor dict should have at least:
          {"name": str, "location": {"x","y","z"}, "scale": {"x","y","z"}}
        Extent is estimated from default_extent_cm × scale unless an "extent"
        key is provided.

        Returns the number of actors registered.
        """
        self.clear()
        registered = 0
        for actor in actors:
            label = actor.get("name") or actor.get("label")
            if not label:
                continue

            loc = actor.get("location", {})
            scale = actor.get("scale", {"x": 1, "y": 1, "z": 1})
            center = Vector3(
                x=float(loc.get("x", 0)),
                y=float(loc.get("y", 0)),
                z=float(loc.get("z", 0)),
            )
            ext_raw = actor.get("extent")
            if ext_raw:
                extent = Vector3(
                    x=float(ext_raw.get("x", default_extent_cm)),
                    y=float(ext_raw.get("y", default_extent_cm)),
                    z=float(ext_raw.get("z", default_extent_cm)),
                )
            else:
                sx = float(scale.get("x", 1))
                sy = float(scale.get("y", 1))
                sz = float(scale.get("z", 1))
                extent = Vector3(
                    x=default_extent_cm * sx,
                    y=default_extent_cm * sy,
                    z=default_extent_cm * sz,
                )

            try:
                self.mark_occupied(label, center, extent)
                registered += 1
            except ValueError:
                # Duplicate label in actor list — skip
                pass

        return registered

    def get_occupied_cells(self) -> dict[tuple[int, int], list[dict]]:
        """Return a snapshot of the grid for debug visualisation."""
        return {
            cell: [
                {
                    "label": e.actor_label,
                    "center": e.center.to_dict(),
                    "radius_cm": e.radius_cm,
                    "z_min": None if e.z_min == -math.inf else e.z_min,
                    "z_max": None if e.z_max == math.inf else e.z_max,
                    "has_obb": e.obb is not None,
                }
                for e in entries
            ]
            for cell, entries in self._cells.items()
        }

    def get_label_index(self) -> dict[str, list[tuple[int, int]]]:
        """Return a copy of the label → cell mapping."""
        return dict(self._label_index)

    def clear(self) -> None:
        """Reset the grid — call when loading a new level."""
        self._cells.clear()
        self._label_index.clear()

    def to_debug_dict(self) -> dict[str, Any]:
        """JSON-serialisable grid snapshot for get_grid_status."""
        return {
            "cell_size_cm": self._cell_size,
            "total_cells_used": len(self._cells),
            "total_entries": sum(len(v) for v in self._cells.values()),
            "tracked_labels": len(self._label_index),
            "labels": sorted(self._label_index.keys()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton — shared by all tool modules
# ---------------------------------------------------------------------------

OCCUPANCY_GRID = OccupancyGrid()
