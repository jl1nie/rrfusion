"""Core MCP models aligned with AGENT.md plus fusion helpers."""

from __future__ import annotations

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
        default_factory=lambda: ["title", "abst", "claim", "apm_applicants", "cross_en_applicants"]
    )
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {
            "title": 80,
            "abst": 320,
            "claim": 320,
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
        default_factory=lambda: ["title", "abst", "claim", "desc", "apm_applicants", "cross_en_applicants"]
    )
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {
            "title": 160,
            "abst": 480,
            "claim": 800,
            "desc": 800,
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


__all__ = [
    "Lane",
    "SemanticStyle",
    "FeatureScope",
    "Meta",
    "Cond",
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
]
