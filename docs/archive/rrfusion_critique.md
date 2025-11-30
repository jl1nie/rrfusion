# Critique of RRFusion MCP v1.3 from a Professional Patent Searcher Perspective

## 1. 用途語への過剰適合問題（Context Drift）
- wide レーンが **用途語を AND 側に含めてしまう**と、  
  以降のすべてのレーン（recall / precision / semantic）が誤った分野へ固定される。
- target_profile が **用途偏りコード**で汚染され、  
  正解集合が用途違いの場合 **F=0 が即確定**。

### 改善案（コード的観点）
```python
# pseudo: wide query sanitation
wide_terms = extract_features(core=True, context=False)
wide_query = MUST(wide_terms) + SHOULD(context_terms)
```

---

## 2. コード prior 依存の過剰強化（FI/FT/CPC Bias）
- 正解文献が **誤分類コード / コード未付与 / 隣接分野**にあるのは実務では常態。
- RRFusion は Fβ* で **コード一致を重く見るため**、  
  コード外の正解文献は構造的に救えない。

### 改善案
```python
# soften code gating
final_score = rrf_score + alpha * code_boost   # alpha < 0.3 に抑制
```

---

## 3. Fβ* proxy が「コード一致≒関連度」になりすぎている
- P*(k), R*(k) が **code_scores に単純依存**するため、  
  コード一致していても **構成要件が全く違う文献**が高得点になり、  
  実務 F=0 の主要因になる。

### 改善案
```python
# add structural relevance
struct_sim = claims_similarity(doc, query)
F_beta_star = blend(code_score, struct_sim, weights=(0.5, 0.5))
```

---

## 4. LLM クエリ生成の「一般語過多」問題
- “system, device, method” のような一般語が AND 側に入りやすく、  
  コア構成語が抜けることで BM25 の **precision / recall 辛さの両方を悪化**させる。

### 改善案
```python
# remove general words
query_terms = [t for t in generated_terms if t not in GENERAL_STOPWORDS]
```

---

## 5. semantic(default) が semantic ではない問題
- semantic(default) が **Patentfield similarity**（BM25 派生）であり、  
  dense embedding ではないため **言い換え耐性がほぼゼロ**。
- 結果として “構成要件を言い換えた正解文献” を落とし、F=0に直行。

### 改善案
```python
# future v1.4: dense-enabled semantic
semantic_query = encode_dense(claims_text)
scores = dot(semantic_query, embeddings)
```

---

## 6. wide の「用途汚染」→ target_profile 汚染 → 全レーン崩壊
- wide の検索語に用途語が混入すると、  
  code_freqs が用途寄りになり target_profile が完全に誤誘導される。

### 改善案
```python
# detect context contamination
if context_code_ratio(target_profile) > threshold:
    target_profile = rebuild_profile_without_context()
```

---

## 7. RRF の線形融合が構造マッチングと相性が悪い
- RRF は rank の単純な逆数和。  
  “A AND B AND C が揃った文献” を評価できず、  
  “A の文献 + B の文献” を高得点にしてしまう。

### 改善案
```python
# enforce component coverage
coverage = faceted_match(doc, required_components=["A","B","C"])
final_score = rrf_score * (1 + gamma * coverage)
```

---

## 8. 代表レビュー（A/B/C）への過剰依存
- 30文献を人手で読むのは重すぎ、  
  実務のタイムラインでは **代表レビューがパフォーマンスボトルネック**になる。

### 改善案
```python
# lightweight representative sampling
representatives = sample_top_k(docs, k=10)
```

---

## 9. 総括（F=0 の主因）
- **用途語混入 → wide 汚染 → profile 汚染 → 全レーン誤誘導**
- **コード prior 過多 → 正解文献がコード外のとき救済不能**
- **semantic が非semantic → 言い換え構成を拾えず recall 崩壊**

→ 実務の正解集合に対して **F=0 となるのは構造的必然**であり、  
　対策は上記のように “コード以外の構造的 proxy” を導入する必要がある。
