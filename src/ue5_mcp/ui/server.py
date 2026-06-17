"""Lightweight web dashboard for ue5-mcp."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ue5_mcp.bridge.client import UEClient, UEConnectionError
from ue5_mcp.config import get_settings
from ue5_mcp.server import create_app

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_UI_PORT = 8765


def _project_name(project_path: str | None) -> str | None:
    if not project_path:
        return None
    return Path(project_path).stem


def _resolve_mode(*, settings, connected: bool, is_mock_ping: bool) -> str:
    if settings.ue_mock_mode:
        return "mock"
    if connected and not is_mock_ping:
        return "editor"
    if settings.ue_project_path:
        return "filesystem"
    return "disconnected"


async def api_status(_request: Request) -> JSONResponse:
    settings = get_settings()
    client = UEClient(settings)
    project = _project_name(settings.ue_project_path)

    try:
        connection = await client.ping()
        connected = bool(connection.get("connected"))
        is_mock_ping = bool(connection.get("mock"))
    except UEConnectionError as exc:
        connection = {"connected": False, "mock": False, "error": str(exc)}
        connected = False
        is_mock_ping = False

    mode = _resolve_mode(settings=settings, connected=connected, is_mock_ping=is_mock_ping)

    if mode == "mock":
        project_display = project or "MockGame"
    elif mode == "editor":
        project_display = project or "Live Editor"
    elif mode == "filesystem":
        project_display = project or "Unknown project"
    else:
        project_display = project or "No project configured"

    return JSONResponse(
        {
            "server": "ue5-mcp",
            "connected": connected,
            "mode": mode,
            "project": project_display,
            "connection": connection,
            "config": {
                "host": settings.ue_host,
                "http_port": settings.ue_http_port,
                "ws_port": settings.ue_ws_port,
                "mock_mode": settings.ue_mock_mode,
                "project_path": settings.ue_project_path,
            },
        }
    )


async def api_tools(_request: Request) -> JSONResponse:
    mcp = create_app()
    tools = await mcp.list_tools()
    return JSONResponse(
        {
            "tools": [
                {
                    "name": tool.name,
                    "description": (tool.description or "").strip(),
                }
                for tool in tools
            ],
            "total": len(tools),
        }
    )


async def index(_request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


routes = [
    Route("/", index),
    Route("/api/status", api_status),
    Route("/api/tools", api_tools),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_UI_PORT, log_level="info")


if __name__ == "__main__":
    main()
