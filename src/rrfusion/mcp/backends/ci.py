"""CI stub backend that mirrors the production lane contract."""

from __future__ import annotations

from ...config import Settings
from .base import HttpLaneBackend


class CIBackend(HttpLaneBackend):
    """Lane backend pointing at the CI stub database."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            settings,
            base_url=settings.ci_db_stub_url,
            search_path=settings.ci_search_path,
            snippets_path=settings.ci_snippets_path,
        )
