"""WWRag lane adapter powered by the HTTP helper."""

from __future__ import annotations

from ...config import Settings
from ...models import DBSearchResponse, GetSnippetsRequest, SearchRequest
from .base import HttpLaneBackend


class WWRagBackend(HttpLaneBackend):
    """Call the internal WWRag vector search endpoint."""

    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] | None = None
        if settings.wwrag_api_key:
            headers = {"Authorization": f"Bearer {settings.wwrag_api_key}"}
        super().__init__(
            settings,
            base_url=settings.wwrag_url,
            search_path=settings.wwrag_search_path,
            snippets_path=settings.wwrag_snippets_path,
            headers=headers,
        )

    def _build_search_payload(self, request: SearchRequest, lane: str) -> dict[str, object]:
        """Build WWRag-specific search body."""
        return request.model_dump()

    def _parse_search_response(self, payload: dict[str, object]) -> DBSearchResponse:
        """Map the WWRag response to MCP’s schema."""
        return DBSearchResponse.model_validate(payload)

    def _build_snippets_payload(
        self, request: GetSnippetsRequest, lane: str | None
    ) -> dict[str, object]:
        """Build the snippet request body expected by WWRag."""
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
