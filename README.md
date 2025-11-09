# rrfusion

Multi-lane patent search with **RRF fusion**, **code-aware frontier**, and **MCP** integration.

This scaffold includes:
- `AGENT.md` — the implementation brief/spec for Codex or any dev agent
- `apps/db_stub` — FastAPI stub entrypoint plus a dedicated Dockerfile
- `apps/mcp-host` — FastMCP/test image Dockerfile reused by Compose
- The MCP CLI image now uses a multi-stage build so dependency installation (pip) is cached between builds, making `cargo make build-cli`/`cargo make start-*` faster.
- `infra/compose.prod.yml` — minimal Redis + MCP stack (no DB stub) suitable for production-like runs
- `infra/compose.test.yml` — CI/closed-network stack with Redis, the DB stub, MCP, and the pytest runner.
 - `infra/compose.stub.yml` — local stub stack with Redis, the DB stub, MCP, and attachable networking for external clients.
- `infra/env.example` — environment defaults (copy to `infra/.env` for Docker)

## Contents

- [Quick start (Docker)](#quick-start-docker)
- [Next steps](#next-steps)
- [FastMCP Host](#fastmcp-host)
- [Usage Workflow](#usage-workflow)
- [MCP Tool Reference](#mcp-tool-reference)
  - [`search_fulltext`](#search_fulltext)
  - [`search_semantic`](#search_semantic)
  - [`blend_frontier_codeaware`](#blend_frontier_codeaware)
  - [`peek_snippets`](#peek_snippets)
  - [`get_snippets`](#get_snippets)
  - [`mutate_run`](#mutate_run)
  - [`get_provenance`](#get_provenance)

## Quick start (Docker)

```bash
cp infra/env.example infra/.env
docker compose -f infra/compose.prod.yml up -d rrfusion-redis rrfusion-mcp
docker compose -f infra/compose.prod.yml ps  # confirm Redis and MCP are healthy
```

Visit `http://localhost:3000/healthz` to confirm the FastMCP host is up. Run `docker compose -f infra/compose.prod.yml down` when you're done. Use `infra/compose.stub.yml` whenever you need an isolated network that also brings up the DB stub and pytest runner (and want to talk to `rrfusion-mcp` from an external container):

> **Network note:** set `MCP_EXTERNAL_NETWORK=<existing-network>` (e.g., `docker_default`) and `MCP_EXTERNAL_NETWORK_ENABLED=true` before running Compose to join an external network. Services still expose their own service names (`rrfusion-redis`, `rrfusion-db-stub`, `rrfusion-mcp`, `rrfusion-tests`) so the stack keeps resolving internally.

`infra/.env` now exposes `DATA_TTL_HOURS=12` and `SNIPPET_TTL_HOURS=24` so run-level data expires after 12 h and snippet payloads after 24 h. You can override these values and the Redis memory knobs (`REDIS_MAX_MEMORY=2gb`, `REDIS_MAXMEMORY_POLICY=volatile-lru`) to tune eviction. Every Compose stack reads the same `.env`, so those limits apply consistently across stub/test/prod setups.

Both `cargo make start-stub` and `scripts/run_e2e.sh` source `infra/.env` before calling Compose, so the stub stack always honors the `MCP_EXTERNAL_NETWORK`/`MCP_EXTERNAL_NETWORK_ENABLED` values you’ve defined there (no Makefile overrides apply). Leave them blank to let Compose build `rrfusion-test-net`, or point them at another attachable bridge if needed.

```bash
docker compose -f infra/compose.stub.yml run --rm rrfusion-tests pytest -m smoke
```

The stub stack forces `MCP_EXTERNAL_NETWORK=rrfusion-test-net` and `MCP_EXTERNAL_NETWORK_ENABLED=false`, so it can create an attachable bridge that always exposes `rrfusion-mcp` to `docker run --network rrfusion-test-net ...` even if your `.env` points at another network.

> **Note:** The FastMCP host uses a single Streamable HTTP endpoint at `/mcp`, so both the POST calls and streaming responses flow through `http://{host}:{port}/mcp`. Set `MCP_SERVICE_HOST`/`MCP_PORT` (e.g., `localhost` in `infra/env.example`, `mcp` in the Compose `.env`) to control where clients should reach the service.

> **Auth:** Set `MCP_API_TOKEN=<token>` in `infra/.env` (and restart the stack) to require `Authorization: Bearer <token>` on every FastMCP request.

## E2E testing & 10k stub data

1. Copy `infra/env.example` to `infra/.env`, then set `STUB_MAX_RESULTS=10000` to force the DB stub to emit 10k docs per lane.  
2. (Optional) Snapshot the deterministic dataset for later inspection:

   ```bash
   uv run python -m rrfusion.scripts.make_stub_dataset --count 10000 --lane fulltext --output tests/data/stub_docs_10k.jsonl
   ```

3. Bring up Redis, the stub, and MCP via the stub stack:

   ```bash
   docker compose -f infra/compose.stub.yml up -d rrfusion-redis rrfusion-db-stub rrfusion-mcp
   ```

   The DB stub is only reachable inside the Compose stack (it listens on `rrfusion-db-stub:8080`), so no host port mapping is published by default.

4. Execute the end-to-end suite, which exercises every MCP tool (search, blend, peek/get snippets, mutate, provenance) against the running stub stack:

   ```bash
   docker compose -f infra/compose.stub.yml run --rm rrfusion-tests pytest -m e2e
   ```

The tests automatically talk to `http://mcp:3000/mcp/...` inside the Compose network, validate Redis cardinalities for the 10k-result lanes, paginate snippets under byte budgets, and cover fault cases (missing runs / doc IDs).

5. Run the large-response FastMCP transport test outside pytest’s event loop via the dedicated script (stub stack):

   ```bash
   docker compose -f infra/compose.stub.yml run --rm rrfusion-tests \
     python -m rrfusion.scripts.run_fastmcp_e2e --scenario peek-large

As a convenience, `scripts/run_e2e.sh` brings the Compose stub stack up, runs the Pytest E2E suite, and tears the stack back down with the correct MCP/DB host names. Run it from the repo root (`bash scripts/run_e2e.sh`) instead of repeating the Compose commands manually.
   ```

    This hits the streamable-http `peek_snippets` tool with a 20 KB budget and 60-item window to confirm the FastMCP stack can stream large payloads without timing out.

3. If you only need to verify `MCPService` together with Redis and the DB stub—without the streaming transport—run the integration suite:

   ```bash
   docker compose -f infra/compose.stub.yml run --rm rrfusion-tests pytest -m integration
   ```

   That flow exercises `search → blend → peek_snippets` directly, isolating problems from the SSE transport.

## FastMCP Host

- `src/rrfusion/mcp/host.py` is a `fastmcp.FastMCP` entrypoint that registers every lane/fusion/snippet tool via the `@mcp.tool` decorator. Each tool docstring contains the canonical signature plus the typical `prompts/list` / `prompts/get` prompts used throughout this README.
- Run it locally via the Python entry point:

```bash
python src/rrfusion/mcp/host.py
```

The script reads `MCP_HOST`/`MCP_PORT`, starts the streamable HTTP transport at `/mcp`, and honors `MCP_SERVICE_HOST` so other services can discover the reachable hostname.

This exposes the same logic as the FastAPI service while letting any MCP-native client install the server directly.

If you prefer Docker, `docker compose -f infra/compose.prod.yml up -d rrfusion-redis rrfusion-mcp` (after copying `infra/env.example` to `infra/.env`) will spin up Redis and the FastMCP host with port `3000` forwarded to your machine; add the DB stub by running `docker compose -f infra/compose.stub.yml up -d rrfusion-db-stub rrfusion-mcp` when you need it.

- FastMCP exposes two curated prompts (`RRFusion MCP Handbook` and `Tool Recipes`) via `@mcp.prompt`. Each prompt crushes the handbook text or the example JSON recipes so that agents can fetch guidance and copy/paste payloads directly from the same server that runs the tools.

## Prompt Catalog

1. **RRFusion MCP Handbook** – follow the documented pipeline, heuristics per tool, telemetry/metric reminders, and security notes directly from `mcp.prompt(name="RRFusion MCP Handbook")`.
2. **Tool Recipes** – pull the JSON examples for `search_fulltext`, `search_semantic`, `blend_frontier_codeaware`, `peek_snippets`, `get_snippets`, `mutate_run`, and `get_provenance` by calling `mcp.prompt(name="Tool Recipes")`.

Call the prompts if you want the FastMCP host itself to serve the guidance text instead of keeping it in README.

## Testing

`scripts/run_e2e.sh` is the canonical local CI flow: it builds `infra-rrfusion-tests`, brings up Redis + DB stub + FastMCP via `infra/compose.stub.yml`, waits for `rrfusion-mcp` to resolve, runs `pytest -m integration`, then `pytest -m e2e`, and finally tears the stack down. This shell script is what we use in the `cargo make` tasks described below.

When you call `cargo make start-stack`/`stop-stack` you get the CI-focused `infra/compose.test.yml` stack running entirely inside a Compose network (its `rrfusion-tests` service hosts the runner). The stub stack remains available via `cargo make start-stub`/`stop-stub` when you need attachable networking.

If you prefer to orchestrate via `cargo make`, the provided `Makefile.toml` defines:

1. `cargo make lint` — run `flake8` inside the CLI image.
2. `cargo make unit` — run annotated unit tests (`pytest -m unit`) inside the CLI image.
3. `cargo make integration` — start the stub stack, run `pytest -m integration`, and shut it down.
4. `cargo make e2e` — start the stub stack, run `pytest -m e2e`, and shut it down.
5. `cargo make ci` — sequentially runs lint, unit, integration, and e2e under a single invocation.

For production-like validation you can also call `cargo make start-prod`/`cargo make stop-prod`, which spin up/down `infra/compose.prod.yml` (Redis + MCP) using the same `.env` so the host port and service variables stay consistent.

Because `cargo make` reuses the same commands locally and in CI, you can run `cargo make ci` on your workstation to exercise the whole stack exactly as GitHub Actions would.

## Usage Workflow

The MCP loop always starts with independent lane searches, continues with fusion/frontier exploration, and then spends snippet budget.

1. Run both `search_fulltext` and `search_semantic` with identical query/filters to mint lane handles.
2. Feed the resulting `run_id_lane` values to `blend_frontier_codeaware` to decide which `k` frontier to review.
3. Use `peek_snippets` sparingly to preview the fused ordering, then `get_snippets` for the short-listed doc IDs.
4. When you need to branch on weights, RRF constants, or code targeting, call `mutate_run` instead of issuing new lane searches.
5. Preserve provenance by logging the fusion `run_id` and, when necessary, resolve it later via `get_provenance`.

## MCP Tool Reference

Each section shows the FastMCP-style decoration you would give the tool in an agent registry. The docstrings list the canonical signature plus typical prompts (`prompts/list` for “give me a ranked list” asks and `prompts/get` for retrieval/handle requests).

### `search_fulltext`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def search_fulltext(
    q: str,
    filters: Filters | None = None,
    top_k: int = 1000,
    rollup: RollupConfig | None = None,
    budget_bytes: int = 4096,
) -> SearchToolResponse:
    """
    signature: search_fulltext(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    prompts/list:
    - "List high-recall patent families mentioning {q} with IPC filters {filters}"
    - "List prior art using only keyword evidence for {q}"
    prompts/get:
    - "Get a lane run handle I can feed into fusion for {q}"
    """
```

The full-text lane maximizes recall by leaning on raw keyword scoring from the DB stub. Use it whenever you adjust lexical filters or before adding semantic context, and always capture the `run_id_lane` it returns.

### `search_semantic`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def search_semantic(
    q: str,
    filters: Filters | None = None,
    top_k: int = 1000,
    rollup: RollupConfig | None = None,
    budget_bytes: int = 4096,
) -> SearchToolResponse:
    """
    signature: search_semantic(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    prompts/list:
    - "List semantically similar inventions about {q}"
    - "List embedding-driven hits that stay on-spec for {q}"
    prompts/get:
    - "Get the semantic lane handle so I can blend with run {q}"
    """
```

This lane biases toward precision by using embedding similarity. Pair it with the full-text lane for every query so downstream fusion can rebalance precision/recall on demand.

### `blend_frontier_codeaware`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def blend_frontier_codeaware(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta: float = 1.0,
    family_fold: bool = True,
    target_profile: dict[str, dict[str, float]] | None = None,
    top_m_per_lane: dict[str, int] | None = None,
    k_grid: list[int] | None = None,
    peek: PeekConfig | None = None,
) -> BlendResponse:
    """
    signature: blend_frontier_codeaware(
        runs: list[BlendRunInput],
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        beta: float = 1.0,
        family_fold: bool = True,
        target_profile: dict[str, dict[str, float]] | None = None,
        top_m_per_lane: dict[str, int] | None = None,
        k_grid: list[int] | None = None,
        peek: PeekConfig | None = None,
    )
    prompts/list:
    - "List the best fusion frontier balancing recall and precision for {runs}"
    - "List fused rankings that favor IPC {target_profile}"
    prompts/get:
    - "Get a fusion run_id with frontier stats so I can peek snippets for {runs}"
    """
```

Fusion consumes multiple lane handles, applies RRF plus optional code-aware boosts, and returns the final ranking with a `frontier` summary. Reuse the `run_id` it emits for snippet peeks, provenance, or further mutation.

### `peek_snippets`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def peek_snippets(
    run_id: str,
    offset: int = 0,
    limit: int = 12,
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
    claim_count: int = 3,
    strategy: Literal["head", "match", "mix"] = "head",
    budget_bytes: int = 12_288,
) -> PeekSnippetsResponse:
    """
    signature: peek_snippets(
        run_id: str,
        offset: int = 0,
        limit: int = 12,
        fields: list[str] | None = None,
        per_field_chars: dict[str, int] | None = None,
        claim_count: int = 3,
        strategy: Literal["head","match","mix"] = "head",
        budget_bytes: int = 12288,
    )
    prompts/list:
    - "List snippet previews for the top {limit} docs in fusion run {run_id}"
    - "List concise abstracts for positions {offset}-{offset + limit}"
    prompts/get:
    - "Get the next peek_cursor so I can continue streaming run {run_id}"
    """
```

`peek_snippets` is the budget-gated way to inspect the fused ordering. Keep requests under `PEEK_MAX_DOCS` and watch the `peek_cursor` if you need to paginate through the ranking.

By default it returns up to 12 items with `["title","abst","claim"]`, clamping each field to 160/480/320 characters so the total size stays under 12 KB (`PEEK_BUDGET_BYTES`). If you request more fields or larger `per_field_chars`, it still guarantees at least one result by progressively truncating title/abstract text first.

### `get_snippets`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def get_snippets(
    ids: list[str],
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]:
    """
    signature: get_snippets(ids: list[str], fields: list[str] | None = None, per_field_chars: dict[str, int] | None = None)
    prompts/list:
    - "List detailed snippets for the decision-ready doc IDs {ids}"
    - "List claims plus abstracts for specific documents after shortlisting"
    prompts/get:
    - "Get the text payloads for ids {ids} without touching the fusion cursor"
    """
```

Use this tool after you already know which doc IDs matter. It skips pagination and returns a simple `{doc_id: {field: text}}` mapping for write-ups or citation exports.

### `mutate_run`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def mutate_run(run_id: str, delta: MutateDelta) -> MutateResponse:
    """
    signature: mutate_run(run_id: str, *, delta: MutateDelta)
    prompts/list:
    - "List how the ranking shifts if we bump semantic weight via {delta.weights}"
    - "List frontier deltas after tightening beta/rrf_k on run {run_id}"
    prompts/get:
    - "Get a fresh run_id derived from {run_id} with updated weights/filters"
    """
```

`mutate_run` copies the cached lane results, reapplies the tweaked recipe, and yields a brand-new fusion run (with lineage). Prefer this over re-searching when you only change blending parameters.

### `get_provenance`

```python
from rrfusion.mcp.host import mcp

@mcp.tool
async def get_provenance(run_id: str) -> ProvenanceResponse:
    """
    signature: get_provenance(run_id: str)
    prompts/list:
    - "List the recipe parameters that produced fusion run {run_id}"
    - "List the historical lineage for run {run_id}"
    prompts/get:
    - "Get parent/history handles so I can audit or reproduce run {run_id}"
    """
```

Call this whenever you need to cite how a run was produced or when you want to rehydrate its recipe for further experimentation.
