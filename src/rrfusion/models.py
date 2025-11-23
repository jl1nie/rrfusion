"""Core MCP models aligned with AGENT.md plus fusion helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Lane = Literal["fulltext", "semantic", "original_dense"]
SemanticStyle = Literal["default", "original_dense"]
FeatureScope = Literal[
    "wide",
    "title_abst_claims",
    "claims_only",
    "top_claim",
    "background_jp",
]
SnippetField = Literal[
    "title",
    "abst",
    "claim",
    "desc",
    "app_doc_id",
    "pub_id",
    "exam_id",
    "app_date",
    "pub_date",
    "apm_applicants",
    "cross_en_applicants",
]

SEARCH_FIELDS_DEFAULT: list[SnippetField] = ["abst", "title", "claim"]


class Meta(BaseModel):
    lane: Lane | None = None
    top_k: int | None = None
    took_ms: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    retries: int | None = None


class Cond(BaseModel):
    lop: Literal["and", "or", "not"]
    field: Literal["ipc", "fi", "cpc", "pubyear", "assignee", "country", "ft"]
    op: Literal["in", "range", "eq", "neq"]
    value: Any

    @field_validator("lop", "op", mode="before")
    def _normalize_case(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value


class FilterEntry(BaseModel):
    field: str
    include_values: list[str] = Field(default_factory=list)
    exclude_values: list[str] = Field(default_factory=list)
    include_codes: list[str] = Field(default_factory=list)
    exclude_codes: list[str] = Field(default_factory=list)
    include_range: dict[str, str] | None = None
    exclude_range: dict[str, str] | None = None

    @field_validator("field", mode="before")
    def _normalize_field(cls, value: Any) -> Any:
        return str(value).lower()


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


def _conds_from_filter_entry(entry: FilterEntry) -> list[Cond]:
    conds: list[Cond] = []

    def add_cond(lop: str, op: str, value: Any) -> None:
        conds.append(Cond(lop=lop, field=entry.field, op=op, value=value))

    if entry.include_values:
        add_cond("and", "in", entry.include_values)
    if entry.exclude_values:
        add_cond("not", "in", entry.exclude_values)
    if entry.include_codes:
        add_cond("and", "in", entry.include_codes)
    if entry.exclude_codes:
        add_cond("not", "in", entry.exclude_codes)
    if entry.include_range:
        start = entry.include_range.get("from") or entry.include_range.get("start")
        end = entry.include_range.get("to") or entry.include_range.get("end")
        if start and end:
            add_cond("and", "range", [start, end])
    if entry.exclude_range:
        start = entry.exclude_range.get("from") or entry.exclude_range.get("start")
        end = entry.exclude_range.get("to") or entry.exclude_range.get("end")
        if start and end:
            add_cond("not", "range", [start, end])
    return conds


def normalize_filters(filters: list[Any] | None) -> list[Cond]:
    if not filters:
        return []
    normalized: list[Cond] = []
    for entry in filters:
        if isinstance(entry, Cond):
            normalized.append(entry)
        elif isinstance(entry, dict):
            if any(key in entry for key in ("include_values", "include_codes", "include_range")):
                filter_entry = FilterEntry.model_validate(entry)
                normalized.extend(_conds_from_filter_entry(filter_entry))
            else:
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


class IncludeOpts(BaseModel):
    codes: bool = True
    code_freqs: bool = True
    scores: bool = False


class SearchItem(BaseModel):
    doc_id: str
    score: float | None = None
    ipc_codes: list[str] | None = None
    cpc_codes: list[str] | None = None
    fi_codes: list[str] | None = None
    ft_codes: list[str] | None = None


class DBSearchResponse(BaseModel):
    items: list[SearchItem]
    code_freqs: dict[str, dict[str, int]] | None = None
    meta: Meta


class FulltextParams(BaseModel):
    query: str
    filters: list[Cond] = Field(default_factory=list)
    top_k: int = 800
    trace_id: str | None = None
    field_boosts: dict[str, float] | None = None
    include: IncludeOpts = IncludeOpts()
    fields: list[SnippetField] = Field(
        default_factory=lambda: SEARCH_FIELDS_DEFAULT.copy()
    )

    @field_validator("filters", mode="before")
    def _normalize_filters(cls, value: Any) -> list[Cond]:
        return normalize_filters(value)


class SemanticParams(BaseModel):
    text: str
    filters: list[Cond] = Field(default_factory=list)
    top_k: int = 800
    trace_id: str | None = None
    include: IncludeOpts = IncludeOpts()
    fields: list[SnippetField] = Field(
        default_factory=lambda: SEARCH_FIELDS_DEFAULT.copy()
    )
    semantic_style: SemanticStyle = "default"
    feature_scope: FeatureScope | None = None

    @field_validator("filters", mode="before")
    def _normalize_filters(cls, value: Any) -> list[Cond]:
        return normalize_filters(value)


SearchParams = FulltextParams | SemanticParams


MultiLaneTool = Literal["search_fulltext", "search_semantic"]


class SearchToolResponse(BaseModel):
    lane: Lane
    run_id_lane: str
    meta: Meta
    count_returned: int
    truncated: bool
    code_freqs: dict[str, dict[str, int]] | None = None
    cursor: str | None = None


class FusionRun(BaseModel):
    lane: Lane
    run_id: str


class FusionParams(BaseModel):
    runs: list[FusionRun]
    weights: dict[Lane, float] = Field(
        default_factory=lambda: {"fulltext": 1.0, "semantic": 1.0, "original_dense": 1.0}
    )
    rrf_k: int = 60
    beta_fuse: float = 1.0
    trace_id: str | None = None


class FusionResult(BaseModel):
    run_id: str
    ids: list[str]
    rank: list[int]
    score: list[float] | None = None
    meta: dict[str, Any]


class PeekSnippetsRequest(BaseModel):
    run_id: str
    offset: int = 0
    limit: int = 12
    fields: list[SnippetField] = Field(
        default_factory=lambda: [
            "title",
            "abst",
            "claim",
            "app_doc_id",
            "pub_id",
            "exam_id",
            "app_date",
            "pub_date",
            "apm_applicants",
            "cross_en_applicants",
        ]
    )
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {
            "title": 80,
            "abst": 320,
            "claim": 320,
            "app_doc_id": 128,
            "pub_id": 128,
            "exam_id": 128,
            "app_date": 64,
            "pub_date": 64,
            "apm_applicants": 128,
            "cross_en_applicants": 128,
        }
    )
    budget_bytes: int = 12_288
    trace_id: str | None = None


class PeekSnippet(BaseModel):
    id: str
    fields: dict[str, str]


class PeekMeta(BaseModel):
    used_bytes: int
    truncated: bool
    peek_cursor: str | None
    total_docs: int
    retrieved: int
    returned: int
    took_ms: int | None = None


class PeekSnippetsResponse(BaseModel):
    run_id: str
    snippets: list[PeekSnippet]
    meta: PeekMeta


class GetSnippetsRequest(BaseModel):
    ids: list[str]
    fields: list[SnippetField] = Field(
        default_factory=lambda: [
            "title",
            "abst",
            "claim",
            "desc",
            "app_doc_id",
            "pub_id",
            "exam_id",
            "app_date",
            "pub_date",
            "apm_applicants",
            "cross_en_applicants",
        ]
    )
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {
            "title": 160,
            "abst": 480,
            "claim": 800,
            "desc": 800,
            "app_doc_id": 128,
            "pub_id": 128,
            "exam_id": 128,
            "app_date": 64,
            "pub_date": 64,
            "apm_applicants": 128,
            "cross_en_applicants": 128,
        }
    )
    trace_id: str | None = None


class GetPublicationRequest(BaseModel):
    ids: list[str]
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id"
    fields: list[SnippetField] = Field(
        default_factory=lambda: ["title", "abst", "claim", "desc", "app_doc_id", "pub_id", "exam_id"]
    )
    trace_id: str | None = None


class MutateDelta(BaseModel):
    weights: dict[str, float] | None = None
    rrf_k: int | None = None
    beta_fuse: float | None = None


class MutateRequest(BaseModel):
    run_id: str
    delta: MutateDelta


class MutateRunRequest(BaseModel):
    run_id: str
    delta: MutateDelta


class MutateRunResponse(BaseModel):
    run_id: str
    ids: list[str]
    rank: list[int]
    score: list[float] | None = None
    meta: dict[str, Any]


class ProvenanceRequest(BaseModel):
    run_id: str
    trace_id: str | None = None


class ProvenanceResponse(BaseModel):
    run_id: str
    meta: dict[str, Any]
    lineage: list[str]
    # Optional structured views derived from meta / storage; fields may be absent
    lane_contributions: dict[str, dict[str, float]] | None = None
    code_distributions: dict[str, dict[str, int]] | None = None
    config_snapshot: dict[str, Any] | None = None


class BlendRunInput(BaseModel):
    lane: Literal["fulltext", "semantic", "original_dense"]
    run_id_lane: str


class BlendRequest(BaseModel):
    runs: list[BlendRunInput]
    weights: dict[str, float] = Field(
        default_factory=lambda: {"fulltext": 1.0, "semantic": 1.0, "original_dense": 1.0}
    )
    rrf_k: int = 60
    beta_fuse: float = 1.0
    target_profile: dict[str, dict[str, float]] = Field(default_factory=dict)
    top_m_per_lane: dict[str, int] = Field(
        default_factory=lambda: {"fulltext": 10000, "semantic": 10000, "original_dense": 10000}
    )
    k_grid: list[int] = Field(default_factory=lambda: [10, 20, 30, 40, 50, 80, 100])
    peek: PeekConfig | None = None


class PeekConfig(BaseModel):
    count: int = 10
    fields: list[str] = Field(default_factory=lambda: ["title", "abst", "claim"])
    per_field_chars: dict[str, int] = Field(
        default_factory=lambda: {"title": 120, "abst": 360, "claim": 320}
    )
    budget_bytes: int = 4096


class BlendFrontierEntry(BaseModel):
    k: int
    P_star: float
    R_star: float
    F_beta_star: float


class BlendResponse(BaseModel):
    run_id: str
    pairs_top: list[tuple[str, float]]
    frontier: list[BlendFrontierEntry]
    freqs_topk: dict[str, dict[str, int]]
    contrib: dict[str, dict[str, float]]
    recipe: dict[str, Any]
    peek_samples: list[dict[str, Any]]
    meta: dict[str, Any] = Field(default_factory=dict)


class MutateResponse(BaseModel):
    new_run_id: str
    frontier: list[BlendFrontierEntry]
    recipe: dict[str, Any]
    meta: dict[str, Any] = Field(default_factory=dict)


class MultiLaneEntryError(BaseModel):
    code: str = Field(
        description="Machine-readable error code such as 'timeout', 'backend_403', or 'validation_error'."
    )
    message: str = Field(
        description="Human-readable summary describing the failure."
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional backend-specific details (HTTP status, exception args, etc.).",
    )


class MultiLaneEntryRequest(BaseModel):
    lane_name: str = Field(
        description="Human/LLM friendly alias such as 'wide_fulltext' or 'precision_claims'."
    )
    tool: MultiLaneTool
    lane: Lane
    params: SearchParams


class MultiLaneSearchRequest(BaseModel):
    lanes: list[MultiLaneEntryRequest]
    trace_id: str | None = Field(
        default=None,
        description="Trace identifier to correlate the batch on MCP logs and telemetry.",
    )


class MultiLaneStatus(str, Enum):
    success = "success"
    error = "error"
    partial = "partial"


class MultiLaneEntryResponse(BaseModel):
    lane_name: str
    tool: MultiLaneTool
    lane: Lane
    status: MultiLaneStatus = Field(
        description="Execution status for this lane (`success`, `error`, or `partial`)."
    )
    took_ms: int | None = Field(
        default=None,
        description="Elapsed time in milliseconds for the lane execution if measured.",
    )
    response: SearchToolResponse | None = Field(
        default=None,
        description="Underlying search tool response when status == success.",
    )
    error: MultiLaneEntryError | None = Field(
        default=None,
        description="Structured error when the lane execution did not succeed.",
    )


class MultiLaneSearchMeta(BaseModel):
    took_ms_total: int | None = None
    trace_id: str | None = None
    success_count: int | None = None
    error_count: int | None = None


class MultiLaneSearchResponse(BaseModel):
    results: list[MultiLaneEntryResponse]
    meta: MultiLaneSearchMeta | None = None


class SearchMetaLite(BaseModel):
    top_k: int | None = None
    count_returned: int | None = None
    truncated: bool | None = None
    took_ms: int | None = None


class LaneCodeSummary(BaseModel):
    top_codes: dict[str, list[str]] | None = None


class MultiLaneLaneSummary(BaseModel):
    lane_name: str
    tool: MultiLaneTool
    lane: Lane
    status: MultiLaneStatus
    run_id_lane: str | None = None
    meta: SearchMetaLite | None = None
    code_summary: LaneCodeSummary | None = None
    error_code: str | None = None
    error_message: str | None = None


class MultiLaneSearchLite(BaseModel):
    lanes: list[MultiLaneLaneSummary]
    trace_id: str | None = None
    took_ms_total: int | None = None
    success_count: int | None = None
    error_count: int | None = None


class BlendLite(BaseModel):
    run_id: str
    top_ids: list[str]
    frontier: list[BlendFrontierEntry]
    top_codes: dict[str, list[str]] | None = None
    meta: dict[str, Any] | None = None


__all__ = [
    "Lane",
    "SemanticStyle",
    "FeatureScope",
    "Meta",
    "Cond",
    "normalize_filters",
    "IncludeOpts",
    "SearchItem",
    "DBSearchResponse",
    "FulltextParams",
    "SemanticParams",
    "SearchToolResponse",
    "FusionRun",
    "FusionParams",
    "FusionResult",
    "PeekSnippetsRequest",
    "PeekSnippetsResponse",
    "PeekMeta",
    "PeekSnippet",
    "GetSnippetsRequest",
    "GetPublicationRequest",
    "MutateDelta",
    "MutateRunRequest",
    "MutateRequest",
    "MutateRunResponse",
    "ProvenanceRequest",
    "ProvenanceResponse",
    "BlendRunInput",
    "BlendRequest",
    "PeekConfig",
    "BlendFrontierEntry",
    "BlendResponse",
    "MutateResponse",
    "SEARCH_FIELDS_DEFAULT",
    "SearchParams",
    "MultiLaneTool",
    "MultiLaneEntryError",
    "MultiLaneEntryRequest",
    "MultiLaneSearchRequest",
    "MultiLaneStatus",
    "MultiLaneEntryResponse",
    "MultiLaneSearchMeta",
    "MultiLaneSearchResponse",
    "MultiLaneSearchLite",
    "MultiLaneLaneSummary",
    "SearchMetaLite",
    "LaneCodeSummary",
    "BlendLite",
]
