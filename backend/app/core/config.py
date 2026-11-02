from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Portfolio IQ API"
    app_env: str = "local"
    api_prefix: str = "/api"
    storage_mode: str = "local"
    local_storage_root: Path = Path("./storage")
    max_upload_mb: int = Field(default=200, gt=0)
    max_cmdb_rows: int = Field(default=5_000, ge=5_000)
    openai_api_key: str | None = None
    openai_model: str | None = None
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
