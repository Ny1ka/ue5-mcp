"""Central configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection and runtime settings for the MCP server and UE bridge."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ue_host: str = "127.0.0.1"
    ue_http_port: int = 30010
    ue_ws_port: int = 30020
    ue_request_timeout_ms: int = 5000
    ue_project_path: str | None = None
    ue_mock_mode: bool = False

    @property
    def ue_http_base_url(self) -> str:
        return f"http://{self.ue_host}:{self.ue_http_port}"


def get_settings() -> Settings:
    return Settings()
