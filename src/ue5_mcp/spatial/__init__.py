"""Spatial validation layer — Layer 1.5 of the Unreal MCP platform.

Provides:
  • PlacementIntent / PlacementResult / SpatialConstraints schemas
  • OccupancyGrid — in-memory spatial hash with asyncio locking, OBB support,
    3-D Z-range tracking, label uniqueness, and world-bounds enforcement
  • SpawnValidator — orchestrates all pre-spawn checks and post-spawn grid marks
"""

from ue5_mcp.spatial.grid import OCCUPANCY_GRID, OccupancyGrid
from ue5_mcp.spatial.schema import PlacementIntent, PlacementResult, SpatialConstraints
from ue5_mcp.spatial.validator import SpawnValidator

__all__ = [
    "SpatialConstraints",
    "PlacementIntent",
    "PlacementResult",
    "OccupancyGrid",
    "OCCUPANCY_GRID",
    "SpawnValidator",
]
