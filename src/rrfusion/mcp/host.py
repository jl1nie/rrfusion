from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

from fastmcp import FastMCP, Prompt
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


# ============================
# Tools
# ============================

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
    prompts/list:
    - "List high-recall patent families mentioning {q} with IPC filters {filters}"
    - "List prior art using only keyword evidence for {q}"
    prompts/get:
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
    prompts/list:
    - "List semantically similar inventions about {q}"
    - "List embedding-driven hits that stay on-spec for {q}"
    prompts/get:
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
    prompts/list:
    - "List the best fusion frontier balancing recall and precision for {runs}"
    - "List fused rankings that favor IPC {target_profile}"
    prompts/get:
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
    prompts/list:
    - "List snippet previews for the top {limit} docs in fusion run {run_id}"
    - "List concise abstracts for positions {offset}-{offset + limit}"
    prompts/get:
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
    prompts/list:
    - "List detailed snippets for the decision-ready doc IDs {ids}"
    - "List claims plus abstracts for specific documents after shortlisting"
    prompts/get:
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
    prompts/list:
    - "List how the ranking shifts if we bump semantic weight via {delta.weights}"
    - "List frontier deltas after tightening beta/rrf_k on run {run_id}"
    prompts/get:
    - "Get a fresh run_id derived from {run_id} with updated weights/filters"
    """
    return await _require_service().mutate_run(run_id=run_id, delta=delta)


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
    return await _require_service().provenance(run_id)


# ============================
# Prompts
# ============================

_HANDBOOK = """# RRFusion MCP Handbook (v1.0)

**Mission**: Maximize Fβ (default β=1) for prior-art retrieval with multi-lane search (fulltext + semantic) and code-aware fusion.  
**Transport**: HTTP/streamable-http at `/{base_path}` (default `/mcp`).  
**Auth**: Bearer token is required if configured on the server.

## 1. Pipeline (Agent-facing)
1) Normalize and expand query (synonyms / acronyms)
2) Run lanes in parallel
   - `search_fulltext` → high recall on keyword evidence
   - `search_semantic` → embedding-driven coverage on-spec
3) Fuse with `blend_frontier_codeaware` (RRF with β control)
4) Peek text budget with `peek_snippets` (head/match/mix)
5) Shortlist and fetch payloads via `get_snippets`
6) If metrics unsatisfactory → `mutate_run` (weights/rrf_k/β)
7) Persist trail with `get_provenance`

## 2. Lane Tools (I/O + Guidance)
### `search_fulltext`
- **Args**: `q`, `filters?`, `top_k=1000`, `rollup?`, `budget_bytes=4096`
- **Tips**: Prefer generous `top_k` (200–1000) for recall. Use IPC/FI/CPC in `filters.must` to restrain drift.

### `search_semantic`
- **Args**: `q`, `filters?`, `top_k=1000`, `rollup?`, `budget_bytes=4096`
- **Tips**: Keep query concise (≤256 chars). When drift risk, mirror the same filters as fulltext.

## 3. Fusion
### `blend_frontier_codeaware`
- **Args**: `runs[]`, `weights?`, `rrf_k=60`, `beta=1.0`, `family_fold=True`, `target_profile?`, `top_m_per_lane?`, `k_grid?`, `peek?`
- **Heuristics**:
  - Start with equal weights; tune via `mutate_run`.
  - Increase `beta` to favor recall; lower to favor precision.
  - `family_fold=True` to avoid family duplicates in top-K.

## 4. Snippet Budgeting
### `peek_snippets`
- **Args**: `run_id`, `offset=0`, `limit=12`, `fields?`, `per_field_chars?`, `claim_count=3`, `strategy=head|match|mix`, `budget_bytes=12288`
- **Patterns**:
  - `head` for abstracts/titles; `match` to focus on query highlights; `mix` to balance.
  - Use `per_field_chars` to cap long fields deterministically.

### `get_snippets`
- **Args**: `ids[]`, `fields?`, `per_field_chars?`
- **Note**: Independent of fusion cursor; safe for random access after shortlist.

## 5. Iterative Tuning
### `mutate_run`
- **Args**: `run_id`, `delta` (weights / rrf_k / beta / filters)
- **Loop**: Adjust → re-peek → compare P/R/Fβ at fixed K.

### `get_provenance`
- **Args**: `run_id`
- **Use**: Audit lineage, reproduce settings, checkpoint good frontiers.

## 6. Metrics & Logging
- Emit: `lane.top_k`, `fuse.rrf_k`, `beta`, `hit@k`, `p@k`, `r@k`, `f_beta@k`
- Backoff: retry on 429/5xx with exponential backoff (≤5 attempts).

## 7. Security
- Never send PII/secret content in queries. Server injects API keys for downstream systems. Client provides **Bearer** token only.

"""

_TOOL_RECIPES = """# Tool Recipes & Few-shot (v1.0)

## search_fulltext — examples
**Good**
```json
{
  "q": "grant-free uplink HARQ process scheduling",
  "filters": {"must": [{"field":"ipc","op":"in","value":["H04W72/04","H04L1/18"]}]},
  "top_k": 500
}
```
**Bad**
```json
{"q":"HARQ","top_k":10}
```

## search_semantic — examples
**Good**
```json
{
  "q": "contention-based uplink, early HARQ feedback for URLLC",
  "filters": {"must":[{"field":"cpc","op":"in","value":["H04W72/12"]}]},
  "top_k": 400
}
```

## blend_frontier_codeaware — examples
**Equal-weight fuse**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
  "rrf_k": 60,
  "beta": 1.0,
  "family_fold": true
}
```
**Favor codes**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
  "target_profile": {"ipc":{"H04W72/04":1.2,"H04L1/18":1.0}},
  "rrf_k": 50
}
```

## peek_snippets — examples
```json
{
  "run_id":"FUSION_123",
  "offset":0,
  "limit":12,
  "strategy":"mix",
  "budget_bytes": 12288
}
```

## get_snippets — examples
```json
{
  "ids":["US2023XXXXXXA1","EPXXXXXXXB1"],
  "fields":["title","abstract","claims"],
  "per_field_chars":{"claims":1200}
}
```

## mutate_run — examples
```json
{
  "run_id":"FUSION_123",
  "delta":{"weights":{"semantic":1.2,"fulltext":1.0},"rrf_k":50,"beta":1.2}
}
```

## get_provenance — example
```json
{"run_id":"FUSION_123"}
```
"""

@mcp.prompt_list
def prompt_list():
    return [
        Prompt(
            name="RRFusion MCP Handbook",
            description="End-to-end pipeline, parameter guidance, metrics, and security.",
            tags=["handbook", "retrieval", "fusion", "f1"]
        ),
        Prompt(
            name="Tool Recipes",
            description="Per-tool signatures with good/bad examples and few-shot JSON.",
            tags=["recipes", "examples"]
        ),
    ]


@mcp.prompt_get
def prompt_get(name: str):
    if name == "RRFusion MCP Handbook":
        # inject base path info for readability
        base_path = "/mcp"
        return _HANDBOOK.format(base_path=base_path)
    if name == "Tool Recipes":
        return _TOOL_RECIPES
    raise ValueError(f"unknown prompt: {name}")


# ============================
# Custom routes
# ============================

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
