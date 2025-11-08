from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("MCP_BASE_URL", "http://localhost:3000/mcp").rstrip("/")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def stub_max_results() -> int:
    value = _env_int("STUB_MAX_RESULTS", 2000)
    return max(1, min(10_000, value))


def _build_cli_env(base_url: str, redis_url: str, stub_max_results: int) -> dict[str, str]:
    env = os.environ.copy()
    env["MCP_BASE_URL"] = base_url
    env["REDIS_URL"] = redis_url
    env["STUB_MAX_RESULTS"] = str(stub_max_results)
    return env


def _run_cli_scenario(env: dict[str, str], scenario: str) -> None:
    cmd = [sys.executable, "-m", "rrfusion.scripts.run_fastmcp_e2e", "--scenario", scenario]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        pytest.fail(
            f"FastMCP CLI scenario '{scenario}' failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def test_lane_search_returns_expected_counts_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "search-counts")


def test_blend_frontier_and_storage_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "blend-frontier")


def test_peek_snippets_pagination_and_budget_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "peek-pagination")


def test_peek_snippets_single_page_only_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "peek-single")


def test_peek_snippets_large_payload_window_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    if stub_max_results < 2000:
        pytest.skip("Large payload peek test requires STUB_MAX_RESULTS >= 2000")
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "peek-large")


def test_get_snippets_returns_all_ids_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "get-snippets")


def test_mutate_and_provenance_chain_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "mutate-chain")


def test_multiple_blend_peek_cycles_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "peek-multi-cycle")


def test_error_handling_for_missing_ids_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "snippets-missing-id")


def test_mutate_requires_existing_run_cli(
    base_url: str,
    redis_url: str,
    stub_max_results: int,
) -> None:
    env = _build_cli_env(base_url, redis_url, stub_max_results)
    _run_cli_scenario(env, "mutate-missing-run")
