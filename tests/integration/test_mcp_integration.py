from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest

from rrfusion.config import Settings
from rrfusion.mcp.service import MCPService
from rrfusion.models import BlendRequest, PeekSnippetsRequest


@asynccontextmanager
async def service_context() -> AsyncIterator[MCPService]:
    settings = Settings()
    service = MCPService(settings)
    try:
        yield service
    finally:
        await service.close()


async def _ensure_runs(service: MCPService) -> tuple[str, str]:
    fulltext = await service.search_lane("fulltext", q="integration query", top_k=200)
    semantic = await service.search_lane("semantic", q="integration query", top_k=200)
    return fulltext.run_id_lane, semantic.run_id_lane


@pytest.mark.integration
@pytest.mark.asyncio
async def test_peek_snippets_flow_with_real_backends():
    async with service_context() as service:
        lane_ft, lane_sem = await _ensure_runs(service)
        blend_request = BlendRequest(
            runs=[
                {"lane": "fulltext", "run_id_lane": lane_ft},
                {"lane": "semantic", "run_id_lane": lane_sem},
            ],
            weights={"recall": 1.0, "precision": 1.0},
            rrf_k=60,
            beta=1.0,
            family_fold=False,
            target_profile={},
            top_m_per_lane={"fulltext": 10000, "semantic": 10000},
            k_grid=[10, 20, 50],
        )
        blend_resp = await service.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta=blend_request.beta,
            family_fold=blend_request.family_fold,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
        )
        run_id = blend_resp.run_id

        peek_req = PeekSnippetsRequest(
            run_id=run_id,
            offset=0,
            limit=50,
            fields=["title", "abst", "claim", "description"],
            per_field_chars={"title": 120, "abst": 360, "claim": 360, "description": 600},
            budget_bytes=4096,
        )
        response = await service.peek_snippets(
            run_id=run_id,
            offset=peek_req.offset,
            limit=peek_req.limit,
            fields=peek_req.fields,
            per_field_chars=peek_req.per_field_chars,
            budget_bytes=peek_req.budget_bytes,
        )

        assert response.items, "integration peek should return docs"
        assert response.peek_cursor is not None
        assert response.used_bytes > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_lane_handles_thousands_of_docs():
    async with service_context() as service:
        response = await service.search_lane("fulltext", q="large search", top_k=5000)
        assert response.count_returned == 5000
        assert response.run_id_lane


@pytest.mark.integration
@pytest.mark.asyncio
async def test_large_search_and_peek_budget_flow():
    async with service_context() as service:
        fulltext = await service.search_lane("fulltext", q="budget stress query", top_k=5000)
        semantic = await service.search_lane("semantic", q="budget stress query", top_k=5000)

        min_count = min(fulltext.count_returned, semantic.count_returned)
        if min_count < 4000:
            pytest.skip("DB stub not configured for large-result scenarios (need >=4k hits)")

        blend_request = BlendRequest(
            runs=[
                {"lane": "fulltext", "run_id_lane": fulltext.run_id_lane},
                {"lane": "semantic", "run_id_lane": semantic.run_id_lane},
            ],
            weights={"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5},
            rrf_k=60,
            beta=1.0,
            family_fold=False,
            target_profile={},
            top_m_per_lane={"fulltext": 5000, "semantic": 5000},
            k_grid=[10, 50, 100, 200],
        )
        fusion = await service.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta=blend_request.beta,
            family_fold=blend_request.family_fold,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
        )

        peek_request = PeekSnippetsRequest(
            run_id=fusion.run_id,
            offset=0,
            limit=80,
            fields=["title", "abst", "claim", "description"],
            per_field_chars={"title": 220, "abst": 520, "claim": 640, "description": 720},
            budget_bytes=20_480,
        )
        peek = await service.peek_snippets(
            run_id=peek_request.run_id,
            offset=peek_request.offset,
            limit=peek_request.limit,
            fields=peek_request.fields,
            per_field_chars=peek_request.per_field_chars,
            budget_bytes=peek_request.budget_bytes,
        )

        assert len(peek.items) >= 10
        assert peek.used_bytes >= 8000
        assert peek.truncated is True
        assert peek.peek_cursor is not None
