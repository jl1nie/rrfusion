# rrfusion

Multi-lane patent search with **RRF fusion**, **code-aware frontier**, and **MCP** integration.

This scaffold includes:
- `AGENT.md` — the implementation brief/spec for Codex or any dev agent
- `apps/db_stub` — FastAPI stub entrypoint plus a dedicated Dockerfile
- `apps/mcp-host` — FastMCP/test image Dockerfile reused by Compose
- `infra/compose.prod.yml` — minimal Redis + MCP stack (no DB stub) suitable for production-like runs
- `infra/compose.test.yml` — hermetic stack with Redis, the DB stub, MCP, and the pytest runner
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

Visit `http://localhost:3000/healthz` to confirm the FastMCP host is up. Run `docker compose -f infra/compose.prod.yml down` when you're done. Use `infra/compose.test.yml` whenever you need an isolated network that also brings up the DB stub and pytest runner:

> **Network note:** set `MCP_EXTERNAL_NETWORK=<existing-network>` (e.g., `docker_default`) before running Compose to join that external network; services still advertise `redis`, `db-stub`, `mcp`, and `tests` aliases so the code inside the stack keeps working.

```bash
docker compose -f infra/compose.test.yml run --rm rrfusion-tests pytest -m smoke
```

> **Note:** The FastMCP host uses a single Streamable HTTP endpoint at `/mcp`, so both the POST calls and streaming responses flow through `http://{host}:{port}/mcp`. Set `MCP_SERVICE_HOST`/`MCP_PORT` (e.g., `localhost` in `infra/env.example`, `mcp` in the Compose `.env`) to control where clients should reach the service.

> **Auth:** Set `MCP_API_TOKEN=<token>` in `infra/.env` (and restart the stack) to require `Authorization: Bearer <token>` on every FastMCP request.

## E2E testing & 10k stub data

1. Copy `infra/env.example` to `infra/.env`, then set `STUB_MAX_RESULTS=10000` to force the DB stub to emit 10k docs per lane.  
2. (Optional) Snapshot the deterministic dataset for later inspection:

   ```bash
   uv run python -m rrfusion.scripts.make_stub_dataset --count 10000 --lane fulltext --output tests/data/stub_docs_10k.jsonl
   ```

3. Bring up Redis, the stub, and MCP as usual:

   ```bash
   docker compose -f infra/compose.test.yml up -d rrfusion-redis rrfusion-db-stub rrfusion-mcp
   ```

   If your host already binds port 8080, export `DB_STUB_PORT=<other>` (and keep `DB_STUB_URL=http://db-stub:8080`) before running Compose so only the host mapping shifts.

4. Execute the end-to-end suite, which exercises every MCP tool (search, blend, peek/get snippets, mutate, provenance) against the running stack:

   ```bash
   docker compose -f infra/compose.test.yml run --rm rrfusion-tests pytest -m e2e
   ```

The tests automatically talk to `http://mcp:3000/mcp/...` inside the Compose network, validate Redis cardinalities for the 10k-result lanes, paginate snippets under byte budgets, and cover fault cases (missing runs / doc IDs).

5. Run the large-response FastMCP transport test outside pytest’s event loop via the dedicated script:

   ```bash
   docker compose -f infra/compose.test.yml run --rm rrfusion-tests \
     python -m rrfusion.scripts.run_fastmcp_e2e --scenario peek-large
   ```

   This hits the streamable-http `peek_snippets` tool with a 20 KB budget and 60-item window to confirm the FastMCP stack can stream large payloads without timing out.

3. If you only need to verify `MCPService` together with Redis and the DB stub—without the streaming transport—run the integration suite:

   ```bash
   docker compose -f infra/compose.test.yml run --rm rrfusion-tests pytest -m integration
   ```

   That flow exercises `search → blend → peek_snippets` directly, isolating problems from the SSE transport.

## FastMCP Host

- `src/rrfusion/mcp/host.py` is a `fastmcp.FastMCP` entrypoint that registers every lane/fusion/snippet tool via the `@mcp.tool` decorator. Each tool docstring contains the canonical signature plus the typical `promits/list` / `prompts/list` / `prompts/gets` prompts used throughout this README.
- Run it locally via the Python entry point:

```bash
python src/rrfusion/mcp/host.py
```

The script reads `MCP_HOST`/`MCP_PORT`, starts the streamable HTTP transport at `/mcp`, and honors `MCP_SERVICE_HOST` so other services can discover the reachable hostname.

This exposes the same logic as the FastAPI service while letting any MCP-native client install the server directly.

If you prefer Docker, `docker compose -f infra/compose.prod.yml up -d rrfusion-redis rrfusion-mcp` (after copying `infra/env.example` to `infra/.env`) will spin up Redis and the FastMCP host with port `3000` forwarded to your machine; add the DB stub by running `docker compose -f infra/compose.test.yml up -d rrfusion-db-stub` when you need it.

## Usage Workflow

The MCP loop always starts with independent lane searches, continues with fusion/frontier exploration, and then spends snippet budget.

1. Run both `search_fulltext` and `search_semantic` with identical query/filters to mint lane handles.
2. Feed the resulting `run_id_lane` values to `blend_frontier_codeaware` to decide which `k` frontier to review.
3. Use `peek_snippets` sparingly to preview the fused ordering, then `get_snippets` for the short-listed doc IDs.
4. When you need to branch on weights, RRF constants, or code targeting, call `mutate_run` instead of issuing new lane searches.
5. Preserve provenance by logging the fusion `run_id` and, when necessary, resolve it later via `get_provenance`.

## MCP Tool Reference

Each section shows the FastMCP-style decoration you would give the tool in an agent registry. The docstrings list the canonical signature plus typical prompts (`promits/list` for “give me a ranked list” asks and `prompts/gets` for retrieval/handle requests).

### `search_fulltext`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="search_fulltext")
async def search_fulltext(request: SearchRequest) -> SearchToolResponse:
    """
    signature: search_fulltext(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    promits/list:
    - "List high-recall patent families mentioning {topic} with IPC filters {codes}"
    prompts/list:
    - "List prior art using only keyword evidence for {technology}"
    prompts/gets:
    - "Get a lane run handle I can feed into fusion for {query}"
    """
```

The full-text lane maximizes recall by leaning on raw keyword scoring from the DB stub. Use it whenever you adjust lexical filters or before adding semantic context, and always capture the `run_id_lane` it returns.

### `search_semantic`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="search_semantic")
async def search_semantic(request: SearchRequest) -> SearchToolResponse:
    """
    signature: search_semantic(q: str, filters: Filters | None = None, top_k: int = 1000, rollup: RollupConfig | None = None, budget_bytes: int = 4096)
    promits/list:
    - "List semantically similar inventions about {capability}"
    prompts/list:
    - "List embedding-driven hits that stay on-spec for {system}"
    prompts/gets:
    - "Get the semantic lane handle so I can blend with run {id}"
    """
```

This lane biases toward precision by using embedding similarity. Pair it with the full-text lane for every query so downstream fusion can rebalance precision/recall on demand.

### `blend_frontier_codeaware`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="blend_frontier_codeaware")
async def blend_frontier_codeaware(request: BlendRequest) -> BlendResponse:
    """
    signature: blend_frontier_codeaware(runs: list[BlendRunInput], weights: dict[str, float], rrf_k: int = 60, beta: float = 1.0, family_fold: bool = True, target_profile: dict[str, dict[str, float]] | None = None, top_m_per_lane: dict[str, int], k_grid: list[int], peek: PeekConfig | None = None)
    promits/list:
    - "List the best fusion frontier for balancing recall and precision on {query}"
    prompts/list:
    - "List fused rankings that favor IPC {code} at {k} depth"
    prompts/gets:
    - "Get a fusion run_id with frontier stats so I can peek snippets later"
    """
```

Fusion consumes multiple lane handles, applies RRF plus optional code-aware boosts, and returns the final ranking with a `frontier` summary. Reuse the `run_id` it emits for snippet peeks, provenance, or further mutation.

### `peek_snippets`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="peek_snippets")
async def peek_snippets(request: PeekSnippetsRequest) -> PeekSnippetsResponse:
    """
    signature: peek_snippets(run_id: str, offset: int = 0, limit: int = 20, fields: list[str] = ..., per_field_chars: dict[str, int] = ..., claim_count: int = 3, strategy: Literal["head","match","mix"] = "head", budget_bytes: int = 12288)
    promits/list:
    - "List snippet previews for the top {n} docs in fusion run {id}"
    prompts/list:
    - "List concise abstracts for positions {offset}-{offset+limit}"
    prompts/gets:
    - "Get the next peek_cursor so I can continue scrolling this run"
    """
```

`peek_snippets` is the budget-gated way to inspect the fused ordering. Keep requests under `PEEK_MAX_DOCS` and watch the `peek_cursor` if you need to paginate through the ranking.

デフォルトでは 12 件・`["title","abst","claim"]`・各 160/480/320 文字に収める設定になっており、総バイト数が 12 KB（`PEEK_BUDGET_BYTES`）を超えないように自動的にスケールします。フィールドを増やしたり大きな `per_field_chars` を指定した場合でも、最低 1 件は返せるようにタイトル／抄録を優先して縮めます。

### `get_snippets`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="get_snippets")
async def get_snippets(request: GetSnippetsRequest) -> dict[str, dict[str, str]]:
    """
    signature: get_snippets(ids: list[str], fields: list[str] = ..., per_field_chars: dict[str, int] = ...)
    promits/list:
    - "List detailed snippets for the decision-ready doc IDs {ids}"
    prompts/list:
    - "List claims plus abstracts for specific documents after shortlisting"
    prompts/gets:
    - "Get the text payloads for ids {ids} without touching the fusion cursor"
    """
```

Use this tool after you already know which doc IDs matter. It skips pagination and returns a simple `{doc_id: {field: text}}` mapping for write-ups or citation exports.

### `mutate_run`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="mutate_run")
async def mutate_run(request: MutateRequest) -> MutateResponse:
    """
    signature: mutate_run(run_id: str, delta: MutateDelta)
    promits/list:
    - "List how the ranking shifts if we bump semantic weight by {x}"
    prompts/list:
    - "List frontier deltas after tightening beta/rrf_k on run {id}"
    prompts/gets:
    - "Get a fresh run_id derived from {id} with updated weights/filters"
    """
```

`mutate_run` copies the cached lane results, reapplies the tweaked recipe, and yields a brand-new fusion run (with lineage). Prefer this over re-searching when you only change blending parameters.

### `get_provenance`

```python
from rrfusion.mcp.host import mcp

@mcp.tool(name="get_provenance")
async def get_provenance(request: ProvenanceRequest) -> ProvenanceResponse:
    """
    signature: get_provenance(run_id: str)
    promits/list:
    - "List the recipe parameters that produced fusion run {id}"
    prompts/list:
    - "List the historical lineage for run {id}"
    prompts/gets:
    - "Get parent/history handles so I can audit or reproduce this run"
    """
```

Call this whenever you need to cite how a run was produced or when you want to rehydrate its recipe for further experimentation.
