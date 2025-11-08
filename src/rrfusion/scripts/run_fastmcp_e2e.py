"""Standalone FastMCP E2E runner to avoid pytest's event-loop interactions."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
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


async def _call_tool(
    client: MCPClient,
    name: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    result = await client.call_tool(name, {"request": payload}, timeout=timeout)
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
    return MCPClient(cfg.base_url, timeout=cfg.timeout, init_timeout=init_timeout)


async def _prepare_lane_runs(
    client: MCPClient,
    redis_client: Redis,
    cfg: RunnerConfig,
    *,
    require_large: bool = False,
) -> dict[str, dict[str, Any]]:
    search_payload = {
        "q": "fastmcp fusion scenario",
        "top_k": cfg.stub_max_results,
        "budget_bytes": 4096,
    }
    lane_runs: dict[str, dict[str, Any]] = {}
    for lane in ("fulltext", "semantic"):
        response = await _call_tool(client, f"search_{lane}", search_payload, timeout=cfg.timeout)
        if require_large and response["count_returned"] < 2000:
            raise RuntimeError(f"{lane} lane returned only {response['count_returned']} docs")
        meta = await _get_run_meta(redis_client, response["run_id_lane"])
        zcard = await redis_client.zcard(meta["lane_key"])
        lane_runs[lane] = {"response": response, "meta": meta, "zcard": zcard}
    return lane_runs


async def _prepare_fusion_run(
    client: MCPClient,
    redis_client: Redis,
    cfg: RunnerConfig,
    *,
    require_large: bool = False,
) -> dict[str, Any]:
    lane_runs = await _prepare_lane_runs(client, redis_client, cfg, require_large=require_large)

    blend_payload = {
        "runs": [
            {"lane": "fulltext", "run_id_lane": lane_runs["fulltext"]["response"]["run_id_lane"]},
            {"lane": "semantic", "run_id_lane": lane_runs["semantic"]["response"]["run_id_lane"]},
        ],
        "weights": {"recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5},
        "rrf_k": 60,
        "beta": 1.0,
        "family_fold": False,
        "target_profile": {},
        "top_m_per_lane": {"fulltext": cfg.stub_max_results, "semantic": cfg.stub_max_results},
        "k_grid": [10, 50, 100, 200, 500],
    }
    fusion = await _call_tool(client, "blend_frontier_codeaware", blend_payload, timeout=cfg.timeout)
    return fusion


async def scenario_search_counts(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        lane_runs = await _prepare_lane_runs(client, redis_client, cfg, require_large=False)
        expected_count = min(cfg.stub_max_results, cfg.stub_max_results)
        for lane, data in lane_runs.items():
            payload = data["response"]
            if payload["count_returned"] != expected_count:
                raise AssertionError(f"{lane} lane returned unexpected size {payload['count_returned']}")
            if payload["code_freqs"]["ipc"] == {} or payload["code_freqs"]["cpc"] == {}:
                raise AssertionError(f"{lane} lane missing code freqs")
            if data["zcard"] != payload["count_returned"]:
                raise AssertionError(f"{lane} lane zcard mismatch {data['zcard']}")

    await redis_client.aclose()


async def scenario_blend_frontier(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        if not fusion["pairs_top"]:
            raise AssertionError("fusion returned empty ranking")
        if not fusion["frontier"]:
            raise AssertionError("frontier missing entries")
        if not fusion["freqs_topk"]["ipc"]:
            raise AssertionError("IPC freqs missing in fusion response")

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
            if not peek["items"]:
                raise AssertionError("peek returned empty items")
            peeked += len(peek["items"])
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
        doc_ids = [doc_id for doc_id, _ in fusion["pairs_top"]][:2]
        doc_ids.append("doc-missing-000")
        response = await _call_tool(
            client,
            "get_snippets",
            {"ids": doc_ids, "fields": ["title"], "per_field_chars": {"title": 40}},
            timeout=cfg.timeout,
        )
        if "doc-missing-000" not in response:
            raise AssertionError("Missing ID not echoed in snippet response")
        if response["doc-missing-000"]["title"] != "":
            raise AssertionError("Missing ID did not return empty snippet")

    await redis_client.aclose()


async def scenario_mutate_missing_run(cfg: RunnerConfig) -> None:
    async with _make_client(cfg) as client:
        try:
            await client.call_tool(
                "mutate_run",
                {"request": {"run_id": "fusion-deadbeef", "delta": {"weights": {"semantic": 1.1}}}},
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
            "fields": ["title", "abst", "claim", "description"],
            "per_field_chars": {"title": 200, "abst": 520, "claim": 640, "description": 720},
            "budget_bytes": 20_480,
        }
        peek = await _call_tool(client, "peek_snippets", peek_payload, timeout=cfg.timeout)

        if len(peek["items"]) < 10:
            raise AssertionError(f"Peek returned too few items: {len(peek['items'])}")
        if peek["used_bytes"] < 8000:
            raise AssertionError(f"Peek used bytes unexpectedly low: {peek['used_bytes']}")
        if not peek.get("truncated"):
            raise AssertionError("Peek response should indicate truncation under tight budget")
        if peek.get("peek_cursor") is None:
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
        if not (0 < len(first["items"]) <= 50):
            raise AssertionError(f"Unexpected first page size {len(first['items'])}")
        cursor = first.get("peek_cursor")
        if cursor is None:
            raise AssertionError("First page missing cursor")
        logger.debug("peek-single items=%s cursor=%s", len(first["items"]), cursor)

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
        if not (0 < len(first["items"]) <= 50):
            raise AssertionError(f"Unexpected first page size {len(first['items'])}")
        cursor = first.get("peek_cursor")
        if cursor is None:
            raise AssertionError("First page missing cursor")
        cursor_int = int(cursor)

        second = await _call_tool(
            client,
            "peek_snippets",
            {"run_id": run_id, "offset": cursor_int, "limit": 12, "budget_bytes": 12_288},
            timeout=cfg.timeout,
        )
        if len(second["items"]) == 0:
            raise AssertionError("Second page returned no items")
        if second.get("peek_cursor") is not None and int(second["peek_cursor"]) < cursor_int:
            raise AssertionError("Cursor did not advance as expected")

        budget_third = await _call_tool(
            client,
            "peek_snippets",
            {
                "run_id": run_id,
                "offset": cursor_int,
                "limit": 12,
                "fields": ["title", "abst", "claim", "description"],
                "per_field_chars": {"title": 200, "abst": 520, "claim": 520, "description": 640},
                "budget_bytes": 1024,
            },
            timeout=cfg.timeout,
        )
        if budget_third.get("peek_cursor") is not None:
            logger.debug("tight budget returned cursor=%s (allowed)", budget_third["peek_cursor"])

    await redis_client.aclose()


async def scenario_get_snippets(cfg: RunnerConfig) -> None:
    redis_client = Redis.from_url(cfg.redis_url)
    await redis_client.ping()

    async with _make_client(cfg) as client:
        fusion = await _prepare_fusion_run(client, redis_client, cfg, require_large=False)
        doc_ids = [doc_id for doc_id, _ in fusion["pairs_top"]][:10]
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
                "beta": 0.8,
            },
        }
        mutation = await _call_tool(client, "mutate_run", mutate_payload, timeout=cfg.timeout)
        if mutation["new_run_id"] == fusion["run_id"]:
            raise AssertionError("mutate_run returned identical run_id")
        if mutation["recipe"]["delta"]["weights"]["semantic"] <= 1.2:
            raise AssertionError("mutate_run did not echo semantic weight delta")

        provenance = await _call_tool(
            client,
            "get_provenance",
            {"run_id": mutation["new_run_id"]},
            timeout=cfg.timeout,
        )
        if provenance["parent"] != fusion["run_id"]:
            raise AssertionError("Provenance parent mismatch")
        if fusion["run_id"] not in provenance["history"]:
            raise AssertionError("Parent run missing from provenance history")

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
    elif cfg.scenario == "peek-multi-cycle":
        await scenario_peek_multi_cycle(cfg)
    elif cfg.scenario == "snippets-missing-id":
        await scenario_snippets_missing_id(cfg)
    elif cfg.scenario == "mutate-missing-run":
        await scenario_mutate_missing_run(cfg)
    else:
        raise ValueError(f"Unknown scenario: {cfg.scenario}")


def parse_args(argv: list[str] | None = None) -> RunnerConfig:
    parser = argparse.ArgumentParser(description="Run FastMCP E2E scenarios outside pytest.")
    parser.add_argument("--base-url", default=os.getenv("MCP_BASE_URL", "http://localhost:3000/mcp"))
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
            "peek-pagination",
            "peek-single",
            "peek-large",
            "peek-multi-cycle",
            "get-snippets",
            "snippets-missing-id",
            "mutate-chain",
            "mutate-missing-run",
        ],
        default="peek-large",
        help="Scenario to execute",
    )
    args = parser.parse_args(argv)
    return RunnerConfig(
        base_url=args.base_url.rstrip("/"),
        redis_url=args.redis_url,
        stub_max_results=args.stub_max_results,
        timeout=args.timeout,
        scenario=args.scenario,
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
