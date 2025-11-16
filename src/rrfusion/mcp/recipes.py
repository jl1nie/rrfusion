# """Handbook + recipe prompts extracted from host.py for reuse or future customization.
# Two human-readable constants for import:
# - HANDBOOK
# - TOOL_RECIPES
# """

HANDBOOK = r"""# RRFusion MCP Handbook v1.3 (English)

## 0. Overview

RRFusion MCP is designed as a **multi-lane, code-aware search optimization
engine that maximizes Fβ (with configurable β) under no-gold-label conditions**.

The main goals for v1.3 are:

- LLM-based feature extraction and synonym clustering  
- Multi-lane lexical retrieval (TT-IDF style) + dense semantic retrieval  
- Technical-field constraints using FI/FT (for JP) or CPC/IPC (for US/WO),
  plus code frequency profiling  
- Rank-based fusion (RRF) combined with Fβ-oriented optimization
  (via `beta_fuse`)  
- **No changes to MCP tool interfaces compared to v1.2**  
- Clear operational policies and lane definitions under v1.3:
  - `ttidf_wide` / `semantic` / `ttidf_recall` / `ttidf_precision`  
  - `original_dense` is **disabled** in v1.3

【Language & Terminology Alignment Rules】

1. Language Alignment (必須)
   For every search lane (fulltext or semantic), the query MUST be constructed
   in the same primary language as the target corpus being searched.
   Do NOT mix multiple languages inside a single query.

   - If the lane filters restrict the corpus to a specific publication region 
     (e.g., JP-only, US-only, EP-only), the query MUST align with the dominant 
     language of that region.
   - JP corpus → Japanese queries.  
     US/EP corpus → English queries.

   Rationale:
   Cross-lingual search causes significant semantic drift, degrades BM25/TT-IDF 
   matching, and destabilizes multi-lane fusion. Language alignment is mandatory.

2. Tokenization-Aware Query Construction
   All generated queries MUST respect the tokenization characteristics of the 
   target corpus. Avoid formulations that are unnatural for the target language 
   or that break expected lexical boundaries.

   - For Japanese corpora (e.g., JP patents), prefer natural Japanese phrases 
     that match morphological segmentation.
   - For English corpora, avoid overlong compound phrases that harm BM25 scoring.

   Rationale:
   Tokenization mismatch lowers lexical match probability and consequently reduces 
   precision/recall across all lanes.

3. Use Canonical Domain Terminology
   The query MUST prefer the canonical terminology that is actually used in the 
   target corpus. Avoid translation-induced terminology drift and avoid obscure 
   synonyms unless the corpus genuinely uses them.

   - Prioritize wording appearing in authoritative sources (e.g., claims/abstract 
     of JP/US/EP patents in the same technical field).
   - Avoid transliterations or non-standard wording that is not used in the 
     target corpus.

   Rationale:
   Using canonical terminology directly improves BM25/TT-IDF hit quality and 
   reduces semantic drift in dense embedding lanes.

【Summary】
To preserve precision/recall balance and maintain stability of multi-lane fusion, 
every lane MUST strictly align:
(1) language, (2) tokenization, and (3) domain terminology 
with the target corpus being searched.

---

## 1. Classification Code Policy

In v1.3, mixing classification code systems in a single lane is prohibited.  
This is essential to keep the **technical-field model (`target_profile`)**
stable and interpretable.

### 1.1 JP publications (domestic)

- Use **FI (File Index) as the primary classification system**.  
- Optionally use **FT (F-Term)** when a function-oriented / technical
  perspective is needed for narrowing.  
- Recommended pattern: **“FI as main + FT as auxiliary”**.  
- When using FI/FT for a lane, **do not mix IPC or CPC into the same lane**.

### 1.2 US / WO / EP publications

- Use **CPC only**, or  
- Use **IPC only**.  
- Even if both are present on a document, each lane must pick **one
  taxonomy** and stick to it.  
- **CPC + IPC mixed in the same lane is prohibited**.

### 1.3 Prohibited combinations (important)

The following combinations are **not allowed** in v1.3 for a single lane:

- JP codes vs. international codes:
  - FI + CPC  
  - FI + IPC  
  - FT + CPC  
  - FT + IPC  
- Mixed international taxonomies in one lane:
  - CPC + IPC  

Reasons:

- Each taxonomy has different granularity and design; mixing them breaks
  the assumptions behind the `target_profile` weighting and code frequency
  models.  
- It blurs the boundaries of the technical field and amplifies semantic drift.

**Rule:** For each lane, use exactly one of the following:

- FI/FT (JP)  
- CPC (US/WO/EP etc.)  
- IPC (US/WO/EP etc.)

---

## 2. Lane Architecture (v1.3)

v1.3 adopts a **semi-fixed multi-lane architecture**:

- A set of **four core lanes** is always present.  
- The LLM may propose **additional specialized lanes** when justified.

### 2.1 Core lanes

These four lanes are considered the **core backbone** of the system.

#### (1) `ttidf_wide` — lexical wide lane

- MCP tool: `search_fulltext`  
- Input: **`query` (search expression)**  
- Characteristics:
  - Wide OR expansion over feature terms and their synonym clusters  
  - Mild use of phrase / proximity (NEAR), not overly constraining  
  - Uses title / abstract / claims / description fields with modest field
    bias  
  - Code constraints (`fi` / `ft` / `cpc` / `ipc`) are **optional**  
- Role:
  - Provides **broad but meaningful recall** for the initial candidate pool  
  - When combined with the `semantic` lane, forms a robust “wide pool”
- Implementation note:
  - Whether the internal scorer is BM25 or TT-IDF is an implementation
    detail.  
  - As a lane, `ttidf_wide` is defined as a **wide lexical / TT-IDF-style
    query structure**, not by the internal scoring function.

---

#### (2) `semantic` — dense semantic lane

- MCP tool: `search_semantic`  
- Input: **`text` (natural language)**  
- Characteristics:
  - 1–3 sentences describing the core search intent.  
  - Text length should be **< 1024 characters** (ideally 300–500 chars).  
  - Shorter, focused text helps avoid embedding dilution and preserves
    semantic sharpness.  
  - Code constraints via FI/FT/CPC/IPC are **optional** and should only be
    applied when semantic drift is a concern.  
- Role:
  - Complements lexical lanes by recovering documents with **vocabulary
    gaps and paraphrased expressions**.  
  - When fused with `ttidf_wide`, it significantly boosts recall.

> `original_dense`  
> In v1.3, the `original_dense` lane is considered **disabled**.
> It remains registered (e.g., for the internal WWRag backend), but the
> production pipeline currently avoids it. When it is re-enabled, treat it
> as a **variant of the semantic lane** rather than introducing a new tool:
> the LLM should keep sending dense prompts through `search_semantic` but
> set an optional style flag (e.g., `semantic_style="original_dense"`)
> so the downstream service knows to route the request to the shorter-text
> dense path. Expect even shorter text inputs (<256 chars) than the
> `semantic` lane.

---

#### (3) `ttidf_recall` — code-constrained high-recall lane

- MCP tool: `search_fulltext`  
- Input: **`query` (search expression)**  
- Characteristics:
  - Wide OR structure using feature terms and synonym clusters.  
  - Multi-word technical terms are preserved as units where possible.  
  - **Technical field is constrained using classification codes**, based on
    the profile learned in the wide pool:
    - JP: FI as main + optional FT  
    - US/WO: either CPC or IPC  
  - Uses claims / title / abstract as main fields, optionally including
    description if needed.  
- Role:
  - Achieves **high recall within the correct technical field** after the
    field is approximated in the wide pool.

---

#### (4) `ttidf_precision` — code-constrained high-precision lane

- MCP tool: `search_fulltext`  
- Input: **`query` (search expression)**  
- Characteristics:
  - Aggressive use of phrase and NEAR operators to capture local
    configurations.  
  - Stronger field bias toward claims.  
  - Uses the **same code scope** as `ttidf_recall` (FI/FT or CPC/IPC).  
  - Synonym clusters are structured such that “strong terms” and “weaker
    variants” are distinguished in the query design (even though MCP sees
    only a flattened query).  
- Role:
  - Works together with `ttidf_recall` to **raise precision** within the
    target field, especially in the top-ranked subset.

---

### 2.2 Optional specialized lanes

In addition to the core lanes, v1.3 allows the LLM to propose **extra
specialized lanes** when a query clearly benefits from them.

Examples:

- `claim_only_fulltext`  
  - A fulltext lane restricted to claims fields only.  
- `title_abstract_boosted`  
  - A lane with strong boosts on title and abstract, suitable for
    overview / landscape-style queries.  
- `near_phrase_heavy`  
  - A lane that aggressively uses phrase/NEAR to capture local patterns.

Guidelines:

- Keep the **total number of lanes small**, typically around 4–6.  
- Adding too many similar lanes reduces the independence of signals and
  can degrade RRF fusion quality.  
- The **four core lanes** (`ttidf_wide`, `semantic`, `ttidf_recall`,
  `ttidf_precision`) should form the backbone.  
- Specialized lanes should be added only when they contribute genuinely new
  information.

---

### 2.3 `original_dense` in v1.3

- The `original_dense` lane is **disabled** in v1.3.  
- It may remain implemented for future use, but:
  - Should not appear in lane recipes;  
  - Should not be passed into `blend_frontier_codeaware`.  
  - If re-enabled in a later version, treat it as a semantic-style
    variant:
    - Call it through `search_semantic` with a dedicated style flag
      (e.g., `semantic_style="original_dense"`).  
    - Expect shorter text inputs than the default `semantic` lane
      (< 256 chars).  
    - The LLM prompt should mention that the lane is dense-only and
      routes to the backend's WWRag-style endpoint.

---

## 3. Pipeline (v1.3)

This section describes the **recommended pipeline** for an LLM-based
agent using RRFusion MCP.  
MCP function signatures remain unchanged from v1.2.

### Step 1. Feature extraction & query profile (inside the LLM)

1. **Normalize the search intent**  
   - Extract the technical problem, solution, and application context from
     the user’s description.  
   - Remove boilerplate or irrelevant parts of the text.

2. **Extract technical feature terms**  
   - Identify major structural elements (A/B/C/...) from claims, especially
     independent claims.  
   - Preserve important multi-word technical terms as units (e.g.,
     “light-emitting element”).

3. **Build synonym / paraphrase clusters**  
   - For each feature term, group synonyms and paraphrased variants:
     - apparatus / device / mechanism  
     - supply / feed / provide  
     - enable / allow / permit  
   - Pay special attention to domain-specific vocabulary (e.g., semiconductor
     processes, communication protocols, etc.).

4. **Construct a query profile (LLM-internal structure)**  
   - `feature_terms`  
   - `synonym_clusters`  
   - `negative_hints` (what is clearly out of scope)  
   - `field_hints` (e.g., claims-heavy vs abstract-heavy)

This query profile is reused across `ttidf_wide`, `semantic`,
`ttidf_recall`, and `ttidf_precision` lanes.

---

### Step 2. Wide multi-lane recall (initial pool)

**Goal:** Build a **wide but meaningful initial candidate pool**.

#### 2.1 Run `ttidf_wide`

- MCP: `search_fulltext`  
- Query structure:
  - Wide OR expansion over feature terms and their synonym clusters.  
  - Mild usage of phrase / NEAR; the goal is not to over-constrain.  
  - Targets multiple fields: claims / title / abstract / description,
    with light field bias.  
- Filters:
  - Basic constraints such as publication year, language, doc_type
    (publication/grant).  
  - Code constraints are **not mandatory** at this stage; in fact, a
    slightly broader scope is useful for learning the code profile later.  
- `top_k`:
  - Typically 800–1500 (depending on system capacity and latency).

#### 2.2 Run `semantic`

- MCP: `search_semantic`  
- Input `text`:
  - 1–3 sentences summarizing the core technical idea.  
  - Text length **< 1024 characters** (ideally 300–500).  
- Filters:
  - Same basic constraints as `ttidf_wide` (year, doc_type, etc.).  
  - Apply code constraints only if semantic drift becomes a noticeable
    issue.  
- `top_k`:
  - Typically 400–800.

The combination of results from `ttidf_wide` and `semantic` forms the
**initial pool** (wide set of `run_id`s).

---

### Step 3. Code frequency profile (technical field estimation)

**Goal:** Derive an FI/FT/CPC/IPC frequency profile from the initial pool
to identify the relevant technical field.

1. For each `run_id` in the wide pool, call `get_provenance`.  
2. From the returned data, collect:
   - Frequency distributions for `fi`, `ft`, `cpc`, `ipc`;  
   - Family information;  
   - Contributions from each lane (if applicable).  
3. Choose the appropriate taxonomy:
   - JP: FI/FT  
   - US/WO: CPC or IPC (but not both)  
4. Within the chosen taxonomy, identify:
   - Highly frequent and highly specific codes;  
   - Codes that appear noisy or off-topic, which should be down-weighted
     or ignored.  
5. If global code frequencies (over the whole corpus) are known, apply
   an IDF-like normalization to emphasize more specific codes over
   generic ones.  
6. Construct **`target_profile`**:
   - A map `{ code: weight }` for the chosen taxonomy only  
   - Example: `{"FI:XXXX": 1.0, "FI:YYYY": 0.7, ...}`

Optionally, derive **code constraints (filters)** for TT-IDF lanes
(`ttidf_recall`, `ttidf_precision`) from `target_profile`.

---

### Step 4. Code-constrained TT-IDF lanes (in-field retrieval)

**Goal:** Within the identified technical field, obtain a good balance of
recall and precision.

#### 4.1 `ttidf_recall`

- MCP: `search_fulltext`  
- Query:
  - Wide OR-based structure over feature terms and synonyms.  
  - Multi-word technical terms kept together wherever possible.  
  - Not overly constrained by proximity; recall is prioritized.  
- Code constraints:
  - Use `target_profile` from Step 3 to define filters:
    - JP: FI as main, FT as optional narrow cuts  
    - US/WO: CPC or IPC  
- Fields:
  - Mainly claims / title / abstract, with description added when needed.  
- Role:
  - High-recall lexical lane **inside the correct technical field**.

#### 4.2 `ttidf_precision`

- MCP: `search_fulltext`  
- Query:
  - More aggressive use of phrase / NEAR.  
  - Strong field bias toward claims.  
  - Synonym clusters are used in a more conservative manner to avoid
    over-expansion.  
- Code constraints:
  - Uses the same code scope as `ttidf_recall`.  
- Role:
  - High-precision lexical lane that refines the set gathered by
    `ttidf_recall`.

Specialized lanes (e.g., claim-only, title/abstract-boosted) can be added
if there is a strong reason, but they should not explode in number.

---

### Step 5. Code-aware rank fusion (RRF + Fβ-oriented tuning)

**Goal:** Fuse the multi-lane results into a single ranking that aligns
with Fβ preferences, leveraging classification codes as priors.

- MCP: `blend_frontier_codeaware`  
- Inputs:
  - `runs`:
    - `{ lane: "ttidf_wide", run_id: ... }`  
    - `{ lane: "semantic", run_id: ... }`  
    - `{ lane: "ttidf_recall", run_id: ... }`  
    - `{ lane: "ttidf_precision", run_id: ... }`  
    - plus any optional specialized lanes used  
  - `weights`:
    - Initial lane weights (e.g., start around 1.0 and tune using
      `mutate_run`).  
  - `rrf_k`:
    - Controls the tail behavior of RRF (e.g., 60–120).  
  - `beta_fuse`:
    - Fusion-level bias: β > 1 for recall-oriented fusion, β < 1 for
      precision-oriented fusion.  
  - `target_profile`:
    - The `{ code: weight }` map from Step 3, using only one taxonomy
      (FI/FT or CPC or IPC).  
  - `family_fold`:
    - Parameters controlling how patent families are folded or grouped in
      the final ranking.

The output is a fused `run_id` that serves as the **main candidate list**
for human review and downstream LLM agents.

---

### Step 6. Snippet budgeting & review

**Goal:** Use a limited text budget to efficiently assess documents and
feedback into query refinement or boundary adjustment.

- MCP: `peek_snippets`
  - Use the fused `run_id` with a **small `budget_bytes`** (e.g., 200–1000).  
  - Choose `strategy`: `head`, `match`, or `mix`, depending on the task.  
  - Tune claim counts and per-field budgets to maximize the signal-to-noise
    ratio for quick screening.

- MCP: `get_snippets`
  - For a selected subset of `doc_ids`, request larger snippet budgets
    (e.g., 2–10 KB).  
  - Feed these snippets into downstream LLM agents for detailed analysis
    (e.g., evidence extraction, claim mapping).

---

### Step 7. Frontier tuning & provenance

**Goal:** Fine-tune parameters and promote effective configurations to
reusable recipes.

- MCP: `mutate_run`
  - Explore variations in lane `weights`, `rrf_k`, and `beta_fuse`.  
  - Observe changes in recall/precision proxies and Fβ-like metrics
    (as available).

- MCP: `get_provenance`
  - For each important run, inspect:
    - Code distributions  
    - Lane contributions  
    - Configuration snapshots  
  - Promote successful parameter sets and lane combinations to **named
    recipes** for future reuse.

---

## 4. MCP Tools (v1.3)

In v1.3, **MCP tool interfaces are unchanged** from v1.2.  
The following tools are assumed:

- `search_fulltext`  
  - Used for TT-IDF/BM25-style lexical lanes:
    - `ttidf_wide`, `ttidf_recall`, `ttidf_precision`, and optional
      specialized lanes.  
- `search_semantic`  
  - Used for the `semantic` dense retrieval lane.  
- `blend_frontier_codeaware`  
  - Performs rank-based fusion with code-aware priors and Fβ-oriented
    tuning.  
- `peek_snippets`, `get_snippets`  
  - Retrieve snippets under different budget strategies.  
- `mutate_run`  
  - Explore variations around a fused run (lane weights, `rrf_k`,
    `beta_fuse`, etc.).  
- `get_provenance`  
  - Inspect run metadata, including FI/FT/CPC/IPC frequency snapshots and
    lane diagnostics.

**Note:**  
The MCP interface **does not** expose `must` / `should` style parameters.
Precision vs recall behavior is controlled by:

- The structure of the search expressions (OR / phrase / NEAR / field
  selection),  
- Lane design (wide vs recall vs precision),  
- Fusion parameters (`weights`, `beta_fuse`, `rrf_k`),

rather than explicit `must/should` flags.

---

## 5. Summary (v1.3 Key Points)

- JP: **FI as primary + optional FT**; US/WO: **CPC or IPC**.  
- Mixing FI/FT with CPC/IPC in the same lane is **prohibited**.  
- The core lane set is:
  - `ttidf_wide`  
  - `semantic`  
  - `ttidf_recall`  
  - `ttidf_precision`  
- `original_dense` is disabled in v1.3 (may be kept for future use via the
  `search_semantic` tool with a `semantic_style` flag).  
- `semantic` is **text-based** (< 1024 chars), while `ttidf_*` lanes are
  **query-based** (structured search expressions).  
- The core design centers on **RRF + code-aware multi-lane fusion** to
  maximize Fβ under no-gold-label conditions.  
- MCP tool interfaces remain identical to v1.2.  
- In practical operation:
  - LLM-based feature extraction and synonym expansion,  
  - Wide-pool construction and code frequency profiling,  
  - Code-constrained TT-IDF lanes,  
  - RRF fusion and frontier tuning  

  should be executed consistently as a single pipeline.

"""


TOOL_RECIPES= r"""
# RRFusion MCP recipes (v1.3)

This section gives high-level guidance on how to instantiate the pipeline
described in the v1.3 handbook using the existing MCP tools, without
changing their signatures.

## Core tools

In v1.3 the MCP tool interfaces remain unchanged from v1.2; the
handbook assumes the following callable tools.

- `search_fulltext`  
  Implements TT-IDF / BM25-style lexical lanes (`ttidf_wide`,
  `ttidf_recall`, `ttidf_precision`, plus optional specialized lanes).
  Each lane recipe differs by query structure, field boosts, and filters.

- `search_semantic`  
  Runs the dense semantic lane (`semantic`) with natural-language text.
  When `original_dense` is re-enabled, it is expected to be invoked via
  this tool using an optional `semantic_style="original_dense"` signal so
  the backend can route to the alternate dense endpoint.

- `blend_frontier_codeaware`  
  Fuses lanes with RRF + code-aware `target_profile` priors and `beta_fuse`
  tuning.

- `peek_snippets`, `get_snippets`  
  Budgeted snippet access for quick review (`peek`) and deeper per-doc
  extraction (`get`).

- `mutate_run`  
  Explores variations in lane weights, `rrf_k`, `beta_fuse`, and other
  fusion-level deltas.

- `get_provenance`  
  Retrieves code-frequency snapshots, lane contributions, and configuration
  metadata for auditing or recipe capture.

**Note:** MCP does not provide `must`/`should` parameters; recall vs precision
is governed by query structure (OR/phrase/NEAR/fields), lane design, and
fusion params.

## Example lane recipes (conceptual)

These are *conceptual*; adapt to your own query-builder implementation.

### Lane: ttidf_wide

- Base: `search_fulltext`
- Input: `query` string (wide OR expansion over feature terms + synonym
  clusters).
- Characteristics:
  - Mild use of phrase / NEAR; do not over-constrain.
  - Uses title / abstract / claims / description with modest field bias.
  - Code constraints (`fi`, `ft`, `cpc`, `ipc`) are optional until the
    field profile is known.
- Filters: years, doc_type, language, and broad code scopes when helpful.
- Top_k: typically 800–1500 for the wide pool.
- Use: Step 2 wide recall + one input to fusion.

### Lane: semantic

- Base: `search_semantic`
- Input: 1–3 sentences describing the core intent (≲1024 chars, ideally
  300–500).
- Characteristics:
  - Dense embeddings help recover paraphrased expressions.
  - Apply code constraints only when semantic drift is apparent.
- Filters: same coarse constraints as `ttidf_wide` (year, doc_type, etc.).
- Top_k: typically 400–800.
- Use: Step 2 wide pool + fusion input.

### Lane: ttidf_recall

- Base: `search_fulltext`
- Input: `query` string with TT-IDF-style scoring; wide OR structure over
  feature terms and synonym clusters while keeping multi-word terms intact.
- Fields: claims/title/abstract (description if needed).
- Code constraints: derived from the Step 3 `target_profile` (FI/FT or CPC/IPC)
  and applied to stay within the technical field.
- Use: Step 4 recall-oriented lane that fills in the in-field candidate pool.

### Lane: ttidf_precision

- Base: `search_fulltext`
- Input: `query` string with aggressive phrase / NEAR usage and strong claim
  field bias.
- Characteristics:
  - Synonym clusters are used conservatively, distinguishing strong vs
    weaker variants.
  - Same code scope as `ttidf_recall` to concentrate within the field.
- Use: Step 4 precision-focused lane that sharpens the in-field ranking.

### Optional lanes (examples)

- `claim_only_fulltext`: same as `ttidf_precision` but claims-only fields.
- `title_abstract_boosted`: strong boosts on title/abstract for overview.
- `near_phrase_heavy`: more aggressive use of phrase/NEAR operators.

## Fusion recipe (blend_frontier_codeaware)

- Inputs:
  - `runs`: list of `{ lane, run_id }` including all lanes used.
  - `weights`: initial lane weights (e.g. `ttidf_wide=1.0`,
    `semantic=1.0`, `ttidf_recall=1.0`, `ttidf_precision=1.2`).
  - `rrf_k`: e.g. 60–120 depending on desired tail contribution.
  - `beta_fuse`: >1 for recall bias, <1 for precision bias.
  - `target_profile`: FI/FT/CPC/IPC prior derived from wide pool.
  - `family_fold`: configuration for family folding.
- Tuning:
  - Use `mutate_run` to explore variations and lock in good defaults.
"""
