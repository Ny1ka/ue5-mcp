"""Persistent UI settings stored in ~/.ue5-mcp/ui-settings.json."""

from __future__ import annotations

import json
from pathlib import Path

_PATH = Path.home() / ".ue5-mcp" / "ui-settings.json"

_DEFAULTS: dict = {
    "llm_provider": "anthropic",
    "llm_api_key": "",
    "llm_model": "claude-opus-4-5",
    "llm_max_tokens": 4096,
}


def load() -> dict:
    if _PATH.exists():
        try:
            saved = json.loads(_PATH.read_text())
            return {**_DEFAULTS, **saved}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(updates: dict) -> dict:
    current = load()
    current.update({k: v for k, v in updates.items() if k in _DEFAULTS})
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(current, indent=2))
    return current
