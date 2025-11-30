# MCP Development Skill

## Purpose
Guide development of MCP tools and FastMCP integration.

## MCP Architecture

```
┌─────────────────────────────────────┐
│ LLM Agent (Claude/GPT)              │
└──────────────┬──────────────────────┘
               │ MCP Protocol
┌──────────────▼──────────────────────┐
│ FastMCP Server (host.py)            │
│ - HTTP Transport (/mcp)             │
│ - Tool Registration (@mcp.tool)     │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│ MCPService (service.py)             │
│ - Business Logic                    │
│ - Redis Orchestration               │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│ Storage Layer (storage.py)          │
│ - Redis Operations                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│ Backend Adapters (backends/)        │
│ - Patentfield                       │
│ - DB Stub (CI/test)                 │
└─────────────────────────────────────┘
```

## MCP Tools

### 1. search_fulltext
**File**: [src/rrfusion/mcp/host.py](../../src/rrfusion/mcp/host.py)

**Signature**:
```python
@mcp.tool
async def search_fulltext(
    query: str,
    filters: list[Cond] | None = None,
    top_k: int = 50,
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id"
) -> list[str]:
    """Fulltext search returning ranked IDs."""
```

**Implementation checklist**:
- [ ] Query validation (not natural language)
- [ ] Filter conversion (Cond → backend format)
- [ ] Redis storage with RRF-ready scores
- [ ] Code freq collection (IPC/CPC/FI/FT)
- [ ] Return run handle only

### 2. search_semantic
**Signature**:
```python
@mcp.tool
async def search_semantic(
    text: str,
    filters: list[Cond] | None = None,
    top_k: int = 50,
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id"
) -> list[str]:
    """Semantic search returning ranked IDs."""
```

**Implementation checklist**:
- [ ] Text validation (natural language expected)
- [ ] Feature scope mapping
- [ ] Redis storage
- [ ] Code freq collection

### 3. rrf_blend_frontier
**Signature**:
```python
@mcp.tool
async def rrf_blend_frontier(
    request: BlendRequest
) -> RunHandle:
    """Fuse multiple lanes with code-aware RRF."""
```

**Implementation checklist**:
- [ ] Validate all run_id_lane exist
- [ ] ZUNIONSTORE with weights
- [ ] Code-aware boosts (A/B/C)
- [ ] Frontier estimation
- [ ] Contribution tracking
- [ ] Store recipe in h:run:{run_id}

### 4. peek_snippets
**Signature**:
```python
@mcp.tool
async def peek_snippets(
    run_id: str,
    offset: int = 0,
    limit: int = 12,
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
    budget_bytes: int = 12_288
) -> PeekSnippetsResponse:
    """Preview top docs with byte budget."""
```

**Implementation checklist**:
- [ ] Enforce PEEK_MAX_DOCS
- [ ] Enforce budget_bytes
- [ ] Field truncation logic
- [ ] Return peek_cursor for pagination

### 5. get_publication
**Signature**:
```python
@mcp.tool
async def get_publication(
    ids: list[str],
    id_type: Literal["pub_id", "app_doc_id", "app_id", "exam_id"] = "app_id",
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None
) -> dict[str, dict[str, str]]:
    """Fetch publication-level data with caps."""
```

**Implementation checklist**:
- [ ] ID type handling (pub_id/app_id/etc)
- [ ] Backend adapter call
- [ ] Per-field char caps
- [ ] Japanese number normalization (特願/特開)

### 6. get_snippets
**Signature**:
```python
@mcp.tool
async def get_snippets(
    ids: list[str],
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None
) -> dict[str, dict[str, str]]:
    """Direct snippet lookup by IDs."""
```

### 7. rrf_mutate_run
**Signature**:
```python
@mcp.tool
async def rrf_mutate_run(
    run_id: str,
    delta: MutateDelta
) -> RunHandle:
    """Create new fusion run with parameter deltas."""
```

**Implementation checklist**:
- [ ] Load parent recipe
- [ ] Apply deltas (absolute overwrite)
- [ ] Recompute fusion
- [ ] Store lineage
- [ ] Return new run_id

### 8. get_provenance
**Signature**:
```python
@mcp.tool
async def get_provenance(
    run_id: str,
    top_k_lane: int = 20,
    top_k_code: int = 30
) -> ProvenanceResponse:
    """Return recipe, lineage, and metrics."""
```

### 9. register_representatives
**Signature**:
```python
@mcp.tool
async def register_representatives(
    run_id: str,
    representatives: list[Representative]
) -> RegisterRepresentativesResponse:
    """Register A/B/C labeled representatives."""
```

**Implementation checklist**:
- [ ] Validate run_id is fusion (not lane)
- [ ] Store representatives in Redis
- [ ] Update priority_pairs computation

## Adding a New MCP Tool

### 1. Define Pydantic models
```python
# In models.py
class MyToolRequest(BaseModel):
    param1: str
    param2: int = 10

class MyToolResponse(BaseModel):
    result: str
    meta: dict
```

### 2. Implement in MCPService
```python
# In mcp/service.py
async def my_new_tool(self, request: MyToolRequest) -> MyToolResponse:
    # Business logic here
    return MyToolResponse(result="...", meta={})
```

### 3. Register in FastMCP host
```python
# In mcp/host.py
@mcp.tool
async def my_new_tool(
    param1: str,
    param2: int = 10
) -> MyToolResponse:
    """
    Tool description for LLM.

    Args:
        param1: Description
        param2: Description
    """
    service = await get_service()
    request = MyToolRequest(param1=param1, param2=param2)
    return await service.my_new_tool(request)
```

### 4. Update prompts/SystemPrompt_v1_5.yaml
```yaml
tool_usage:
  my_new_tool:
    when_to_use:
      - step: my_pipeline_step
    key_arguments:
      - param1
      - param2
    notes:
      - Usage guidance for LLM
```

### 5. Add tests
```python
# tests/integration/test_my_tool.py
async def test_my_new_tool():
    service = MCPService(...)
    request = MyToolRequest(param1="test")
    response = await service.my_new_tool(request)
    assert response.result == "expected"
```

### 6. Update AGENT.md
Add API specification to section 5.

## Testing MCP Tools

### Local FastMCP server
```bash
# Start server
uv run fastmcp run --transport http src/rrfusion/mcp/host.py -- --host 0.0.0.0 --port 3000

# Health check
curl http://localhost:3000/healthz
```

### Docker stack
```bash
# Start CI stack
cargo make start-ci

# Test via pytest
docker compose -f infra/compose.ci.yml exec -T rrfusion-tests pytest -m e2e

# Manual tool call
docker compose -f infra/compose.ci.yml exec -T rrfusion-tests python -c "
import httpx
resp = httpx.post('http://mcp:3000/mcp/tools/call', json={
    'name': 'search_fulltext',
    'arguments': {'query': 'solar panel', 'top_k': 10}
})
print(resp.json())
"
```

### Integration tests
```python
# tests/integration/test_mcp_integration.py
# Tests service layer without HTTP transport

async def test_search_fulltext_integration():
    service = MCPService(...)
    response = await service.search_fulltext(...)
    assert response.run_id
```

### E2E tests
```python
# tests/e2e/test_mcp_tools.py
# Tests full FastMCP HTTP stack

async def test_search_fulltext_e2e():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://mcp:3000/mcp/tools/call",
            json={"name": "search_fulltext", "arguments": {...}}
        )
        assert resp.status_code == 200
```

## Backend Adapters

### Patentfield Adapter
**File**: [src/rrfusion/mcp/backends/patentfield.py](../../src/rrfusion/mcp/backends/patentfield.py)

**Responsibilities**:
- Convert filters to Patentfield API format
- Handle FI normalization
- Map semantic feature_scope to Patentfield feature
- Parse responses

### DB Stub Adapter
**File**: [src/rrfusion/mcp/backends/ci.py](../../src/rrfusion/mcp/backends/ci.py)

**Responsibilities**:
- Deterministic randomized results
- Support STUB_MAX_RESULTS
- Generate synthetic code frequencies
- Provide snippet cache

## Common Patterns

### Error handling
```python
from fastapi import HTTPException

@mcp.tool
async def my_tool(...):
    try:
        # Logic
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")
```

### Redis key naming
```python
# Use storage.py helpers
from rrfusion.storage import (
    lane_key,      # z:{snapshot}:{query_hash}:{lane}
    fusion_key,    # z:rrf:{run_id}
    freq_key,      # h:freq:{run_id}:{lane}
    run_key,       # h:run:{run_id}
    snippet_key    # h:snippet:{doc_id}
)
```

### Async context
```python
# Always use async for Redis/HTTP
async def my_func():
    async with service.redis_client.pipeline() as pipe:
        pipe.zrevrange(...)
        pipe.hgetall(...)
        results = await pipe.execute()
```

## References
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [MCP Protocol Spec](https://spec.modelcontextprotocol.io/)
- [host.py implementation](../../src/rrfusion/mcp/host.py)
- [service.py implementation](../../src/rrfusion/mcp/service.py)
- [AGENT.md MCP Tools](../../AGENT.md#L152-L355)
