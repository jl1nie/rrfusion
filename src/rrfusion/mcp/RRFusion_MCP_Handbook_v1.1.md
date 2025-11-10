# RRFusion MCP Handbook (v1.1)

**Mission**: Maximize *effective* Fβ (default β=1) for prior-art retrieval using multi-lane search and code-aware fusion under no-gold-label conditions.  
**Transport**: HTTP / streamable-http at `/{base_path}` (default `/mcp`).  
**Auth**: Bearer token if configured.

> Notes
> - Lane raw scores are **incomparable**. Use **rank-based fusion (RRF)** as the primary method.  
> - `beta_fuse` below controls **precision/recall trade-off in fusion**, not the Fβ metric itself.

---

## 1. Pipeline (Agent-facing)
1) Normalize & synonymize query (LLM; acronyms, phrases, negatives)
2) Run lanes in parallel
   - `search_fulltext` → **precision-skewed** keyword evidence; expand recall via synonyms & larger `top_k`
   - `search_semantic` → embedding coverage with same filters to curb drift
3) Fuse via `blend_frontier_codeaware` (RRF + code prior)
4) Budget check with `peek_snippets` (head/match/mix)
5) Shortlist then `get_snippets`
6) If proxy-metrics unsatisfactory → `mutate_run` (weights / rrf_k / beta_fuse / filters)
7) Persist with `get_provenance`

---

## 2. Lane Tools

### `search_fulltext`
- **Args**: 
  - `q: string`
  - `filters?: { must?: Cond[]; should?: Cond[]; must_not?: Cond[] }`
  - `top_k: int = 800`
  - `rollup?: { family_fold?: boolean = true }`
  - `budget_bytes: int = 4096`
  - `seed?: int`, `trace_id?: string`
- **Cond**: `{ field: "ipc|fi|cpc|pubyear|assignee|country", op: "in|range|eq|neq", value: any }`
- **Tips**: Use field boosts server-side (claims > title > abstract > desc). Keep `top_k` generous (200–1000), and mirror filters in semantic.

### `search_semantic`
- **Args**: same as `search_fulltext`
- **Tips**: Keep `q` concise (≤256 chars). Apply same `filters` when drift risk exists.

---

## 3. Fusion

### `blend_frontier_codeaware`
- **Args**:
  - `runs: [{ lane: "fulltext|semantic", run_id: string }]`
  - `weights?: { fulltext?: float, semantic?: float }`  (lane **rank** weights)
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

---

## 4. Snippet Budgeting

### `peek_snippets`
- **Args**:
  - `run_id`, `offset=0`, `limit=12`
  - `fields?: ["title","abstract","claims","desc"]`
  - `per_field_chars?: { field: int }`
  - `claim_count=3`
  - `strategy: "head"|"match"|"mix"`
  - `budget_bytes=12288`
- **Patterns**:
  - `head` → titles/abstracts
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

# Tool Recipes & Few-shot (v1.1)

## search_fulltext — examples
**Good**
```json
{
  "q": "grant-free uplink HARQ process scheduling",
  "filters": {
    "must": [{"field":"ipc","op":"in","value":["H04W72/04","H04L1/18"]}],
    "should": [{"field":"pubyear","op":"range","value":{"gte":2018}}],
    "must_not": []
  },
  "top_k": 500
}
```

**Good (phrase/near)**
```json
{
  "q": "\"uplink grant-free\"~3 early HARQ feedback",
  "filters": {"must":[{"field":"cpc","op":"in","value":["H04W72/12"]}]},
  "top_k": 600
}
```

**Bad**
```json
{"q":"HARQ","top_k":10}
```

---

## search_semantic — examples
**Good**
```json
{
  "q": "contention-based uplink, early HARQ feedback for URLLC",
  "filters": {"must":[{"field":"cpc","op":"in","value":["H04W72/12"]}]},
  "top_k": 400
}
```

---

## blend_frontier_codeaware — examples
**Equal-weight fuse**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
  "rrf_k": 60,
  "beta_fuse": 1.0,
  "family_fold": true
}
```

**Favor codes**
```json
{
  "runs": [{"lane":"fulltext","run_id":"L1"}, {"lane":"semantic","run_id":"L2"}],
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
  "fields":["title","abstract","claims"],
  "per_field_chars":{"claims":1200}
}
```

---

## mutate_run — examples
```json
{
  "run_id":"FUSION_123",
  "delta":{"weights":{"semantic":1.2,"fulltext":1.0},"rrf_k":50,"beta_fuse":1.2}
}
```

---

## get_provenance — example
```json
{"run_id":"FUSION_123"}
```
