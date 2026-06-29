"""Append-only audit log for the UE5 MCP server.

Every tool call that modifies editor state is recorded here so that:
  • Changes can be reviewed, replayed, or rolled back manually.
  • The AI can inspect recent history to avoid duplicate work.
  • Operators have a paper trail for automated sessions.

Log format: one JSON object per line (JSONL), written atomically to
  ~/.ue5-mcp/audit.jsonl  (override with UE_AUDIT_LOG_PATH).

Each record contains:
  {
    "ts":       "2024-01-01T12:00:00.123Z",   # ISO-8601 UTC
    "tool":     "spawn_actor",                  # MCP tool name
    "params":   {"asset_path": "...", ...},     # Input parameters (sanitised)
    "outcome":  "ok" | "error" | "dry_run",
    "summary":  "Spawned BP_Enemy at (500, 0, 0)",
    "mock":     false
  }
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_write_lock = asyncio.Lock()


async def record(
    settings: Any,
    tool: str,
    params: dict[str, Any],
    result: dict[str, Any] | str,
    *,
    outcome: str = "ok",
) -> None:
    """Append one audit record to the log file.

    This is a best-effort write — failures are silently swallowed so that an
    audit-log error never breaks a tool call.  The lock prevents interleaved
    writes when multiple tool calls run concurrently.

    Args:
        settings:  The active Settings instance (provides path + enabled flag).
        tool:      MCP tool name (e.g. "spawn_actor").
        params:    Dict of input parameters passed to the tool.
        result:    Tool return value or error message.
        outcome:   "ok", "error", or "dry_run".
    """
    if not settings.ue_audit_enabled:
        return

    log_path: Path = settings.resolved_audit_log_path

    # Build a human-readable summary from the result.
    if isinstance(result, dict):
        summary = result.get("summary") or _auto_summary(tool, result)
        is_mock = bool(result.get("mock"))
    else:
        summary = str(result)[:200]
        is_mock = False

    record_obj: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "params": _sanitise(params),
        "outcome": outcome,
        "summary": summary,
        "mock": is_mock,
    }

    try:
        async with _write_lock:
            await asyncio.get_event_loop().run_in_executor(
                None, _sync_append, log_path, record_obj
            )
    except Exception:
        pass  # Audit log failure must never break a tool call.


def _sync_append(log_path: Path, record_obj: dict[str, Any]) -> None:
    """Synchronous file append — called from a thread pool."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record_obj, default=str) + "\n")


def _sanitise(params: dict[str, Any]) -> dict[str, Any]:
    """Remove or truncate values that shouldn't be in the audit log."""
    clean: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, str) and len(v) > 500:
            clean[k] = v[:500] + "…"
        else:
            clean[k] = v
    return clean


def _auto_summary(tool: str, result: dict[str, Any]) -> str:
    """Generate a human-readable summary line from common result shapes."""
    if not result.get("success", True) and result.get("error"):
        return f"ERROR: {result['error']}"

    # Tool-specific summaries for common shapes.
    if tool == "spawn_actor":
        name = result.get("spawned_actor", "?")
        loc = result.get("transform", {}).get("location", {})
        return f"Spawned {name} at ({loc.get('x', 0)}, {loc.get('y', 0)}, {loc.get('z', 0)})"
    if tool == "move_actor":
        return f"Moved {result.get('actor', '?')}"
    if tool == "delete_actor":
        dr = " (dry_run)" if result.get("dry_run") else ""
        return f"Deleted {result.get('actor', '?')}{dr}"
    if tool == "spawn_foliage":
        return f"Placed {result.get('instances_placed', '?')} {result.get('mesh', '')} instances"
    if tool == "clear_foliage":
        return f"Cleared {result.get('instances_removed', '?')} foliage instances"
    if tool == "create_blueprint":
        name = result.get("blueprint_name", "?")
        path = result.get("save_path", "?")
        return f"Created Blueprint {name} at {path}"
    if tool == "compile_blueprint":
        errors = result.get("error_count", 0)
        status = "OK" if errors == 0 else f"{errors} error(s)"
        return f"Compiled {result.get('blueprint_path', '?')}: {status}"
    if tool == "run_automation_test":
        return f"Test {result.get('test_name', '?')}: {result.get('status', '?')}"
    if tool == "start_pie":
        return "Started PIE session"
    if tool == "stop_pie":
        return "Stopped PIE session"
    if tool == "send_console_command":
        return f"Console: {result.get('command', '?')}"
    if tool == "open_level":
        return f"Opened level {result.get('level_path', '?')}"
    if tool == "save_current_level":
        lvl = result.get("level", "?")
        return f"Saved level {lvl}"

    # Generic fallback.
    if result.get("applied"):
        return f"Applied {result['applied']}"
    return f"{tool} → {result.get('success', '?')}"


async def read_recent(settings: Any, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent audit log entries (tail of the file).

    Used by the AI to review what was done in the current session.

    Args:
        settings: Active Settings instance.
        limit:    Maximum number of entries to return (newest first).

    Returns:
        List of audit record dicts, newest first.
    """
    log_path: Path = settings.resolved_audit_log_path
    if not log_path.exists():
        return []

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(records) >= limit:
                break
        return records
    except OSError:
        return []
