# """Handbook + recipe prompts extracted from host.py for reuse or future customization.
# Two human-readable constants for import:
# - HANDBOOK
# - TOOL_RECIPES
# """

HANDBOOK = r"""
# RRFusion MCP Handbook (v1.3, multi-lane + code-aware)

**Goal**  
Maximize *effective* Fβ (default β = 1, configurable) for prior-art style
search under no-gold-label conditions, by combining:

- LLM-driven query normalization & feature extraction
- Multi-lane retrieval (fulltext BM25-style, TT-IDF variants, dense semantic)
- Code-aware fusion using FI / FT / CPC / IPC frequency profiles
- Rank-based fusion (RRF) + Fβ-oriented frontier tuning

Transport: HTTP / `streamable-http` at `/{base_path}` (default `/mcp`).  
Auth: Bearer token if configured.

> Notes
> - Lane raw scores are **incomparable** → always use **rank-based fusion (RRF)**.
> - `beta_fuse` in fusion controls recall/precision bias **inside the fusion
>   step**, not the external evaluation metric Fβ.
> - The MCP interface exposes only *flat* filters (`and|or|not`). Precision /
>   recall behaviour is controlled via **query structure** (OR/phrase/NEAR,
>   field boosts, etc.), not via explicit `must/should` parameters.

---

## 1. Classification codes (FI / FT / CPC / IPC)

### 1.1 Allowed combinations

To keep the technical field definition clean, **do not mix code systems**.
Use exactly one of the following patterns per query / run:

1. **JP (domestic)**
   - Use **FI as the primary classification**.
   - Optionally combine with **FT** when a functional/technical
     (function-oriented) cut is needed.
   - Use: **FI主体 + FT併用**（FI main, FT auxiliary）.

2. **US / WO**
   - Use **CPC only**, *or*
   - Use **IPC only**.
   - Do **not** mix CPC and IPC in the same run.

3. **Prohibited combinations**
   - FI/FT × CPC/IPC の混在は禁止:
     - FI + CPC, FI + IPC, FT + CPC, FT + IPC などは使用しない。

### 1.2 How codes are used

- Codes are primarily used to:
  - define the **technical field** of the query; and
  - support **code-aware fusion** via `target_profile` in
    `blend_frontier_codeaware`.
- Code-based filters (`filters`) must remain **flat**:
  - `lop: "and|or|not"`, `field: "fi|ft|cpc|ipc"`, `value: "..."`.
- You may:
  - define a *broad* code scope for wide/fulltext/semantic lanes; and
  - define a *tighter* scope for TT-IDF style narrow lanes.
- Code constraints are **available** to all lanes (fulltext, TT-IDF,
  semantic), but are **not mandatory** on every query. The agent may
  choose per lane whether code-constraining helps or hurts recall.

---

## 2. Lane architecture (v1.3)

### 2.1 Core lanes (fixed)

v1.3 assumes a **semi-fixed multi-lane** design. The following lanes
are considered **core** and should exist for almost all queries:

1. `fulltext_wide`
   - Fulltext BM25-style retrieval.
   - Wide OR over feature terms + synonym expansions.
   - Minimal structural constraints.
   - May or may not use code constraints, depending on the task.

2. `semantic`
   - Dense semantic retrieval via `search_semantic`.
   - Short, focused text (< 1024 chars for semantic, <256 chars for original_dense) summarizing the query intent.
   - May optionally be code-constrained when semantic drift risk is high.

3. `ttidf_recall`
   - Fulltext TT-IDF style lane tuned for **high recall** within the right
     technical field.
   - Uses feature terms + synonyms with relatively generous OR structure.
   - Typically **code-constrained** using FI/FT/CPC/IPC.

4. `ttidf_precision`
   - Fulltext TT-IDF lane tuned for **higher precision**:
     - multi-word terms kept as units where possible,
     - more phrase / NEAR usage,
     - stronger claim-field emphasis.
   - Typically uses the same code scope as `ttidf_recall`.

These four lanes form the **standard backbone** for Fβ-oriented fusion.

> `original_dense`  
> A legacy/original-dense lane may exist in the implementation, but is
> **disabled in v1.3**. Keep the code for forward-compatibility, but do
> not use it in recipes or in `blend_frontier_codeaware` inputs.

### 2.2 Optional specialized lanes

In addition to the core lanes, the agent **may propose** extra specialized
lanes when justified by the query. These still reuse the existing MCP tools
(`search_fulltext`, `search_semantic`) and do not require API changes. Examples:

- `claim_only_fulltext`
  - Fulltext search restricted to claim fields.
  - Useful when structural/claim language is crucial.

- `title_abstract_boosted`
  - Fulltext lane with strong boosts on title/abstract.
  - Good for quick “landscape / overview” style tasks.

- `near_phrase_heavy`
  - Fulltext lane heavy on phrase/NEAR operator usage.
  - Useful when exact local configurations matter.

Guidelines:

- Keep the number of lanes **small and meaningful** (typically 4–6).
- Adding many similar lanes tends to **hurt** fusion quality and complexity.
- Fusion is rank-based; lanes should carry **diverse signals**, not nearly
  identical ones.

---

## 3. High-level pipeline (agent-facing, v1.3)

This section describes the intended *logical* pipeline. It does not change
the MCP function signatures.

### Step 1: Normalize, extract features, expand synonyms

Given a natural-language search intent (problem/solution, key claim, etc.),
the agent should:

1. Normalize text (remove boilerplate, clarify what is in/out of scope).
2. Extract **technical feature terms**:
   - Identify claim-level functional blocks (feature A/B/C...).
   - Keep important multi-word terms as units (e.g. “light-emitting element”).
3. Build synonym/paraphrase clusters per feature:
   - apparatus/device/mechanism, supply/feed/provide, etc.
4. Construct a **query profile** (agent-side object) that includes:
   - `feature_terms`
   - `synonym_clusters`
   - `negative_hints`
   - optional hints for fields (claims vs desc).

This query profile is reused across all lanes.

### Step 2: Wide multi-lane recall (initial pool)

Goal: obtain a **wide but meaningful** candidate pool.

- Run `fulltext_wide` lane:
  - `search_fulltext` with a wide BM25-style recipe.
  - Use generous OR over feature terms and synonyms.
  - Use only minimal flat `filters` (years, language, doc_type, etc.).
- Run `semantic` lane in parallel:
  - `search_semantic` with a concise intent summary.
  - Optionally apply the same flat filters if drift is a concern.
- (Optional) run additional wide variants if needed.

The result is one or more `run_id` values representing the **wide pool**.

### Step 3: Learn a code frequency profile (FI / FT / CPC / IPC)

Goal: determine the **dominant technical field(s)**.

For each wide `run_id`:

1. Call `get_provenance` to obtain:
   - code frequency snapshots for `fi`, `ft`, `cpc`, `ipc` (if available),
   - family information and other diagnostics.
2. From these, build a **code frequency profile**:
   - Top codes (high frequency, high specificity).
   - Down-weight noisy / off-topic codes.
   - Optionally normalize with global frequencies (IDF-like).
3. Derive a `target_profile` candidate:
   - `{ code: weight }` per taxonomy (FI/FT or CPC or IPC, not mixed).
4. Optionally derive **code-based filters** for subsequent runs:
   - Flat filters such as `field="fi"` and `value="F-term code..."`.
   - Apply them to TT-IDF lanes and, if helpful, to fulltext/semantic lanes.

### Step 4: Code-aware TT-IDF lanes (recall + precision)

Goal: run TT-IDF style lanes **within the right technical field**.

Using the query profile (Step 1) and code profile (Step 3):

- `ttidf_recall`:
  - Fulltext TT-IDF lane for **high recall**.
  - Wide OR over feature terms/synonyms.
  - Typically code-constrained using FI/FT (JP) or CPC/IPC (US/WO).
- `ttidf_precision`:
  - Fulltext TT-IDF lane for **higher precision**:
    - more phrase/NEAR usage,
    - claim-biased field behaviour,
    - stricter combinations of terms.

Additional specialized lanes (e.g. claim-only) may be added when needed,
but the default is at least the two TT-IDF lanes above.

### Step 5: Code-aware fusion (RRF + Fβ-oriented tuning)

Goal: fuse all relevant lanes into a single ranking aligned with Fβ.

Use `blend_frontier_codeaware` with:

- `runs`: a list of `{ lane, run_id }` from:
  - `fulltext_wide`,
  - `semantic`,
  - `ttidf_recall`,
  - `ttidf_precision`,
  - and any optional lanes used for the query.
- `weights`: lane-level weights (to be tuned via `mutate_run`).
- `rrf_k`: RRF parameter (tail behaviour).
- `beta_fuse`: fusion-level bias toward recall vs precision.
- `target_profile`: code frequency–derived `{ code: weight }` map.
- `family_fold`: how to fold patent families in the result.

The result is a fused `run_id` acting as the **main candidate list**.

### Step 6: Snippet budgeting & review

- Use `peek_snippets` on the fused `run_id` to:
  - preview top items with a small `budget_bytes`,
  - choose a strategy (`head|match|mix`),
  - adjust per-field budgets and claim counts.
- Use `get_snippets` for deeper analysis on selected `doc_ids` with
  a larger budget and feed those snippets to downstream LLM agents.

### Step 7: Frontier tuning & provenance

- Use `mutate_run` to explore variations around a good fused run:
  - adjust lane `weights`, `rrf_k`, `beta_fuse`,
  - add/remove lanes,
  - observe impact on recall/precision proxies.
- Use `get_provenance` to capture:
  - code distributions,
  - lane contributions,
  - configuration snapshots.
- Promote successful settings to **named recipes** for future reuse.

"""

RECIPES= r"""
# RRFusion MCP recipes (v1.3)

This section gives high-level guidance on how to instantiate the pipeline
described in the v1.3 handbook using the existing MCP tools, without
changing their signatures.

## Core tools

- `search_fulltext`  
  Fulltext / TT-IDF / BM25-style lanes. Different lanes are implemented
  via different *recipes* (query structure, field boosts, filters).

- `search_semantic`  
  Dense semantic lane (`semantic`).

- `blend_frontier_codeaware`  
  Rank-based fusion with code-aware priors and Fβ-oriented tuning.

- `peek_snippets`, `get_snippets`  
  Snippet budgeting for human/LLM review.

- `mutate_run`  
  Explore variations in lane weights, `rrf_k`, `beta_fuse`, etc.

- `get_provenance`  
  Inspect runs, including FI/FT/CPC/IPC frequency snapshots.

## Example lane recipes (conceptual)

These are *conceptual*; adapt to your own query-builder implementation.

### Lane: fulltext_wide

- Base: `search_fulltext`
- Fields: title, abstract, claims, description.
- Query:
  - OR over feature terms and synonyms,
  - may include simple phrase operators but no heavy NEAR.
- Filters:
  - years, doc_type, language,
  - optional broad code scope (`fi` or `cpc`/`ipc` depending on region).
- Use: Step 2 (wide pool) and as one input to fusion.

### Lane: semantic

- Base: `search_semantic`
- Input text: 1–3 sentences summarising the core technical idea.
- Filters:
  - same coarse constraints as `fulltext_wide` if needed.
- Use: Step 2 (wide pool) and as one input to fusion.

### Lane: ttidf_recall

- Base: `search_fulltext`
- Query:
  - TT-IDF style scoring,
  - wide OR over feature terms/synonyms,
  - multi-word terms recognized but not overly constrained.
- Filters:
  - **code-constrained** by FI (JP) or CPC/IPC (US/WO).
- Use: Step 4, recall-oriented lane.

### Lane: ttidf_precision

- Base: `search_fulltext`
- Query:
  - TT-IDF style scoring,
  - more phrase/NEAR usage,
  - stronger claim-field emphasis.
- Filters:
  - same code scope as `ttidf_recall`.
- Use: Step 4, precision-oriented lane.

### Optional lanes (examples)

- `claim_only_fulltext`: same as `ttidf_precision` but claims-only fields.
- `title_abstract_boosted`: strong boosts on title/abstract for overview.
- `near_phrase_heavy`: more aggressive use of phrase/NEAR operators.

## Fusion recipe (blend_frontier_codeaware)

- Inputs:
  - `runs`: list of `{ lane, run_id }` including all lanes used.
  - `weights`: initial lane weights (e.g. `fulltext_wide=1.0`,
    `semantic=1.0`, `ttidf_recall=1.0`, `ttidf_precision=1.2`).
  - `rrf_k`: e.g. 60–120 depending on desired tail contribution.
  - `beta_fuse`: >1 for recall bias, <1 for precision bias.
  - `target_profile`: FI/FT/CPC/IPC prior derived from wide pool.
  - `family_fold`: configuration for family folding.
- Tuning:
  - Use `mutate_run` to explore variations and lock in good defaults.
"""
