"""Pydantic models shared by DB stub and MCP services."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Filters(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    ipc: list[str] | None = None
    cpc: list[str] | None = None
    assignee: list[str] | None = None


class RollupConfig(BaseModel):
    ipc_level: int | None = None
    cpc_level: str | None = None


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1)
    filters: Filters | None = None
    top_k: int = Field(1000, ge=1, le=10000)
    rollup: RollupConfig | None = None
    budget_bytes: int = Field(4096, ge=1024)


class SearchItem(BaseModel):
    doc_id: str
    score: float
    title: str
    abst: str
    claim: str
    description: str
    ipc_codes: list[str]
    cpc_codes: list[str]


class DBSearchResponse(BaseModel):
    items: list[SearchItem]
    code_freqs: dict[str, dict[str, int]]


class SearchToolResponse(BaseModel):
    lane: Literal["fulltext", "semantic"]
    run_id_lane: str
    count_returned: int
    truncated: bool
    code_freqs: dict[str, dict[str, int]]
    cursor: str | None = None


class BlendRunInput(BaseModel):
    lane: Literal["fulltext", "semantic"]
    run_id_lane: str


class PeekConfig(BaseModel):
    count: int = 10
    fields: list[str] = Field(default_factory=lambda: ["title", "abst"])
    per_field_chars: dict[str, int] = Field(
        default_factory=lambda: {"title": 120, "abst": 360}
    )
    budget_bytes: int = 4096


class BlendRequest(BaseModel):
    runs: list[BlendRunInput]
    weights: dict[str, float] = Field(
        default_factory=lambda: {"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5}
    )
    rrf_k: int = 60
    beta: float = 1.0
    family_fold: bool = True
    target_profile: dict[str, dict[str, float]] = Field(default_factory=dict)
    top_m_per_lane: dict[str, int] = Field(default_factory=lambda: {"fulltext": 10000, "semantic": 10000})
    k_grid: list[int] = Field(default_factory=lambda: [10, 20, 30, 40, 50, 80, 100])
    peek: PeekConfig | None = None


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


class PeekSnippetsRequest(BaseModel):
    run_id: str
    offset: int = 0
    limit: int = 20
    fields: list[str] = Field(default_factory=lambda: ["title", "abst"])
    per_field_chars: dict[str, int] = Field(
        default_factory=lambda: {"title": 120, "abst": 360, "claim": 280, "description": 480}
    )
    claim_count: int = 3
    strategy: Literal["head", "match", "mix"] = "head"
    budget_bytes: int = 12_288


class PeekSnippetsResponse(BaseModel):
    items: list[dict[str, Any]]
    used_bytes: int
    truncated: bool
    peek_cursor: str | None = None


class GetSnippetsRequest(BaseModel):
    ids: list[str]
    fields: list[str] = Field(default_factory=lambda: ["title", "abst"])
    per_field_chars: dict[str, int] = Field(default_factory=lambda: {"title": 120, "abst": 360})


class MutateDelta(BaseModel):
    add_keywords: list[str] | None = None
    drop_keywords: list[str] | None = None
    add_ipc: list[str] | None = None
    drop_ipc: list[str] | None = None
    rollup_change: dict[str, Any] | None = None
    weights: dict[str, float] | None = None
    rrf_k: int | None = None
    beta: float | None = None


class MutateRequest(BaseModel):
    run_id: str
    delta: MutateDelta


class MutateResponse(BaseModel):
    new_run_id: str
    frontier: list[BlendFrontierEntry]
    recipe: dict[str, Any]


class ProvenanceRequest(BaseModel):
    run_id: str


class ProvenanceResponse(BaseModel):
    recipe: dict[str, Any]
    parent: str | None = None
    history: list[str] = Field(default_factory=list)


__all__ = [
    "Filters",
    "RollupConfig",
    "SearchRequest",
    "SearchToolResponse",
    "BlendRequest",
    "BlendResponse",
    "PeekSnippetsRequest",
    "PeekSnippetsResponse",
    "GetSnippetsRequest",
    "MutateRequest",
    "MutateResponse",
    "ProvenanceRequest",
    "ProvenanceResponse",
    "DBSearchResponse",
    "SearchItem",
]
