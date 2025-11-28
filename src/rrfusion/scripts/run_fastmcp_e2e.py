"""Standalone FastMCP E2E runner to avoid pytest's event-loop interactions."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from fastmcp.client import Client as MCPClient
from fastmcp.exceptions import ToolError
from redis.asyncio import Redis

logger = logging.getLogger("rrfusion.fastmcp_e2e")


@dataclass
class RunnerConfig:
    base_url: str
    redis_url: str
    stub_max_results: int
    timeout: float
    scenario: str
    api_token: str | None


async def _call_tool(
    client: MCPClient,
    name: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    result = await client.call_tool(name, payload, timeout=timeout)
    return result.structured_content


async def _get_run_meta(redis_client: Redis, run_id: str) -> dict[str, Any]:
    raw = await redis_client.hget(f"h:run:{run_id}", "meta")
    if not raw:
        raise RuntimeError(f"run metadata missing for {run_id}")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _make_client(cfg: RunnerConfig) -> MCPClient:
    init_timeout = max(cfg.timeout / 3, 1.0)
    return MCPClient(
        cfg.base_url,
        timeout=cfg.timeout,
        init_timeout=init_timeout,
        auth=cfg.api_token,
    )


def _assert_took_ms(value: int | None, label: str) -> None:
    if value is None or not isinstance(value, int) or value < 0:
        raise AssertionError(f"{label} missing valid timing metadata took_ms={value}")


async def _prepare_lane_runs(
    client: MCPClient,
    redis_client: Redis,
    cfg: RunnerConfig,
    *,
    require_large: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Prepare lane runs via backend-oriented rrf_search_*_raw tools.

    This returns lane run handles plus stored Redis metadata, rather than relying
    on legacy search_* tool response payloads.
    """
    lane_runs: dict[str, dict[str, Any]] = {}
    for lane in ("fulltext", "semantic"):
        if lane == "fulltext":
            tool_name = "rrf_search_fulltext_raw"
            params: dict[str, Any] = {
                "query": "fastmcp fusion scenario",
                "top_k": cfg.stub_max_results,
                "filters": None,
            }
        else:
            tool_name = "rrf_search_semantic_raw"
            params = {
                "text": "fastmcp fusion scenario",
                "top_k": cfg.stub_max_results,
                "filters": None,
                "semantic_style": "default",
            }
        handle = await _call_tool(
            client,
            tool_name,
            {"params": params},
            timeout=cfg.timeout,
        )
        meta_payload = handle.get("meta") or {}
        _assert_took_ms(meta_payload.get("took_ms"), f"{lane} search")
        count_returned = meta_payload.get("count_returned") or 0
        if require_large and count_returned < 2000:
            raise RuntimeError(f"{lane} lane returned only {count_returned} docs")
        run_id = handle["run_id"]
        meta = await _get_run_meta(redis_client, run_id)
        zcard = await redis_client.zcard(meta["lane_key"])
        lane_runs[lane] = {"handle": handle, "meta": meta, "zcard": zcard}
    return lane_runs


async def _prepare_fusion_run(
    client: MCPClient,
    redis_client: Redis,
    cfg: RunnerConfig,
    *,
    require_large: bool = False,
) -> dict[str, Any]:
    lane_runs = await _prepare_lane_runs(
        client, redis_client, cfg, require_large=require_large
    )

    blend_payload = {
        "runs": [
            {
                "lane": "fulltext",
                "run_id_lane": lane_runs["fulltext"]["handle"]["run_id"],
            },
            {
                "lane": "semantic",
                "run_id_lane": lane_runs["semantic"]["handle"]["run_id"],
            },
        ],
        "weights": {"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5},
        "rrf_k": 60,
        "beta_fuse": 1.0,
        "target_profile": {},
        "top_m_per_lane": {"fulltext": cfg.stub_max_results, "semantic": cfg.stub_max_results},
        "k_grid": [10, 50, 100, 200, 500],
        "peek": None,
    }
    fusion = await _call_tool(client, "rrf_blend_frontier", {"request": blend_payload}, timeout=cfg.timeout)
    _assert_took_ms(fusion.get("meta", {}).get("took_ms"), "fusion run")
    return fusion


async def scenario_search_counts(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        lane_runs = await _prepare_lane_runs(
            client, redis_client, cfg, require_large=False
        )
        expected_count = min(cfg.stub_max_results, cfg.stub_max_results)
        for lane, data in lane_runs.items():
            handle = data["handle"]
            meta_payload = handle.get("meta") or {}
            _assert_took_ms(meta_payload.get("took_ms"), f"{lane} search counts")
            count_returned = meta_payload.get("count_returned")
            if count_returned != expected_count:
                raise AssertionError(
                    f"{lane} lane returned unexpected size {count_returned}"
                )
            if data["zcard"] != count_returned:
                raise AssertionError(
                    f"{lane} lane zcard mismatch {data['zcard']}"
                )

    await redis_client.aclose()


async def scenario_blend_frontier(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        # rrf_blend_frontier now returns a RunHandle; validate fusion via snippets
        # and stored Redis metadata instead of inline payload fields.
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        run_id = fusion["run_id"]
        meta_payload = fusion.get("meta") or {}
        _assert_took_ms(meta_payload.get("took_ms"), "blend frontier")

        # Frontier existence check via peek_snippets
        peek = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": 0, "limit": 20, "budget_bytes": 4096},
            timeout=cfg.timeout,
        )
        if not peek.get("snippets"):
            raise AssertionError("fusion frontier produced no snippets")

        # Code frequency snapshot from stored run metadata
        run_meta = await _get_run_meta(redis_client, run_id)
        freqs = run_meta.get("freqs_topk") or {}
        if not freqs.get("ipc"):
            raise AssertionError("IPC freqs missing in fusion metadata")
        if not freqs.get("fi"):
            raise AssertionError("FI freqs missing in fusion metadata")
        if not freqs.get("ft"):
            raise AssertionError("FT freqs missing in fusion metadata")

    await redis_client.aclose()


async def scenario_run_multilane_search_batch(cfg: RunnerConfig) -> None:
    """Smoke test the lightweight multi-lane pathway that returns MultiLaneSearchLite."""
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        lanes = [
            {
                "lane_name": "lite_fulltext",
                "tool": "search_fulltext",
                "lane": "fulltext",
                "params": {"query": "lite integration query", "top_k": 60},
            },
            {
                "lane_name": "lite_semantic",
                "tool": "search_semantic",
                "lane": "semantic",
                "params": {"text": "lite integration query", "top_k": 60},
            },
        ]
        payload = {"lanes": lanes, "trace_id": "fastmcp-multilane-batch-lite"}
        response = await _call_tool(client, "run_multilane_search", payload, timeout=cfg.timeout)
        summaries = response.get("lanes") or []
        trace_id = response.get("trace_id")
        if trace_id and trace_id != payload["trace_id"]:
            raise AssertionError("Lite multi-lane trace_id mismatch")
        if len(summaries) != len(lanes):
            raise AssertionError("Lite multi-lane returned unexpected count")
        success_count = sum(1 for entry in summaries if entry.get("status") == "success")
        if success_count != len(lanes):
            raise AssertionError("Some lite lanes failed")
        for entry, lane in zip(summaries, lanes):
            if entry.get("lane") != lane["lane"]:
                raise AssertionError("Lite lane lane mismatch")
            handle = entry.get("handle") or {}
            if not handle.get("run_id"):
                raise AssertionError("Lite lane missing handle.run_id")
            meta_payload = handle.get("meta") or {}
            if meta_payload.get("top_k") != lane["params"]["top_k"]:
                raise AssertionError("Lite lane meta top_k mismatch")
            code_summary = entry.get("code_summary") or {}
            if not code_summary.get("top_codes"):
                raise AssertionError("Lite lane missing code_summary")

    await redis_client.aclose()


async def scenario_run_multilane_search_batch_precise(cfg: RunnerConfig) -> None:
    """Smoke test the full multi-lane pathway using the lite multi-lane tool with RunHandle payloads."""
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        lanes = [
            {
                "lane_name": "wide_fulltext",
                "tool": "search_fulltext",
                "lane": "fulltext",
                "params": {"query": "multilane integration query", "top_k": 80},
            },
            {
                "lane_name": "wide_semantic",
                "tool": "search_semantic",
                "lane": "semantic",
                "params": {"text": "multilane integration query", "top_k": 80},
            },
        ]
        payload = {"lanes": lanes, "trace_id": "fastmcp-multilane-batch"}
        response = await _call_tool(client, "run_multilane_search", payload, timeout=cfg.timeout)
        summaries = response.get("lanes") or []
        if len(summaries) != len(lanes):
            raise AssertionError("run_multilane_search returned unexpected result count")
        for entry, lane in zip(summaries, lanes):
            if entry.get("status") != "success":
                raise AssertionError(f"Lane {lane['lane_name']} failed: {entry}")
            handle = entry.get("handle") or {}
            if not handle.get("run_id"):
                raise AssertionError(f"Lane {lane['lane_name']} missing handle.run_id")


async def scenario_freq_snapshot(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        lane_runs = await _prepare_lane_runs(client, redis_client, cfg, require_large=False)
        for lane, data in lane_runs.items():
            freq_key = data["meta"].get("freq_key")
            if not freq_key:
                raise AssertionError(f"{lane} run missing freq_key")
            payload = await redis_client.hgetall(freq_key)
            if b"fi" not in payload or b"ft" not in payload:
                raise AssertionError(f"{lane} freq summary missing FI/FT keys")
            fi_values = json.loads(payload[b"fi"]) if payload[b"fi"] else {}
            ft_values = json.loads(payload[b"ft"]) if payload[b"ft"] else {}
            if fi_values == {} and ft_values == {}:
                raise AssertionError(f"{lane} freq summary missing FI and FT data")

    await redis_client.aclose()


async def scenario_peek_multi_cycle(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        peeked = 0
        for idx in range(3):
            fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
            peek = await _call_tool(
                client,
                "peek_snippets",
                {"run_id": fusion["run_id"], "offset": 0, "limit": 20, "budget_bytes": 2048},
                timeout=cfg.timeout,
            )
            if not peek["snippets"]:
                raise AssertionError("peek returned empty items")
            _assert_took_ms(peek.get("meta", {}).get("took_ms"), "peek multi cycle")
            peeked += len(peek["snippets"])
        info = await redis_client.info("memory")
        if info.get("used_memory", 0) <= 0:
            raise AssertionError("Redis memory info unavailable")
        if peeked <= 0:
            raise AssertionError("No items peeked over cycles")

    await redis_client.aclose()


async def scenario_snippets_missing_id(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        run_id = fusion["run_id"]
        peek = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": 0, "limit": 10, "budget_bytes": 2048},
            timeout=cfg.timeout,
        )
        doc_ids = [snippet["id"] for snippet in peek.get("snippets", [])][:2]
        doc_ids.append("doc-missing-000")
        response = await _call_tool(
            client,
            "get_snippets",
            {"ids": doc_ids, "fields": ["title"], "per_field_chars": {"title": 40}},
            timeout=cfg.timeout,
        )
        if "doc-missing-000" not in response:
            raise AssertionError("Missing ID not echoed in snippet response")
        title_field = response["doc-missing-000"].get("title", "")
        if len(title_field) > 40:
            raise AssertionError("Missing ID snippet exceeded title cap")

    await redis_client.aclose()


async def scenario_mutate_missing_run(cfg: RunnerConfig) -> None:
    async with _make_client(cfg) as client:
        try:
            await client.call_tool(
                "rrf_mutate_run",
                {"run_id": "fusion-deadbeef", "delta": {"weights": {"semantic": 1.1}}},
                timeout=cfg.timeout,
            )
        except ToolError:
            return
        raise AssertionError("mutate_run did not raise ToolError for missing run")


async def scenario_peek_large(cfg: RunnerConfig) -> None:
    if cfg.stub_max_results < 2000:
        raise RuntimeError("Large peek scenario requires STUB_MAX_RESULTS >= 2000")

    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=True)
        peek_payload = {
            "run_id": fusion["run_id"],
            "offset": 0,
            "limit": 60,
            "fields": ["title", "abst", "claim", "desc"],
            "per_field_chars": {"title": 200, "abst": 520, "claim": 640, "desc": 720},
            "budget_bytes": 20_480,
        }
        peek = await _call_tool(client, "peek_snippets", peek_payload, timeout=cfg.timeout)
        meta = peek.get("meta") or {}
        _assert_took_ms(meta.get("took_ms"), "peek large")

        if len(peek["snippets"]) < 10:
            raise AssertionError(f"Peek returned too few items: {len(peek['snippets'])}")
        if meta.get("used_bytes", 0) <= 0:
            raise AssertionError(f"Peek used bytes unexpectedly low: {meta.get('used_bytes')}")
        if not meta.get("truncated"):
            logger.warning("Peek response not truncated even with tight budget; check payload sizing")
        if meta.get("peek_cursor") is None:
            raise AssertionError("Peek response missing cursor")

    await redis_client.aclose()


async def scenario_peek_single(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        run_id = fusion["run_id"]

        first = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": 0, "limit": 12, "budget_bytes": 12_288},
            timeout=cfg.timeout,
        )
        if not (0 < len(first["snippets"]) <= 50):
            raise AssertionError(f"Unexpected first page size {len(first['snippets'])}")
        cursor = first.get("meta", {}).get("peek_cursor")
        if cursor is None:
            raise AssertionError("First page missing cursor")
        logger.debug("peek-single items=%s cursor=%s", len(first["snippets"]), cursor)
        _assert_took_ms(first.get("meta", {}).get("took_ms"), "peek single")

    await redis_client.aclose()


async def scenario_peek_pagination(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        run_id = fusion["run_id"]

        first = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": 0, "limit": 12, "budget_bytes": 12_288},
            timeout=cfg.timeout,
        )
        if not (0 < len(first["snippets"]) <= 50):
            raise AssertionError(f"Unexpected first page size {len(first['snippets'])}")
        cursor = first.get("meta", {}).get("peek_cursor")
        if cursor is None:
            raise AssertionError("First page missing cursor")
        cursor_int = int(cursor)
        _assert_took_ms(first.get("meta", {}).get("took_ms"), "peek pagination first page")

        second = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": cursor_int, "limit": 12, "budget_bytes": 12_288},
            timeout=cfg.timeout,
        )
        if len(second["snippets"]) == 0:
            raise AssertionError("Second page returned no items")
        second_cursor = second.get("meta", {}).get("peek_cursor")
        if second_cursor is not None and int(second_cursor) < cursor_int:
            raise AssertionError("Cursor did not advance as expected")
        _assert_took_ms(second.get("meta", {}).get("took_ms"), "peek pagination second page")

        budget_third = await _call_tool(
            client,
            "peek_snippets",
            {
                "run_id": run_id,
                "offset": cursor_int,
                "limit": 12,
                "fields": ["title", "abst", "claim", "desc"],
                "per_field_chars": {"title": 200, "abst": 520, "claim": 520, "desc": 640},
                "budget_bytes": 1024,
            },
            timeout=cfg.timeout,
        )
        tight_cursor = budget_third.get("meta", {}).get("peek_cursor")
        if tight_cursor is not None:
            logger.debug("tight budget returned cursor=%s (allowed)", tight_cursor)
        _assert_took_ms(budget_third.get("meta", {}).get("took_ms"), "peek pagination budget page")

    await redis_client.aclose()


async def scenario_get_snippets(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        run_id = fusion["run_id"]
        peek = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": 0, "limit": 20, "budget_bytes": 4096},
            timeout=cfg.timeout,
        )
        doc_ids = [snippet["id"] for snippet in peek.get("snippets", [])][:10]
        if not doc_ids:
            raise AssertionError("Fusion run returned no doc IDs for snippet fetch")

        response = await _call_tool(
            client,
            "get_snippets",
            {"ids": doc_ids, "fields": ["title", "abst"], "per_field_chars": {"title": 60, "abst": 120}},
            timeout=cfg.timeout,
        )
        if set(response.keys()) != set(doc_ids):
            raise AssertionError("Snippet response missing IDs")
        for doc_id in doc_ids:
            fields = response[doc_id]
            if len(fields["title"]) > 60 or len(fields["abst"]) > 120:
                raise AssertionError(f"Snippet length exceeded caps for {doc_id}")

    await redis_client.aclose()


async def scenario_mutate_chain(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        mutate_payload = {
            "run_id": fusion["run_id"],
            "delta": {
                "weights": {"semantic": 1.25},
                "rrf_k": 45,
                "beta_fuse": 0.8,
            },
        }
        mutation = await _call_tool(
            client, "rrf_mutate_run", mutate_payload, timeout=cfg.timeout
        )
        new_run_id = mutation.get("run_id")
        if not new_run_id or new_run_id == fusion["run_id"]:
            raise AssertionError("rrf_mutate_run returned identical or empty run_id")
        meta_payload = mutation.get("meta") or {}
        _assert_took_ms(meta_payload.get("took_ms"), "mutate run")

        provenance = await _call_tool(
            client,
            "get_provenance",
            {"run_id": new_run_id},
            timeout=cfg.timeout,
        )
        meta = provenance.get("meta", {})
        lineage = provenance.get("lineage", [])
        if meta.get("parent") != fusion["run_id"]:
            raise AssertionError("Provenance parent mismatch")
        if fusion["run_id"] not in lineage:
            raise AssertionError("Parent run missing from provenance history")
        recipe = meta.get("recipe", {})
        delta = recipe.get("delta", {})
        weights = delta.get("weights", {})
        if weights.get("semantic", 0) <= 1.2:
            raise AssertionError("Provenance delta did not record semantic weight change")
        if delta.get("beta_fuse") != 0.8:
            raise AssertionError("Provenance recipe beta_fuse mismatch")
        _assert_took_ms(meta.get("took_ms"), "provenance")

    await redis_client.aclose()


async def scenario_peek_mutate_snippets(cfg: RunnerConfig) -> None:
    """End-to-end check of the standard review loop: fusion → peek → mutate → peek → get_snippets."""
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        # 1) Prepare a baseline fusion run
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        base_run_id = fusion["run_id"]

        # 2) First peek_snippets on the baseline frontier
        first_peek = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": base_run_id, "offset": 0, "limit": 20, "budget_bytes": 4096},
            timeout=cfg.timeout,
        )
        if not first_peek["snippets"]:
            raise AssertionError("Initial peek_snippets returned no snippets")
        _assert_took_ms(first_peek.get("meta", {}).get("took_ms"), "peek_mutate first peek")

        # 3) Mutate the fusion run once
        mutate_payload = {
            "run_id": base_run_id,
            "delta": {
                "weights": {"semantic": 1.1},
            },
        }
        mutation = await _call_tool(
            client, "rrf_mutate_run", mutate_payload, timeout=cfg.timeout
        )
        new_run_id = mutation.get("run_id")
        if not new_run_id or new_run_id == base_run_id:
            raise AssertionError("rrf_mutate_run did not produce a distinct run_id")
        _assert_took_ms(
            mutation.get("meta", {}).get("took_ms"), "peek_mutate mutate_run"
        )

        # 4) Second peek_snippets on the mutated frontier
        second_peek = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": new_run_id, "offset": 0, "limit": 20, "budget_bytes": 4096},
            timeout=cfg.timeout,
        )
        if not second_peek["snippets"]:
            raise AssertionError("Second peek_snippets after mutate returned no snippets")
        _assert_took_ms(second_peek.get("meta", {}).get("took_ms"), "peek_mutate second peek")

        # 5) get_snippets on a small set of top candidates for detailed inspection
        doc_ids = [snippet["id"] for snippet in first_peek.get("snippets", [])][:10]
        if not doc_ids:
            raise AssertionError("Fusion run returned no doc IDs for diagnostic get_snippets")
        snippets = await _call_tool(
            client,
            "get_snippets",
            {"ids": doc_ids, "fields": ["title", "abst"], "per_field_chars": {"title": 80, "abst": 160}},
            timeout=cfg.timeout,
        )
        if set(snippets.keys()) != set(doc_ids):
            raise AssertionError("Diagnostic get_snippets response missing IDs")
        for doc_id in doc_ids:
            fields = snippets[doc_id]
            if len(fields.get("title", "")) > 80 or len(fields.get("abst", "")) > 160:
                raise AssertionError(f"Diagnostic snippets exceeded caps for {doc_id}")

    await redis_client.aclose()


async def scenario_semantic_style_dense(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        payload = {
            "params": {
                "text": "dense lane smoke test",
                "top_k": 50,
                "semantic_style": "original_dense",
                "filters": None,
            }
        }
        handle = await _call_tool(
            client, "rrf_search_semantic_raw", payload, timeout=cfg.timeout
        )
        meta_payload = handle.get("meta") or {}
        _assert_took_ms(
            meta_payload.get("took_ms"), "semantic style dense search"
        )
        if meta_payload.get("count_returned", 0) == 0:
            raise AssertionError("original_dense lane returned no docs")

        run_id = handle["run_id"]
        meta = await _get_run_meta(redis_client, run_id)
        if meta.get("lane") != "original_dense":
            raise AssertionError(
                "semantic_style request did not route to original_dense lane"
            )
        params = meta.get("params", {})
        if params.get("semantic_style") != "original_dense":
            raise AssertionError("stored run metadata missing semantic_style flag")

    await redis_client.aclose()


async def run(cfg: RunnerConfig) -> None:
    if cfg.scenario == "peek-large":
        await scenario_peek_large(cfg)
    elif cfg.scenario == "peek-single":
        await scenario_peek_single(cfg)
    elif cfg.scenario == "peek-pagination":
        await scenario_peek_pagination(cfg)
    elif cfg.scenario == "get-snippets":
        await scenario_get_snippets(cfg)
    elif cfg.scenario == "mutate-chain":
        await scenario_mutate_chain(cfg)
    elif cfg.scenario == "search-counts":
        await scenario_search_counts(cfg)
    elif cfg.scenario == "blend-frontier":
        await scenario_blend_frontier(cfg)
    elif cfg.scenario == "freq-snapshot":
        await scenario_freq_snapshot(cfg)
    elif cfg.scenario == "multilane-batch":
        await scenario_run_multilane_search_batch(cfg)
    elif cfg.scenario == "multilane-batch-precise":
        await scenario_run_multilane_search_batch_precise(cfg)
    elif cfg.scenario == "peek-mutate-snippets":
        await scenario_peek_mutate_snippets(cfg)
    elif cfg.scenario == "peek-multi-cycle":
        await scenario_peek_multi_cycle(cfg)
    elif cfg.scenario == "snippets-missing-id":
        await scenario_snippets_missing_id(cfg)
    elif cfg.scenario == "mutate-missing-run":
        await scenario_mutate_missing_run(cfg)
    elif cfg.scenario == "semantic-style-dense":
        await scenario_semantic_style_dense(cfg)
    else:
        raise ValueError(f"Unknown scenario: {cfg.scenario}")



def _default_mcp_client_host() -> str:
    return os.getenv("MCP_SERVICE_HOST") or os.getenv("MCP_HOST", "localhost")


def _default_mcp_base_url() -> str:
    host = _default_mcp_client_host()
    port = os.getenv("MCP_PORT", "3000")
    return f"http://{host}:{port}/mcp"


def parse_args(argv: list[str] | None = None) -> RunnerConfig:
    parser = argparse.ArgumentParser(description="Run FastMCP E2E scenarios outside pytest.")
    parser.add_argument("--base-url", default=_default_mcp_base_url())
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument(
        "--stub-max-results",
        type=int,
        default=int(os.getenv("STUB_MAX_RESULTS", "2000")),
        help="Expected stub max results per lane (set to 10000 for stress runs)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("FASTMCP_E2E_TIMEOUT", "10")),
        help="Per-call timeout in seconds",
    )
    parser.add_argument(
        "--scenario",
        choices=[
            "search-counts",
            "blend-frontier",
            "freq-snapshot",
            "peek-pagination",
            "peek-single",
            "peek-large",
            "peek-multi-cycle",
            "get-snippets",
            "snippets-missing-id",
            "mutate-chain",
            "mutate-missing-run",
            "semantic-style-dense",
            "multilane-batch",
            "multilane-batch-precise",
            "peek-mutate-snippets",
        ],
        default="peek-large",
        help="Scenario to execute",
    )
    parser.add_argument(
        "--api-token",
        default=os.getenv("MCP_API_TOKEN"),
        help="Bearer token for MCP server authentication (defaults to MCP_API_TOKEN env).",
    )
    args = parser.parse_args(argv)
    return RunnerConfig(
        base_url=args.base_url.rstrip("/"),
        redis_url=args.redis_url,
        stub_max_results=args.stub_max_results,
        timeout=args.timeout,
        scenario=args.scenario,
        api_token=args.api_token or None,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    cfg = parse_args(argv)
    try:
        asyncio.run(run(cfg))
    except Exception as exc:  # pragma: no cover - CLI diagnostics
        logger.error("FastMCP E2E scenario failed: %s", exc, exc_info=True)
        return 1
    logger.info("FastMCP E2E scenario '%s' succeeded", cfg.scenario)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
