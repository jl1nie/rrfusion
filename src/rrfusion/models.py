"""Core MCP models aligned with AGENT.md plus fusion helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Lane = Literal["fulltext", "semantic"]
SnippetField = Literal[
    "title",
    "abst",
    "claim",
    "desc",
    "app_doc_id",
    "pub_id",
    "exam_id",
]


class Meta(BaseModel):
    lane: Lane | None = None
    top_k: int | None = None
    took_ms: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    retries: int | None = None


class Cond(BaseModel):
    lop: Literal["and", "or", "not"]
    field: Literal["ipc", "fi", "cpc", "pubyear", "assignee", "country"]
    op: Literal["in", "range", "eq", "neq"]
    value: Any


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
    budget_bytes: int = 4096
    trace_id: str | None = None
    include: IncludeOpts = IncludeOpts()


class SemanticParams(BaseModel):
    text: str
    filters: list[Cond] = Field(default_factory=list)
    top_k: int = 800
    budget_bytes: int = 4096
    trace_id: str | None = None
    include: IncludeOpts = IncludeOpts()


class SearchToolResponse(BaseModel):
    lane: Lane
    run_id_lane: str
    response: DBSearchResponse
    count_returned: int
    truncated: bool
    code_freqs: dict[str, dict[str, int]] | None = None
    cursor: str | None = None


class FusionRun(BaseModel):
    lane: Lane
    run_id: str


class GateConfig(BaseModel):
    tau: float = 0.05
    sigma: float | None = None


class MMRConfig(BaseModel):
    enable: bool = True
    lambda_mmr: float = 0.7


class FusionParams(BaseModel):
    runs: list[FusionRun]
    weights: dict[Lane, float] = Field(
        default_factory=lambda: {"fulltext": 1.0, "semantic": 1.0}
    )
    rrf_k: int = 60
    beta_fuse: float = 1.0
    lambda_code: float = 0.25
    gate: GateConfig = GateConfig()
    mmr: MMRConfig = MMRConfig()
    limit: int = 200
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
    fields: list[SnippetField] = Field(default_factory=lambda: ["title", "abst", "claim"])
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {"title": 160, "abst": 480, "claim": 320}
    )
    strategy: Literal["head", "match", "mix"] = "mix"
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


class PeekSnippetsResponse(BaseModel):
    run_id: str
    snippets: list[PeekSnippet]
    meta: PeekMeta


class GetSnippetsRequest(BaseModel):
    ids: list[str]
    fields: list[SnippetField] = Field(default_factory=lambda: ["title", "abst", "claim"])
    per_field_chars: dict[SnippetField, int] = Field(
        default_factory=lambda: {"title": 160, "abst": 480, "claim": 320}
    )
    trace_id: str | None = None


class GetPublicationRequest(BaseModel):
    ids: list[str]
    id_type: Literal["pub_id", "app_doc_id", "exam_id"] = "pub_id"
    fields: list[SnippetField] = Field(
        default_factory=lambda: ["title", "abst", "claim", "desc", "app_doc_id", "pub_id", "exam_id"]
    )
    trace_id: str | None = None


class SnippetsResponse(BaseModel):
    run_id: str | None = None
    snippets: dict[str, dict[str, str]]
    meta: dict[str, Any]


class MutateDelta(BaseModel):
    weights: dict[Lane, float] | None = None
    rrf_k: int | None = None
    beta_fuse: float | None = None
    lambda_code: float | None = None
    gate: GateConfig | None = None
    mmr: MMRConfig | None = None
    limit: int | None = None


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
    weights: dict[str, float] = Field(default_factory=lambda: {"fulltext": 1.0, "semantic": 1.0})
    rrf_k: int = 60
    beta_fuse: float = 1.0
    family_fold: bool = True
    target_profile: dict[str, dict[str, float]] = Field(default_factory=dict)
    top_m_per_lane: dict[str, int] = Field(
        default_factory=lambda: {"fulltext": 10000, "semantic": 10000}
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


class MutateResponse(BaseModel):
    new_run_id: str
    frontier: list[BlendFrontierEntry]
    recipe: dict[str, Any]


__all__ = [
    "Lane",
    "Meta",
    "Cond",
    "IncludeOpts",
    "SearchItem",
    "DBSearchResponse",
    "FulltextParams",
    "SemanticParams",
    "SearchToolResponse",
    "FusionRun",
    "GateConfig",
    "MMRConfig",
    "FusionParams",
    "FusionResult",
    "PeekSnippetsRequest",
    "PeekSnippetsResponse",
    "PeekMeta",
    "PeekSnippet",
    "GetSnippetsRequest",
    "GetPublicationRequest",
    "SnippetsResponse",
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
]
