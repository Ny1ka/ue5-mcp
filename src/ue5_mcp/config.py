"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection and runtime settings for the MCP server and UE bridge."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Unreal Engine connection
    ue_host: str = "127.0.0.1"
    ue_http_port: int = 30010
    ue_ws_port: int = 30020
    ue_request_timeout_ms: int = 5000
    ue_project_path: str | None = None
    ue_mock_mode: bool = False

    # Layer 6 · Safety settings
    # Set UE_READ_ONLY=true to disable all write/destructive tools server-wide.
    ue_read_only: bool = False

    # Set UE_SCOPE_PATH to restrict all tool operations to a /Game/... prefix.
    # e.g. UE_SCOPE_PATH=/Game/Sandbox  — prevents editing assets outside Sandbox.
    ue_scope_path: str = ""

    # Audit log — written to ~/.ue5-mcp/audit.jsonl when enabled.
    ue_audit_enabled: bool = True
    ue_audit_log_path: str = ""

    @property
    def ue_http_base_url(self) -> str:
        return f"http://{self.ue_host}:{self.ue_http_port}"

    @property
    def resolved_audit_log_path(self) -> Path:
        """Return the absolute path to the audit log file."""
        if self.ue_audit_log_path:
            return Path(self.ue_audit_log_path)
        return Path(os.path.expanduser("~/.ue5-mcp/audit.jsonl"))


def get_settings() -> Settings:
    return Settings()
