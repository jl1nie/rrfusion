from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, AsyncIterator, Literal

from fastmcp import FastMCP
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from rrfusion.config import get_settings
from rrfusion.mcp.recipes import HANDBOOK, TOOL_RECIPES
from rrfusion.mcp.service import MCPService
from rrfusion.models import (
    BlendResponse,
    BlendRunInput,
    Cond,
    MutateDelta,
    MutateResponse,
    PeekConfig,
    PeekSnippetsResponse,
    ProvenanceResponse,
    SearchToolResponse,
    SemanticStyle,
    SnippetField,
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


def _elapsed_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))


def _record_tool_timing(response: Any, took_ms: int) -> None:
    if isinstance(response, SearchToolResponse):
        response.response.meta.took_ms = took_ms
    elif isinstance(response, PeekSnippetsResponse):
        response.meta.took_ms = took_ms
    elif isinstance(response, BlendResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, MutateResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, ProvenanceResponse):
        response.meta["took_ms"] = took_ms


# ============================
# Prompts
# ============================

"""Handbook/recipe strings now live in rrfusion.mcp.recipes."""

@mcp.prompt(name="RRFusion MCP Handbook")
def _prompt_handbook() -> str:
    return HANDBOOK.format(base_path="mcp")


@mcp.prompt(name="Tool Recipes")
def _prompt_recipes() -> str:
    return TOOL_RECIPES


# ============================
# Tools
# ============================


@mcp.tool
async def search_fulltext(
    query: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    top_k: int = 800,
    budget_bytes: int = 4096,
    trace_id: str | None = None,
) -> SearchToolResponse:
    """
    signature: search_fulltext(
        query: str,
        filters: list[Cond] | None = None,
        fields: list[SnippetField] | None = None,
        top_k: int = 800,
        budget_bytes: int = 4096,
        trace_id: str | None = None,
    )
    prompts/list:
    - "List high-recall patent families mentioning {query} with IPC filters {filters}"
    - "List prior art using only keyword evidence for {query}"
    prompts/get:
    - "Get a lane run handle I can feed into fusion for {query}"
    """
    start = perf_counter()
    response = await _require_service().search_lane(
        "fulltext",
        query=query,
        filters=filters,
        fields=fields,
        top_k=top_k,
        budget_bytes=budget_bytes,
        trace_id=trace_id,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def search_semantic(
    text: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    top_k: int = 800,
    budget_bytes: int = 4096,
    trace_id: str | None = None,
    semantic_style: SemanticStyle = "default",
) -> SearchToolResponse:
    """
    signature: search_semantic(
        text: str,
        filters: list[Cond] | None = None,
        fields: list[SnippetField] | None = None,
        top_k: int = 800,
        budget_bytes: int = 4096,
        trace_id: str | None = None,
        semantic_style: Literal["default", "original_dense"] = "default",
    )
    prompts/list:
    - "List semantically similar inventions about {text}"
    - "List embedding-driven hits that stay on-spec for {text}"
    prompts/get:
    - "Get the semantic lane handle so I can blend with run {text}"
    """
    lane = "semantic" if semantic_style == "default" else "original_dense"
    start = perf_counter()
    response = await _require_service().search_lane(
        lane,
        text=text,
        filters=filters,
        fields=fields,
        top_k=top_k,
        budget_bytes=budget_bytes,
        trace_id=trace_id,
        semantic_style=semantic_style,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def blend_frontier_codeaware(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta_fuse: float = 1.0,
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
        beta_fuse: float = 1.0,
        family_fold: bool = True,
        target_profile: dict[str, dict[str, float]] | None = None,
        top_m_per_lane: dict[str, int] | None = None,
        k_grid: list[int] | None = None,
        peek: PeekConfig | None = None,
    )
    prompts/list:
    - "List the best fusion frontier balancing recall and precision for {runs}"
    - "List fused rankings that favor IPC {target_profile}"
    prompts/get:
    - "Get a fusion run_id with frontier stats so I can peek snippets for {runs}"
    """
    start = perf_counter()
    response = await _require_service().blend(
        runs=runs,
        weights=weights,
        rrf_k=rrf_k,
        beta_fuse=beta_fuse,
        family_fold=family_fold,
        target_profile=target_profile,
        top_m_per_lane=top_m_per_lane,
        k_grid=k_grid,
        peek=peek,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


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
    prompts/list:
    - "List snippet previews for the top {limit} docs in fusion run {run_id}"
    - "List concise absts for positions {offset}-{offset + limit}"
    prompts/get:
    - "Get the next peek_cursor so I can continue streaming run {run_id}"
    """
    start = perf_counter()
    response = await _require_service().peek_snippets(
        run_id=run_id,
        offset=offset,
        limit=limit,
        fields=fields,
        per_field_chars=per_field_chars,
        claim_count=claim_count,
        strategy=strategy,
        budget_bytes=budget_bytes,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def get_snippets(
    ids: list[str],
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]:
    """
    signature: get_snippets(ids: list[str], fields: list[str] | None = None, per_field_chars: dict[str, int] | None = None)
    prompts/list:
    - "List detailed snippets for the decision-ready doc IDs {ids}"
    - "List claims plus absts for specific documents after shortlisting"
    prompts/get:
    - "Get the text payloads for ids {ids} without touching the fusion cursor"
    """
    return await _require_service().get_snippets(
        ids=ids,
        fields=fields,
        per_field_chars=per_field_chars,
    )


@mcp.tool
async def get_publication(
    ids: list[str],
    id_type: Literal["pub_id", "app_doc_id", "exam_id"] = "pub_id",
    fields: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """
    signature: get_publication(ids: list[str], id_type: Literal["pub_id","app_doc_id","exam_id"], fields: list[str] | None = None)
    prompts/list:
    - "Retrieve the full public document for {ids} without truncation"
    - "Show publication/app/exam IDs for {ids}"
    prompts/get:
    - "Get the full text for {ids} using {id_type}"
    """
    return await _require_service().get_publication(ids=ids, id_type=id_type, fields=fields)


@mcp.tool
async def mutate_run(run_id: str, delta: MutateDelta) -> MutateResponse:
    """
    signature: mutate_run(run_id: str, delta: MutateDelta)
    prompts/list:
    - "List how the ranking shifts if we bump semantic weight via {delta.weights}"
    - "List frontier deltas after tightening beta_fuse/rrf_k on run {run_id}"
    prompts/get:
    - "Get a fresh run_id derived from {run_id} with updated weights/filters"
    """
    start = perf_counter()
    response = await _require_service().mutate_run(run_id=run_id, delta=delta)
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def get_provenance(run_id: str) -> ProvenanceResponse:
    """
    signature: get_provenance(run_id: str)
    prompts/list:
    - "List the recipe parameters that produced fusion run {run_id}"
    - "List the historical lineage for run {run_id}"
    prompts/get:
    - "Get parent/history handles so I can audit or reproduce run {run_id}"
    """
    start = perf_counter()
    response = await _require_service().provenance(run_id)
    _record_tool_timing(response, _elapsed_ms(start))
    return response


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
