"""Core business logic for the MCP FastAPI service."""

from __future__ import annotations

import json
import logging
from collections import Counter
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException, status
from redis.asyncio import Redis

from ..config import Settings
from ..fusion import (
    aggregate_code_freqs,
    apply_code_boosts,
    apply_representative_priority,
    compute_frontier,
    compute_lane_ranks,
    compute_pi_scores,
    compute_rrf_scores,
    compute_fusion_metrics,
    sort_scores,
)
from ..models import (
    BlendRequest,
    BlendResponse,
    BlendRunInput,
    Cond,
    FeatureScope,
    FulltextParams,
    FusionMetrics,
    GetPublicationRequest,
    GetSnippetsRequest,
    IncludeOpts,
    Lane,
    Meta,
    MultiLaneEntryError,
    MultiLaneEntryResponse,
    MultiLaneSearchMeta,
    MultiLaneSearchRequest,
    MultiLaneSearchResponse,
    MultiLaneStatus,
    MultiLaneTool,
    MutateDelta,
    MutateRequest,
    MutateResponse,
    PeekConfig,
    PeekMeta,
    PeekSnippet,
    PeekSnippetsRequest,
    PeekSnippetsResponse,
    ProvenanceResponse,
    RunHandle,
    SEARCH_FIELDS_DEFAULT,
    SearchItem,
    SearchMetaLite,
    SearchParams,
    SemanticParams,
    SemanticStyle,
    SnippetField,
    RepresentativeEntry,
)
from ..mcp.defaults import (
    FUSION_DEFAULT_BETA_FUSE,
    FUSION_DEFAULT_K_GRID,
    FUSION_DEFAULT_RRF_K,
    FUSION_DEFAULT_TOP_M_PER_LANE,
    FUSION_DEFAULT_WEIGHTS,
)
from ..snippets import build_snippet_item, cap_by_budget
from ..storage import RedisStorage
from ..utils import hash_query, normalize_fi_subgroup
from .backends import LaneBackend, LaneBackendRegistry

logger = logging.getLogger(__name__)

FIELD_ORDER = [
    "title",
    "abst",
    "claim",
    "desc",
    "app_doc_id",
    "app_id",
    "pub_id",
    "exam_id",
    "app_date",
    "pub_date",
    "apm_applicants",
    "cross_en_applicants",
]
FIELD_DEFAULT_CHARS = {
    "title": 160,
    "abst": 480,
    "claim": 320,
    "desc": 400,
    "app_doc_id": 128,
    "app_id": 128,
    "pub_id": 128,
    "exam_id": 128,
    "app_date": 64,
    "pub_date": 64,
    "apm_applicants": 128,
    "cross_en_applicants": 128,
}
FIELD_MIN_CHARS = {
    "title": 80,
    "abst": 240,
    "claim": 160,
    "desc": 200,
    "app_doc_id": 32,
    "app_id": 32,
    "pub_id": 32,
    "exam_id": 32,
    "app_date": 20,
    "pub_date": 20,
    "apm_applicants": 64,
    "cross_en_applicants": 64,
}

DEFAULT_CODE_FREQ_TOP_K = 30
IDENTIFIER_FIELDS = ("app_doc_id", "app_id", "pub_id")
MULTI_LANE_TOOL_LANES: dict[MultiLaneTool, set[Lane]] = {
    "search_fulltext": {"fulltext"},
    "search_semantic": {"semantic", "original_dense"},
}


def _code_freq_summary(items: list[SearchItem]) -> dict[str, dict[str, int]]:
    """Aggregate IPC/CPC/FI/FT frequencies from returned items."""

    taxonomy_counters: dict[str, Counter[str]] = {
        taxonomy: Counter() for taxonomy in ("ipc", "cpc", "fi", "ft")
    }
    for item in items:
        taxonomy_counters["ipc"].update(item.ipc_codes)
        taxonomy_counters["cpc"].update(item.cpc_codes)
        taxonomy_counters["fi"].update(item.fi_codes)
        taxonomy_counters["ft"].update(item.ft_codes)
    return {taxonomy: dict(counter) for taxonomy, counter in taxonomy_counters.items()}


def _trim_code_freqs(
    freqs: dict[str, dict[str, int]] | None, top_k: int | None
) -> dict[str, dict[str, int]] | None:
    """Return a truncated view of the frequency table for the response."""
    if not freqs or not top_k or top_k <= 0:
        return freqs
    trimmed: dict[str, dict[str, int]] = {}
    for taxonomy, distribution in freqs.items():
        sorted_codes = sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)
        limited = sorted_codes[:top_k]
        trimmed[taxonomy] = {code: count for code, count in limited}
    return trimmed



def _elapsed_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))


def _search_meta(lane: str, params: SearchParams) -> Meta:
    meta_params: dict[str, Any] = {
        "query": getattr(params, "query", None) or getattr(params, "text", None),
        "filters": [cond.model_dump() for cond in params.filters],
        "fields": getattr(params, "fields", None),
        "include": params.include.model_dump(),
    }
    semantic_style = getattr(params, "semantic_style", None)
    if semantic_style is not None:
        meta_params["semantic_style"] = semantic_style
    field_boosts = getattr(params, "field_boosts", None)
    if field_boosts is not None:
        meta_params["field_boosts"] = field_boosts
    feature_scope = getattr(params, "feature_scope", None)
    if feature_scope is not None:
        meta_params["feature_scope"] = feature_scope
    return Meta(
        lane=lane,
        top_k=params.top_k,
        params=meta_params,
        trace_id=params.trace_id,
    )


def _build_search_item(
    doc_id: str,
    score: float,
    doc_meta: dict[str, Any],
    include: IncludeOpts,
) -> SearchItem:
    """Construct a lean SearchItem honoring include flags."""
    ipc_codes = doc_meta.get("ipc_codes") if include.codes else None
    cpc_codes = doc_meta.get("cpc_codes") if include.codes else None
    fi_codes = doc_meta.get("fi_codes") if include.codes else None
    fi_norm_codes = doc_meta.get("fi_norm_codes") if include.codes else None
    ft_codes = doc_meta.get("ft_codes") if include.codes else None
    return SearchItem(
        doc_id=doc_id,
        score=score if include.scores else None,
        ipc_codes=ipc_codes,
        cpc_codes=cpc_codes,
        fi_codes=fi_codes,
        fi_norm_codes=fi_norm_codes,
        ft_codes=ft_codes,
    )


async def _collect_lane_items(
    storage: RedisStorage,
    run_id: str,
    lane: str,
    top_k: int,
    include: IncludeOpts,
) -> tuple[list[SearchItem], dict[str, dict[str, int]] | None]:
    meta = await storage.get_run_meta(run_id)
    if not meta:
        return [], {}
    lane_key = meta.get("lane_key")
    if not lane_key:
        return [], {}
    stop = max(top_k - 1, 0)
    docs = await storage.zslice(lane_key, 0, stop, desc=True)
    doc_ids = [doc_id for doc_id, _ in docs]
    doc_metadata = await storage.get_docs(doc_ids)
    items: list[SearchItem] = []
    for doc_id, score in docs:
        metadata = doc_metadata.get(doc_id, {})
        items.append(_build_search_item(doc_id, score, metadata, include))
    freq_summary = await storage.get_freq_summary(run_id, lane) if include.code_freqs else None
    return items, freq_summary


class MCPService:
    def __init__(
        self,
        settings: Settings,
        *,
        backend_registry: LaneBackendRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.redis = Redis.from_url(settings.redis_url)
        self.storage = RedisStorage(self.redis, settings)
        self.backend_registry = backend_registry or LaneBackendRegistry(settings)

    async def close(self) -> None:
        try:
            await self.backend_registry.close()
        finally:
            await self.redis.aclose()

    # ------------------------------------------------------------------ #
    async def search_lane(
        self,
        lane: str,
        *,
        params: SearchParams | None = None,
        query: str | None = None,
        text: str | None = None,
        filters: list[Cond] | None = None,
        fields: list[SnippetField] | None = None,
        top_k: int = 800,
        trace_id: str | None = None,
        semantic_style: SemanticStyle = "default",
        field_boosts: dict[str, float] | None = None,
        feature_scope: FeatureScope | None = None,
        code_freq_top_k: int | None = DEFAULT_CODE_FREQ_TOP_K,
    ) -> RunHandle:
        start = perf_counter()
        backend = self.backend_registry.get_backend(lane)
        if not backend:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"lane {lane} unsupported",
            )
        if lane == "original_dense":
            semantic_style = "original_dense"

        if params is None:
            requested_fields = fields or SEARCH_FIELDS_DEFAULT
            if lane == "fulltext":
                actual_query = query
                if not actual_query:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="query required for fulltext lane",
                    )
                # Prepare fulltext request with user query + filters
                params = FulltextParams(
                    query=actual_query,
                    filters=filters or [],
                    fields=requested_fields,
                    top_k=top_k,
                    trace_id=trace_id,
                    field_boosts=field_boosts,
                )
            else:
                actual_text = text
                if not actual_text:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="text required for semantic lane",
                    )
                # Prepare semantic request when lane is semantic
                params = SemanticParams(
                    text=actual_text,
                    filters=filters or [],
                    fields=requested_fields,
                    top_k=top_k,
                    trace_id=trace_id,
                    semantic_style=semantic_style,
                    feature_scope=feature_scope,
                )
        db_payload = await backend.search(params, lane=lane)
        # hydrate lane results into dictionaries for caching and snippet fetching
        docs = [item.model_dump(exclude_none=True) for item in db_payload.items]
        # compute stats for the run
        count_returned = len(docs)
        truncated = count_returned < params.top_k
        filters_payload = [cond.model_dump() for cond in params.filters]
        query_hash = hash_query(
            getattr(params, "query", getattr(params, "text", "")),
            filters_payload or None,
        )
        run_id = f"{lane}-{uuid4().hex[:8]}"
        metadata = {
            "query": getattr(params, "query", getattr(params, "text", "")),
            "filters": filters_payload,
            "top_k": params.top_k,
            "count_returned": count_returned,
            "truncated": truncated,
            "query_hash": query_hash,
        }

        meta = _search_meta(lane, params)
        metadata["params"] = meta.params
        freq_summary = db_payload.code_freqs or _code_freq_summary(db_payload.items)
        await self.storage.store_lane_run(
            run_id=run_id,
            lane=lane,
            query_hash=query_hash,
            docs=docs,
            metadata=metadata,
            freq_summary=freq_summary,
        )

        meta.took_ms = _elapsed_ms(start)
        return RunHandle(
            run_id=run_id,
            meta=SearchMetaLite(
                top_k=meta.top_k,
                count_returned=count_returned,
                truncated=truncated,
                took_ms=meta.took_ms,
            ),
        )

    async def multi_lane_search(
        self, req: MultiLaneSearchRequest
    ) -> MultiLaneSearchResponse:
        """
        Execute the requested lanes sequentially using existing search tools.
        """
        results: list[MultiLaneEntryResponse] = []
        success_count = 0
        error_count = 0
        start = perf_counter()

        for entry in req.lanes:
            lane_start = perf_counter()
            lane_status = MultiLaneStatus.success
            handle: RunHandle | None = None
            error: MultiLaneEntryError | None = None
            allowed_lanes = MULTI_LANE_TOOL_LANES.get(entry.tool)
            if not allowed_lanes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"unsupported tool {entry.tool} for multi-lane search",
                )
            try:
                if entry.lane not in allowed_lanes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"lane {entry.lane} incompatible with tool {entry.tool}",
                    )

                handle = await self.search_lane(lane=entry.lane, params=entry.params)
                success_count += 1
            except HTTPException as exc:
                lane_status = MultiLaneStatus.error
                error_count += 1
                error = MultiLaneEntryError(
                    code=f"http_{exc.status_code}",
                    message=str(exc.detail or exc),
                    details={"status_code": exc.status_code, "detail": exc.detail},
                )
            except Exception as exc:
                lane_status = MultiLaneStatus.error
                error_count += 1
                error = MultiLaneEntryError(
                    code=type(exc).__name__,
                    message=str(exc),
                    details={},
                )
            finally:
                lane_end = perf_counter()
                results.append(
                    MultiLaneEntryResponse(
                        lane_name=entry.lane_name,
                        tool=entry.tool,
                        lane=entry.lane,
                        status=lane_status,
                        took_ms=int((lane_end - lane_start) * 1000),
                        handle=handle if lane_status == MultiLaneStatus.success else None,
                        error=error,
                    )
                )

        total = int((perf_counter() - start) * 1000)
        meta = MultiLaneSearchMeta(
            took_ms_total=total,
            trace_id=req.trace_id,
            success_count=success_count,
            error_count=error_count,
        )
        return MultiLaneSearchResponse(results=results, meta=meta)

    async def _fetch_snippets_from_backend(
        self,
        backend: LaneBackend,
        lane: str | None,
        *,
        ids: list[str],
        fields: list[str],
        per_field_chars: dict[str, int],
    ) -> dict[str, dict[str, str]]:
        # Always request identifier fields from the backend, even if the caller
        # did not include them explicitly, so that app_doc_id/app_id/pub_id are populated.
        effective_fields: list[str] = list(fields)
        for id_field in IDENTIFIER_FIELDS:
            if id_field not in effective_fields:
                effective_fields.append(id_field)
        request = GetSnippetsRequest(
            ids=ids,
            fields=effective_fields,
            per_field_chars=per_field_chars or {},
        )
        try:
            return await backend.fetch_snippets(request, lane=lane)
        except NotImplementedError:
            return {}

    # ------------------------------------------------------------------ #
    async def blend(
        self,
        *,
        runs: list[BlendRunInput],
        weights: dict[str, float] | None = None,
        rrf_k: int | None = None,
        beta_fuse: float | None = None,
        target_profile: dict[str, dict[str, float]] | None = None,
        top_m_per_lane: dict[str, int] | None = None,
        k_grid: list[int] | None = None,
        peek: PeekConfig | None = None,
        parent_meta: dict[str, Any] | None = None,
        representatives: list[RepresentativeEntry] | None = None,
    ) -> BlendResponse:
        start = perf_counter()
        if not runs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="runs required"
            )
        effective_rrf_k = rrf_k if rrf_k is not None else FUSION_DEFAULT_RRF_K
        effective_beta_fuse = beta_fuse if beta_fuse is not None else FUSION_DEFAULT_BETA_FUSE
        request = BlendRequest(
            runs=runs,
            weights=(weights or FUSION_DEFAULT_WEIGHTS.copy()),
            rrf_k=effective_rrf_k,
            beta_fuse=effective_beta_fuse,
            target_profile=target_profile or {},
            top_m_per_lane=(top_m_per_lane or FUSION_DEFAULT_TOP_M_PER_LANE.copy()),
            k_grid=(k_grid or FUSION_DEFAULT_K_GRID.copy()),
            peek=peek,
            representatives=representatives or [],
        )
        if not request.runs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="runs required"
            )

        lane_docs: dict[str, list[tuple[str, float]]] = {}
        doc_ids: set[str] = set()
        lane_meta: dict[str, dict[str, Any]] = {}

        for run in request.runs:
            meta = await self.storage.get_run_meta(run.run_id_lane)
            if not meta:
                raise HTTPException(
                    status_code=404, detail=f"run {run.run_id_lane} not found"
                )
            if meta.get("run_type") != "lane":
                raise HTTPException(
                    status_code=400, detail=f"run {run.run_id_lane} is not a lane run"
                )
            lane_key = meta["lane_key"]
            limit = request.top_m_per_lane.get(run.lane, 1000)
            stop = limit - 1 if limit > 0 else -1
            docs = await self.storage.zslice(lane_key, 0, stop, desc=True)
            lane_docs[run.lane] = docs
            doc_ids.update(doc_id for doc_id, _ in docs)
            lane_meta[run.run_id_lane] = meta

        doc_metadata = await self.storage.get_docs(doc_ids)
        doc_codes: dict[str, dict[str, list[str]]] = {}
        for doc_id, meta in doc_metadata.items():
            fi_norm_codes = meta.get("fi_norm_codes", []) or []
            if not fi_norm_codes:
                seen: set[str] = set()
                fallback: list[str] = []
                for code in meta.get("fi_codes", []) or []:
                    normalized = normalize_fi_subgroup(code)
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        fallback.append(normalized)
                fi_norm_codes = fallback
            doc_codes[doc_id] = {
                "ipc": meta.get("ipc_codes", []),
                "cpc": meta.get("cpc_codes", []),
                "fi": meta.get("fi_codes", []),
                "fi_norm": fi_norm_codes,
                "ft": meta.get("ft_codes", []),
            }

        # Build per-run weights list (use per-run weights if specified, else fallback to lane-level weights dict)
        run_weights = [(run.lane, run.weight) for run in request.runs]

        scores, contributions = compute_rrf_scores(
            lane_docs, request.rrf_k, run_weights
        )

        # For code boosts, extract code/code_secondary weights from the weights dict
        code_boost_weights = {
            "code": request.weights.get("code", 0.0),
            "code_secondary": request.weights.get("code_secondary", 0.0),
        }
        scores = apply_code_boosts(
            scores,
            contributions,
            doc_codes,
            request.target_profile,
            code_boost_weights,
        )
        ordered = sort_scores(scores)
        ordered_ids = [doc_id for doc_id, _ in ordered]
        metrics_payload = compute_fusion_metrics(
            lane_docs=lane_docs,
            doc_metadata=doc_metadata,
            ordered=ordered,
        )
        lane_ranks = compute_lane_ranks(lane_docs)
        pi_scores = compute_pi_scores(
            doc_metadata,
            request.target_profile,
            request.facet_terms,
            request.facet_weights,
            lane_ranks,
            request.lane_weights,
            request.pi_weights,
        )
        frontier = compute_frontier(
            ordered_ids, request.k_grid, pi_scores, request.beta_fuse
        )

        priority_pairs = apply_representative_priority(ordered, request.representatives)

        max_k = max(request.k_grid) if request.k_grid else len(ordered_ids)
        max_k = min(max_k, len(ordered_ids))
        freqs_topk = aggregate_code_freqs(doc_metadata, ordered_ids[:max_k])

        contrib_payload: dict[str, dict[str, float]] = {}
        for doc_id, _score in ordered[:20]:
            total = sum(contributions[doc_id].values())
            if total == 0:
                continue
            contrib_payload[doc_id] = {
                key: round(value / total, 3)
                for key, value in contributions[doc_id].items()
            }

        peek_samples: list[dict[str, Any]] = []
        if request.peek:
            items = []
            for doc_id in ordered_ids[: request.peek.count]:
                doc_meta = doc_metadata.get(doc_id)
                if not doc_meta:
                    continue
                items.append(
                    build_snippet_item(
                        doc_id,
                        doc_meta,
                        request.peek.fields,
                        request.peek.per_field_chars,
                    )
                )
            peek_samples, _, _ = cap_by_budget(items, request.peek.budget_bytes)

        run_id = f"fusion-{uuid4().hex[:10]}"
        recipe = {
            "weights": request.weights,
            "rrf_k": request.rrf_k,
            "beta_fuse": request.beta_fuse,
            "target_profile": request.target_profile,
            "top_m_per_lane": request.top_m_per_lane,
            "k_grid": request.k_grid,
            "peek": request.peek.model_dump() if request.peek else None,
            "representatives": [
                rep.model_dump(exclude_none=True) for rep in request.representatives
            ]
            if request.representatives
            else [],
        }
        history = list(parent_meta.get("history", [])) if parent_meta else []
        if parent_meta:
            history.append(parent_meta["run_id"])

        representative_payload = recipe.get("representatives", [])
        await self.storage.store_rrf_run(
            run_id=run_id,
            scores=ordered,
            metadata={
                "run_type": "fusion",
                "source_runs": [run.model_dump() for run in request.runs],
                "recipe": recipe,
                "parent": parent_meta.get("run_id") if parent_meta else None,
                "history": history,
                "freqs_topk": freqs_topk,
                "contrib": contrib_payload,
                "metrics": metrics_payload,
                "representatives": representative_payload,
            },
        )

        response = BlendResponse(
            run_id=run_id,
            pairs_top=ordered[:max_k],
            frontier=frontier,
            freqs_topk=freqs_topk,
            contrib=contrib_payload,
            recipe=recipe,
            peek_samples=peek_samples,
            priority_pairs=priority_pairs[:max_k] if priority_pairs else [],
            representatives=[
                RepresentativeEntry.model_validate(rep)
                for rep in representative_payload
            ],
            metrics=FusionMetrics.model_validate(metrics_payload),
        )
        response.meta["took_ms"] = _elapsed_ms(start)
        return response

    # ------------------------------------------------------------------ #
    async def peek_snippets(
        self,
        *,
        run_id: str,
        offset: int = 0,
        limit: int = 12,
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
        budget_bytes: int = 12_288,
    ) -> PeekSnippetsResponse:
        request_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "offset": offset,
            "limit": limit,
            "budget_bytes": budget_bytes,
        }
        if fields is not None:
            request_kwargs["fields"] = fields
        if per_field_chars is not None:
            request_kwargs["per_field_chars"] = per_field_chars
        request = PeekSnippetsRequest(**request_kwargs)
        meta = await self.storage.get_run_meta(request.run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="run not found")

        key = (
            meta.get("rrf_key")
            if meta.get("run_type") == "fusion"
            else meta.get("lane_key")
        )
        if not key:
            raise HTTPException(status_code=400, detail="run missing sorted set key")

        limit = min(request.limit, self.settings.peek_max_docs)
        timing_start = perf_counter()
        if limit <= 0:
            total_docs = await self.redis.zcard(key)
            return PeekSnippetsResponse(
                run_id=request.run_id,
                snippets=[],
                meta=PeekMeta(
                    used_bytes=0,
                    truncated=False,
                    peek_cursor=None,
                    total_docs=total_docs,
                    retrieved=0,
                    returned=0,
                    took_ms=_elapsed_ms(timing_start),
                ),
            )

        slice_start = request.offset
        stop = request.offset + limit - 1
        budget_limit = min(request.budget_bytes, self.settings.peek_budget_bytes)
        effective_chars = _coerce_field_char_limits(
            request.fields, request.per_field_chars, budget_limit
        )
        logger.debug(
            "peek_snippets run=%s key=%s offset=%s limit=%s budget=%s",
            request.run_id,
            key,
            slice_start,
            limit,
            budget_limit,
        )
        rows = await self.storage.zslice(key, slice_start, stop, desc=True)
        logger.debug("peek_snippets fetched %s rows from %s", len(rows), key)
        doc_ids = [doc_id for doc_id, _ in rows]
        doc_metadata = await self.storage.get_docs(doc_ids)
        logger.debug("peek_snippets hydrated %s docs with metadata", len(doc_metadata))

        snippet_lane = self.settings.snippet_backend_lane
        backend = self.backend_registry.get_backend(snippet_lane)
        fields = request.fields or ["title", "abst", "claim"]
        per_field_chars = request.per_field_chars
        # Treat identifier fields as mandatory for backend refresh so that
        # app_doc_id/app_id/pub_id are always populated in snippets.
        required_fields = list(fields)
        for id_field in IDENTIFIER_FIELDS:
            if id_field not in required_fields:
                required_fields.append(id_field)
        missing_ids = [
            doc_id
            for doc_id in doc_ids
            if not doc_metadata.get(doc_id)
            or any(not doc_metadata[doc_id].get(field) for field in required_fields)
        ]
        if missing_ids and backend:
            fetched = await self._fetch_snippets_from_backend(
                backend=backend,
                lane=snippet_lane,
                ids=missing_ids,
                fields=fields,
                per_field_chars=per_field_chars,
            )
            if fetched:
                docs_to_upsert: list[dict[str, str]] = []
                for doc_id, payload in fetched.items():
                    existing = doc_metadata.get(doc_id, {})
                    merged = {**existing, **payload}
                    doc_metadata[doc_id] = merged
                    docs_to_upsert.append({"doc_id": doc_id, **payload})
                await self.storage.upsert_docs(docs_to_upsert)

        items = [
            build_snippet_item(
                doc_id, doc_metadata.get(doc_id, {}), request.fields, effective_chars
            )
            for doc_id in doc_ids
        ]
        capped, used_bytes, truncated = cap_by_budget(items, budget_limit)
        if not capped and doc_ids:
            fallback = _fallback_snippet(
                doc_ids[0],
                doc_metadata.get(doc_ids[0], {}),
                request.fields,
                budget_limit,
            )
            if fallback:
                capped = [fallback[0]]
                used_bytes = fallback[1]
                truncated = True
        logger.debug(
            "peek_snippets budget result items=%s used=%s truncated=%s",
            len(capped),
            used_bytes,
            truncated,
        )
        total_docs = await self.redis.zcard(key)
        retrieved = len(doc_ids)
        returned = len(capped)
        if returned == 0 and truncated and retrieved > 0:
            returned = retrieved
        cursor = None
        if returned > 0 and request.offset + returned < total_docs:
            cursor = str(request.offset + returned)
        elif returned == 0:
            truncated = False
        logger.debug(
            "peek_snippets cursor=%s total_docs=%s retrieved=%s returned=%s",
            cursor,
            total_docs,
            retrieved,
            returned,
        )

        snippets_payload = [
            PeekSnippet(
                id=item["id"],
                fields={k: v for k, v in item.items() if k != "id"},
            )
            for item in capped
        ]
        return PeekSnippetsResponse(
            run_id=request.run_id,
            snippets=snippets_payload,
            meta=PeekMeta(
                used_bytes=used_bytes,
                truncated=truncated,
                peek_cursor=cursor,
                total_docs=total_docs,
                retrieved=retrieved,
                returned=returned,
                took_ms=_elapsed_ms(timing_start),
            ),
        )

    # ------------------------------------------------------------------ #
    async def get_snippets(
        self,
        *,
        ids: list[str],
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
    ) -> dict[str, dict[str, str]]:
        request_kwargs: dict[str, Any] = {"ids": ids}
        if fields is not None:
            request_kwargs["fields"] = fields
        if per_field_chars is not None:
            request_kwargs["per_field_chars"] = per_field_chars
        request = GetSnippetsRequest(**request_kwargs)
        doc_metadata = await self.storage.get_docs(request.ids)
        backend = self.backend_registry.get_backend("fulltext")
        missing_ids = []
        # Ensure backend is queried when identifier fields or requested fields are missing.
        required_fields = list(request.fields)
        for id_field in IDENTIFIER_FIELDS:
            if id_field not in required_fields:
                required_fields.append(id_field)
        for doc_id in request.ids:
            snippet = doc_metadata.get(doc_id, {})
            if not snippet or any(not snippet.get(field) for field in required_fields):
                missing_ids.append(doc_id)
        if missing_ids and backend:
            fetched = await self._fetch_snippets_from_backend(
                backend=backend,
                lane="fulltext",
                ids=missing_ids,
                fields=request.fields,
                per_field_chars=request.per_field_chars,
            )
            if fetched:
                docs_to_upsert: list[dict[str, Any]] = []
                for doc_id, payload in fetched.items():
                    existing = doc_metadata.get(doc_id, {})
                    merged = {**existing, **payload}
                    doc_metadata[doc_id] = merged
                    docs_to_upsert.append({"doc_id": doc_id, **payload})
                await self.storage.upsert_docs(docs_to_upsert)
        response: dict[str, dict[str, str]] = {}
        for doc_id in request.ids:
            snippet = build_snippet_item(
                doc_id,
                doc_metadata.get(doc_id, {}),
                request.fields,
                request.per_field_chars,
            )
            snippet.pop("id", None)
            response[doc_id] = snippet
        return response

    async def get_publication(
        self,
        *,
        ids: list[str],
        id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id",
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
    ) -> dict[str, dict[str, str]]:
        request_kwargs: dict[str, Any] = {
            "ids": ids,
            "id_type": id_type,
        }
        if fields is not None:
            request_kwargs["fields"] = fields
        if per_field_chars is not None:
            request_kwargs["per_field_chars"] = per_field_chars
        request = GetPublicationRequest(**request_kwargs)
        backend = self.backend_registry.get_backend("fulltext")
        if not backend:
            raise HTTPException(status_code=500, detail="no backend configured")
        return await backend.fetch_publication(request, lane="fulltext")

    # ------------------------------------------------------------------ #
    async def mutate_run(self, *, run_id: str, delta: MutateDelta) -> MutateResponse:
        start = perf_counter()
        request = MutateRequest(run_id=run_id, delta=delta)
        meta = await self.storage.get_run_meta(request.run_id)
        if not meta or meta.get("run_type") != "fusion":
            raise HTTPException(status_code=404, detail="fusion run not found")

        base_recipe = meta.get("recipe", {})
        updated_recipe = json.loads(json.dumps(base_recipe))

        if request.delta.weights:
            updated_recipe["weights"] = {
                **updated_recipe.get("weights", {}),
                **request.delta.weights,
            }
        if request.delta.rrf_k is not None:
            updated_recipe["rrf_k"] = request.delta.rrf_k
        if request.delta.beta_fuse is not None:
            updated_recipe["beta_fuse"] = request.delta.beta_fuse

        updated_recipe.setdefault(
            "top_m_per_lane",
            base_recipe.get("top_m_per_lane", {"fulltext": 10000, "semantic": 10000}),
        )
        updated_recipe.setdefault(
            "k_grid", base_recipe.get("k_grid", [10, 20, 30, 40, 50])
        )
        updated_recipe.setdefault(
            "target_profile", base_recipe.get("target_profile", {})
        )
        if "representatives" not in updated_recipe:
            updated_recipe["representatives"] = base_recipe.get("representatives", [])

        normalized_runs = []
        for run in meta.get("source_runs", []):
            if isinstance(run, dict):
                normalized_runs.append(BlendRunInput(**run))
            else:
                normalized_runs.append(BlendRunInput.model_validate(run))

        blend_request = BlendRequest(
            runs=normalized_runs,
            weights=updated_recipe.get("weights", {}),
            rrf_k=updated_recipe.get("rrf_k", FUSION_DEFAULT_RRF_K),
            beta_fuse=updated_recipe.get(
                "beta_fuse", updated_recipe.get("beta", FUSION_DEFAULT_BETA_FUSE)
            ),
            target_profile=updated_recipe.get("target_profile", {}),
            top_m_per_lane=updated_recipe.get(
                "top_m_per_lane", FUSION_DEFAULT_TOP_M_PER_LANE.copy()
            ),
            k_grid=updated_recipe.get("k_grid", FUSION_DEFAULT_K_GRID.copy()),
            peek=None,
            representatives=[
                RepresentativeEntry.model_validate(rep)
                for rep in updated_recipe.get("representatives", []) or []
            ],
        )

        response = await self.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta_fuse=blend_request.beta_fuse,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
            peek=blend_request.peek,
            parent_meta=meta,
            representatives=blend_request.representatives,
        )
        delta_payload = request.delta.model_dump(exclude_none=True)
        response.recipe["delta"] = delta_payload

        new_meta = await self.storage.get_run_meta(response.run_id)
        if new_meta:
            recipe_meta = new_meta.get("recipe", {})
            recipe_meta["delta"] = delta_payload
            new_meta["recipe"] = recipe_meta
            await self.storage.set_run_meta(response.run_id, new_meta)

        response = MutateResponse(
            new_run_id=response.run_id,
            frontier=response.frontier,
            recipe=response.recipe,
        )
        response.meta["took_ms"] = _elapsed_ms(start)
        return response

    # ------------------------------------------------------------------ #
    async def provenance(
        self,
        run_id: str,
        top_k_lane: int = 20,
        top_k_code: int = 30,
    ) -> ProvenanceResponse:
        start = perf_counter()
        meta = await self.storage.get_run_meta(run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="run not found")
        run_type = meta.get("run_type")

        code_distributions: dict[str, dict[str, int]] | None = None
        lane_contributions: dict[str, dict[str, float]] | None = None
        config_snapshot: dict[str, Any] | None = None
        metrics: FusionMetrics | None = None

        representatives: list[RepresentativeEntry] | None = None

        if run_type == "lane":
            lane = meta.get("lane")
            if lane:
                code_distributions = await self.storage.get_freq_summary(run_id, lane)
            config_snapshot = {
                "lane": lane,
                "query": meta.get("query"),
                "filters": meta.get("filters"),
                "top_k": meta.get("top_k"),
                "params": meta.get("params", {}),
            }
        elif run_type == "fusion":
            # For fusion runs, use stored frontier stats and recipe as the snapshot
            code_distributions = meta.get("freqs_topk")
            lane_contributions = meta.get("contrib")
            config_snapshot = meta.get("recipe")
            raw_reps = meta.get("representatives") or (config_snapshot or {}).get("representatives", [])
            if raw_reps:
                key = meta.get("rrf_key")
                ranks: dict[str, int] = {}
                scores: dict[str, float] = {}
                if key:
                    rows = await self.storage.zrange_all(key, desc=True)
                    for idx, (doc_id, score) in enumerate(rows, start=1):
                        ranks[doc_id] = idx
                        scores[doc_id] = score
                representatives = []
                for payload in raw_reps:
                    try:
                        rep = RepresentativeEntry.model_validate(payload)
                    except Exception:
                        continue
                    rep.rank = ranks.get(rep.doc_id)
                    rep.score = scores.get(rep.doc_id)
                    representatives.append(rep)
            metrics_payload = meta.get("metrics")
            if isinstance(metrics_payload, dict):
                try:
                    metrics = FusionMetrics.model_validate(metrics_payload)
                except Exception:
                    metrics = None

        if code_distributions:
            code_distributions = _trim_code_freqs(code_distributions, top_k_code)

        if lane_contributions and top_k_lane > 0:
            limited_items = list(lane_contributions.items())[:top_k_lane]
            lane_contributions = {doc_id: payload for doc_id, payload in limited_items}

        meta_with_timing = {**meta, "took_ms": _elapsed_ms(start)}
        return ProvenanceResponse(
            run_id=run_id,
            meta=meta_with_timing,
            lineage=meta_with_timing.get("history", []),
            lane_contributions=lane_contributions,
            code_distributions=code_distributions,
            config_snapshot=config_snapshot,
            metrics=metrics,
            representatives=representatives,
        )

    def _normalize_representatives(
        self, representatives: list[RepresentativeEntry]
    ) -> list[RepresentativeEntry]:
        if not representatives:
            raise HTTPException(
                status_code=400,
                detail="representatives is required and must include at least one document",
            )
        if len(representatives) > 30:
            raise HTTPException(
                status_code=400,
                detail="representatives list is limited to at most 30 entries",
            )
        seen: set[str] = set()
        normalized: list[RepresentativeEntry] = []
        for idx, entry in enumerate(representatives, start=1):
            doc_id = (entry.doc_id or "").strip()
            if not doc_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"representative #{idx} has an empty doc_id",
                )
            if doc_id in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"duplicate representative doc_id found: {doc_id}",
                )
            seen.add(doc_id)
            normalized.append(entry.model_copy(update={"doc_id": doc_id}))
        return normalized

    # ------------------------------------------------------------------ #
    async def register_representatives(
        self,
        *,
        run_id: str,
        representatives: list[RepresentativeEntry],
    ) -> ProvenanceResponse:
        meta = await self.storage.get_run_meta(run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="run not found")
        if meta.get("run_type") != "fusion":
            raise HTTPException(
                status_code=400, detail="representatives can only be registered for fusion runs"
            )
        existing = meta.get("representatives") or (meta.get("recipe") or {}).get("representatives")
        if existing:
            raise HTTPException(
                status_code=400,
                detail="representatives already registered for this fusion run; create a new fusion run if you need to redefine representatives",
            )
        normalized = self._normalize_representatives(representatives)
        reps_payload = [rep.model_dump(exclude_none=True) for rep in normalized]
        meta["representatives"] = reps_payload
        recipe = meta.get("recipe")
        if isinstance(recipe, dict):
            recipe["representatives"] = reps_payload
            meta["recipe"] = recipe
        await self.storage.set_run_meta(run_id, meta)
        return await self.provenance(run_id)


__all__ = ["MCPService"]


def _coerce_field_char_limits(
    fields: list[str],
    requested: dict[str, int],
    budget_limit: int,
) -> dict[str, int]:
    ordered: list[str] = [field for field in FIELD_ORDER if field in fields]
    ordered.extend(field for field in fields if field not in ordered)
    if not ordered:
        return {}

    chars: dict[str, int] = {}
    total = 0
    for field in ordered:
        base = requested.get(field, FIELD_DEFAULT_CHARS.get(field, 200))
        cap = FIELD_DEFAULT_CHARS.get(field, base)
        value = min(base, cap)
        floor = FIELD_MIN_CHARS.get(field, 32)
        value = max(floor, value)
        chars[field] = value
        total += value

    if total == 0:
        return chars

    overhead = 64 + 24 * len(chars)
    allowance = max(budget_limit - overhead, 64)
    if total <= allowance:
        return chars

    ratio = allowance / total
    for field in chars:
        floor = FIELD_MIN_CHARS.get(field, 32)
        chars[field] = max(floor, int(chars[field] * ratio))
    return chars


def _fallback_snippet(
    doc_id: str,
    doc_meta: dict[str, Any] | None,
    requested_fields: list[str],
    budget_limit: int,
) -> tuple[dict[str, Any], int] | None:
    ordered = [field for field in FIELD_ORDER if field in requested_fields]
    ordered.extend(field for field in requested_fields if field not in ordered)
    payload = doc_meta or {}
    for count in range(len(ordered), 0, -1):
        subset = ordered[:count]
        per_chars = {field: FIELD_MIN_CHARS.get(field, 32) for field in subset}
        snippet = build_snippet_item(doc_id, payload, subset, per_chars)
        encoded = len(json.dumps(snippet, ensure_ascii=False).encode("utf-8"))
        if encoded <= budget_limit:
            return snippet, encoded
    return None
