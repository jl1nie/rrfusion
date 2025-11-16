"""Patentfield-specific lane adapter."""

from __future__ import annotations

import logging

import httpx

from ...config import Settings
from ...models import (
    Cond,
    DBSearchResponse,
    GetPublicationRequest,
    GetSnippetsRequest,
    Meta,
    SearchItem,
)
from .base import HttpLaneBackend, SearchParams

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


FIELD_COLUMN_MAP: dict[str, str] = {
    "title": "title",
    "abst": "abstract",
    "claim": "claims",
    "desc": "description",
    "app_doc_id": "app_doc_id",
    "pub_id": "pub_id",
    "exam_id": "exam_id",
}

FIELD_FILTER_MAP: dict[str, str] = {
    "ipc": "ipc",
    "cpc": "cpc",
    "fi": "fi",
    "ft": "ft",
    "pubyear": "pubyear",
    "assignee": "assignee",
    "country": "country",
}


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
            publications_path=settings.patentfield_publications_path,
            headers=headers,
        )

    def _resolve_columns(self, requested: list[str]) -> list[str]:
        columns = ["app_doc_id", "pub_id", "exam_id"]
        for field in requested:
            column = FIELD_COLUMN_MAP.get(field)
            if column and column not in columns:
                columns.append(column)
        return columns

    def _build_conditions(self, filters: list["Cond"] | None) -> list[dict[str, object]] | None:
        if not filters:
            return None
        conditions: list[dict[str, object]] = []
        for cond in filters:
            key = FIELD_FILTER_MAP.get(cond.field, cond.field)
            entry: dict[str, object] = {"key": key, "lop": cond.lop, "op": cond.op}
            if cond.op == "range" and isinstance(cond.value, (list, tuple)) and len(cond.value) == 2:
                entry["q1"] = cond.value[0]
                entry["q2"] = cond.value[1]
            else:
                entry["q"] = cond.value
            conditions.append(entry)
        return conditions

    def _build_search_payload(
        self, request: SearchParams, lane: str
    ) -> dict[str, object]:
        """Map MCP parameters to the Patentfield API."""
        query = getattr(request, "query", getattr(request, "text", ""))
        columns = self._resolve_columns(
            list(getattr(request, "fields", []))
        )
        payload = {
            "search_type": "semantic" if lane == "semantic" else "fulltext",
            "q": query,
            "limit": request.top_k,
            "columns": columns,
            "feature": "word_weights",
        }
        if request.filters:
            conditions = self._build_conditions(request.filters)
            if conditions:
                payload["conditions"] = conditions
        if getattr(request, "budget_bytes", None) is not None:
            payload["budget_bytes"] = getattr(request, "budget_bytes")
        if getattr(request, "trace_id", None):
            payload["trace_id"] = getattr(request, "trace_id")
        logger.info("Patentfield search payload: %s", payload)
        return payload

    def _parse_search_response(
        self, payload: dict[str, object], request: SearchParams, lane: str
    ) -> DBSearchResponse:
        """Convert Patentfield JSON into `DBSearchResponse`."""
        hits = payload.get("results") or payload.get("items") or []
        items = []
        for hit in hits:
            doc_id = hit.get("pub_id") or hit.get("doc_id") or hit.get("app_doc_id")
            if not doc_id:
                continue
            items.append(
                SearchItem(
                    doc_id=doc_id,
                    score=float(hit.get("score", 0.0)),
                    ipc_codes=hit.get("ipc_codes", []),
                    cpc_codes=hit.get("cpc_codes", []),
                    fi_codes=hit.get("fi_codes", []),
                    ft_codes=hit.get("ft_codes", []),
                )
            )
        meta = Meta(
            lane=lane if lane in ("fulltext", "semantic") else "fulltext",
            top_k=request.top_k,
            params={"query": getattr(request, "query", getattr(request, "text", ""))},
        )
        freqs = self._aggregate_code_summary(items)
        return DBSearchResponse(items=items, code_freqs=freqs, meta=meta)

    def _aggregate_code_summary(
        self, items: list[SearchItem]
    ) -> dict[str, dict[str, int]]:
        freqs: dict[str, dict[str, int]] = {
            "ipc": {},
            "cpc": {},
            "fi": {},
            "ft": {},
        }
        for item in items:
            for taxonomy, codes in (
                ("ipc", item.ipc_codes),
                ("cpc", item.cpc_codes),
                ("fi", item.fi_codes),
                ("ft", item.ft_codes),
            ):
                if not codes:
                    continue
                for code in codes:
                    freqs[taxonomy][code] = freqs[taxonomy].get(code, 0) + 1
        return freqs

    def _build_snippets_payload(
        self, request: GetSnippetsRequest, lane: str | None
    ) -> dict[str, object]:
        """Prepare snippet request body for Patentfield."""
        return request.model_dump()

    def _parse_snippet_response(
        self, payload: dict[str, object], requested_fields: list[str]
    ) -> dict[str, dict[str, str]]:
        hits = payload.get("results") or payload.get("items") or []
        result: dict[str, dict[str, str]] = {}
        for hit in hits:
            doc_id = hit.get("pub_id") or hit.get("doc_id") or hit.get("app_doc_id")
            if not doc_id:
                continue
            row: dict[str, str] = {}
            for field in requested_fields:
                if field == "pub_id":
                    row[field] = doc_id
                    continue
                column = FIELD_COLUMN_MAP.get(field, field)
                row[field] = hit.get(column, "")
            result[doc_id] = row
        return result

    async def search(self, request: SearchParams, lane: str) -> DBSearchResponse:
        payload = self._build_search_payload(request, lane)
        try:
            response = await self.http.post(f"{self.search_path}/{lane}", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Patentfield search returned %s", exc.response.status_code)
            if exc.response.status_code == 404:
                return DBSearchResponse(items=[], code_freqs=None, meta=Meta(lane=lane))
            raise
        logger.info("Patentfield search status: %s", response.status_code)
        return self._parse_search_response(response.json(), request, lane)

    async def fetch_snippets(
        self, request: GetSnippetsRequest, lane: str | None = None
    ) -> dict[str, dict[str, str]]:
        payload = self._build_snippets_payload(request, lane)
        logger.info("Patentfield snippets payload: %s", payload)
        try:
            response = await self.http.post(self.snippets_path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Patentfield snippets status: %s", exc.response.status_code)
            if exc.response.status_code == 404:
                return {}
            raise
        logger.info("Patentfield snippets status: %s", response.status_code)
        return self._parse_snippet_response(response.json(), request.fields)

    async def fetch_publication(
        self, request: GetPublicationRequest, lane: str | None = None
    ) -> dict[str, dict[str, str]]:
        if not request.ids:
            return {}
        name = request.ids[0]
        params = {"id_type": request.id_type}
        if request.fields:
            params["columns"] = ",".join(request.fields)
        logger.info("Patentfield publication GET: %s params=%s", name, params)
        try:
            response = await self.http.get(
                f"{self.publications_path}/{name}", params=params
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("Patentfield publication status: %s", exc.response.status_code)
            if exc.response.status_code == 404:
                return {}
            raise
        logger.info("Patentfield publication status: %s", response.status_code)
        return {name: response.json()}
