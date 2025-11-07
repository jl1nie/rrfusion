# AGENT.md — rrfusion (Multi-lane Patent Search Engine)

> **Goal:** Provide Codex (or any dev agent) with a single, authoritative brief that covers the scaffold, randomized DB stub, and the final code-aware RRF implementation. Heavy data lives in Redis; MCP endpoints return compact handles and summaries only.

---

## 0. Definition of Done

### 0.1 Randomized stub milestone
- `docker compose up --build` starts **redis**, **db-stub**, and **mcp**; all services report healthy.
- MCP exposes every tool at `/mcp/...` with the exact signatures listed below.
- `search_fulltext/semantic` call the DB stub, store results in Redis ZSETs, and return only handles (`run_id_lane`, cursors, metadata).
- `blend_frontier_codeaware` performs baseline RRF in Python, returns fused IDs, a mocked frontier, code freqs, and run `recipe`.
- `peek_snippets`/`get_snippets` call the stub, enforcing `PEEK_MAX_DOCS` + `PEEK_BUDGET_BYTES`.
- `mutate_run` mints a new `run_id` (can reuse cached data at this phase).
- `get_provenance` returns stored metadata/recipe.

### 0.2 Algorithm milestone
- Lane rankings store **RRF-ready** scores (`w_lane / (rrf_k + rank)`); fusion uses Redis `ZUNIONSTORE`.
- Code-aware adjustments (A/B/C), lane modulation, code-only lane, and contribution tracking are implemented.
- Frontier estimation uses the code coverage proxies described below.
- Family folding is supported.
- `peek_snippets` obeys doc+byte caps while honoring requested strategies.
- `mutate_run` truly reapplies deltas and recomputes fusion/frontiers.

---

## 1. Architecture & Repo Layout
- **Redis**: stores per-lane ZSETs, fusion runs, snippets, metadata, and optional doc caches.
- **DB stub (FastAPI)**: deterministic random scores/snippets used for local development.
- **MCP server (FastAPI)**: exposes MCP tools, orchestrates Redis + stub, and owns fusion logic.

```
rrfusion/
  AGENT.md                 # <- this brief
  README.md                # quick start + workflow
  deploy/docker-compose.yml
  db-stub/                 # FastAPI stub + Dockerfile
  mcp/                     # MCP FastAPI app + Dockerfile
  src/rrfusion/            # shared libs (config, storage, fusion, snippets)
  tests/                   # unit tests for fusion/snippet helpers
```

---

## 2. Environment & Tooling

### 2.1 Runtime configuration
Read from `.env` (see `deploy/.env.example` or `env.example` in repo root).

| Key | Default | Notes |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `DB_STUB_URL` | `http://db-stub:8080` | Randomized scores & snippets |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `3000` | MCP port |
| `RRF_K` | `60` | RRF constant |
| `PEEK_MAX_DOCS` | `100` | Snippet count cap |
| `PEEK_BUDGET_BYTES` | `12288` | Snippet payload cap |

### 2.2 Development workflow
- Install [`uv`](https://github.com/astral-sh/uv`) and ensure it is on `PATH`.
- From repo root: `uv sync --all-packages` to create/refresh the managed virtual env.
- Run tests via `uv run pytest` (use `uv run pytest tests/<pkg>` for subsets).
- Local services:
  ```bash
  uv run uvicorn db-stub.app:app --host 0.0.0.0 --port 8080
  uv run uvicorn mcp.app:app --host 0.0.0.0 --port 3000
  ```
- Docker Compose (Redis + stub + MCP):
  ```bash
  cd deploy
  cp .env.example .env
  docker compose up --build
  ```

---

## 3. Redis Data Model
- **Lane ZSET** `z:{snapshot}:{query_hash}:{lane}`  
  - Member: `doc_id` (uint64/string).  
  - Score: stub phase → raw score; algorithm phase → `w_lane / (rrf_k + rank)`.
- **Fusion ZSET** `z:rrf:{run_id}` via `ZUNIONSTORE ... WEIGHTS 1 ...`.
- **Code freq hashes** `h:freq:{run_id}:{lane}`: store compact IPC/CPC counts (top-N).
- **Run metadata** `h:run:{run_id}`: JSON payload describing recipe, parent, lineage, source lanes, and snapshot info.
- **Doc/snippet cache** `h:doc:{doc_id}` (+ optional `h:doc2fam`). TTLs: lane/fusion/freq/run 24h, snippets 72h.

---

## 4. Services

### 4.1 Redis
Provided by `deploy/docker-compose.yml`. Ensure persistence via `redis-data` volume and health check.

### 4.2 DB Stub API (FastAPI)
- `GET /healthz` → `{"status":"ok"}`.
- `POST /search/{lane}` (lane ∈ {`fulltext`, `semantic`}): body = `SearchRequest` (see §5). Returns:
  ```json
  {
    "items": [
      {
        "doc_id": "string",
        "score": 0.91,
        "title": "...",
        "abst": "...",
        "claim": "...",
        "description": "...",
        "ipc_codes": ["H04L"],
        "cpc_codes": ["H04L9/32"]
      }
    ],
    "code_freqs": {
      "ipc": {"H04L": 12},
      "cpc": {"H04L9/32": 6}
    }
  }
  ```
  - `doc_id` values are deterministic random strings; `score` variance differs per lane.
- `POST /snippets`  
  Body = `{ "ids": [...], "fields": [...], "per_field_chars": {...}, "claim_count": 3, "strategy": "head|match|mix" }`.  
  Returns `{ doc_id: { field: truncated_text } }`, respecting char caps.

### 4.3 MCP server (FastAPI)
- Routes mounted at `/mcp/...` (plus `/healthz`).
- **Stub milestone behavior**: call DB stub for data, keep fusion in Python, mock frontier.
- **Algorithm milestone behavior**: rely on Redis for per-lane scores, fusion, snippets; implement code-aware + family fold logic outlined in §6.

---

## 5. MCP Tools (HTTP APIs)

### 5.1 `search_fulltext` / `search_semantic`
Fetch top-k results from the DB stub, store them in Redis, and return handles only.

**Input**
```json
{
  "q": "string",
  "filters": {
    "date_from": "YYYY-MM-DD?",
    "date_to": "YYYY-MM-DD?",
    "ipc": ["string"]?,
    "cpc": ["string"]?,
    "assignee": ["string"]?
  },
  "top_k": 10000,
  "rollup": { "ipc_level": 4, "cpc_level": "main_group" },
  "budget_bytes": 4096
}
```

**Output**
```json
{
  "lane": "fulltext" | "semantic",
  "run_id_lane": "string",
  "count_returned": 10000,
  "truncated": true,
  "code_freqs": { "ipc": {"H04L":12}, "cpc": {"H04L9/32":6} },
  "cursor": "string"
}
```

**Implementation notes**
- Stub milestone: use raw stub scores, store them directly, and return metadata.
- Algorithm milestone: store RRF-ready scores (`w_lane/(rrf_k + rank)`), and persist code freqs + doc caches for later fusion.

---

### 5.2 `blend_frontier_codeaware`
Perform RRF fusion with optional code awareness and frontier reporting.

**Input**
```json
{
  "runs": [
    { "lane": "fulltext", "run_id_lane": "string" },
    { "lane": "semantic",  "run_id_lane": "string" }
  ],
  "weights": { "recall": 1.0, "precision": 1.0, "semantic": 1.0, "code": 0.5 },
  "rrf_k": 60,
  "beta": 1.0,
  "family_fold": true,
  "target_profile": { "ipc": {"H04L": 0.7, "H04W": 0.3} },
  "top_m_per_lane": { "fulltext": 10000, "semantic": 10000 },
  "k_grid": [10,20,30,40,50,80,100,150,200],
  "peek": {
    "count": 10,
    "fields": ["title","abst"],
    "per_field_chars": { "title": 120, "abst": 360 },
    "budget_bytes": 4096
  }
}
```

**Output**
```json
{
  "run_id": "string",
  "pairs_top": [["123456789", 0.913], ["..."]],
  "frontier": [{"k": 50, "P_star": 0.62, "R_star": 0.55, "F_beta_star": 0.58}],
  "freqs_topk": { "ipc": {"H04L": 22}, "cpc": {"H04L9/32": 11} },
  "contrib": { "123456789": {"recall":0.4,"semantic":0.4,"code":0.2} },
  "recipe": { "weights": {...}, "rrf_k": 60, "beta": 1.0, "family_fold": true, "snapshot": "..." },
  "peek_samples": [ { "id":"123456789", "title":"...", "abst":"..." } ]
}
```

**Implementation notes**
- Stub milestone: run RRF in Python, generate a mocked frontier (e.g., random relevance prior), store fusion results in Redis for consistency.
- Algorithm milestone: use Redis `ZUNIONSTORE`, apply code-aware adjustments (§6), compute true frontier proxies, family fold, and contribution shares. Include lineage metadata for reproducibility.

---

### 5.3 `peek_snippets`
Return snippets for a run, honoring doc count + byte budgets.

**Input**
```json
{
  "run_id": "string",
  "offset": 0,
  "limit": 20,
  "fields": ["title","abst","claim","description"],
  "per_field_chars": { "title":120, "abst":360, "claim":280, "description":480 },
  "claim_count": 3,
  "strategy": "head" | "match" | "mix",
  "budget_bytes": 12288
}
```

**Output**
```json
{
  "items": [
    { "id":"123", "title":"...", "abst":"...", "claim":"...", "description":"..." }
  ],
  "used_bytes": 11800,
  "truncated": false,
  "peek_cursor": "string"
}
```

**Implementation notes**
- Stub milestone: request snippets from DB stub per doc ID and enforce caps client-side.
- Algorithm milestone: favor cached snippets in Redis; if missing, backfill via stub. Budget enforcement stays the same.

---

### 5.4 `get_snippets`
Direct lookup by IDs (post-selection). Same field rules as `peek_snippets`.

**Input**
```json
{ "ids": ["123","124"], "fields": ["title","abst"], "per_field_chars": {"title":120,"abst":360} }
```

**Output**
```json
{ "123": {"title":"...", "abst":"..."}, "124": {"title":"...", "abst":"..."} }
```

- Use cached snippets when possible; otherwise fetch from stub.

---

### 5.5 `mutate_run`
Immutable delta exploration; server reuses cached lanes, recomputing fusion/frontier as needed.

**Input**
```json
{
  "run_id": "string",
  "delta": {
    "add_keywords": ["..."]?,
    "drop_keywords": ["..."]?,
    "add_ipc": ["..."]?,
    "drop_ipc": ["..."]?,
    "rollup_change": { "ipc_level": 4 }?,
    "weights": { "precision": 1.2 }?,
    "rrf_k": 30?,
    "beta": 0.5?
  }
}
```

**Output**
```json
{ "new_run_id": "string", "frontier": [...], "recipe": {...} }
```

- Stub milestone: may simply copy parent fusion results with a new `run_id`.
- Algorithm milestone: apply deltas to recipe (weights, rrf_k, beta, target profile, rollup), recompute fusion via Redis, update lineage.

---

### 5.6 `get_provenance`
Return `recipe` and lineage for auditability.

**Input**
```json
{ "run_id": "string" }
```

**Output**
```json
{ "recipe": {...}, "parent": "run_id?", "history": ["run_a","run_b","..."] }
```

- Ensure every run (lane + fusion) stores enough metadata to satisfy this endpoint.

---

## 6. Algorithms & Heuristics (Final implementation)

### 6.1 RRF scoring & storage
- On `search_*`, compute `score = w_lane / (rrf_k + rank)` (rank is 1-based). Store in `z:{snapshot}:{query_hash}:{lane}`.
- Persist per-doc snippets + code lists in Redis for subsequent steps.
- When blending, use Redis `ZUNIONSTORE z:rrf:{run_id} N lane_keys WEIGHTS 1 ...` (lanes already weight-encoded).

### 6.2 Code-aware adjustments (A/B/C)
- **A) Per-doc boost**: compute overlap score `g(d)` using `target_profile` weights (hierarchical IPC/CPC matches allowed). Normalize `g(d)` to [0,1], then update doc score: `ŝ_ℓ(d) = s_ℓ(d) * (1 + α_ℓ * norm(g(d)))`.
- **B) Lane modulation**: compare lane code freqs `F_ℓ` to `target_profile T` (e.g., cosine similarity). Adjust lane weights: `w'_ℓ = w_ℓ * (1 + β * sim(F_ℓ, T))`. Apply this by scaling lane ZSET scores before fusion (scaling factors can be applied via another `ZUNIONSTORE`).
- **C) Code-only lane**: optionally create a `rank_code(d)` ZSET using `g(d)` as the score and include it in fusion with a small `w_code` (e.g., 0.5).

### 6.3 Frontier estimation
- For each `k` in `k_grid`, compute:
  - `P_star(k)`: average relevance proxy `π'(d)` in top-k, where `π'(d) = σ(a*ŝ(d) + b + γ*z(g(d)))`.
  - `R_star(k)`: `ρ * coverage(k) + (1-ρ) * CDF_score(k)` where coverage measures IPC/CPC diversity wrt `target_profile`.
  - `F_beta_star(k)`: standard Fβ from `P_star` and `R_star`.
- Return 10–20 representative points (use provided grid).

### 6.4 Family folding
- Maintain `doc_id → family_id` map (simple rule ok during scaffold, e.g., `fam = doc_id // 10`).
- When reading fusion ranks, skip docs whose family already appeared until the requested `k` unique families are collected.

### 6.5 Contribution tracking
- While computing RRF, accumulate per-doc contributions by lane (`recall`, `precision`, `semantic`, `code`). Normalize to percentages before returning.

---

## 7. LLM Operating Rules (prompt-ready)
- Always fetch lanes with the **same query/filters/rollup**.
- Never request full `(doc_id, score)` arrays; use handles only.
- Fuse with `blend_frontier_codeaware`; pick `k` from the returned `frontier` (or explicit `top_K_read`).
- Use `peek_snippets` sparingly (≤ `PEEK_MAX_DOCS`, obey `PEEK_BUDGET_BYTES`).
- Prefer `family_fold:true` and report `run_id/recipe` for reproducibility.
- Tune precision vs recall using `weights` and `rrf_k` (smaller = precision bias).

---

## 8. Testing & Acceptance
- **Smoke**: `search_fulltext` → `search_semantic` → `blend_frontier_codeaware` → `peek_snippets`. Assert run IDs exist, Redis ZSETs populated, frontier non-empty, snippet budgets respected.
- **Unit**: fusion math, code boosts, snippet truncation, family folding.
- **Integration**: `mutate_run` delta path, `get_provenance` lineage, Redis TTL behavior.
- **Acceptance checklist**
  - `docker compose up -d` starts Redis + services healthy.
  - MCP reads `REDIS_URL`, writes lane ZSETs, and fuses via Redis.
  - Frontier computation is server-side and reproducible via `recipe`.
  - Snippet endpoints enforce doc count and byte caps.

This AGENT.md is the single source of truth; the previous `AGENT_2.md`, `CODEX_BRIEF_STUB.md`, and `CODEX_BRIEF_ALGO.md` have been merged here.
