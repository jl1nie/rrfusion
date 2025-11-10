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

# ============================
# Prompts
# ============================

_HANDBOOK = """# RRFusion MCP Handbook (v1.1)

**Mission**: Maximize *effective* Fβ (default β=1) for prior-art retrieval using multi-lane search and code-aware fusion under no-gold-label conditions.  
**Transport**: HTTP / streamable-http at `/{base_path}` (default `/mcp`).  
**Auth**: Bearer token if configured.

> Notes
> - Lane raw scores are **incomparable**. Use **rank-based fusion (RRF)** as the primary method.  
> - `beta_fuse` below controls **precision/recall trade-off in fusion**, not the Fβ metric itself.

---

## 1. Pipeline (Agent-facing)
1) Normalize & synonymize query (LLM; acronyms, phrases, negatives)
2) Run lanes in parallel
   - `search_fulltext` → **precision-skewed** keyword evidence; expand recall via synonyms & larger `top_k`
   - `search_semantic` → embedding coverage with same filters to curb drift
3) Fuse via `blend_frontier_codeaware` (RRF + code prior)
4) Budget check with `peek_snippets` (head/match/mix)
5) Shortlist then `get_snippets`
6) If proxy-metrics unsatisfactory → `mutate_run` (weights / rrf_k / beta_fuse / filters)
7) Persist with `get_provenance`

---

## 2. Lane Tools

### `search_fulltext`
- **Args**: 
  - `q: string`
  - `filters?: { must?: Cond[]; should?: Cond[]; must_not?: Cond[] }`
  - `top_k: int = 800`
  - `rollup?: { family_fold?: boolean = true }`
  - `budget_bytes: int = 4096`
  - `seed?: int`, `trace_id?: string`
- **Cond**: `{ field: "ipc|fi|cpc|pubyear|assignee|country", op: "in|range|eq|neq", value: any }`
- **Tips**: Use field boosts server-side (claims > title > abstract > desc). Keep `top_k` generous (200–1000), and mirror filters in semantic.

### `search_semantic`
- **Args**: same as `search_fulltext`
- **Tips**: Keep `q` concise (≤256 chars). Apply same `filters` when drift risk exists.

---

## 3. Fusion

### `blend_frontier_codeaware`
- **Args**:
  - `runs: [{ lane: "fulltext|semantic", run_id: string }]`
  - `weights?: { fulltext?: float, semantic?: float }`  (lane **rank** weights)
  - `rrf_k: int = 60`
  - `beta_fuse: float = 1.0`  ← higher → recall, lower → precision
  - `family_fold: boolean = true`
  - `target_profile?: { ipc|fi|cpc: { code: weight } }`
  - `code_idf_mode?: "global"|"domain" = "global"`
  - `top_m_per_lane?: int`
  - `k_grid?: [int]`   // optional sweep
  - `peek?: { limit?: int }`
- **Code prior**:
  - Let `idf_c = log(N / (1 + freq(c)))`
  - Let query-side code weights be `w_q(c)` from PRF/LLM.
  - Doc-side contribution: `s_code(d) = Σ_{c∈C_d} idf_c * w_q(c)`
  - Final rank score ~ `RRF(rank)` adjusted by lane weights, then **re-ranked** by `s_code(d)` with a small mixing λ.

---

## 4. Snippet Budgeting

### `peek_snippets`
- **Args**:
  - `run_id`, `offset=0`, `limit=12`
  - `fields?: ["title","abstract","claims","desc"]`
  - `per_field_chars?: { field: int }`
  - `claim_count=3`
  - `strategy: "head"|"match"|"mix"`
  - `budget_bytes=12288`
- **Patterns**:
  - `head` → titles/abstracts
  - `match` → query highlights focus
  - `mix` → balanced

### `get_snippets`
- **Args**: `ids[]`, `fields?`, `per_field_chars?`, `seed?`
- **Note**: Independent of fusion cursor; random access OK.

---

## 5. Iterative Tuning

### `mutate_run`
- **Args**: 
  - `run_id`
  - `delta`: `{ weights?|rrf_k?|beta_fuse?|filters?|top_m_per_lane?|family_fold? }`
- **Loop**: Adjust → re-peek → compare proxy P/R/Fβ at fixed K.

### `get_provenance`
- **Args**: `run_id`
- **Returns**: inputs, filters, lane stats, fusion params (`weights, rrf_k, beta_fuse`), code prior snapshot, metrics, `seed`, `trace_id`.

---

## 6. Metrics & Logging (No-gold regime)

- **Emit**:  
  - `lane.top_k`, `fuse.rrf_k`, `beta_fuse`, `hit@k`, `p@k`, `r@k`, `f_beta@k`, `diversity@k`
- **Proxy definitions**:
  - `p@k` ≔ cross-lane agreement ratio at K (RRF ∩ lane tops)
  - `r@k` ≔ PRF 再検索での再出現率 at K
  - `f_beta@k` ≔ above two combined as Fβ (β from Mission)
  - `diversity@k` ≔ 1 − avg pairwise similarity (MMR 由来)

---

## 7. Security
- Never send PII/secret in queries.  
- Server injects downstream API keys.  
- Client supplies **Bearer** token only.  
- Redact snippets beyond `budget_bytes`.

---

"""

_TOOL_RECIPES = """# Tool Recipes & Few-shot (v1.1)

## search_fulltext — examples
**Good**
```json
{
  "q": "grant-free uplink HARQ process scheduling",
  "filters": {
    "must": [{"field":"ipc","op":"in","value":["H04W72/04","H04L1/18"]}],
    "should": [{"field":"pubyear","op":"range","value":{"gte":2018}}],
    "must_not": []
  },
  "top_k": 500
}
```

**Good (phrase/near)**
```json
{
  "q": "\"uplink grant-free\"~3 early HARQ feedback",
  "filters": {"must":[{"field":"cpc","op":"in","value":["H04W72/12"]}]},
  "top_k": 600
}
```

**Bad**
```json
{"q":"HARQ","top_k":10}
```

---

## search_semantic — examples
**Good**
```json
{
  "q": "contention-based uplink, early HARQ feedback for URLLC",
  "filters": {"must":[{"field":"cpc","op":"in","value":["H04W72/12"]}]},
  "top_k": 400
}
```

---

## blend_frontier_codeaware — examples
**Equal-weight fuse**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
  "rrf_k": 60,
  "beta_fuse": 1.0,
  "family_fold": true
}
```

**Favor codes**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
  "target_profile": {"ipc":{"H04W72/04":1.2,"H04L1/18":1.0}},
  "rrf_k": 50,
  "beta_fuse": 0.9
}
```

---

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

---

## get_snippets — examples
```json
{
  "ids":["US2023XXXXXXA1","EPXXXXXXXB1"],
  "fields":["title","abstract","claims"],
  "per_field_chars":{"claims":1200}
}
```

---

## mutate_run — examples
```json
{
  "run_id":"FUSION_123",
  "delta":{"weights":{"semantic":1.2,"fulltext":1.0},"rrf_k":50,"beta_fuse":1.2}
}
```

---

## get_provenance — example
```json
{"run_id":"FUSION_123"}
```

"""
# ============================
@mcp.prompt(name="RRFusion MCP Handbook")
def _prompt_handbook() -> str:
    return _HANDBOOK.format(base_path="mcp")


@mcp.prompt(name="Tool Recipes")
def _prompt_recipes() -> str:
    return _TOOL_RECIPES


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
    return await _require_service().blend(
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
    signature: mutate_run(run_id: str, delta: MutateDelta)
    prompts/list:
    - "List how the ranking shifts if we bump semantic weight via {delta.weights}"
    - "List frontier deltas after tightening beta_fuse/rrf_k on run {run_id}"
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
