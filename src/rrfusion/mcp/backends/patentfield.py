"""Patentfield-specific lane adapter."""

from __future__ import annotations

from ...config import Settings
from ...models import DBSearchResponse, GetSnippetsRequest, SearchRequest
from .base import HttpLaneBackend


class PatentfieldBackend(HttpLaneBackend):
    """Call the Patentfield REST endpoint and return DBSearchResponse."""

    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] | None = None
        if settings.patentfield_api_key:
            headers = {"Authorization": f"Bearer {settings.patentfield_api_key}"}
        super().__init__(
            settings,
            base_url=settings.patentfield_url,
            search_path=settings.patentfield_search_path,
            snippets_path=settings.patentfield_snippets_path,
            headers=headers,
        )

    def _build_search_payload(self, request: SearchRequest, lane: str) -> dict[str, object]:
        """Translate MCP search request into Patentfield payload."""
        return request.model_dump()

    def _parse_search_response(self, payload: dict[str, object]) -> DBSearchResponse:
        """Convert Patentfield JSON into `DBSearchResponse`."""
        return DBSearchResponse.model_validate(payload)

    def _build_snippets_payload(
        self, request: GetSnippetsRequest, lane: str | None
    ) -> dict[str, object]:
        """Prepare snippet request body for Patentfield."""
        return request.model_dump()

    async def search(self, request: SearchRequest, lane: str) -> DBSearchResponse:
        payload = self._build_search_payload(request, lane)
        response = await self.http.post(f"{self.search_path}/{lane}", json=payload)
        response.raise_for_status()
        return self._parse_search_response(response.json())

    async def fetch_snippets(
        self, request: GetSnippetsRequest, lane: str | None = None
    ) -> dict[str, dict[str, str]]:
        payload = self._build_snippets_payload(request, lane)
        response = await self.http.post(self.snippets_path, json=payload)
        response.raise_for_status()
        return response.json()
