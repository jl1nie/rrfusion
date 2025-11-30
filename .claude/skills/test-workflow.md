# Test Workflow Skill

## Purpose
Execute RRFusion test suite following the project's testing strategy.

## Usage
Run this skill when you need to:
- Verify changes before committing
- Debug test failures
- Validate new features

## Commands

### Full CI Pipeline
```bash
cargo make ci
```

### Individual Test Suites
```bash
# Lint only
cargo make lint

# Unit tests only
cargo make unit

# Integration tests (with Docker stack)
cargo make integration

# E2E tests (with FastMCP transport)
cargo make e2e
```

### Manual Docker Stack Management
```bash
# Start CI stack
cargo make start-ci

# Check logs
cargo make logs

# Stop CI stack
cargo make stop-ci
```

## Test Markers
- `@pytest.mark.integration`: MCP service integration without transport
- `@pytest.mark.e2e`: Full FastMCP HTTP transport tests

## Common Issues

### Redis connection errors
- Ensure `cargo make start-ci` succeeded
- Check `docker compose -f infra/compose.ci.yml ps`

### Test failures after spec changes
1. Update [prompts/SystemPrompt_v1_5.yaml](../../prompts/SystemPrompt_v1_5.yaml)
2. Update [docs/searcher/01_concept.md](../../docs/searcher/01_concept.md)
3. Re-run tests with `cargo make ci`

## Development Loop
1. Make code changes
2. Run `cargo make lint` first (fast feedback)
3. Run `cargo make unit` for isolated tests
4. Run `cargo make integration` for Redis/MCP tests
5. Run `cargo make e2e` for full stack validation
