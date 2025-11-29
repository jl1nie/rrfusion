# fi-improvement.md
## FI Edition Symbol Handling Improvement Plan (RRFusion)

This document summarizes the implementation and prompt-side modifications required to correctly handle **FI edition symbols (分冊識別記号)** in RRFusion.

Edition symbols **are technical subdivisions** and should therefore be *retained*, but **never used as MUST filters** in search queries because their assignment across years/document-types is unstable.  
The correct strategy is: **keep them, but use them only as secondary ranking signals; treat subgroup-level FI as the primary classifier.**

---

# 1. Goals

- Retain FI edition symbols as technical metadata.
- Remove edition symbols from query-side MUST filters to prevent recall loss.
- Compute CCW and structural metrics on *subgroup-level FI only*.
- Introduce two-level handling for fusion code-aware boosts:
  - Primary = subgroups
  - Secondary = edition symbols (weak)

---

# 2. Implementation Tasks (Codex)

## 2.1 Add FI Normalization Function

```
def normalize_fi_subgroup(fi: str) -> str:
    """
    Normalize FI for CCW/clustering:
    - Input : 'G06V10/82A', 'G06V10/82B'
    - Output: 'G06V10/82'
    """
    # TODO: strip trailing A-Z
```

---

## 2.2 Redis / DB Storage Changes

Store both FI forms per document:

```
{
  "fi_full": "G06V10/82A",
  "fi_norm": "G06V10/82"
}
```

- Compute `fi_norm` at ingestion.
- Migrate older records accordingly.

---

## 2.3 CCW Computation — use fi_norm ONLY

Modify CCW logic:

- Replace FI lookups with `fi_norm`.
- Prevent cluster fragmentation caused by edition symbols.

---

## 2.4 Fusion Code-Aware Boost (Two-Level Boost)

### Primary (subgroup-level):

```
if fi_norm in target_profile.primary_codes:
    score *= (1 + gamma_primary)
```

### Secondary (edition-level):

```
if fi_full in target_profile.secondary_codes:
    score *= (1 + gamma_secondary)
```

Target profile structure:

```
class TargetProfile:
    primary_codes: list[str]      # fi_norm
    secondary_codes: list[str]    # fi_full
```

---

## 2.5 Query Generation / MCP Side

All FI filters in queries must use **fi_norm only**.

- NEVER allow queries like `FI="G06V10/82A"` as MUST.
- MCP should expose only subgroup-level FI to the LLM.

---

# 3. SystemPrompt Modifications

## 3.1 Add FI Handling Rules

```
### Handling FI and edition symbols

- Use FI subgroup (e.g., "G06V10/82") as PRIMARY code in all queries.
- Edition symbols ("A", "B", "C", ...) are technical subdivisions but MUST NOT be used
  as MUST filters.
- Backend fusion engine handles edition symbols as weak ranking hints.
```

---

## 3.2 Add Precision Lane Prohibition

```
Do NOT use FI edition symbols in fulltext_precision as mandatory filters.
Only the subgroup-level FI may appear in the filter sections.
```

---

## 3.3 Profiling Instructions

```
- PRIMARY: subgroup FI (fi_norm)
- SECONDARY: full FI (fi_full)
- PRIMARY codes shape lane design.
- SECONDARY codes are used only by backend boosts.
```

---

# 4. Recommended Strategy Summary

| Layer | Action |
|------|--------|
| Storage | Keep fi_full + fi_norm |
| Query | Use fi_norm only |
| Fusion | primary=subgroup, secondary=edition |
| CCW | Use fi_norm only |
| Profiling | primary=subgroup, secondary=edition |
| Prompt | Ban edition-symbol MUST conditions |

---

# 5. Final Summary

- Edition symbols **must be kept** because they represent technical subdivisions.
- They **must not be used as hard filters** because assignment is unstable.
- Best practice is layered handling:
  - Use subgroup for filtering/metrics.
  - Use edition symbols as weak ranking hints in fusion.
fi-improvement.md
fi-improvement.md を表示しています。