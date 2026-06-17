"""Bridge layer between MCP tools and Unreal Engine."""

from ue5_mcp.bridge.asset_registry import ASSET_CATEGORIES, classify_by_class, classify_by_path
from ue5_mcp.bridge.asset_scanner import AssetEntry, ScanResult, scan_content_directory
from ue5_mcp.bridge.client import UEClient, UEConnectionError

__all__ = [
    "UEClient",
    "UEConnectionError",
    "ASSET_CATEGORIES",
    "classify_by_class",
    "classify_by_path",
    "AssetEntry",
    "ScanResult",
    "scan_content_directory",
]
