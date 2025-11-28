from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest

from rrfusion.config import Settings
from rrfusion.mcp.backends import CIBackend, LaneBackendRegistry
from rrfusion.mcp.service import MCPService
from rrfusion.models import (
    BlendRequest,
    FulltextParams,
    MultiLaneEntryRequest,
    MultiLaneSearchRequest,
    MultiLaneStatus,
    PeekSnippetsRequest,
    SemanticParams,
    ProvenanceResponse,
)


@asynccontextmanager
async def service_context() -> AsyncIterator[MCPService]:
    settings = Settings()
    ci_backend = CIBackend(settings)
    registry = LaneBackendRegistry(
        settings,
        overrides={
            "fulltext": ci_backend,
            "semantic": ci_backend,
            "original_dense": ci_backend,
        },
    )
    service = MCPService(settings, backend_registry=registry)
    try:
        yield service
    finally:
        await service.close()


def _stub_max_results() -> int:
    value = os.getenv("STUB_MAX_RESULTS")
    if not value:
        return 2000
    try:
        parsed = int(value)
    except ValueError:
        return 2000
    return max(1, min(10_000, parsed))


async def _ensure_runs(service: MCPService) -> tuple[str, str]:
    fulltext = await service.search_lane("fulltext", query="integration query", top_k=200)
    semantic = await service.search_lane("semantic", text="integration query", top_k=200)
    _assert_took_ms(fulltext.meta.took_ms, "fulltext integration search")
    _assert_took_ms(semantic.meta.took_ms, "semantic integration search")
    return fulltext.run_id, semantic.run_id


def _assert_took_ms(value: int | None, source: str) -> None:
    if value is None or value < 0:
        raise AssertionError(f"{source} missing timing metadata took_ms={value}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_lane_search_batch_runs_sequential():
    async with service_context() as service:
        lanes = [
            MultiLaneEntryRequest(
                lane_name="multi_fulltext",
                tool="search_fulltext",
                lane="fulltext",
                params=FulltextParams(query="multi lane integration", top_k=60),
            ),
            MultiLaneEntryRequest(
                lane_name="multi_semantic",
                tool="search_semantic",
                lane="semantic",
                params=SemanticParams(text="integration multi lane scenario", top_k=60),
            ),
        ]
        request = MultiLaneSearchRequest(lanes=lanes, trace_id="integ-multi-lane")
        response = await service.multi_lane_search(request)
        assert response.meta is not None
        assert response.meta.trace_id == "integ-multi-lane"
        assert response.meta.success_count == 2
        assert response.meta.error_count == 0
        assert len(response.results) == 2
        assert response.results[0].lane_name == "multi_fulltext"
        assert response.results[1].lane_name == "multi_semantic"
        for entry in response.results:
            assert entry.status == MultiLaneStatus.success
            assert entry.error is None
            assert entry.handle is not None
            _assert_took_ms(entry.took_ms, f"{entry.lane_name} multi-lane timing")


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
            beta_fuse=1.0,
            target_profile={},
            top_m_per_lane={"fulltext": 10000, "semantic": 10000},
            k_grid=[10, 20, 50],
        )
        blend_resp = await service.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta_fuse=blend_request.beta_fuse,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
        )
        run_id = blend_resp.run_id

        peek_req = PeekSnippetsRequest(
            run_id=run_id,
            offset=0,
            limit=50,
            fields=["title", "abst", "claim", "desc"],
            per_field_chars={
                "title": 120,
                "abst": 360,
                "claim": 360,
                "desc": 600,
            },
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

        assert response.snippets, "integration peek should return docs"
        assert response.meta.peek_cursor is not None
        assert response.meta.used_bytes > 0
        _assert_took_ms(response.meta.took_ms, "peek snippets flow")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_publication_returns_full_fields():
    async with service_context() as service:
        search_resp = await service.search_lane("fulltext", query="fulltext", top_k=1)
        peek = await service.peek_snippets(
            run_id=search_resp.run_id,
            limit=1,
            fields=["title", "abst", "claim"],
            per_field_chars={"title": 64, "abst": 128, "claim": 128},
        )
        assert peek.snippets, "search should produce a snippet for publication lookup"
        doc_id = peek.snippets[0].id

        publication = await service.get_publication(
            ids=[doc_id],
            id_type="app_doc_id",
            fields=["title", "abst", "desc", "app_doc_id", "app_id", "pub_id", "exam_id"],
        )
        snippet = publication.get(doc_id, {})
        assert snippet.get("app_doc_id") == doc_id
        assert snippet.get("app_id"), "app_id should appear in publication"
        assert snippet.get("pub_id"), "pub_id should appear in publication"
        assert snippet.get("exam_id"), "exam_id should appear in publication"
        assert snippet.get("desc"), "Full description should be present"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_lane_handles_thousands_of_docs():
    async with service_context() as service:
        response = await service.search_lane("fulltext", query="large search", top_k=5000)
        expected = min(5000, _stub_max_results())
        assert response.meta.count_returned == expected
        assert response.run_id
        _assert_took_ms(response.meta.took_ms, "large search lane")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_large_search_and_peek_budget_flow():
    async with service_context() as service:
        fulltext = await service.search_lane(
            "fulltext", query="budget stress query", top_k=5000
        )
        semantic = await service.search_lane(
            "semantic", text="budget stress query", top_k=5000
        )

        _assert_took_ms(fulltext.meta.took_ms, "budget stress fulltext")
        _assert_took_ms(semantic.meta.took_ms, "budget stress semantic")

        min_count = min(
            fulltext.meta.count_returned or 0,
            semantic.meta.count_returned or 0,
        )
        if min_count < 4000:
            pytest.skip(
                "DB stub not configured for large-result scenarios (need >=4k hits)"
            )

        blend_request = BlendRequest(
            runs=[
                {"lane": "fulltext", "run_id_lane": fulltext.run_id},
                {"lane": "semantic", "run_id_lane": semantic.run_id},
            ],
            weights={"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5},
            rrf_k=60,
            beta_fuse=1.0,
            target_profile={},
            top_m_per_lane={"fulltext": 5000, "semantic": 5000},
            k_grid=[10, 50, 100, 200],
        )
        fusion = await service.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta_fuse=blend_request.beta_fuse,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
        )
        _assert_took_ms(fusion.meta.get("took_ms"), "large fusion run")

        peek_request = PeekSnippetsRequest(
            run_id=fusion.run_id,
            offset=0,
            limit=80,
            fields=["title", "abst", "claim", "desc"],
            per_field_chars={
                "title": 220,
                "abst": 520,
                "claim": 640,
                "desc": 720,
            },
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

        assert len(peek.snippets) >= 10
        _assert_took_ms(peek.meta.took_ms, "large peek")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_provenance_returns_structured_metadata_for_lane_and_fusion():
    async with service_context() as service:
        # Prepare a lane run (fulltext_wide 相当)
        lane_resp = await service.search_lane("fulltext", query="provenance lane", top_k=200)
        lane_prov = await service.provenance(lane_resp.run_id)
        assert isinstance(lane_prov, ProvenanceResponse)
        # lane meta should at least include basic config
        assert lane_prov.meta.get("lane") == "fulltext"
        assert lane_prov.meta.get("query")
        # code_distributions and config_snapshot are populated for lane runs
        assert isinstance(lane_prov.code_distributions, dict)
        assert "fi" in lane_prov.code_distributions
        assert isinstance(lane_prov.config_snapshot, dict)
        assert lane_prov.config_snapshot.get("lane") == "fulltext"
        assert lane_prov.config_snapshot.get("query")

        # Prepare a fusion run and check fusion provenance
        semantic_resp = await service.search_lane("semantic", text="provenance semantic", top_k=200)
        blend_request = BlendRequest(
            runs=[
                {"lane": "fulltext", "run_id_lane": lane_resp.run_id},
                {"lane": "semantic", "run_id_lane": semantic_resp.run_id},
            ],
            weights={"fulltext": 1.0, "semantic": 1.0},
            rrf_k=60,
            beta_fuse=1.0,
            target_profile={},
            top_m_per_lane={"fulltext": 200, "semantic": 200},
            k_grid=[10, 20, 50],
        )
        fusion = await service.blend(
            runs=blend_request.runs,
            weights=blend_request.weights,
            rrf_k=blend_request.rrf_k,
            beta_fuse=blend_request.beta_fuse,
            target_profile=blend_request.target_profile,
            top_m_per_lane=blend_request.top_m_per_lane,
            k_grid=blend_request.k_grid,
        )
        fusion_prov = await service.provenance(fusion.run_id)
        assert isinstance(fusion_prov, ProvenanceResponse)
        # fusion meta must mark run_type and have a recipe
        assert fusion_prov.meta.get("run_type") == "fusion"
        assert isinstance(fusion_prov.meta.get("recipe"), dict)
        # fusion provenance should expose lane_contributions and code_distributions
        assert isinstance(fusion_prov.code_distributions, dict)
        assert isinstance(fusion_prov.lane_contributions, dict)
        # config_snapshot mirrors the recipe for fusion runs
        assert isinstance(fusion_prov.config_snapshot, dict)
        assert fusion_prov.config_snapshot.get("rrf_k") == 60


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_dense_lane_metadata():
    async with service_context() as service:
        response = await service.search_lane("original_dense", text="dense boost query", top_k=40)
        # Inspect lane metadata via provenance instead of direct response fields
        prov = await service.provenance(response.run_id)
        assert prov.meta.get("lane") == "original_dense"
        params = prov.meta.get("params") or {}
        assert params.get("semantic_style") == "original_dense"
        _assert_took_ms(response.meta.took_ms, "original_dense search")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snippet_identifier_fields_available():
    async with service_context() as service:
        search_resp = await service.search_lane("fulltext", query="id fields", top_k=5)
        peek = await service.peek_snippets(
            run_id=search_resp.run_id,
            limit=3,
            fields=["app_doc_id", "pub_id", "exam_id"],
            per_field_chars={"app_doc_id": 32, "app_id": 32, "pub_id": 32, "exam_id": 32},
        )
        doc_ids = [snippet.id for snippet in peek.snippets]
        assert doc_ids, "search should return doc IDs for snippet validations"
        _assert_took_ms(search_resp.meta.took_ms, "id field search")

        snippets = await service.get_snippets(
            ids=doc_ids,
            fields=["app_doc_id", "app_id", "pub_id", "exam_id"],
            per_field_chars={"app_doc_id": 32, "app_id": 32, "pub_id": 32, "exam_id": 32},
        )

        for doc_id in doc_ids:
            snippet = snippets.get(doc_id, {})
            assert snippet.get("app_doc_id") == doc_id
            assert snippet.get("app_id"), "app_id should be populated"
            assert snippet.get("pub_id"), "pub_id should be populated"
            assert snippet.get("exam_id"), "exam_id should be populated"
