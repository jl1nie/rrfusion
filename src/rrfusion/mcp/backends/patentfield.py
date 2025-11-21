"""Patentfield-specific lane adapter."""

from __future__ import annotations

import logging
from typing import Any

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
    "app_id": "app_id",
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

CODE_FIELDS = ("ipcs", "cpcs", "fis", "fterms")


class PatentfieldBackend(HttpLaneBackend):
    """Call the Patentfield REST endpoint and return DBSearchResponse."""

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

    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] | None = None
        if settings.patentfield_api_key:
            headers = {"Authorization": f"Token {settings.patentfield_api_key}"}
        super().__init__(
            settings,
            base_url=settings.patentfield_url,
            search_path=settings.patentfield_search_path,
            snippets_path=settings.patentfield_snippets_path,
            publications_path=settings.patentfield_publications_path,
            headers=headers,
        )

    def _resolve_columns(self, requested: list[str]) -> list[str]:
        columns: list[str] = []
        for field in requested:
            column = FIELD_COLUMN_MAP.get(field, field)
            if column not in columns:
                columns.append(column)
        for id_field in ("app_id", "pub_id", "exam_id"):
            if id_field not in columns:
                columns.append(id_field)
        for code_field in CODE_FIELDS:
            if code_field not in columns:
                columns.append(code_field)
        return columns

    def _map_fields_to_columns(self, fields: list[str]) -> list[str]:
        seen: set[str] = set()
        columns: list[str] = []
        for field in fields:
            column = FIELD_COLUMN_MAP.get(field, field)
            if column not in seen:
                columns.append(column)
                seen.add(column)
        return columns

    def _extract_records(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            for key in ("records", "results", "items"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    return [entry for entry in candidate if isinstance(entry, dict)]
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
        return []

    def _doc_id_from_record(self, record: dict[str, Any]) -> str | None:
        for key in ("app_id", "doc_id", "pub_id", "exam_id"):
            value = record.get(key)
            if value:
                return str(value)
        return None

    def _normalize_score(self, record: dict[str, Any]) -> float:
        raw = record.get("_score") or record.get("score") or 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _normalize_codes(self, record: dict[str, Any], *keys: str) -> list[str]:
        for key in keys:
            value = record.get(key)
            if isinstance(value, list):
                return [str(code) for code in value if code]
        return []

    def _field_text(self, record: dict[str, Any], field: str) -> str:
        candidates: list[str] = []
        alias = FIELD_COLUMN_MAP.get(field)
        if alias:
            candidates.append(alias)
        candidates.append(field)
        for candidate in candidates:
            value = record.get(candidate)
            if value:
                return str(value)
        return ""

    def _normalize_payload_records(
        self,
        payload: Any,
        extracted: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if extracted:
            return extracted
        if isinstance(payload, dict):
            normalized: list[dict[str, Any]] = []
            for key, value in payload.items():
                if key in ("records", "results", "items"):
                    continue
                if isinstance(value, dict):
                    record = dict(value)
                    if "doc_id" not in record:
                        record["doc_id"] = key
                    normalized.append(record)
            return normalized
        return []

    def _build_conditions(
        self, filters: list[Cond] | None
    ) -> list[dict[str, Any]] | None:
        if not filters:
            return None
        conditions: list[dict[str, Any]] = []
        for cond in filters:
            key = FIELD_FILTER_MAP.get(cond.field, cond.field)
            lop = cond.lop.lower()
            entry: dict[str, Any] = {"key": key, "lop": lop, "op": cond.op}
            if (
                cond.op == "range"
                and isinstance(cond.value, (list, tuple))
                and len(cond.value) == 2
            ):
                entry["q1"] = cond.value[0]
                entry["q2"] = cond.value[1]
            else:
                if cond.op == "in":
                    q_value = cond.value
                    normalized: list[object] = []
                    if isinstance(q_value, dict):
                        for value in q_value.values():
                            if isinstance(value, (list, tuple)):
                                normalized.extend(value)
                            else:
                                normalized.append(value)
                    elif isinstance(q_value, (list, tuple)):
                        normalized.extend(q_value)
                    else:
                        normalized.append(q_value)
                    entry["q"] = normalized
                else:
                    entry["q"] = cond.value
            conditions.append(entry)
        return conditions

    def _build_search_payload(
        self, request: SearchParams, lane: str
    ) -> dict[str, object]:
        """Map MCP parameters to the Patentfield API."""
        query = getattr(request, "query", getattr(request, "text", ""))
        columns = self._resolve_columns(list(getattr(request, "fields", [])))
        columns_set = set(columns)
        search_type = (
            "semantic" if lane in ("semantic", "original_dense") else "fulltext"
        )
        payload: dict[str, object] = {
            "search_type": search_type,
            "q": query,
            "limit": min(request.top_k, self.settings.patentfield_max_results),
            "offset": 0,
            "columns": columns,
            "sort_keys": list(self.settings.patentfield_sort_keys),
            "score_type": "similarity_score" if search_type == "semantic" else "tfidf",
        }
        # Map semantic feature_scope to Patentfield feature parameter
        if search_type == "semantic":
            feature_scope = getattr(request, "feature_scope", None)
            feature_map: dict[str, str] = {
                "wide": "word_weights",
                "title_abst_claims": "claims_weights",
                "claims_only": "all_claims_weights",
                "top_claim": "top_claim_weights",
                "background_jp": "tbpes_weights",
            }
            feature = feature_map.get(feature_scope or "wide", "word_weights")
            payload["feature"] = feature
        # Map fulltext field_boosts to Patentfield weights parameter
        if search_type == "fulltext":
            boosts = getattr(request, "field_boosts", None)
            if boosts:
                # Patentfield 側の weights は整数指定想定のため、内部 float を int に丸めて渡す
                weights: dict[str, int] = {}
                for key, value in boosts.items():
                    ivalue = int(value)
                    if key == "title":
                        if "title" in columns_set:
                            weights["title"] = ivalue
                    elif key in ("abst", "abstract"):
                        if "abstract" in columns_set:
                            weights["abstract"] = ivalue
                    elif key in ("claim", "claims"):
                        if "claims" in columns_set:
                            weights["app_claim"] = ivalue
                    elif key in ("desc", "description"):
                        if "description" in columns_set:
                            weights["description"] = ivalue
                    else:
                        # Pass through unknown keys as-is to allow backend evolution
                        weights[key] = ivalue
                if weights:
                    payload["weights"] = [weights]
        if request.filters:
            conditions = self._build_conditions(request.filters)
            if conditions:
                payload["conditions"] = conditions
        if getattr(request, "trace_id", None):
            payload["trace_id"] = getattr(request, "trace_id")
        logger.info("Patentfield search payload: %s", payload)
        return payload

    def _parse_search_response(
        self, payload: dict[str, object], request: SearchParams, lane: str
    ) -> DBSearchResponse:
        """Convert Patentfield JSON into `DBSearchResponse`."""
        hits = self._extract_records(payload)
        items: list[SearchItem] = []
        for hit in hits:
            doc_id = self._doc_id_from_record(hit)
            if not doc_id:
                continue
            items.append(
                SearchItem(
                    doc_id=doc_id,
                    score=self._normalize_score(hit),
                    ipc_codes=self._normalize_codes(hit, "ipcs", "ipc_codes"),
                    cpc_codes=self._normalize_codes(hit, "cpcs", "cpc_codes"),
                    fi_codes=self._normalize_codes(hit, "fis", "fi_codes"),
                    ft_codes=self._normalize_codes(hit, "fterms", "fts", "ft_codes"),
                )
            )
        meta_params = {"query": getattr(request, "query", getattr(request, "text", ""))}
        meta = Meta(
            lane=lane if lane in ("fulltext", "semantic") else "fulltext",
            top_k=request.top_k,
            params=meta_params,
        )
        freqs = self._aggregate_code_summary(items)
        return DBSearchResponse(items=items, code_freqs=freqs, meta=meta)

    def _parse_snippet_response(
        self,
        payload: dict[str, object] | list[dict[str, object]],
        requested_fields: list[str],
    ) -> dict[str, dict[str, str]]:
        hits = self._extract_records(payload)
        normalized = self._normalize_payload_records(payload, hits)
        result: dict[str, dict[str, str]] = {}
        for hit in normalized:
            doc_id = self._doc_id_from_record(hit)
            if not doc_id:
                continue
            row: dict[str, str] = {}
            for field in requested_fields:
                row[field] = self._field_text(hit, field)
            result[doc_id] = row
        return result

    def _parse_publication_response(
        self, payload: dict[str, object], request: GetPublicationRequest
    ) -> dict[str, dict[str, str]]:
        hits = self._extract_records(payload)
        normalized = self._normalize_payload_records(payload, hits)
        result: dict[str, dict[str, str]] = {}
        for hit in normalized:
            doc_id = self._doc_id_from_record(hit)
            if not doc_id:
                continue
            row: dict[str, str] = {}
            for field in request.fields:
                row[field] = self._field_text(hit, field)
            result[doc_id] = row
        return result

    def _build_snippets_payload(
        self, request: GetSnippetsRequest, lane: str | None
    ) -> dict[str, object]:
        """Prepare a streamed search payload that fetches the requested fields for specific doc_ids."""
        if not request.ids:
            return {}
        columns = self._map_fields_to_columns(request.fields)
        if not columns:
            columns = self._map_fields_to_columns(["title", "abst", "claim"])
        for doc_key in ("app_id", "pub_id", "exam_id"):
            if doc_key not in columns:
                columns.append(doc_key)
        limit = min(len(request.ids), self.settings.patentfield_max_results)
        query_ids = [str(doc_id).strip() for doc_id in request.ids if str(doc_id).strip()]
        if query_ids:
            q_entries = [f'pub_id:"{doc_id}"' for doc_id in query_ids]
            q_string = " OR ".join(q_entries)
        else:
            q_string = "*"
        payload: dict[str, object] = {
            "search_type": "fulltext",
            "q": q_string,
            "limit": max(1, limit),
            "offset": 0,
            "columns": columns,
            "targets": columns,
            "score_type": "tfidf",
            "sort_keys": list(self.settings.patentfield_sort_keys),
        }
        return payload

    async def search(self, request: SearchParams, lane: str) -> DBSearchResponse:
        payload = self._build_search_payload(request, lane)
        try:
            response = await self.http.post(f"{self.search_path}", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            resp = exc.response
            status = resp.status_code
            error_message = ""
            try:
                data = resp.json()
                if isinstance(data, dict):
                    error_message = data.get("message") or data.get("detail") or ""
            except ValueError:
                text = resp.text
                if text:
                    error_message = text[:512]
            if error_message:
                logger.warning("Patentfield search HTTP %s: %s", status, error_message)
            else:
                logger.warning("Patentfield search HTTP %s", status)
            if status == 404:
                return DBSearchResponse(items=[], code_freqs=None, meta=Meta(lane=lane))
            raise
        except httpx.RequestError as exc:
            logger.error("Patentfield search request error: %s", exc)
            raise
        logger.info("Patentfield search status: %s", response.status_code)
        return self._parse_search_response(response.json(), request, lane)

    async def fetch_snippets(
        self, request: GetSnippetsRequest, lane: str | None = None
    ) -> dict[str, dict[str, str]]:
        payload = self._build_snippets_payload(request, lane)
        if not payload:
            return {}
        logger.info("Patentfield snippet search payload: %s", payload)
        try:
            response = await self.http.post(f"{self.search_path}", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            resp = exc.response
            status = resp.status_code
            error_message = ""
            try:
                data = resp.json()
                if isinstance(data, dict):
                    error_message = data.get("message") or data.get("detail") or ""
            except ValueError:
                text = resp.text
                if text:
                    error_message = text[:512]
            if error_message:
                logger.warning("Patentfield snippets HTTP %s: %s", status, error_message)
            else:
                logger.warning("Patentfield snippets HTTP %s", status)
            if status == 404:
                return {}
            raise
        except httpx.RequestError as exc:
            logger.error("Patentfield snippets request error: %s", exc)
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
            params["columns"] = self._map_fields_to_columns(request.fields)
        logger.info("Patentfield publication GET: %s params=%s", name, params)
        try:
            response = await self.http.get(
                f"{self.publications_path}/{name}", params=params
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            resp = exc.response
            status = resp.status_code
            error_message = ""
            try:
                data = resp.json()
                if isinstance(data, dict):
                    error_message = data.get("message") or data.get("detail") or ""
            except ValueError:
                text = resp.text
                if text:
                    error_message = text[:512]
            if error_message:
                logger.warning("Patentfield publication HTTP %s: %s", status, error_message)
            else:
                logger.warning("Patentfield publication HTTP %s", status)
            if status == 404:
                return {}
            raise
        except httpx.RequestError as exc:
            logger.error("Patentfield publication request error: %s", exc)
            raise
        logger.info("Patentfield publication status: %s", response.status_code)
        return self._parse_publication_response(response.json(), request)
