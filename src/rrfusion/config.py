"""Configuration helpers shared across services."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings."""

    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    db_stub_url: str = Field("http://localhost:8080", alias="DB_STUB_URL")
    mcp_host: str = Field("0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(3000, alias="MCP_PORT")
    snapshot: str = Field("default")
    rrf_k: int = Field(60, alias="RRF_K")
    peek_max_docs: int = Field(100, alias="PEEK_MAX_DOCS")
    peek_budget_bytes: int = Field(12_288, alias="PEEK_BUDGET_BYTES")
    data_ttl_hours: int = Field(24)
    snippet_ttl_hours: int = Field(72)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO")

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(
            Path(__file__).resolve().parent.parent / ".env",
            Path.cwd() / ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()  # type: ignore[call-arg]


__all__ = ["Settings", "get_settings"]
