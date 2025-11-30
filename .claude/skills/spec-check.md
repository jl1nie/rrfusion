# Specification Check Skill

## Purpose
Verify consistency between code and specification documents.

## Key Documents

### 1. SystemPrompt.yaml
**Location**: [src/rrfusion/SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml)

**What to check**:
- Lane definitions match code implementation
- MCP tool signatures are synchronized
- FI/FT handling rules are followed
- Language policy is consistent

**When to update**:
- Adding/modifying MCP tools
- Changing lane parameters
- Updating fusion logic
- Modifying code handling (FI/FT/CPC/IPC)

### 2. RRFusionSpecification.md
**Location**: [src/rrfusion/RRFusionSpecification.md](../../src/rrfusion/RRFusionSpecification.md)

**What to check**:
- Mathematical formulas match fusion.py
- Lane design principles are followed
- Code system policies are enforced
- A/B/C and B/P/T decomposition is correct

**When to update**:
- Changing RRF algorithm
- Modifying frontier estimation
- Adding new lane types
- Updating code-aware boost logic

### 3. AGENT.md
**Location**: [AGENT.md](../../AGENT.md)

**What to check**:
- API signatures match mcp/host.py
- Redis data model matches storage.py
- Algorithm descriptions match fusion.py
- Test acceptance criteria are met

**When to update**:
- Changing MCP API
- Modifying Redis schema
- Updating fusion algorithm
- Adding new services

## Consistency Checklist

Before committing changes, verify:

- [ ] Code changes reflected in AGENT.md
- [ ] SystemPrompt.yaml updated if MCP tools changed
- [ ] RRFusionSpecification.md updated if algorithm changed
- [ ] Test cases added/updated
- [ ] FI normalization infrastructure works correctly (if storage/fusion modified)
- [ ] System supports both fi_norm and fi_full appropriately
- [ ] All code systems (FI/FT/CPC/IPC) are handled independently
- [ ] Implementation supports LLM agent behaviors defined in SystemPrompt.yaml

## Quick Verification Commands

```bash
# Check if FI normalization is used
rg "fi_norm" src/rrfusion/

# Check FI normalization infrastructure
rg "fi_norm|fi_full" src/rrfusion/storage.py src/rrfusion/fusion.py

# Verify SystemPrompt structure
python -c "import yaml; yaml.safe_load(open('src/rrfusion/SystemPrompt.yaml'))"

# Check MCP tool consistency
rg "@mcp\.tool" src/rrfusion/mcp/host.py
```

## Example Workflow

When implementing FI normalization feature:
1. Review SystemPrompt.yaml code_usage_policy section
2. Implement `normalize_fi_subgroup()` in utils.py
3. Update storage.py to store fi_full + fi_norm
4. Update fusion.py for two-level boost
5. Update RRFusionSpecification.md if algorithm changes
6. Add tests in tests/unit/test_fi_normalization.py
7. Run `cargo make ci`
