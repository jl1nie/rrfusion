# Lane Design Skill

## Purpose
Guide the design and implementation of search lanes in RRFusion.

## Lane Types

### 1. fulltext_wide
**Purpose**: Broad recall, avoid missing candidates

**Parameters**:
```python
field_boosts = {
    "title": 80,
    "abstract": 10,
    "claim": 5,
    "description": 1
}
```

**Query style**: Natural language + broad keywords, 200-1000 chars

**Code policy**: No FI/FT filters (or very loose)

### 2. semantic
**Purpose**: Conceptual similarity, surface related prior art

**Parameters**:
```python
semantic_style = "default"  # original_dense is disabled
feature_scope = "wide"      # or title_abst_claims, claims_only, background_jp
```

**Query style**: 1-3 paragraphs describing core technical idea

**Code policy**: No codes or SHOULD-only

### 3. fulltext_recall
**Purpose**: In-field coverage with target_profile

**Parameters**:
```python
field_boosts = {
    "title": 40,
    "abstract": 10,
    "claim": 5,
    "description": 4
}
```

**Query style**: Feature terms + synonyms, 100-300 chars

**Code policy**: FI/FT OR-groups from target_profile

### 4. fulltext_precision
**Purpose**: High-precision candidates

**Parameters**:
```python
field_boosts = {
    "title": 80,
    "abstract": 20,
    "claim": 40,
    "description": 40
}
```

**Query style**: A (MUST) + B (MUST) + C (SHOULD), 50-150 chars

**Code policy**: Same as recall, tighter focus

### 5. fulltext_problem (conditional)
**Purpose**: Problem F-Term focused search

**Parameters**:
```python
field_boosts = {
    "title": 40,
    "abstract": 10,
    "claim": 5,
    "description": 4
}
```

**Query style**: Background + Problem FT + Techfeature

**Code policy**: FT only (Problem perspective)

**Activation**: Only when Problem FT codes are clearly identified

## Code System Support

### Implementation Requirements

The system must support multiple classification systems **independently**:

- **FI (File Index)**: Japan-specific detailed classification
  - Must provide both `fi_norm` (subgroup) and `fi_full` (with edition symbols)
  - Used primarily for JP-focused searches

- **FT (F-Term)**: Problem/structure tags
  - Thematic classification system
  - Often used alongside FI in JP searches

- **CPC**: EPO/USPTO cooperative classification
  - Used for US/EP focused searches

- **IPC**: International patent classification
  - Universal baseline classification

### SystemPrompt.yaml Defines Usage Rules

[SystemPrompt.yaml](../../src/rrfusion/SystemPrompt.yaml) defines **how the LLM agent uses** these systems:

- **JP-focused lanes**: Typically use FI/FT
- **Non-JP lanes**: Typically use CPC or IPC
- **Code mixing**: LLM agent avoids mixing systems in single lane

**As a developer**: Your implementation must support all combinations flexibly. The LLM agent decides the strategy; your code executes it correctly.

### Storage Requirements

```python
# Example document structure
{
    "doc_id": "JP2023123456",
    "ipc": ["H04L29/06"],
    "cpc": ["H04L63/0428"],
    "fi_norm": ["H04L9/32"],      # Subgroup level
    "fi_full": ["H04L9/32A"],     # With edition symbol
    "ft": ["5B089AA01", "5B089BB12"]
}

## Query Construction

### Logical Operators
```python
# AND (default)
"solar AND panel"

# OR
"(solar OR ソーラー) AND パネル"

# NOT (use sparingly)
"solar NOT battery"
```

### Phrase Search
```python
"solar panel"  # exact phrase
```

### NEAR Search
```python
"*N5\"太陽 電池\""        # unordered, within 5 chars
"*ONP5\"太陽 電池\""      # ordered, within 5 chars
"*N10\"(太陽 ソーラー) (電池 パネル)\""  # with alternatives
```

### Anti-patterns ❌

```python
# DON'T: Overconstrain with many ANDs
"A AND B AND C AND D AND E AND F AND G"

# DON'T: Complex NEAR nesting
"*N5\"(upper body AND face AND NOT mask)\""

# DON'T: Aggressive NOT blocks
"(A AND B) AND NOT (C OR D OR E OR F OR G)"

# DON'T: Single ultra-narrow FI
filters = [{"field": "fi", "op": "in", "value": ["G06V10/82A"]}]

# DON'T: Mix code systems
filters = [
    {"field": "fi", "op": "in", "value": ["G06V10/82"]},
    {"field": "cpc", "op": "in", "value": ["G06V10/82"]}
]
```

## A/B/C Decomposition

### A: Core technical mechanism
- Face recognition algorithm
- Cooling structure
- Sensor configuration
- Control logic

**Treatment**: MUST in fulltext_precision

### B: Constraints / secondary conditions
- Latency requirements
- Cost constraints
- Safety requirements
- Privacy considerations

**Treatment**: MUST in fulltext_precision, SHOULD in recall

### C: Use cases / deployment contexts
- Gate systems
- Access control
- Vehicle-mounted
- Medical devices

**Treatment**: SHOULD (NOT MUST) in all lanes

## Adding a New Lane

### 1. Define logical lane
```python
# In SystemPrompt.yaml
- name: fulltext_custom
  tool: search_fulltext
  purpose: custom_recall
  parameters:
    field_boosts:
      title: 60
      abstract: 15
      claim: 10
      description: 5
```

### 2. Implement query generation
```python
# LLM generates query following lane's query_style
query = build_custom_query(feature_terms, synonym_clusters)
```

### 3. Configure fusion
```python
# In BlendRequest
runs = [
    {"lane": "fulltext", "run_id_lane": "custom-run-id"},
    # ... other lanes
]
weights = {"fulltext": 1.0, "custom": 0.8}
```

### 4. Test
```bash
# Add test case
# tests/integration/test_custom_lane.py

cargo make integration
```

### 5. Update docs
- SystemPrompt.yaml: Add lane definition
- RRFusionSpecification.md: Add lane description
- AGENT.md: Update if MCP changes needed

## References
- [SystemPrompt.yaml lanes section](../../src/rrfusion/SystemPrompt.yaml#L273-L397)
- [RRFusionSpecification.md Chapter 3](../../src/rrfusion/RRFusionSpecification.md#311)
- [mcp/host.py tool implementations](../../src/rrfusion/mcp/host.py)
