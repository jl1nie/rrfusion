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
        response.meta.took_ms = took_ms
    elif isinstance(response, PeekSnippetsResponse):
        response.meta.took_ms = took_ms
    elif isinstance(response, BlendResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, MutateResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, ProvenanceResponse):
        response.meta["took_ms"] = took_ms


def _normalize_optional_list(value: Any) -> Any:
    """Coerce empty objects/lists for optional list-typed tool arguments to None."""
    if value is None:
        return None
    if value == {}:
        return None
    if isinstance(value, list):
        return value
    # Any other unexpected type: leave as-is and let validation fail loudly
    return value


def _normalize_optional_dict(value: Any) -> Any:
    """Coerce empty dict-like values for optional dict-typed arguments to None."""
    if value is None:
        return None
    if value == {}:
        return None
    return value


def _normalize_optional_str(value: Any) -> Any:
    """Normalize empty strings or empty containers for optional str-like arguments to None."""
    if value is None:
        return None
    if value == "" or value == {} or value == []:
        return None
    return value


def _normalize_date_value(value: Any) -> Any:
    def _format(v: Any) -> Any:
        if isinstance(v, int):
            s = str(v)
            if len(s) == 8 and s.isdigit():
                return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if isinstance(v, str) and len(v) == 8 and v.isdigit():
            return f"{v[:4]}-{v[4:6]}-{v[6:]}"
        return v

    if isinstance(value, (list, tuple)):
        return [_format(v) for v in value]
    if isinstance(value, dict):
        return {k: _format(v) for k, v in value.items()}
    return _format(value)


def _normalize_filters(filters: list[Any] | None) -> list[Cond]:
    """Coerce incoming filters to a list of Cond models."""
    if not filters:
        return []
    normalized: list[Cond] = []
    for entry in filters:
        if isinstance(entry, Cond):
            normalized.append(entry)
        elif isinstance(entry, dict):
            payload = dict(entry)
            if "value" in payload:
                payload["value"] = _normalize_date_value(payload["value"])
            if payload.get("op") == "range" and isinstance(payload.get("value"), dict):
                value_dict = payload["value"]
                start = value_dict.get("from") or value_dict.get("start")
                end = value_dict.get("to") or value_dict.get("end")
                if start is not None and end is not None:
                    payload["value"] = [start, end]
            normalized.append(Cond.model_validate(payload))
        else:
            raise RuntimeError(f"unexpected filter type: {type(entry)}")
    return normalized


def _guess_lane_from_run_id(run_id: str) -> str:
    if run_id.startswith("fulltext"):
        return "fulltext"
    if run_id.startswith("semantic"):
        return "semantic"
    if run_id.startswith("original_dense"):
        return "original_dense"
    return "fulltext"


def _normalize_blend_runs(runs: list[Any] | None) -> list[BlendRunInput]:
    normalized: list[BlendRunInput] = []
    if not runs:
        return normalized
    for entry in runs:
        if isinstance(entry, BlendRunInput):
            normalized.append(entry)
        elif isinstance(entry, dict):
            payload = dict(entry)
            if "run_id_lane" not in payload and "run_id" in payload:
                payload["run_id_lane"] = payload["run_id"]
                payload.pop("run_id", None)
            if "lane" not in payload and "run_id_lane" in payload:
                payload["lane"] = _guess_lane_from_run_id(payload["run_id_lane"])
            normalized.append(BlendRunInput.model_validate(payload))
        elif isinstance(entry, str):
            lane_part, _, run_part = entry.partition("-")
            candidate_lane = lane_part if lane_part in {"fulltext", "semantic", "original_dense"} else _guess_lane_from_run_id(entry)
            normalized.append(
                BlendRunInput(
                    lane=candidate_lane,
                    run_id_lane=run_part if run_part else entry,
                )
            )
        else:
            raise RuntimeError(f"invalid run entry type: {type(entry)}")
    return normalized


def _normalize_target_profile(
    target_profile: dict[str, Any] | None,
) -> dict[str, dict[str, float]] | None:
    """
    Coerce a flat or partially-specified target_profile into
    taxonomy -> {code -> weight} form.

    - If a flat dict[str,float|int] is given, assume FI taxonomy and wrap
      as {"fi": {...}}.
    - If dict[str,dict] is given, coerce inner values to float.
    """
    if not target_profile:
        return None
    # Detect flat dict: all values are scalar numbers
    if all(
        not isinstance(value, dict) and isinstance(value, (int, float))
        for value in target_profile.values()
    ):
        return {"fi": {code: float(weight) for code, weight in target_profile.items()}}
    # Otherwise assume taxonomy->dict
    normalized: dict[str, dict[str, float]] = {}
    for taxonomy, codes in target_profile.items():
        if not isinstance(codes, dict):
            # Skip unexpected shapes to avoid crashing
            continue
        normalized[taxonomy] = {
            code: float(weight) for code, weight in codes.items()
        }
    return normalized or None


# ============================
# Prompts
# ============================

# ============================
# Tools
# ============================


@mcp.tool
async def search_fulltext(
    query: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    field_boosts: dict[str, float] | None = None,
    top_k: int = 800,
    code_freq_top_k: int | None = 30,
    trace_id: str | None = None,
) -> SearchToolResponse:
    """
    summary: Run lexical full-text search over patent documents using TT-IDF/BM25-style scoring.
    when_to_use:
      - Use in the wide_search step for the fulltext lane.
      - Use when you need high-recall keyword-based candidates before fusion.
    arguments:
      query:
        type: string
        required: true
        description: Search expression describing the technical idea in the corpus language.
      filters:
        type: list[Cond]
        required: false
        description: Optional structured filters (e.g., years, jurisdictions, classification codes).
      fields:
        type: list[SnippetField]
        required: false
        description: Which text sections to index/return; defaults to ["abst","title","claim"].
      field_boosts:
        type: dict[string,float]
        required: false
        description: Optional per-field boosts for the fulltext backend (e.g., {"title":100,"abst":10,"claim":5}); controls Patentfield weights.
      top_k:
        type: int
        required: false
        description: Maximum number of hits to retrieve for this lane (typically up to 800).
      code_freq_top_k:
        type: int
        required: false
        description: Limit how many codes appear in the lane-level `code_freqs` summary (default: 30, set to `None` to surface all codes).
      trace_id:
        type: string
        required: false
        description: Optional identifier to correlate this lane run in logs/telemetry.
    constraints:
      - Query must be non-empty and written in the primary language of the target corpus.
      - Keep top_k within reasonable limits to avoid unnecessary latency.
    returns:
      run_id_lane:
        description: Handle for this fulltext lane run, to be used in fusion, peek_snippets, and provenance.
      notes:
        - Response also includes lane-level code frequencies and timing metadata in response.meta.took_ms.
        - Text sections are not stored in this response; use peek_snippets/get_snippets for snippet text.
    """
    start = perf_counter()
    response = await _require_service().search_lane(
        "fulltext",
        query=query,
        filters=_normalize_filters(filters),
        fields=_normalize_optional_list(fields),
        field_boosts=_normalize_optional_dict(field_boosts),
        top_k=top_k,
        trace_id=trace_id,
        code_freq_top_k=code_freq_top_k,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def search_semantic(
    text: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    feature_scope: str | None = None,
    top_k: int = 800,
    code_freq_top_k: int | None = 30,
    trace_id: str | None = None,
    semantic_style: SemanticStyle = "default",
) -> SearchToolResponse:
    """
    summary: Run similarity-score-based semantic search using natural language guidance.
    when_to_use:
      - Use in the wide_search step for the semantic lane when you need contextual similarity.
      - Use when you want to adjust which sections (claims/background/etc.) drive the similarity score.
    arguments:
      text:
        type: string
        required: true
        description: Natural language description of the technical idea (1–3 paragraphs).
      filters:
        type: list[Cond]
        required: false
        description: Restrict by years, jurisdictions, languages, or other metadata fields.
      fields:
        type: list[SnippetField]
        required: false
        description: Which text sections to return in lane snippets; defaults to ["abst","title","claim"].
      feature_scope:
        type: '"wide" | "title_abst_claims" | "claims_only" | "top_claim" | "background_jp"'
        required: false
        description: Semantic feature scope controlling which sections contribute to similarity (mapped to Patentfield feature).
      top_k:
        type: int
        required: false
        description: Number of top results to retrieve (typically up to 800) for ranking storage only (snippet text is not returned).
      code_freq_top_k:
        type: int
        required: false
        description: Limit how many codes appear in the lane-level `code_freqs` summary (default: 30, set to `None` to surface all codes).
      trace_id:
        type: string
        required: false
        description: Optional identifier to correlate this lane run in logs/telemetry.
      semantic_style:
        type: '"default" | "original_dense"'
        required: false
        description: Internal implementation selector; "default" is the standard setting.
    constraints:
      - Text must be written in the primary language of the target corpus.
      - semantic_style must be "default" for this deployment; "original_dense" is disabled in v1.3.
    returns:
      run_id_lane:
        description: ID of this semantic search run, to be used in fusion, peek_snippets, and provenance.
      notes:
        - Results include doc_id, similarity score, and code information for downstream fusion and analysis.
        - Text sections are not stored; ask for snippets via peek_snippets/get_snippets when needed.
    """
    lane = "semantic" if semantic_style == "default" else "original_dense"
    start = perf_counter()
    response = await _require_service().search_lane(
        lane,
        text=text,
        filters=_normalize_filters(filters),
        fields=_normalize_optional_list(fields),
        feature_scope=_normalize_optional_str(feature_scope),
        top_k=top_k,
        trace_id=trace_id,
        semantic_style=semantic_style,
        code_freq_top_k=code_freq_top_k,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def blend_frontier_codeaware(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta_fuse: float = 1.0,
    target_profile: dict[str, dict[str, float]] | None = None,
    top_m_per_lane: dict[str, int] | None = None,
    k_grid: list[int] | None = None,
    peek: PeekConfig | None = None,
) -> BlendResponse:
    """
    summary: Fuse multiple lane runs with RRF and optional code-aware boosts, returning a frontier summary.
    when_to_use:
      - Use after obtaining lane run handles from search_fulltext and/or search_semantic.
      - Use when you need a single fused ranking plus precision/recall-style frontier metrics.
    arguments:
      runs:
        type: list[BlendRunInput]
        required: true
        description: Lane/run_id pairs referencing existing lane search runs.
      weights:
        type: dict[str, float]
        required: false
        description: Lane weight map keyed by physical lanes and code (e.g., {"fulltext":1.0,"semantic":0.8,"code":0.5}).
      rrf_k:
        type: int
        required: false
        description: RRF tail parameter controlling contribution from deeper ranks (default 60).
      beta_fuse:
        type: float
        required: false
        description: F-beta-like bias for frontier computation (>1 for recall, <1 for precision).
      target_profile:
        type: dict[str, dict[str, float]]
        required: false
        description: Code prior by taxonomy (e.g., {"ipc":{"H04L":0.7}, "fi":{"H04L1/00":1.0}}) for code-aware boosts.
      top_m_per_lane:
        type: dict[str, int]
        required: false
        description: Maximum docs to read per lane before fusion.
      k_grid:
        type: list[int]
        required: false
        description: K values at which to compute the frontier summary (P_star, R_star, F_beta_star).
      peek:
        type: PeekConfig
        required: false
        description: Optional inline peek configuration to sample a few top fused snippets.
    constraints:
      - Each run in runs must reference an existing lane run_id with compatible filters.
      - At least one lane run is required; otherwise fusion cannot proceed.
    returns:
      run_id:
        description: Fusion run identifier; use it with peek_snippets, mutate_run, and get_provenance.
      notes:
        - Response includes pairs_top (ranking), frontier stats, code frequency summaries, and contribution breakdowns.
    """
    start = perf_counter()
    response = await _require_service().blend(
        runs=_normalize_blend_runs(runs),
        weights=weights,
        rrf_k=rrf_k,
        beta_fuse=beta_fuse,
        target_profile=_normalize_target_profile(target_profile),
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
    budget_bytes: int = 12_288,
) -> PeekSnippetsResponse:
    """
    summary: Return budgeted snippet previews for a lane or fusion run.
    when_to_use:
      - Use after fusion (or lane search) when you need to inspect a slice of the ranking.
      - Use when you must respect a strict byte budget for snippet previews.
    arguments:
      run_id:
        type: string
        required: true
        description: Lane or fusion run identifier whose ranking you want to peek.
      offset:
        type: int
        required: false
        description: Zero-based starting position in the ranking.
      limit:
        type: int
        required: false
        description: Maximum number of documents to consider from offset (capped by peek_max_docs).
      fields:
        type: list[string]
        required: false
        description: Fields to include in snippets; defaults to ["title","abst","claim"] when omitted.
      per_field_chars:
        type: dict[string,int]
        required: false
        description: Per-field character limits before byte budgeting is applied.
      budget_bytes:
        type: int
        required: false
        description: Global JSON byte budget for all returned snippets combined.
    constraints:
      - Effective limit is min(limit, PEEK_MAX_DOCS); large windows may be truncated by budget_bytes.
      - If no items fit within the budget, a single minimal fallback snippet may be returned.
    returns:
      snippets:
        description: List of snippet objects with id and per-field text, plus meta including peek_cursor and used_bytes.
      notes:
        - Use meta.peek_cursor to request the next slice; stop when it becomes null.
    """
    start = perf_counter()
    response = await _require_service().peek_snippets(
        run_id=run_id,
        offset=offset,
        limit=limit,
        fields=fields,
        per_field_chars=per_field_chars,
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
    summary: Fetch detailed snippets for a selected set of document IDs.
    when_to_use:
      - Use after you have shortlisted specific doc_ids from a ranking.
      - Use when you need richer snippets than peek_snippets provides for final review or export.
    arguments:
      ids:
        type: list[string]
        required: true
        description: Document identifiers to fetch snippets for (typically pub_id values from rankings).
      fields:
        type: list[string]
        required: false
        description: Fields to include in the snippet payload; defaults to ["title","abst","claim"].
      per_field_chars:
        type: dict[string,int]
        required: false
        description: Per-field character caps; larger than peek_snippets when you need more context.
    constraints:
      - This call does not paginate; keep ids size modest to avoid large payloads.
    returns:
      snippets:
        description: Mapping from doc_id to a dict of {field: text} snippets.
      notes:
        - Use this for decision-ready docs; for uncapped full publications, prefer get_publication.
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
    summary: Retrieve uncapped publication-level fields for one or more documents.
    when_to_use:
      - Use when snippet budgets would hide important detail (e.g., full description).
      - Use when you need canonical identifiers (pub_id/app_doc_id/exam_id) in the payload.
    arguments:
      ids:
        type: list[string]
        required: true
        description: Identifiers whose publication records you want to fetch.
      id_type:
        type: '"pub_id" | "app_doc_id" | "exam_id"'
        required: false
        description: Which identifier namespace the ids list refers to (defaults to "pub_id").
      fields:
        type: list[string]
        required: false
        description: Publication fields to return; omit to use a sensible default set including desc and IDs.
    constraints:
      - This call bypasses snippet byte budgets; use selectively for deep dives, not wide scans.
    returns:
      publications:
        description: Mapping from requested identifier to a dict of publication-level fields.
      notes:
        - Use get_publication for a small set of key docs when you need their full context.
    """
    return await _require_service().get_publication(ids=ids, id_type=id_type, fields=fields)


@mcp.tool
async def mutate_run(run_id: str, delta: MutateDelta) -> MutateResponse:
    """
    summary: Recompute a fusion run with updated blending parameters while reusing cached lane results.
    when_to_use:
      - Use after a successful fusion when you want to explore alternative weights or RRF constants.
      - Use when you need a new frontier variant without repeating lane searches.
    arguments:
      run_id:
        type: string
        required: true
        description: Fusion run identifier to mutate.
      delta:
        type: MutateDelta
        required: true
        description: Replacement values for weights, rrf_k, and/or beta_fuse to apply to the stored recipe.
    constraints:
      - Delta fields overwrite the stored recipe values; they are not interpreted as +/- offsets.
      - The referenced run_id must point to an existing fusion run, not a lane run.
    returns:
      new_run_id:
        description: Identifier of the newly computed fusion run with updated parameters.
      notes:
        - Response includes the new frontier, updated recipe (with delta recorded), and timing metadata.
    """
    start = perf_counter()
    response = await _require_service().mutate_run(run_id=run_id, delta=delta)
    _record_tool_timing(response, _elapsed_ms(start))
    return response


@mcp.tool
async def get_provenance(run_id: str) -> ProvenanceResponse:
    """
    summary: Inspect the stored recipe and lineage metadata for a given run.
    when_to_use:
      - Use when you need to audit how a lane or fusion run was produced.
      - Use before mutating or reproducing a run so you can reuse its configuration.
    arguments:
      run_id:
        type: string
        required: true
        description: Lane or fusion run identifier whose provenance you want to inspect.
    constraints:
      - The run_id must exist in storage; otherwise an error is returned.
    returns:
      provenance:
        description: Object containing the stored recipe, parent, and history fields for the run.
      notes:
        - Use this payload to reconstruct or explain fusion decisions and to chain further mutations.
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
