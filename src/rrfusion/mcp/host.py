from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

from fastmcp import FastMCP
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from rrfusion.config import get_settings
from rrfusion.mcp.service import MCPService
from rrfusion.models import (
    BlendResponse,
    BlendRunInput,
    Filters,
    MutateDelta,
    MutateResponse,
    PeekConfig,
    PeekSnippetsResponse,
    ProvenanceResponse,
    RollupConfig,
    SearchToolResponse,
)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
)
_service: MCPService | None = None
LifespanState = dict[str, Any]


@asynccontextmanager
async def _lifespan(_: FastMCP[LifespanState]) -> AsyncIterator[LifespanState]:
    global _service
    service = MCPService(settings)
    _service = service
    try:
        yield {"service": "rrfusion"}
    finally:
        await service.close()
        _service = None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Simple bearer token authentication for FastMCP's HTTP transport."""

    def __init__(self, app, *, token: str | None):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if not self._token or request.scope.get("type") != "http":
            return await call_next(request)

        auth_header = request.headers.get("authorization") or ""
        scheme, _, candidate = auth_header.partition(" ")

        if scheme.lower() != "bearer" or not candidate:
            return JSONResponse(
                {"detail": "Missing or invalid Authorization header"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        if candidate != self._token:
            return JSONResponse(
                {"detail": "Invalid bearer token"},
                status_code=403,
            )

        return await call_next(request)


class RRFusionFastMCP(FastMCP):
    """FastMCP subclass that injects Starlette middleware for HTTP transports."""

    def __init__(self, *args, auth_token: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._auth_token = auth_token

    def http_app(
        self,
        path: str | None = None,
        middleware: list[StarletteMiddleware] | None = None,
        json_response: bool | None = None,
        stateless_http: bool | None = None,
        transport: Literal["http", "streamable-http", "sse"] = "http",
    ):
        http_middleware = list(middleware or [])
        if self._auth_token:
            http_middleware.insert(
                0,
                StarletteMiddleware(BearerAuthMiddleware, token=self._auth_token),
            )

        return super().http_app(
            path=path,
            middleware=http_middleware,
            json_response=json_response,
            stateless_http=stateless_http,
            transport=transport,
        )


mcp = RRFusionFastMCP(
    name="rrfusion-mcp",
    instructions="Multi-lane patent search with RRF fusion, code-aware frontier, and snippet budgeting.",
    version="0.1.0",
    lifespan=_lifespan,
    auth_token=settings.mcp_api_token,
)


def _require_service() -> MCPService:
    if _service is None:
        raise RuntimeError("MCP service is not initialized")
    return _service


@mcp.tool
async def search_fulltext(
    q: str,
    filters: Filters | None = None,
    top_k: int = 1000,
    rollup: RollupConfig | None = None,
    budget_bytes: int = 4096,
) -> SearchToolResponse:
    """
    signature: search_fulltext(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    promits/list:
    - "List high-recall patent families mentioning {q} with IPC filters {filters}"
    prompts/list:
    - "List prior art using only keyword evidence for {q}"
    prompts/gets:
    - "Get a lane run handle I can feed into fusion for {q}"
    """

    return await _require_service().search_lane(
        "fulltext",
        q=q,
        filters=filters,
        top_k=top_k,
        rollup=rollup,
        budget_bytes=budget_bytes,
    )


@mcp.tool
async def search_semantic(
    q: str,
    filters: Filters | None = None,
    top_k: int = 1000,
    rollup: RollupConfig | None = None,
    budget_bytes: int = 4096,
) -> SearchToolResponse:
    """
    signature: search_semantic(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    promits/list:
    - "List semantically similar inventions about {q}"
    prompts/list:
    - "List embedding-driven hits that stay on-spec for {q}"
    prompts/gets:
    - "Get the semantic lane handle so I can blend with run {q}"
    """

    return await _require_service().search_lane(
        "semantic",
        q=q,
        filters=filters,
        top_k=top_k,
        rollup=rollup,
        budget_bytes=budget_bytes,
    )


@mcp.tool
async def blend_frontier_codeaware(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta: float = 1.0,
    family_fold: bool = True,
    target_profile: dict[str, dict[str, float]] | None = None,
    top_m_per_lane: dict[str, int] | None = None,
    k_grid: list[int] | None = None,
    peek: PeekConfig | None = None,
) -> BlendResponse:
    """
    signature: blend_frontier_codeaware(
        runs: list[BlendRunInput],
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        beta: float = 1.0,
        family_fold: bool = True,
        target_profile: dict[str, dict[str, float]] | None = None,
        top_m_per_lane: dict[str, int] | None = None,
        k_grid: list[int] | None = None,
        peek: PeekConfig | None = None,
    )
    promits/list:
    - "List the best fusion frontier balancing recall and precision for {runs}"
    prompts/list:
    - "List fused rankings that favor IPC {target_profile}"
    prompts/gets:
    - "Get a fusion run_id with frontier stats so I can peek snippets for {runs}"
    """

    return await _require_service().blend(
        runs=runs,
        weights=weights,
        rrf_k=rrf_k,
        beta=beta,
        family_fold=family_fold,
        target_profile=target_profile,
        top_m_per_lane=top_m_per_lane,
        k_grid=k_grid,
        peek=peek,
    )


@mcp.tool
async def peek_snippets(
    run_id: str,
    offset: int = 0,
    limit: int = 12,
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
    claim_count: int = 3,
    strategy: Literal["head", "match", "mix"] = "head",
    budget_bytes: int = 12_288,
) -> PeekSnippetsResponse:
    """
    signature: peek_snippets(
        run_id: str,
        offset: int = 0,
        limit: int = 12,
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
        claim_count: int = 3,
        strategy: Literal["head","match","mix"] = "head",
        budget_bytes: int = 12288,
    )
    promits/list:
    - "List snippet previews for the top {limit} docs in fusion run {run_id}"
    prompts/list:
    - "List concise abstracts for positions {offset}-{offset + limit}"
    prompts/gets:
    - "Get the next peek_cursor so I can continue streaming run {run_id}"
    """

    return await _require_service().peek_snippets(
        run_id=run_id,
        offset=offset,
        limit=limit,
        fields=fields,
        per_field_chars=per_field_chars,
        claim_count=claim_count,
        strategy=strategy,
        budget_bytes=budget_bytes,
    )


@mcp.tool
async def get_snippets(
    ids: list[str],
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]:
    """
    signature: get_snippets(ids: list[str], fields: list[str] | None = None, per_field_chars: dict[str, int] | None = None)
    promits/list:
    - "List detailed snippets for the decision-ready doc IDs {ids}"
    prompts/list:
    - "List claims plus abstracts for specific documents after shortlisting"
    prompts/gets:
    - "Get the text payloads for ids {ids} without touching the fusion cursor"
    """

    return await _require_service().get_snippets(
        ids=ids,
        fields=fields,
        per_field_chars=per_field_chars,
    )


@mcp.tool
async def mutate_run(run_id: str, delta: MutateDelta) -> MutateResponse:
    """
    signature: mutate_run(run_id: str, *, delta: MutateDelta)
    promits/list:
    - "List how the ranking shifts if we bump semantic weight via {delta.weights}"
    prompts/list:
    - "List frontier deltas after tightening beta/rrf_k on run {run_id}"
    prompts/gets:
    - "Get a fresh run_id derived from {run_id} with updated weights/filters"
    """

    return await _require_service().mutate_run(run_id=run_id, delta=delta)


@mcp.tool
async def get_provenance(run_id: str) -> ProvenanceResponse:
    """
    signature: get_provenance(run_id: str)
    promits/list:
    - "List the recipe parameters that produced fusion run {run_id}"
    prompts/list:
    - "List the historical lineage for run {run_id}"
    prompts/gets:
    - "Get parent/history handles so I can audit or reproduce run {run_id}"
    """

    return await _require_service().provenance(run_id)


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> JSONResponse:
    """Lightweight health check for load balancers hitting GET /healthz."""

    return JSONResponse({"status": "ok"})


__all__ = ["mcp"]


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        path="/mcp",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
