# rrfusion

Multi-lane patent search with **RRF fusion**, **code-aware frontier**, and **MCP** integration.

This scaffold includes:
- `AGENT.md` — the implementation brief/spec for Codex or any dev agent
- `deploy/docker-compose.yml` — spins up **Redis** locally
- `deploy/.env.example` — environment defaults

## Contents

- [Quick start (Redis only)](#quick-start-redis-only)
- [Next steps](#next-steps)
- [Usage Workflow](#usage-workflow)
- [MCP Tool Reference](#mcp-tool-reference)
  - [`search_fulltext`](#search_fulltext)
  - [`search_semantic`](#search_semantic)
  - [`blend_frontier_codeaware`](#blend_frontier_codeaware)
  - [`peek_snippets`](#peek_snippets)
  - [`get_snippets`](#get_snippets)
  - [`mutate_run`](#mutate_run)
  - [`get_provenance`](#get_provenance)

## Quick start (Redis only)

```bash
cd deploy
cp .env.example .env
docker compose up -d
docker ps  # confirm redis is up
```

## Next steps

- Point your MCP server to `REDIS_URL` from `.env`
- Hand `AGENT.md` to Codex to scaffold the FastMCP server and DB stub
- Keep large `(doc_id, score)` arrays in Redis; expose **handles** (run_id/cursor) to the LLM

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
from fastmcp import mcp

@mcp.tools.register(name="search_fulltext", path="/mcp/search_fulltext", method="POST")
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
from fastmcp import mcp

@mcp.tools.register(name="search_semantic", path="/mcp/search_semantic", method="POST")
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
from fastmcp import mcp

@mcp.tools.register(name="blend_frontier_codeaware", path="/mcp/blend_frontier_codeaware", method="POST")
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
from fastmcp import mcp

@mcp.tools.register(name="peek_snippets", path="/mcp/peek_snippets", method="POST")
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

### `get_snippets`

```python
from fastmcp import mcp

@mcp.tools.register(name="get_snippets", path="/mcp/get_snippets", method="POST")
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
from fastmcp import mcp

@mcp.tools.register(name="mutate_run", path="/mcp/mutate_run", method="POST")
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
from fastmcp import mcp

@mcp.tools.register(name="get_provenance", path="/mcp/get_provenance", method="POST")
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
