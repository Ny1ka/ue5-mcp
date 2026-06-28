"""Web UI server — chat interface + status dashboard for ue5-mcp."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ue5_mcp.bridge.client import UEClient, UEConnectionError
from ue5_mcp.config import get_settings
from ue5_mcp.server import create_app
from ue5_mcp.ui.chat import stream_chat
from ue5_mcp.ui.settings_store import load as load_ui_settings
from ue5_mcp.ui.settings_store import save as save_ui_settings

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_UI_PORT = 8765


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


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

    project_display = {
        "mock": project or "MockGame",
        "editor": project or "Live Editor",
        "filesystem": project or "Unknown project",
        "disconnected": project or "No project configured",
    }.get(mode, project or "—")

    return JSONResponse({
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
    })


async def api_tools(_request: Request) -> JSONResponse:
    mcp = create_app()
    tools = await mcp.list_tools()
    return JSONResponse({
        "tools": [
            {"name": t.name, "description": (t.description or "").strip()}
            for t in tools
        ],
        "total": len(tools),
    })


async def api_settings(request: Request) -> JSONResponse:
    if request.method == "GET":
        stored = load_ui_settings()
        display = dict(stored)
        raw_key: str = display.get("llm_api_key") or ""
        if raw_key:
            display["llm_api_key"] = raw_key[:8] + "•" * max(0, len(raw_key) - 8)
            display["has_api_key"] = True
        else:
            display["has_api_key"] = False
        return JSONResponse(display)

    data = await request.json()
    allowed = {"llm_provider", "llm_api_key", "llm_model", "llm_max_tokens"}
    updates = {k: v for k, v in data.items() if k in allowed}
    save_ui_settings(updates)
    return JSONResponse({"ok": True, "saved": sorted(updates.keys())})


async def api_chat(request: Request) -> StreamingResponse:
    data = await request.json()
    messages: list[dict] = data.get("messages", [])

    stored = load_ui_settings()
    api_key: str = stored.get("llm_api_key") or ""
    # Allow the client to override the model per-request (from the in-UI selector)
    model: str = data.get("model") or stored.get("llm_model") or "claude-opus-4-5"
    max_tokens: int = int(stored.get("llm_max_tokens") or 4096)

    mcp_app = create_app()

    async def generate():
        async for chunk in stream_chat(messages, api_key, model, max_tokens, mcp_app):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def index(_request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

routes = [
    Route("/", index),
    Route("/api/status", api_status),
    Route("/api/tools", api_tools),
    Route("/api/settings", api_settings, methods=["GET", "POST"]),
    Route("/api/chat", api_chat, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_UI_PORT, log_level="info")


if __name__ == "__main__":
    main()
