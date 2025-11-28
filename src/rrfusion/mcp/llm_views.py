"""Thin LLM-friendly views derived from MCP responses."""

from __future__ import annotations

from rrfusion.models import (
    LaneCodeSummary,
    MultiLaneEntryResponse,
    MultiLaneLaneSummary,
    MultiLaneSearchLite,
    MultiLaneSearchResponse,
)

MAX_CODE_SUMMARY = 3


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


def _lane_summary(entry: MultiLaneEntryResponse, code_limit: int) -> MultiLaneLaneSummary:
    payload = entry.handle
    return MultiLaneLaneSummary(
        lane_name=entry.lane_name,
        tool=entry.tool,
        lane=entry.lane,
        status=entry.status,
        handle=payload,
        code_summary=None,
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
