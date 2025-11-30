# Claude Code Development Guide for RRFusion

## Overview
This directory contains Claude Code skills and documentation for developing the RRFusion multi-lane patent search system.

## What is RRFusion?
RRFusion is a sophisticated patent search engine that:
- Combines multiple search strategies (fulltext, semantic, code-based) using Reciprocal Rank Fusion (RRF)
- Provides code-aware ranking with FI/FT/CPC/IPC classification systems
- Exposes search capabilities via MCP (Model Context Protocol) for LLM agents
- Uses Redis for high-performance caching and fusion operations
- Originally developed with Codex (Anthropic's AI development tool)

## Quick Start for Claude Code

### 1. First Time Setup
```bash
# Install dependencies
uv sync --all-packages

# Copy environment template
cp infra/env.example infra/.env

# Start development stack
cargo make start-ci

# Verify health
curl http://localhost:3000/healthz
```

### 2. Read Key Documents First
1. [AGENT.md](../../AGENT.md) - Implementation spec & API reference
2. [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) - LLM agent behavior
3. [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md) - Mathematical foundation

### 3. Development Workflow
```bash
# 1. Make changes
# 2. Check specs consistency (use spec-check skill)
# 3. Run tests (use test-workflow skill)
cargo make lint
cargo make unit
cargo make integration
cargo make e2e

# 4. Commit with updated docs
```

## Skills Directory

### [test-workflow.md](skills/test-workflow.md)
Execute test suites and debug test failures.

**Use when**:
- Running tests before commit
- Debugging CI failures
- Validating new features

**Key commands**:
- `cargo make ci` - Full test suite
- `cargo make integration` - Integration tests with Redis/MCP
- `cargo make e2e` - End-to-end FastMCP tests

### [spec-check.md](skills/spec-check.md)
Verify consistency between code and specification documents.

**Use when**:
- Before committing changes
- After modifying MCP tools
- When changing fusion algorithm
- Adding new lanes

**Checklist**:
- SystemPrompt.yaml synchronized
- RRFusionSpecification.md updated
- AGENT.md API spec current
- Code implementation matches specifications

### [lane-design.md](skills/lane-design.md)
Guide for designing and implementing search lanes.

**Use when**:
- Adding new search lanes
- Tuning existing lanes
- Understanding lane roles
- Debugging query construction

**Covers**:
- Lane types (wide/recall/precision/semantic/problem)
- Field boosts configuration
- Code system rules (FI/FT/CPC/IPC)
- A/B/C decomposition
- Query construction patterns
- Anti-patterns to avoid

### [redis-debug.md](skills/redis-debug.md)
Debug Redis data structures and storage issues.

**Use when**:
- Lane results missing
- Fusion runs not found
- Code frequencies incorrect
- Memory eviction issues

**Tools**:
- Redis CLI commands
- Key inspection patterns
- TTL verification
- Memory analysis

### [mcp-development.md](skills/mcp-development.md)
Guide for developing MCP tools and FastMCP integration.

**Use when**:
- Adding new MCP tools
- Debugging tool calls
- Understanding MCP architecture
- Testing backend adapters

**Covers**:
- MCP tool signatures
- FastMCP registration
- Backend adapters (Patentfield, DB stub)
- Testing strategies
- Error handling patterns

### [fusion-algorithm.md](skills/fusion-algorithm.md)
Implementation guide for RRF fusion and code-aware algorithms.

**Use when**:
- Understanding fusion math
- Debugging scoring issues
- Tuning fusion parameters
- Implementing new metrics

**Covers**:
- Weighted RRF formula
- Code-aware adjustments (A/B/C)
- Frontier estimation (P*/R*/F*)
- Structural metrics (LAS/CCW/S-shape/Fproxy)
- Contribution tracking
- Tuning recipes

## Architecture Overview

```
┌──────────────────────────────────────────┐
│ LLM Agent                                │
│ (Uses SystemPrompt.yaml for behavior)   │
└───────────────┬──────────────────────────┘
                │ MCP Protocol
┌───────────────▼──────────────────────────┐
│ FastMCP Server (src/rrfusion/mcp/host.py)│
│ - search_fulltext / search_semantic      │
│ - rrf_blend_frontier                     │
│ - peek_snippets / get_snippets           │
│ - rrf_mutate_run / get_provenance        │
└───────────────┬──────────────────────────┘
                │
┌───────────────▼──────────────────────────┐
│ Fusion Engine (src/rrfusion/fusion.py)  │
│ - Weighted RRF                           │
│ - Code-aware boost (FI/FT/CPC/IPC)       │
│ - Frontier estimation                    │
└───────────────┬──────────────────────────┘
                │
┌───────────────▼──────────────────────────┐
│ Redis Storage (src/rrfusion/storage.py) │
│ - Lane ZSETs                             │
│ - Fusion runs                            │
│ - Code frequencies                       │
│ - Snippet cache                          │
└───────────────┬──────────────────────────┘
                │
┌───────────────▼──────────────────────────┐
│ Backend Adapters                         │
│ - Patentfield (production)               │
│ - DB Stub (CI/testing)                   │
└──────────────────────────────────────────┘
```

## Key Concepts

### Lanes
Search strategies with different purposes:
- **fulltext_wide**: Broad recall
- **semantic**: Conceptual similarity
- **fulltext_recall**: In-field coverage
- **fulltext_precision**: High-precision candidates
- **fulltext_problem**: Problem-focused (conditional)

### Code Systems
Patent classification systems (NEVER mix in single lane):
- **FI** (File Index): Japan-specific, use subgroups (fi_norm) only
- **FT** (F-Term): Problem/structure tags, boost-only in most cases
- **CPC**: EPO/USPTO cooperative classification
- **IPC**: International patent classification

### RRF Fusion
Combines multiple lane rankings:
```
RRF(doc) = Σ(w_lane / (rrf_k + rank_lane(doc)))
```

### Code-Aware Boost
Adjusts scores based on FI/CPC/IPC overlap with target_profile:
```
boosted_score(doc) = rrf_score(doc) * (1 + α * code_overlap(doc))
```

### Frontier Metrics
Estimate precision/recall without ground truth:
- **P*(k)**: Relevance proxy average
- **R*(k)**: Code coverage + score distribution
- **F_β*(k)**: F-measure with β=1.5 (favor recall)

## Important Development Principles

### Understanding the System Architecture

RRFusion is designed to be used by **LLM agents** (like Claude or GPT) that follow specific search strategies defined in [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml). As a Claude Code developer, your role is to:

1. **Implement the infrastructure** that supports those strategies
2. **Maintain consistency** between code and specifications
3. **Ensure the system behaves** as documented in AGENT.md and SystemPrompt.yaml

### Key Implementation Requirements

#### FI Normalization Support
The system must support **two-level FI handling**:
- `fi_norm`: Subgroup-level codes (e.g., "G06V10/82") - used for filtering and metrics
- `fi_full`: Full codes with edition symbols (e.g., "G06V10/82A") - used for weak ranking hints

**Why this matters**: The LLM agent's SystemPrompt defines how these fields are used in queries. Your implementation must provide both fields correctly.

#### Code System Flexibility
The system must support multiple classification systems (FI/FT/CPC/IPC) **independently**:
- Storage layer: Store all code systems per document
- Fusion layer: Apply code-aware boosts using the requested system
- Backend adapters: Map filters correctly per system

**Why this matters**: The LLM agent decides which code system to use per lane based on jurisdiction (JP→FI/FT, US/EP→CPC/IPC). Your implementation must handle all systems correctly.

#### Query Interface Design
The MCP tools must accept:
- `search_fulltext`: Structured Boolean queries (AND/OR/NOT/NEAR/phrase)
- `search_semantic`: Natural language text
- Both: Flexible filter conditions for any code system

**Why this matters**: The LLM agent generates different query styles per lane. Your implementation must parse and execute them correctly.

### Testing Strategy
1. `cargo make lint` - Fast syntax checks
2. `cargo make unit` - Isolated unit tests
3. `cargo make integration` - Redis/MCP integration
4. `cargo make e2e` - Full FastMCP stack

## Common Tasks

### Adding a New MCP Tool
1. Define Pydantic models in [models.py](../../src/rrfusion/models.py)
2. Implement business logic in [mcp/service.py](../../src/rrfusion/mcp/service.py)
3. Register in [mcp/host.py](../../src/rrfusion/mcp/host.py) with `@mcp.tool`
4. Update [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) tool_usage section
5. Update [AGENT.md](../../AGENT.md) API spec
6. Add tests in tests/integration/
7. Run `cargo make ci`

See [mcp-development.md](skills/mcp-development.md) for details.

### Adding a New Lane
1. Define in [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) lanes section
2. Set field_boosts, code_system_policy, query_style
3. Update [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md)
4. Test with different queries
5. Document in [lane-design.md](skills/lane-design.md)

### Debugging Fusion Issues
1. Use [redis-debug.md](skills/redis-debug.md) to inspect ZSETs
2. Check code frequencies with `HGETALL h:freq:{run_id}:fulltext`
3. Verify target_profile with `get_provenance`
4. Review structural metrics (LAS/CCW/S-shape/Fproxy)
5. See [fusion-algorithm.md](skills/fusion-algorithm.md) for tuning

### Fixing Test Failures
1. Check which suite failed (lint/unit/integration/e2e)
2. For integration/e2e: Verify Docker stack with `cargo make start-ci`
3. Check Redis connection and data
4. Review recent spec changes
5. Update SystemPrompt.yaml if MCP tools changed

See [test-workflow.md](skills/test-workflow.md) for details.

## Environment Variables

### infra/.env
```bash
# Redis
REDIS_URL=redis://redis:6379/0
REDIS_MAX_MEMORY=2gb
REDIS_MAXMEMORY_POLICY=volatile-lru

# MCP Server
MCP_HOST=0.0.0.0
MCP_PORT=3000
MCP_SERVICE_HOST=mcp  # Use 'localhost' outside Docker

# Fusion
RRF_K=60
PEEK_MAX_DOCS=100
PEEK_BUDGET_BYTES=12288

# TTLs
DATA_TTL_HOURS=12
SNIPPET_TTL_HOURS=24

# Testing
STUB_MAX_RESULTS=2000  # Set to 10000 for E2E load tests
```

## Troubleshooting

### Tests failing after code changes
1. Update [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml)
2. Update [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md)
3. Check [spec-check.md](skills/spec-check.md) consistency checklist
4. Re-run `cargo make ci`

### Redis connection errors
```bash
# Check Docker stack
docker compose -f infra/compose.ci.yml ps

# Restart if needed
cargo make stop-ci
cargo make start-ci
```

### MCP tool call failures
1. Check tool signature in [mcp/host.py](../../src/rrfusion/mcp/host.py)
2. Verify request models in [models.py](../../src/rrfusion/models.py)
3. Check backend adapter response in [backends/](../../src/rrfusion/mcp/backends/)
4. Test with integration suite: `cargo make integration`

### Fusion scores look wrong
1. Inspect Redis ZSET: `ZREVRANGE z:rrf:{run_id} 0 10 WITHSCORES`
2. Check lane scores are RRF-ready: `w_lane / (k + rank)`
3. Verify code frequencies: `HGETALL h:freq:{run_id}:fulltext`
4. Review [fusion-algorithm.md](skills/fusion-algorithm.md) formulas

## Resources

### Documentation
- [README.md](../../README.md) - Quick start & workflow
- [AGENT.md](../../AGENT.md) - Implementation brief
- [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) - LLM agent spec
- [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md) - Design philosophy & math

### Code Structure
```
src/rrfusion/
├── mcp/
│   ├── host.py          # FastMCP tool registration
│   ├── service.py       # Business logic
│   ├── backends/        # Patentfield, DB stub adapters
│   └── defaults.py      # Default parameters
├── fusion.py            # RRF & code-aware algorithms
├── storage.py           # Redis operations
├── models.py            # Pydantic models
├── snippets.py          # Snippet handling
└── config.py            # Environment config
```

### Testing
```
tests/
├── unit/                # Pure logic tests
├── integration/         # MCP service + Redis (no HTTP)
└── e2e/                 # Full FastMCP stack via HTTP
```

### Infrastructure
```
infra/
├── compose.prod.yml     # Production-like (Redis + MCP)
├── compose.ci.yml       # CI hermetic (Redis + DB stub + MCP + pytest)
├── compose.stub.yml     # Local E2E (attachable network)
└── env.example          # Environment template
```

## Contributing

### Before committing
1. Run full test suite: `cargo make ci`
2. Update relevant specs (use [spec-check.md](skills/spec-check.md))
3. Add/update tests for changed functionality
4. Verify implementation matches documented behavior in AGENT.md and SystemPrompt.yaml
5. Ensure FI normalization infrastructure works correctly (if modified storage/fusion layers)

### Code style
- Use Ruff for linting: `cargo make lint`
- Follow existing patterns in codebase
- Add type hints for new functions
- Document complex algorithms with references to spec

### Testing philosophy
- Unit tests: Pure logic, no external dependencies
- Integration tests: Service layer with Redis, no HTTP transport
- E2E tests: Full FastMCP HTTP stack, realistic scenarios

## Getting Help

### When stuck
1. Read the relevant skill:
   - Tests failing? → [test-workflow.md](skills/test-workflow.md)
   - Spec confusion? → [spec-check.md](skills/spec-check.md)
   - Lane design? → [lane-design.md](skills/lane-design.md)
   - Redis issues? → [redis-debug.md](skills/redis-debug.md)
   - MCP tools? → [mcp-development.md](skills/mcp-development.md)
   - Fusion math? → [fusion-algorithm.md](skills/fusion-algorithm.md)

2. Check the specifications:
   - [AGENT.md](../../AGENT.md) for API details
   - [SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) for LLM behavior
   - [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md) for theory

3. Inspect the code:
   - [src/rrfusion/](../../src/rrfusion/) for implementation
   - [tests/](../../tests/) for test examples

### Pro Tips
- Always start Docker stack before integration/e2e tests
- Use `redis-cli MONITOR` to watch real-time Redis activity
- Check `h:run:{run_id}` metadata for fusion debugging
- FI normalization: Ensure both fi_norm and fi_full are stored and available
- Structural metrics (Fproxy) guide tuning: ≥0.5 is healthy
- When in doubt, read [RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md)
- Remember: SystemPrompt.yaml defines LLM agent behavior, your code implements the infrastructure

---

**Happy coding with Claude Code!** 🚀
