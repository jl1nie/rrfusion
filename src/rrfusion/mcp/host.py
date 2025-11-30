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
    BlendRequest,
    BlendResponse,
    BlendRunInput,
    Cond,
    FulltextParams,
    Lane,
    LaneCodeSummary,
    MutateDelta,
    MutateResponse,
    MultiLaneEntryRequest,
    MultiLaneSearchLite,
    MultiLaneSearchRequest,
    MultiLaneSearchResponse,
    MultiLaneStatus,
    MultiLaneTool,
    PeekConfig,
    PeekSnippetsResponse,
    ProvenanceResponse,
    RunHandle,
    SearchMetaLite,
    SearchParams,
    SemanticParams,
    normalize_filters,
)
from rrfusion.mcp.llm_views import build_multi_lane_search_lite

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
)
_service: MCPService | None = None
LifespanState = dict[str, Any]
_MULTILANE_CODE_LIMIT = 3
_DEFAULT_COUNTRY = "JP"


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


def _normalize_filters(raw_filters: Any | None) -> list[Cond]:
    """
    Backwards-compatible wrapper around rrfusion.models.normalize_filters
    used by tests. Raises RuntimeError on invalid payloads.
    """
    try:
        return normalize_filters(raw_filters)
    except Exception as exc:  # pragma: no cover - behavior verified in tests
        raise RuntimeError("invalid filters payload") from exc


def _normalize_filters_with_default_country(raw_filters: Any | None) -> list[Cond]:
    """
    Normalize filters and ensure a default JP country filter is present
    when the caller did not specify any country constraint.
    """
    conds = normalize_filters(raw_filters)
    for cond in conds:
        if cond.field == "country":
            return conds
    conds.append(Cond(lop="and", field="country", op="in", value=[_DEFAULT_COUNTRY]))
    return conds


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
    if isinstance(response, PeekSnippetsResponse):
        response.meta.took_ms = took_ms
    elif isinstance(response, BlendResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, MutateResponse):
        response.meta["took_ms"] = took_ms
    elif isinstance(response, ProvenanceResponse):
        response.meta["took_ms"] = took_ms

#
# Normalization helpers
#

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
    target_profile: Any | None,
) -> dict[str, dict[str, float]] | None:
    """
    Coerce a flat or partially-specified target_profile into
    taxonomy -> {code -> weight} form.

    - If a flat dict[str,float|int] is given, assume FI taxonomy and wrap
      as {"fi": {...}}.
    - If dict[str,dict] is given, coerce inner values to float.
    """
    if not target_profile or not isinstance(target_profile, dict):
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


def _normalize_multilane_entries(
    entries: list[Any] | None,
) -> list[MultiLaneEntryRequest]:
    normalized: list[MultiLaneEntryRequest] = []
    if not entries:
        return normalized
    for entry in entries:
        if isinstance(entry, MultiLaneEntryRequest):
            normalized.append(entry)
        elif isinstance(entry, dict):
            normalized.append(_normalize_multilane_entry_dict(entry))
        else:
            raise RuntimeError(f"invalid multi-lane entry type: {type(entry)}")
    return normalized


def _normalize_multilane_entry_dict(payload: dict[str, Any]) -> MultiLaneEntryRequest:
    data = dict(payload)
    tool = _normalize_multilane_tool(data.get("tool"), data.get("lane"))
    lane = _normalize_multilane_lane(data.get("lane"), tool, data.get("params"))
    params = _normalize_multilane_params(data.pop("params", None), tool, lane)
    lane_name = _normalize_multilane_lane_name(data, tool, lane)
    return MultiLaneEntryRequest(
        lane_name=lane_name,
        tool=tool,
        lane=lane,
        params=params,
    )


def _normalize_multilane_tool(
    value: Any | None,
    lane_hint: Any | None = None,
) -> MultiLaneTool:
    if isinstance(value, MultiLaneTool):
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in {"search_fulltext", "fulltext"}:
            return "search_fulltext"
        if normalized in {"search_semantic", "semantic"}:
            return "search_semantic"
    if isinstance(lane_hint, str):
        normalized = lane_hint.lower()
        if normalized in {"semantic", "original_dense"}:
            return "search_semantic"
        if normalized == "fulltext":
            return "search_fulltext"
    raise ValueError(f"unsupported multi-lane tool: {value!r}")


def _normalize_multilane_lane(
    candidate: Any | None,
    tool: MultiLaneTool,
    params: Any | None,
) -> Lane:
    if isinstance(candidate, str):
        normalized = candidate.lower()
        if normalized in {"fulltext", "semantic", "original_dense"}:
            return normalized
    if tool == "search_semantic":
        if isinstance(params, dict):
            style = params.get("semantic_style")
            if isinstance(style, str) and style.lower() == "original_dense":
                return "original_dense"
        return "semantic"
    return "fulltext"


def _normalize_multilane_lane_name(
    payload: dict[str, Any],
    tool: MultiLaneTool,
    lane: Lane,
) -> str:
    for key in ("lane_name", "name", "alias", "label"):
        candidate = payload.get(key)
        if candidate:
            return str(candidate)
    return f"{tool}_{lane}"


def _normalize_multilane_params(
    raw: Any | None,
    tool: MultiLaneTool,
    lane: Lane,
) -> SearchParams:
    if isinstance(raw, (FulltextParams, SemanticParams)):
        return raw
    if raw is None:
        raise ValueError("params required for multi-lane entry")
    if isinstance(raw, str):
        payload: dict[str, Any] = {"query" if tool == "search_fulltext" else "text": raw}
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        raise ValueError(f"unsupported params type: {type(raw)}")

    payload["filters"] = _normalize_filters_with_default_country(payload.get("filters"))

    fields_value = _normalize_optional_list(payload.get("fields"))
    if fields_value is None:
        payload.pop("fields", None)
    else:
        payload["fields"] = fields_value

    field_boosts_value = _normalize_optional_dict(payload.get("field_boosts"))
    if field_boosts_value is None:
        payload.pop("field_boosts", None)
    else:
        payload["field_boosts"] = field_boosts_value

    feature_scope_value = _normalize_optional_str(payload.get("feature_scope"))
    if feature_scope_value is None:
        payload.pop("feature_scope", None)
    else:
        payload["feature_scope"] = feature_scope_value

    def _coerce_key(dest: str, candidates: tuple[str, ...]) -> None:
        if dest in payload:
            return
        for key in candidates:
            value = payload.pop(key, None)
            if value is not None:
                payload[dest] = value
                break

    if lane == "fulltext":
        _coerce_key("query", ("query", "q", "text"))
        if "query" not in payload:
            raise ValueError("query required for fulltext multi-lane params")
        return FulltextParams.model_validate(payload)
    _coerce_key("text", ("text", "query", "q"))
    if "text" not in payload:
        raise ValueError("text required for semantic multi-lane params")
    if lane == "original_dense":
        payload["semantic_style"] = "original_dense"
    return SemanticParams.model_validate(payload)


#
# Execution helpers
#

async def _execute_multilane_search(
    lanes: list[MultiLaneEntryRequest],
    trace_id: str | None,
) -> MultiLaneSearchResponse:
    normalized = _normalize_multilane_entries(lanes)
    request = MultiLaneSearchRequest(lanes=normalized, trace_id=trace_id)
    return await _require_service().multi_lane_search(request)


async def _execute_blend_frontier(
    runs: list[Any] | None,
    weights: dict[str, float] | None,
    rrf_k: int | None,
    beta_fuse: float | None,
    target_profile: Any | None,
    top_m_per_lane: dict[str, int] | None,
    k_grid: list[int] | None,
    peek: PeekConfig | None,
) -> BlendResponse:
    return await _require_service().blend(
        runs=_normalize_blend_runs(runs),
        weights=weights,
        rrf_k=rrf_k,
        beta_fuse=beta_fuse,
        target_profile=_normalize_target_profile(target_profile),
        top_m_per_lane=top_m_per_lane,
        k_grid=k_grid,
        peek=peek,
    )


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
    top_k: int = 50,
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id",
) -> list[str]:
    """
    summary: Run a TT-IDF/BM25-style full-text search and return publication IDs only.
    when_to_use:
      - Use for user-facing keyword search where you only need a ranked list of publication identifiers.
      - Use when you do not need lane handles or code frequency summaries and want to keep context small.
    arguments:
      query:
        type: string
        required: true
        description: Search expression describing the technical idea in the corpus language.
      filters:
        type: list[Cond]
        required: false
        description: Optional structured filter conditions (IPC/FI/CPC/year/assignee/country/ft).
      top_k:
        type: int
        required: false
        description: Number of top-ranked hits to return (default: 50).
      id_type:
        type: '"pub_id" | "app_doc_id" | "app_id" | "exam_id"'
        required: false
        description: Which identifier type to return for each hit; falls back to internal doc_id if missing.
    constraints:
      - Query must be non-empty and written in the primary language of the target corpus.
    returns:
      ids:
        description: Ranked list of identifiers corresponding to id_type, in decreasing relevance order.
      notes:
        - To obtain lane handles and code frequencies for fusion workflows, use rrf_search_fulltext_raw instead.
    """
    search_response = await _require_service().search_lane(
        "fulltext",
        query=query,
        filters=_normalize_filters_with_default_country(filters),
        top_k=top_k,
    )
    peek = await _require_service().peek_snippets(
        run_id=search_response.run_id,
        offset=0,
        limit=top_k,
        fields=[id_type],
        per_field_chars={id_type: 64},
        budget_bytes=4096,
    )
    ids: list[str] = []
    for snippet in peek.snippets:
        value = snippet.fields.get(id_type, "")
        ids.append(value or snippet.id)
    return ids


@mcp.tool
async def search_semantic(
    text: str,
    filters: list[Cond] | None = None,
    top_k: int = 50,
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id",
) -> list[str]:
    """
    summary: Run semantic similarity search and return publication IDs only.
    when_to_use:
      - Use when you want a user-facing semantic search that returns just a ranked list of identifiers.
    arguments:
      text:
        type: string
        required: true
        description: Natural language description of the technical idea (1–3 paragraphs).
      filters:
        type: list[Cond]
        required: false
        description: Optional structured filter conditions (IPC/FI/CPC/year/assignee/country/ft).
      top_k:
        type: int
        required: false
        description: Number of top-ranked hits to return (default: 50).
      id_type:
        type: '"pub_id" | "app_doc_id" | "app_id" | "exam_id"'
        required: false
        description: Which identifier type to return for each hit; falls back to internal doc_id if missing.
    constraints:
      - Text must be written in the primary language of the target corpus.
    returns:
      ids:
        description: Ranked list of identifiers corresponding to id_type, in decreasing semantic similarity.
      notes:
        - To obtain lane handles and code frequencies for fusion workflows, use rrf_search_semantic_raw instead.
    """
    response = await _require_service().search_lane(
        "semantic",
        text=text,
        filters=_normalize_filters_with_default_country(filters),
        top_k=top_k,
    )
    peek = await _require_service().peek_snippets(
        run_id=response.run_id,
        offset=0,
        limit=top_k,
        fields=[id_type],
        per_field_chars={id_type: 64},
        budget_bytes=4096,
    )
    ids: list[str] = []
    for snippet in peek.snippets:
        value = snippet.fields.get(id_type, "")
        ids.append(value or snippet.id)
    return ids


@mcp.tool
async def rrf_search_fulltext_raw(params: FulltextParams) -> RunHandle:
    """
    summary: Run a raw fulltext lane search and return only a run handle with lightweight meta.
    when_to_use:
      - Use from RRFusion backend workflows when you only need a lane run_id for later fusion and snippet retrieval.
      - Prefer this over search_fulltext when you do not need lane-level code frequencies or detailed metadata.
    arguments:
      params:
        type: FulltextParams
        required: true
        description: Structured fulltext search parameters including query, filters, and top_k.
    returns:
      run_id:
        description: Lane run identifier to be passed into fusion and provenance tools.
      meta:
        description: Lightweight search metadata (top_k, count_returned, truncated, took_ms).
    """
    # Delegate directly to the internal lane search and return its RunHandle.
    return await _require_service().search_lane("fulltext", params=params)


@mcp.tool
async def rrf_search_semantic_raw(params: SemanticParams) -> RunHandle:
    """
    summary: Run a raw semantic lane search and return only a run handle with lightweight meta.
    when_to_use:
      - Use from RRFusion backend workflows that will later fuse or inspect semantic runs via run_id.
    arguments:
      params:
        type: SemanticParams
        required: true
        description: Structured semantic search parameters including text, filters, feature_scope, and top_k.
    returns:
      run_id:
        description: Lane run identifier for this semantic search.
      meta:
        description: Lightweight search metadata (top_k, count_returned, truncated, took_ms).
    """
    lane: Lane = "semantic" if params.semantic_style == "default" else "original_dense"
    # Delegate directly to the internal lane search and return its RunHandle.
    return await _require_service().search_lane(lane, params=params)


@mcp.tool
async def rrf_blend_frontier(request: BlendRequest) -> RunHandle:
    """
    summary: Fuse multiple lane runs into a single fusion run and return only a run handle.
    when_to_use:
      - Use from RRFusion backend workflows after obtaining lane run_ids via rrf_search_*_raw.
      - Prefer this over older fusion tools when you only need a fusion run_id and lightweight meta.
    arguments:
      request:
        type: BlendRequest
        required: true
        description: Fusion configuration including lane runs, weights, rrf_k, beta_fuse, and target_profile.
    returns:
      run_id:
        description: Fusion run identifier to be passed into provenance and snippet tools.
      meta:
        description: Lightweight fusion metadata (top_k, count_returned, took_ms).
    """
    start = perf_counter()
    response = await _require_service().blend(
        runs=request.runs,
        weights=request.weights,
        rrf_k=request.rrf_k,
        beta_fuse=request.beta_fuse,
        target_profile=request.target_profile,
        top_m_per_lane=request.top_m_per_lane,
        k_grid=request.k_grid,
        peek=request.peek,
        representatives=request.representatives,
    )
    _record_tool_timing(response, _elapsed_ms(start))
    count = len(response.pairs_top)
    meta = SearchMetaLite(
        top_k=count,
        count_returned=count,
        truncated=None,
        took_ms=response.meta.get("took_ms"),
    )
    return RunHandle(run_id=response.run_id, meta=meta)


@mcp.tool
async def rrf_mutate_run(run_id: str, delta: MutateDelta) -> RunHandle:
    """
    summary: Create a new fusion run by applying a parameter delta to an existing fusion run.
    when_to_use:
      - Use when exploring alternative weights, rrf_k, or beta_fuse settings based on an existing fusion run.
    arguments:
      run_id:
        type: string
        required: true
        description: Existing fusion run identifier to mutate.
      delta:
        type: MutateDelta
        required: true
        description: Replacement values for weights, rrf_k, and/or beta_fuse in the stored recipe.
    returns:
      run_id:
        description: Newly created fusion run identifier after applying the delta.
      meta:
        description: Lightweight metadata about the recomputed fusion (top_k, count_returned, took_ms).
    """
    start = perf_counter()
    response = await _require_service().mutate_run(run_id=run_id, delta=delta)
    _record_tool_timing(response, _elapsed_ms(start))
    count = len(response.frontier) if response.frontier else 0
    meta = SearchMetaLite(
        top_k=count,
        count_returned=count,
        truncated=None,
        took_ms=response.meta.get("took_ms"),
    )
    return RunHandle(run_id=response.new_run_id, meta=meta)


@mcp.tool
async def run_multilane_search(
    lanes: list[MultiLaneEntryRequest],
    trace_id: str | None = None,
) -> MultiLaneSearchLite:
    """
    summary: Execute multiple search lanes and return a compressed summary of their outcomes.
    when_to_use:
      - When you only need lane handles, timing, and top code snippets for LLM context.
      - Use after wide search/code profiling when you want to keep the response payload small.
    arguments:
      lanes:
        type: list[MultiLaneEntryRequest]
        required: true
        description: Ordered batch of lane specifications (lane_name, tool, lane, params).
      trace_id:
        type: string
        required: false
        description: Trace identifier propagated to the lightweight response.
    returns:
      lanes:
        description: Summaries for each lane with status, handles, and top codes.
      note:
        - This tool omits full per-lane payloads to conserve context and instead returns RunHandle objects and lightweight code summaries.
    """
    response = await _execute_multilane_search(lanes, trace_id)
    lite = build_multi_lane_search_lite(response)

    # Enrich lane summaries with lightweight code frequency snapshots from storage.
    service = _require_service()
    for lane_summary in lite.lanes:
        if (
            lane_summary.status != MultiLaneStatus.success
            or lane_summary.handle is None
        ):
            continue
        freqs = await service.storage.get_freq_summary(
            lane_summary.handle.run_id, lane_summary.lane
        )
        if not freqs:
            continue
        top_codes: dict[str, list[str]] = {}
        for taxonomy, distribution in freqs.items():
            if not distribution:
                continue
            sorted_codes = sorted(
                distribution.items(), key=lambda kv: kv[1], reverse=True
            )
            top_codes[taxonomy] = [
                code for code, _ in sorted_codes[:_MULTILANE_CODE_LIMIT]
            ]
        if top_codes:
            lane_summary.code_summary = LaneCodeSummary(top_codes=top_codes)

    return lite


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
        description: Document identifiers to fetch snippets for (typically EPODOC-style application IDs from rankings).
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
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id",
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]:
    """
    summary: Retrieve publication-level fields for one or more documents, with optional per-field character caps.
    when_to_use:
      - Use when snippet budgets would hide important detail (e.g., full description).
      - Use when you need canonical identifiers (pub_id/app_doc_id/exam_id) in the payload.
    arguments:
      ids:
        type: list[string]
        required: true
        description: Identifiers whose publication records you want to fetch.
      id_type:
        type: '"pub_id" | "app_doc_id" | "app_id" | "exam_id"'
        required: false
        description: Which identifier namespace the ids list refers to (defaults to "app_id").
      fields:
        type: list[string]
        required: false
        description: Publication fields to return; omit to use a sensible default set including desc and IDs.
      per_field_chars:
        type: dict[string,int]
        required: false
        description: Optional per-field character caps; if omitted, a publication-specific default larger than get_snippets is applied to avoid overflowing LLM context.
    constraints:
      - This call is intended for deep dives on a very small set of documents; even with per-field caps, keep ids size modest to avoid large payloads.
    returns:
      publications:
        description: Mapping from requested identifier to a dict of publication-level fields.
      notes:
        - Use get_publication for a small set of key docs when you need richer context than get_snippets; adjust per_field_chars only when you have clear reasons to widen or tighten the defaults.
    """
    return await _require_service().get_publication(
        ids=ids,
        id_type=id_type,
        fields=fields,
        per_field_chars=per_field_chars,
    )


@mcp.tool
async def get_provenance(
    run_id: str,
    top_k_lane: int = 20,
    top_k_code: int = 30,
) -> ProvenanceResponse:
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
      top_k_lane:
        type: integer
        required: false
        description: Maximum number of documents to include in lane_contributions (RRF top-ranked docs).
      top_k_code:
        type: integer
        required: false
        description: Maximum number of codes per taxonomy to include in code_distributions.
    constraints:
      - The run_id must exist in storage; otherwise an error is returned.
    returns:
      provenance:
        description: Object containing the stored recipe, parent, and history fields for the run.
      notes:
        - Use this payload to reconstruct or explain fusion decisions and to chain further mutations.
    """
    start = perf_counter()
    response = await _require_service().provenance(
        run_id, top_k_lane=top_k_lane, top_k_code=top_k_code
    )
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
