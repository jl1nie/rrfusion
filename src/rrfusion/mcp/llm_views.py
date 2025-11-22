"""Thin LLM-friendly views derived from MCP responses."""

from __future__ import annotations

from rrfusion.models import (
    BlendLite,
    BlendResponse,
    BlendFrontierEntry,
    LaneCodeSummary,
    MultiLaneEntryResponse,
    MultiLaneLaneSummary,
    MultiLaneSearchLite,
    MultiLaneSearchResponse,
    SearchMetaLite,
    SearchToolResponse,
)

MAX_CODE_SUMMARY = 3
MAX_BLEND_TOP_IDS = 20
MAX_BLEND_FRONTIER = 4


def _summarize_code_freqs(
    freqs: dict[str, dict[str, int]] | None, limit: int
) -> LaneCodeSummary | None:
    if not freqs:
        return None
    top_codes: dict[str, list[str]] = {}
    for taxonomy, distribution in freqs.items():
        if not distribution:
            continue
        sorted_codes = sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)
        top_codes[taxonomy] = [code for code, _ in sorted_codes[:limit]]
    if not top_codes:
        return None
    return LaneCodeSummary(top_codes=top_codes)


def _extract_meta(response: SearchToolResponse) -> SearchMetaLite:
    return SearchMetaLite(
        top_k=response.meta.top_k,
        count_returned=response.count_returned,
        truncated=response.truncated,
        took_ms=response.meta.took_ms,
    )


def _lane_summary(entry: MultiLaneEntryResponse, code_limit: int) -> MultiLaneLaneSummary:
    payload = entry.response
    return MultiLaneLaneSummary(
        lane_name=entry.lane_name,
        tool=entry.tool,
        lane=entry.lane,
        status=entry.status,
        run_id_lane=payload.run_id_lane if payload else None,
        meta=_extract_meta(payload) if payload else None,
        code_summary=_summarize_code_freqs(payload.code_freqs, code_limit)
        if payload
        else None,
        error_code=entry.error.code if entry.error else None,
        error_message=entry.error.message if entry.error else None,
    )


def build_multi_lane_search_lite(
    response: MultiLaneSearchResponse, code_limit: int = MAX_CODE_SUMMARY
) -> MultiLaneSearchLite:
    return MultiLaneSearchLite(
        lanes=[_lane_summary(entry, code_limit) for entry in response.results],
        trace_id=response.meta.trace_id if response.meta else None,
        took_ms_total=response.meta.took_ms_total if response.meta else None,
        success_count=response.meta.success_count if response.meta else None,
        error_count=response.meta.error_count if response.meta else None,
    )


def _summarize_frontier(
    frontier: list[BlendFrontierEntry], limit: int | None
) -> list[BlendFrontierEntry]:
    if limit is None:
        return frontier
    return frontier[:limit]


def _top_ids(response: BlendResponse, limit: int) -> list[str]:
    return [doc_id for doc_id, _ in response.pairs_top[:limit]]


def _summarize_top_codes(
    freqs: dict[str, dict[str, int]] | None, limit: int
) -> dict[str, list[str]] | None:
    if not freqs:
        return None
    payload: dict[str, list[str]] = {}
    for taxonomy, distribution in freqs.items():
        if not distribution:
            continue
        sorted_codes = sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)
        payload[taxonomy] = [code for code, _ in sorted_codes[:limit]]
    return payload or None


def build_blend_lite(
    response: BlendResponse,
    *,
    top_ids_limit: int = MAX_BLEND_TOP_IDS,
    frontier_limit: int | None = MAX_BLEND_FRONTIER,
    code_limit: int = MAX_CODE_SUMMARY,
) -> BlendLite:
    return BlendLite(
        run_id=response.run_id,
        top_ids=_top_ids(response, top_ids_limit),
        frontier=_summarize_frontier(response.frontier, frontier_limit),
        top_codes=_summarize_top_codes(response.freqs_topk, code_limit),
        meta={"took_ms": response.meta.get("took_ms")} if response.meta else None,
    )
