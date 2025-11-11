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
    mcp_host: str = Field("0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(3000, alias="MCP_PORT")
    snapshot: str = Field("default")
    rrf_k: int = Field(60, alias="RRF_K")
    peek_max_docs: int = Field(100, alias="PEEK_MAX_DOCS")
    peek_budget_bytes: int = Field(12_288, alias="PEEK_BUDGET_BYTES")
    data_ttl_hours: int = Field(12)
    snippet_ttl_hours: int = Field(24)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO")
    mcp_api_token: str | None = Field(default=None, alias="MCP_API_TOKEN")
    patentfield_url: str = Field("http://localhost:8080", alias="PATENTFIELD_URL")
    patentfield_search_path: str = Field("/search", alias="PATENTFIELD_SEARCH_PATH")
    patentfield_snippets_path: str = Field("/snippets", alias="PATENTFIELD_SNIPPETS_PATH")
    patentfield_api_key: str | None = Field(default=None, alias="PATENTFIELD_API_KEY")
    wwrag_url: str = Field("http://localhost:8090", alias="WWRAG_URL")
    wwrag_search_path: str = Field("/search", alias="WWRAG_SEARCH_PATH")
    wwrag_api_key: str | None = Field(default=None, alias="WWRAG_API_KEY")
    wwrag_snippets_path: str = Field("/snippets", alias="WWRAG_SNIPPETS_PATH")
    ci_db_stub_url: str = Field("http://rrfusion-db-stub:8080", alias="CI_DB_STUB_URL")
    ci_search_path: str = Field("/search", alias="CI_SEARCH_PATH")
    ci_snippets_path: str = Field("/snippets", alias="CI_SNIPPETS_PATH")

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(
            Path(__file__).resolve().parent.parent / "infra" / ".env",
            Path.cwd() / "infra" / ".env",
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
