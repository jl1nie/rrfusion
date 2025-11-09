"""Core business logic for the MCP FastAPI service."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import HTTPException, status
from redis.asyncio import Redis

from ..config import Settings
from ..fusion import (
    aggregate_code_freqs,
    apply_code_boosts,
    compute_frontier,
    compute_relevance_flags,
    compute_rrf_scores,
    sort_scores,
)
from ..models import (
    BlendRequest,
    BlendResponse,
    BlendRunInput,
    DBSearchResponse,
    Filters,
    GetSnippetsRequest,
    MutateDelta,
    MutateRequest,
    MutateResponse,
    PeekConfig,
    PeekSnippetsRequest,
    PeekSnippetsResponse,
    ProvenanceResponse,
    RollupConfig,
    SearchRequest,
    SearchToolResponse,
)
from ..snippets import build_snippet_item, cap_by_budget
from ..storage import RedisStorage
from ..utils import hash_query

logger = logging.getLogger(__name__)

FIELD_ORDER = ["title", "abst", "claim", "description"]
FIELD_DEFAULT_CHARS = {
    "title": 160,
    "abst": 480,
    "claim": 320,
    "description": 400,
}
FIELD_MIN_CHARS = {
    "title": 80,
    "abst": 240,
    "claim": 160,
    "description": 200,
}

DEFAULT_WEIGHTS = {"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5}
DEFAULT_TOP_M_PER_LANE = {"fulltext": 10000, "semantic": 10000}
DEFAULT_K_GRID = [10, 20, 30, 40, 50, 80, 100]


class MCPService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis = Redis.from_url(settings.redis_url)
        self.storage = RedisStorage(self.redis, settings)
        self.http = httpx.AsyncClient(base_url=settings.db_stub_url, timeout=30.0)

    async def close(self) -> None:
        await self.http.aclose()
        await self.redis.close()

    # ------------------------------------------------------------------ #
    async def search_lane(
        self,
        lane: str,
        *,
        q: str,
        filters: Filters | None = None,
        top_k: int = 1000,
        rollup: RollupConfig | None = None,
        budget_bytes: int = 4096,
    ) -> SearchToolResponse:
        request = SearchRequest(
            q=q,
            filters=filters,
            top_k=top_k,
            rollup=rollup,
            budget_bytes=budget_bytes,
        )
        response = await self.http.post(f"/search/{lane}", json=request.model_dump())
        response.raise_for_status()
        db_payload = DBSearchResponse.model_validate(response.json())
        docs = [item.model_dump() for item in db_payload.items]
        count_returned = len(docs)
        truncated = count_returned < request.top_k
        query_hash = hash_query(
            request.q,
            request.filters.model_dump() if request.filters else None,
        )
        run_id = f"{lane}-{uuid4().hex[:8]}"
        metadata = {
            "query": request.q,
            "filters": request.filters.model_dump() if request.filters else {},
            "rollup": request.rollup.model_dump() if request.rollup else {},
            "top_k": request.top_k,
            "count_returned": count_returned,
            "truncated": truncated,
            "query_hash": query_hash,
        }

        freq_summary = db_payload.code_freqs
        await self.storage.store_lane_run(
            run_id=run_id,
            lane=lane,
            query_hash=query_hash,
            docs=docs,
            metadata=metadata,
            freq_summary=freq_summary,
        )

        return SearchToolResponse(
            lane=lane,
            run_id_lane=run_id,
            count_returned=count_returned,
            truncated=truncated,
            code_freqs=freq_summary,
            cursor=None,
        )

    # ------------------------------------------------------------------ #
    async def blend(
        self,
        *,
        runs: list[BlendRunInput],
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        beta: float = 1.0,
        family_fold: bool = True,
        target_profile: dict[str, dict[str, float]] | None = None,
        top_m_per_lane: dict[str, int] | None = None,
        k_grid: list[int] | None = None,
        peek: PeekConfig | None = None,
        parent_meta: dict[str, Any] | None = None,
    ) -> BlendResponse:
        if not runs:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="runs required")
        request = BlendRequest(
            runs=runs,
            weights=(weights or DEFAULT_WEIGHTS.copy()),
            rrf_k=rrf_k,
            beta=beta,
            family_fold=family_fold,
            target_profile=target_profile or {},
            top_m_per_lane=(top_m_per_lane or DEFAULT_TOP_M_PER_LANE.copy()),
            k_grid=(k_grid or DEFAULT_K_GRID.copy()),
            peek=peek,
        )
        if not request.runs:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="runs required")

        lane_docs: dict[str, list[tuple[str, float]]] = {}
        doc_ids: set[str] = set()
        lane_meta: dict[str, dict[str, Any]] = {}

        for run in request.runs:
            meta = await self.storage.get_run_meta(run.run_id_lane)
            if not meta:
                raise HTTPException(status_code=404, detail=f"run {run.run_id_lane} not found")
            if meta.get("run_type") != "lane":
                raise HTTPException(status_code=400, detail=f"run {run.run_id_lane} is not a lane run")
            lane_key = meta["lane_key"]
            limit = request.top_m_per_lane.get(run.lane, 1000)
            stop = limit - 1 if limit > 0 else -1
            docs = await self.storage.zslice(lane_key, 0, stop, desc=True)
            lane_docs[run.lane] = docs
            doc_ids.update(doc_id for doc_id, _ in docs)
            lane_meta[run.run_id_lane] = meta

        doc_metadata = await self.storage.get_docs(doc_ids)
        doc_codes = {
            doc_id: {
                "ipc": meta.get("ipc_codes", []),
                "cpc": meta.get("cpc_codes", []),
            }
            for doc_id, meta in doc_metadata.items()
        }

        scores, contributions = compute_rrf_scores(lane_docs, request.rrf_k, request.weights)
        scores = apply_code_boosts(
            scores,
            contributions,
            doc_codes,
            request.target_profile,
            request.weights,
        )
        ordered = sort_scores(scores)
        ordered_ids = [doc_id for doc_id, _ in ordered]

        relevant_flags = compute_relevance_flags(doc_metadata, request.target_profile)
        frontier = compute_frontier(ordered_ids, request.k_grid, relevant_flags, request.beta)

        max_k = max(request.k_grid) if request.k_grid else len(ordered_ids)
        max_k = min(max_k, len(ordered_ids))
        freqs_topk = aggregate_code_freqs(doc_metadata, ordered_ids[:max_k])

        contrib_payload: dict[str, dict[str, float]] = {}
        for doc_id, _score in ordered[:20]:
            total = sum(contributions[doc_id].values())
            if total == 0:
                continue
            contrib_payload[doc_id] = {
                key: round(value / total, 3) for key, value in contributions[doc_id].items()
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
            "beta": request.beta,
            "family_fold": request.family_fold,
            "target_profile": request.target_profile,
            "top_m_per_lane": request.top_m_per_lane,
            "k_grid": request.k_grid,
            "peek": request.peek.model_dump() if request.peek else None,
        }
        history = list(parent_meta.get("history", [])) if parent_meta else []
        if parent_meta:
            history.append(parent_meta["run_id"])

        await self.storage.store_rrf_run(
            run_id=run_id,
            scores=ordered,
            metadata={
                "run_type": "fusion",
                "source_runs": [run.model_dump() for run in request.runs],
                "recipe": recipe,
                "parent": parent_meta.get("run_id") if parent_meta else None,
                "history": history,
            },
        )

        return BlendResponse(
            run_id=run_id,
            pairs_top=ordered[: max_k],
            frontier=frontier,
            freqs_topk=freqs_topk,
            contrib=contrib_payload,
            recipe=recipe,
            peek_samples=peek_samples,
        )

    # ------------------------------------------------------------------ #
    async def peek_snippets(
        self,
        *,
        run_id: str,
        offset: int = 0,
        limit: int = 12,
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
        claim_count: int = 3,
        strategy: Literal["head", "match", "mix"] = "head",
        budget_bytes: int = 12_288,
    ) -> PeekSnippetsResponse:
        request_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "offset": offset,
            "limit": limit,
            "claim_count": claim_count,
            "strategy": strategy,
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

        key = meta.get("rrf_key") if meta.get("run_type") == "fusion" else meta.get("lane_key")
        if not key:
            raise HTTPException(status_code=400, detail="run missing sorted set key")

        limit = min(request.limit, self.settings.peek_max_docs)
        if limit <= 0:
            return PeekSnippetsResponse(items=[], used_bytes=0, truncated=False, peek_cursor=None)

        start = request.offset
        stop = request.offset + limit - 1
        budget_limit = min(request.budget_bytes, self.settings.peek_budget_bytes)
        effective_chars = _coerce_field_char_limits(request.fields, request.per_field_chars, budget_limit)
        logger.debug(
            "peek_snippets run=%s key=%s offset=%s limit=%s budget=%s",
            request.run_id,
            key,
            start,
            limit,
            budget_limit,
        )
        rows = await self.storage.zslice(key, start, stop, desc=True)
        logger.debug("peek_snippets fetched %s rows from %s", len(rows), key)
        doc_ids = [doc_id for doc_id, _ in rows]
        doc_metadata = await self.storage.get_docs(doc_ids)
        logger.debug("peek_snippets hydrated %s docs with metadata", len(doc_metadata))

        items = [
            build_snippet_item(doc_id, doc_metadata.get(doc_id, {}), request.fields, effective_chars)
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

        return PeekSnippetsResponse(
            items=capped,
            used_bytes=used_bytes,
            truncated=truncated,
            peek_cursor=cursor,
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

    # ------------------------------------------------------------------ #
    async def mutate_run(self, *, run_id: str, delta: MutateDelta) -> MutateResponse:
        request = MutateRequest(run_id=run_id, delta=delta)
        meta = await self.storage.get_run_meta(request.run_id)
        if not meta or meta.get("run_type") != "fusion":
            raise HTTPException(status_code=404, detail="fusion run not found")

        base_recipe = meta.get("recipe", {})
        updated_recipe = json.loads(json.dumps(base_recipe))

        if request.delta.weights:
            updated_recipe["weights"] = {**updated_recipe.get("weights", {}), **request.delta.weights}
        if request.delta.rrf_k is not None:
            updated_recipe["rrf_k"] = request.delta.rrf_k
        if request.delta.beta is not None:
            updated_recipe["beta"] = request.delta.beta

        updated_recipe.setdefault(
            "top_m_per_lane",
            base_recipe.get("top_m_per_lane", {"fulltext": 10000, "semantic": 10000}),
        )
        updated_recipe.setdefault("k_grid", base_recipe.get("k_grid", [10, 20, 30, 40, 50]))
        updated_recipe.setdefault("target_profile", base_recipe.get("target_profile", {}))

        normalized_runs = []
        for run in meta.get("source_runs", []):
            if isinstance(run, dict):
                normalized_runs.append(BlendRunInput(**run))
            else:
                normalized_runs.append(BlendRunInput.model_validate(run))

        blend_request = BlendRequest(
            runs=normalized_runs,
            weights=updated_recipe.get("weights", {}),
            rrf_k=updated_recipe.get("rrf_k", self.settings.rrf_k),
            beta=updated_recipe.get("beta", 1.0),
            family_fold=base_recipe.get("family_fold", True),
            target_profile=updated_recipe.get("target_profile", {}),
            top_m_per_lane=updated_recipe.get("top_m_per_lane", {"fulltext": 10000, "semantic": 10000}),
            k_grid=updated_recipe.get("k_grid", [10, 20, 30, 40, 50]),
            peek=None,
        )

        response = await self.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta=blend_request.beta,
            family_fold=blend_request.family_fold,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
            peek=blend_request.peek,
            parent_meta=meta,
        )
        delta_payload = request.delta.model_dump(exclude_none=True)
        response.recipe["delta"] = delta_payload

        new_meta = await self.storage.get_run_meta(response.run_id)
        if new_meta:
            recipe_meta = new_meta.get("recipe", {})
            recipe_meta["delta"] = delta_payload
            new_meta["recipe"] = recipe_meta
            await self.storage.set_run_meta(response.run_id, new_meta)

        return MutateResponse(
            new_run_id=response.run_id,
            frontier=response.frontier,
            recipe=response.recipe,
        )

    # ------------------------------------------------------------------ #
    async def provenance(self, run_id: str) -> ProvenanceResponse:
        meta = await self.storage.get_run_meta(run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="run not found")
        recipe = meta.get("recipe", {})
        return ProvenanceResponse(
            recipe=recipe,
            parent=meta.get("parent"),
            history=meta.get("history", []),
        )


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
