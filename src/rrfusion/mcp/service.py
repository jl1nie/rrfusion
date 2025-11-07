"""Core business logic for the MCP FastAPI service."""

from __future__ import annotations

import json
from typing import Any
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
    BlendRunInput,
    BlendRequest,
    BlendResponse,
    DBSearchResponse,
    GetSnippetsRequest,
    MutateRequest,
    MutateResponse,
    PeekSnippetsRequest,
    PeekSnippetsResponse,
    ProvenanceRequest,
    ProvenanceResponse,
    SearchRequest,
    SearchToolResponse,
)
from ..snippets import build_snippet_item, cap_by_budget
from ..storage import RedisStorage
from ..utils import hash_query


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
    async def search_lane(self, lane: str, request: SearchRequest) -> SearchToolResponse:
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
    async def blend(self, request: BlendRequest, *, parent_meta: dict[str, Any] | None = None) -> BlendResponse:
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
    async def peek_snippets(self, request: PeekSnippetsRequest) -> PeekSnippetsResponse:
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
        rows = await self.storage.zslice(key, start, stop, desc=True)
        doc_ids = [doc_id for doc_id, _ in rows]
        doc_metadata = await self.storage.get_docs(doc_ids)

        items = [
            build_snippet_item(doc_id, doc_metadata.get(doc_id, {}), request.fields, request.per_field_chars)
            for doc_id in doc_ids
        ]
        capped, used_bytes, truncated = cap_by_budget(items, min(request.budget_bytes, self.settings.peek_budget_bytes))
        total_docs = await self.redis.zcard(key)
        cursor = None
        if request.offset + len(capped) < total_docs:
            cursor = str(request.offset + len(capped))

        return PeekSnippetsResponse(
            items=capped,
            used_bytes=used_bytes,
            truncated=truncated,
            peek_cursor=cursor,
        )

    # ------------------------------------------------------------------ #
    async def get_snippets(self, request: GetSnippetsRequest) -> dict[str, dict[str, str]]:
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
    async def mutate_run(self, request: MutateRequest) -> MutateResponse:
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

        response = await self.blend(blend_request, parent_meta=meta)
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
