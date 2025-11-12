"""Base abstractions for lane-specific backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ...config import Settings
from ...models import (
    DBSearchResponse,
    FulltextParams,
    GetPublicationRequest,
    GetSnippetsRequest,
    SemanticParams,
)

SearchParams = FulltextParams | SemanticParams


class LaneBackend(ABC):
    """Interface that adapters implement to serve a lane’s search request."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    async def search(self, request: SearchParams, lane: str) -> DBSearchResponse:
        """Execute a lane search and return a DB-shaped response."""

    async def close(self) -> None:
        """Optional cleanup hook."""
        return None

    async def fetch_snippets(
        self,
        request: GetSnippetsRequest,
        lane: str | None = None,
    ) -> dict[str, dict[str, str]]:
        """Fetch snippet payloads for documents when peek needs text."""
        raise NotImplementedError


class HttpLaneBackend(LaneBackend):
    """Lane backend convenience base that sends HTTP requests."""

    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str,
        search_path: str = "/search",
        snippets_path: str = "/snippets",
        publications_path: str = "/publications",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(settings)
        self.http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers=headers,
        )
        self.search_path = search_path.rstrip("/")
        self.snippets_path = snippets_path.rstrip("/")
        self.publications_path = publications_path.rstrip("/")

    async def search(self, request: SearchParams, lane: str) -> DBSearchResponse:
        response = await self.http.post(
            f"{self.search_path}/{lane}", json=request.model_dump()
        )
        response.raise_for_status()
        return DBSearchResponse.model_validate(response.json())

    async def fetch_snippets(
        self,
        request: GetSnippetsRequest,
        lane: str | None = None,
    ) -> dict[str, dict[str, str]]:
        response = await self.http.post(self.snippets_path, json=request.model_dump())
        response.raise_for_status()
        return response.json()

    async def fetch_publication(
        self,
        request: GetPublicationRequest,
        lane: str | None = None,
    ) -> dict[str, dict[str, str]]:
        response = await self.http.post(
            self.publications_path, json=request.model_dump()
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self.http.aclose()
