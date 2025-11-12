# """Handbook + recipe prompts extracted from host.py for reuse or future customization.
# Two human-readable constants for import:
# - HANDBOOK
# - TOOL_RECIPES
# """

HANDBOOK = '''
# RRFusion MCP Handbook (v1.2, multi-lane)

**Mission**: Maximize *effective* Fβ (default β=1) for prior-art retrieval using **multi-lane search** (fulltext-wide / fulltext-focused / fulltext-hybrid / semantic) and **code-aware fusion** under no-gold-label conditions.  
**Transport**: HTTP / streamable-http at `/{base_path}` (default `/mcp`).  
**Auth**: Bearer token if configured.

> Notes
> - Lane raw scores are **incomparable**. Use **rank-based fusion (RRF)** as the primary method.  
> - `beta_fuse` below controls **precision/recall trade-off in fusion**, not the Fβ metric itself.

---

## 1. Pipeline (Agent-facing)
1) Normalize & synonymize query (LLM; acronyms, phrases, negatives)
2) Run lanes in parallel (**multi-lane**)
   - `search_fulltext.wide` → broad keyword recall (builds initial pool)
   - `search_fulltext.focused` → constrained keywords / phrase / NEAR to sharpen precision
   - `search_fulltext.hybrid` → mixed logic (OR expansion + MUST/SHOULD) for balance
   - `search_semantic` → embedding coverage with shared filters to curb drift
3) Fuse via `blend_frontier_codeaware` (RRF + code prior)
4) Budget check with `peek_snippets` (head/match/mix)
5) Shortlist then `get_snippets`
6) If proxy-metrics unsatisfactory → `mutate_run` (weights / rrf_k / beta_fuse / filters)
7) Persist with `get_provenance`

---

## 2. Lane Tools

### `search_fulltext`
- **Args**: 
  - `query: string`
  - `filters?: list[Cond]` (each `Cond` owns `lop`=`and|or|not`) – server honors the flat clause list; `must/should` groups are not enforced
  - `fields?: list[SnippetField]` (same options as `get_publication.fields`, default `["abst","title","claim"]`; add `"desc"` only when you need description text)
  - `top_k: int = 800`
  - `budget_bytes: int = 4096`
  - `seed?: int`, `trace_id?: string`
- **Cond**: `{ lop: "and|or|not", field: "ipc|fi|cpc|pubyear|assignee|country", op: "in|range|eq|neq", value: any }`
- **Tips**: Use field boosts server-side (claim > title > abst > desc). Keep `top_k` generous (200–1000), and mirror filters in semantic.

### `search_semantic`
- **Args**: (replace `query` with `text`), other args same as `search_fulltext`
- **Tips**: Keep `text` concise (≤256 chars). Apply the **same `filters`** when drift risk exists.

---

## 3. Fusion

### `blend_frontier_codeaware`
- **Args**:
  - `runs: [{ lane: "fulltext-wide|fulltext-focused|fulltext-hybrid|semantic", run_id: string }]`
  - `weights?: { fulltext-wide?: float, fulltext-focused?: float, fulltext-hybrid?: float, semantic?: float }` (lane **rank** weights)
  - `rrf_k: int = 60`
  - `beta_fuse: float = 1.0`  ← higher → recall, lower → precision
  - `family_fold: boolean = true`
  - `target_profile?: { ipc|fi|cpc: { code: weight } }`
  - `code_idf_mode?: "global"|"domain" = "global"`
  - `top_m_per_lane?: int`
  - `k_grid?: [int]`   // optional sweep
  - `peek?: { limit?: int }`
- **Code prior**:
  - Let `idf_c = log(N / (1 + freq(c)))`
  - Let query-side code weights be `w_q(c)` from PRF/LLM.
  - Doc-side contribution: `s_code(d) = Σ_{c∈C_d} idf_c * w_q(c)`
  - Final rank score ~ `RRF(rank)` adjusted by lane weights, then **re-ranked** by `s_code(d)` with a small mixing λ.
  - When encoding `target_profile` for Japanese families, prefer FI coverage first and treat FT references as supporting signal; fall back to IPC/CPC only if FI/FT is absent or for non-JP jurisdictions.

---

## 4. Snippet Budgeting

### `peek_snippets`
- **Args**:
  - `run_id`, `offset=0`, `limit=12`
- `fields?: ["title","abst","claim","desc"]`
  - `per_field_chars?: { field: int }`
  - `claim_count=3`
  - `strategy: "head"|"match"|"mix"`
  - `budget_bytes=12288`
- **Patterns**:
- `head` → titles/absts
  - `match` → query highlights focus
  - `mix` → balanced

### `get_snippets`
- **Args**: `ids[]`, `fields?`, `per_field_chars?`, `seed?`
- **Note**: Independent of fusion cursor; random access OK.

---

## 5. Iterative Tuning

### `mutate_run`
- **Args**: 
  - `run_id`
  - `delta`: `{ weights?|rrf_k?|beta_fuse?|filters?|top_m_per_lane?|family_fold? }`
- **Loop**: Adjust → re-peek → compare proxy P/R/Fβ at fixed K.

### `get_provenance`
- **Args**: `run_id`
- **Returns**: inputs, filters, lane stats, fusion params (`weights, rrf_k, beta_fuse`), code prior snapshot, metrics, `seed`, `trace_id`.

---

## 6. Metrics & Logging (No-gold regime)

- **Emit**:  
  - `lane.top_k`, `fuse.rrf_k`, `beta_fuse`, `hit@k`, `p@k`, `r@k`, `f_beta@k`, `diversity@k`
- **Proxy definitions**:
  - `p@k` ≔ cross-lane agreement ratio at K (RRF ∩ lane tops)
  - `r@k` ≔ PRF 再検索での再出現率 at K
  - `f_beta@k` ≔ above two combined as Fβ (β from Mission)
  - `diversity@k` ≔ 1 − avg pairwise similarity (MMR 由来)

---

## 7. Security
- Never send PII/secret in queries.  
- Server injects downstream API keys.  
- Client supplies **Bearer** token only.  
- Redact snippets beyond `budget_bytes`.

---

*Build: 2025-11-12T22:24:22*

'''

TOOL_RECIPES = '''
# Tool Recipes & Few-shot (v1.2, multi-lane)

## search_fulltext — examples
**Wide (recall-oriented)**
```json
{
  "query": "uplink AND (HARQ OR \"early feedback\")",
  "filters": [
    {"lop":"and","field":"ipc","op":"in","value":["H04W72/04","H04L1/18"]}
  ],
  "fields": ["abst","title","claim"],
  "top_k": 800
}
```

**Focused (precision-oriented)**
```json
{
  "query": "\"uplink grant-free\"~3 NEAR/10 (early feedback OR URLLC)",
  "filters": [
    {"lop":"and","field":"cpc","op":"in","value":["H04W72/12"]}
  ],
  "fields": ["abst","title","claim"],
  "top_k": 400
}
```

**Hybrid (balanced)**
```json
{
  "query": "uplink AND (\"grant-free\" OR \"non-scheduled\") AND (HARQ OR feedback)",
  "filters": [],
  "fields": ["abst","title","claim"],
  "top_k": 600
}
```

**Bad**
```json
{"query":"HARQ","top_k":10}
```

---

## search_semantic — examples
**Default**
```json
{
  "text": "contention-based uplink with early HARQ feedback for URLLC",
  "filters": [{"lop":"and","field":"cpc","op":"in","value":["H04W72/12"]}],
  "fields": ["abst","title","claim"],
  "top_k": 500
}
```

---

## blend_frontier_codeaware — examples
**Equal-weight fuse**
```json
{
  "runs": [
    {"lane":"fulltext-wide","run_id":"FT_WIDE"},
    {"lane":"fulltext-focused","run_id":"FT_FOC"},
    {"lane":"fulltext-hybrid","run_id":"FT_HYB"},
    {"lane":"semantic","run_id":"SEM"}
  ],
  "rrf_k": 60,
  "beta_fuse": 1.0,
  "family_fold": true
}
```

**Favor codes**
```json
{
  "runs": [
    {"lane":"fulltext-wide","run_id":"FT_WIDE"},
    {"lane":"fulltext-focused","run_id":"FT_FOC"},
    {"lane":"fulltext-hybrid","run_id":"FT_HYB"},
    {"lane":"semantic","run_id":"SEM"}
  ],
  "target_profile": {"ipc":{"H04W72/04":1.2,"H04L1/18":1.0}},
  "rrf_k": 50,
  "beta_fuse": 0.9
}
```

---

## peek_snippets — examples
```json
{
  "run_id":"FUSION_123",
  "offset":0,
  "limit":12,
  "strategy":"mix",
  "budget_bytes": 12288
}
```

---

## get_snippets — examples
```json
{
  "ids":["US2023XXXXXXA1","EPXXXXXXXB1"],
  "fields":["title","abst","claim"],
  "per_field_chars":{"claim":1200}
}
```

---

## mutate_run — examples
```json
{
  "run_id":"FUSION_123",
  "delta":{"weights":{"fulltext-focused":1.2,"semantic":1.1},"rrf_k":50,"beta_fuse":0.9}
}
```

---

## get_provenance — example
```json
{"run_id":"FUSION_123"}
```

'''
