# 融合エンジン仕様

本章では、RRFusionの核心である融合アルゴリズムの実装仕様を解説します。

## 1. RRF（Reciprocal Rank Fusion）基本アルゴリズム

### 基本式

```
RRF_score(d) = Σ [ w_lane_type_i / (k + rank_i(d)) ]
```

- `d`: 文献
- `rank_i(d)`: レーンiでの文献dの順位（1-indexed）
- `w_lane_type_i`: レーンタイプiの重み（weights.fulltext / weights.semantic / weights.code）
- `k`: 定数（デフォルト60）

### Pythonリファレンス実装

```python
def calculate_rrf_score(doc_id: str, lane_results: List[LaneResult], weights: Dict[str, float], k: float = 60) -> float:
    """
    Calculate RRF score for a document
    """
    score = 0.0
    for lane_result in lane_results:
        rank = lane_result.get_rank(doc_id)
        if rank is None:
            continue  # 文献がこのレーンに存在しない

        lane_type = lane_result.lane  # "fulltext" | "semantic" | "code"
        w = weights.get(lane_type, 1.0)

        score += w / (k + rank)

    return score
```

## 2. π(d)ブースト

### π(d)の計算

```
π(d) = w_code × π_code(d) + w_facet × π_facet(d) + w_lane × π_lane(d)
```

#### π_code(d): target_profileとのコード一致度

```python
def calculate_pi_code(doc: Document, target_profile: TargetProfile) -> float:
    """
    Calculate code matching score
    """
    score = 0.0

    # FI codes
    for fi_code in doc.fi_norm:
        if fi_code in target_profile.fi:
            score += target_profile.fi[fi_code]

    # F-Term codes
    for ft_code in doc.ft:
        if ft_code in target_profile.ft:
            score += target_profile.ft[ft_code]

    # Normalize (optional)
    max_score = sum(target_profile.fi.values()) + sum(target_profile.ft.values())
    if max_score > 0:
        score /= max_score

    return score
```

#### π_facet(d): A/B/C要素（facet_terms）の出現度

```python
def calculate_pi_facet(doc: Document, facet_terms: Dict[str, List[str]], facet_weights: Dict[str, float]) -> float:
    """
    Calculate facet matching score
    """
    score = 0.0
    doc_text = " ".join([doc.title, doc.abst, doc.claim])

    for facet_name, terms in facet_terms.items():
        facet_weight = facet_weights.get(facet_name, 1.0)
        match_count = sum(1 for term in terms if term in doc_text)

        if match_count > 0:
            score += facet_weight * (match_count / len(terms))

    # Normalize
    total_facets = len(facet_terms)
    if total_facets > 0:
        score /= total_facets

    return score
```

#### π_lane(d): 出現レーン数

```python
def calculate_pi_lane(doc_id: str, lane_results: List[LaneResult]) -> float:
    """
    Calculate lane coverage score
    """
    present_in_lanes = sum(1 for lane in lane_results if lane.has_doc(doc_id))
    total_lanes = len(lane_results)

    return present_in_lanes / total_lanes if total_lanes > 0 else 0.0
```

### π(d)の統合

```python
def calculate_pi(doc_id: str, doc: Document, lane_results: List[LaneResult],
                 target_profile: TargetProfile, facet_terms: Dict, facet_weights: Dict,
                 pi_weights: Dict[str, float]) -> float:
    """
    Calculate π(d) boost score
    """
    pi_code_val = calculate_pi_code(doc, target_profile)
    pi_facet_val = calculate_pi_facet(doc, facet_terms, facet_weights)
    pi_lane_val = calculate_pi_lane(doc_id, lane_results)

    pi = (pi_weights.get("code", 0.4) * pi_code_val +
          pi_weights.get("facet", 0.3) * pi_facet_val +
          pi_weights.get("lane", 0.3) * pi_lane_val)

    return pi
```

## 3. 最終スコア計算

### 融合スコア

```
final_score(d) = RRF_score(d) × (1 + β × π(d))
```

```python
def calculate_final_score(doc_id: str, doc: Document, lane_results: List[LaneResult],
                          weights: Dict, target_profile: TargetProfile,
                          facet_terms: Dict, facet_weights: Dict, pi_weights: Dict,
                          rrf_k: float, beta_fuse: float) -> float:
    """
    Calculate final fusion score
    """
    rrf_score = calculate_rrf_score(doc_id, lane_results, weights, rrf_k)
    pi = calculate_pi(doc_id, doc, lane_results, target_profile, facet_terms, facet_weights, pi_weights)

    final_score = rrf_score * (1 + beta_fuse * pi)
    return final_score
```

## 4. lane_weightsの適用

### レーン個別の重み

```python
def calculate_rrf_score_with_lane_weights(doc_id: str, lane_results: List[LaneResult],
                                           weights: Dict[str, float], lane_weights: Dict[str, float],
                                           k: float = 60) -> float:
    """
    Calculate RRF score with lane-specific weights
    """
    score = 0.0
    for lane_result in lane_results:
        rank = lane_result.get_rank(doc_id)
        if rank is None:
            continue

        # lane typeレベルの重み
        lane_type = lane_result.lane  # "fulltext" | "semantic"
        w_type = weights.get(lane_type, 1.0)

        # 個別レーンの重み
        lane_name = lane_result.lane_name  # "recall" | "precision" | "semantic"
        w_lane = lane_weights.get(lane_name, 1.0)

        # 両方を掛ける
        w = w_type * w_lane

        score += w / (k + rank)

    return score
```

## 5. 2段階ブースト（fi_norm primary, fi_full secondary）

### Primary boost: fi_norm

target_profileのfiはfi_normベース:

```python
target_profile = {
    "fi": {
        "G06V10/82": 1.0,    # fi_norm
        "G06V40/16": 0.9
    }
}
```

π_code(d)計算時にfi_normで一致度を計算（上記参照）。

### Secondary boost: fi_full

```python
def calculate_pi_code_with_fi_full(doc: Document, target_profile: TargetProfile) -> float:
    """
    Calculate code matching score with fi_full secondary boost
    """
    # Primary boost: fi_norm
    score = 0.0
    for fi_code in doc.fi_norm:
        if fi_code in target_profile.fi:
            score += target_profile.fi[fi_code]

    # Secondary boost: fi_full（弱いヒント）
    fi_full_bonus = 0.0
    for fi_full_code in doc.fi_full:
        fi_norm_code = normalize_fi(fi_full_code)
        if fi_norm_code in target_profile.fi:
            # edition symbolが一致する場合、小さなボーナス
            fi_full_bonus += 0.1 * target_profile.fi[fi_norm_code]

    score += fi_full_bonus

    # Normalize
    max_score = sum(target_profile.fi.values()) + sum(target_profile.ft.values())
    if max_score > 0:
        score /= max_score

    return score
```

## 6. 構造メトリクス計算

### LAS（Lane Agreement Score）

```python
def calculate_las(lane_results: List[LaneResult], top_k: int = 50) -> float:
    """
    Calculate Lane Agreement Score (average Jaccard coefficient of top-k docs)
    """
    from itertools import combinations

    top_docs_per_lane = []
    for lane in lane_results:
        top_docs = set(lane.get_top_docs(top_k))
        top_docs_per_lane.append(top_docs)

    # Calculate pairwise Jaccard
    jaccard_scores = []
    for (set_a, set_b) in combinations(top_docs_per_lane, 2):
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        jaccard = intersection / union if union > 0 else 0.0
        jaccard_scores.append(jaccard)

    return sum(jaccard_scores) / len(jaccard_scores) if jaccard_scores else 0.0
```

### CCW（Class Consistency Weight）

```python
def calculate_ccw(ranked_docs: List[RankedDoc], top_k: int = 50) -> float:
    """
    Calculate Class Consistency Weight (1 - normalized entropy of FI distribution)
    """
    import math
    from collections import Counter

    # Extract FI codes from top-k docs
    fi_codes = []
    for doc in ranked_docs[:top_k]:
        fi_codes.extend(doc.metadata.get("fi_norm", []))

    # Calculate frequency
    fi_counter = Counter(fi_codes)
    total = sum(fi_counter.values())

    # Calculate entropy
    entropy = 0.0
    for count in fi_counter.values():
        p = count / total
        entropy -= p * math.log2(p)

    # Normalized entropy
    max_entropy = math.log2(len(fi_counter)) if len(fi_counter) > 1 else 1.0
    normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    # CCW = 1 - normalized_entropy
    ccw = 1 - normalized_entropy
    return ccw
```

### S_shape（Score-Shape Index）

```python
def calculate_s_shape(ranked_docs: List[RankedDoc], top_k: int = 50) -> float:
    """
    Calculate Score-Shape Index (top-3 score sum / top-50 score sum)
    """
    if len(ranked_docs) < 3:
        return 0.0

    top_3_sum = sum(doc.score for doc in ranked_docs[:3])
    top_k_sum = sum(doc.score for doc in ranked_docs[:min(top_k, len(ranked_docs))])

    return top_3_sum / top_k_sum if top_k_sum > 0 else 0.0
```

### F_struct（Structural F-score）

```python
def calculate_f_struct(las: float, ccw: float) -> float:
    """
    Calculate Structural F-score (F1-like combination of LAS and CCW)
    """
    if las + ccw == 0:
        return 0.0

    return 2 * las * ccw / (las + ccw)
```

### Fproxy（Fusion Proxy Score）

```python
def calculate_fproxy(f_struct: float, s_shape: float) -> float:
    """
    Calculate Fusion Proxy Score (F_struct with S_shape penalty)
    """
    penalty = max(0.0, (s_shape - 0.35) / 0.65) if s_shape > 0.35 else 0.0
    fproxy = f_struct * (1 - penalty)
    return fproxy
```

### 統合

```python
def calculate_structural_metrics(ranked_docs: List[RankedDoc], lane_results: List[LaneResult]) -> StructuralMetrics:
    """
    Calculate all structural metrics
    """
    las = calculate_las(lane_results, top_k=50)
    ccw = calculate_ccw(ranked_docs, top_k=50)
    s_shape = calculate_s_shape(ranked_docs, top_k=50)
    f_struct = calculate_f_struct(las, ccw)
    fproxy = calculate_fproxy(f_struct, s_shape)

    return StructuralMetrics(
        LAS=las,
        CCW=ccw,
        S_shape=s_shape,
        F_struct=f_struct,
        Fproxy=fproxy
    )
```

## 7. rrf_blend_frontierの実装

### 全体フロー

```python
def rrf_blend_frontier(runs: List[RunHandle], target_profile: TargetProfile,
                       weights: Dict, lane_weights: Dict, pi_weights: Dict,
                       facet_terms: Dict, facet_weights: Dict,
                       rrf_k: float, beta_fuse: float) -> FusionResult:
    """
    Fuse multiple search results using RRF + π(d) boost
    """
    # 1. Load lane results
    lane_results = [load_lane_result(run) for run in runs]

    # 2. Collect all unique doc_ids
    all_doc_ids = set()
    for lane in lane_results:
        all_doc_ids.update(lane.doc_ids)

    # 3. Calculate final scores for each doc
    scored_docs = []
    for doc_id in all_doc_ids:
        doc = load_document(doc_id)
        final_score = calculate_final_score(
            doc_id, doc, lane_results, weights, target_profile,
            facet_terms, facet_weights, pi_weights, rrf_k, beta_fuse
        )
        scored_docs.append((doc_id, final_score, doc))

    # 4. Sort by score
    scored_docs.sort(key=lambda x: x[1], reverse=True)

    # 5. Build ranked_docs
    ranked_docs = []
    for rank, (doc_id, score, doc) in enumerate(scored_docs, start=1):
        ranked_docs.append(RankedDoc(
            rank=rank,
            doc_id=doc_id,
            pub_id=doc.pub_id,
            score=score,
            metadata=doc.metadata
        ))

    # 6. Calculate structural metrics
    metrics = calculate_structural_metrics(ranked_docs, lane_results)

    # 7. Return FusionResult
    run_id = generate_run_id("fusion")
    return FusionResult(
        run_id=run_id,
        ranked_docs=ranked_docs,
        metrics=metrics,
        params=FusionParams(
            weights=weights,
            lane_weights=lane_weights,
            pi_weights=pi_weights,
            rrf_k=rrf_k,
            beta_fuse=beta_fuse
        )
    )
```

## 8. rrf_mutate_runの実装

### パラメータ再融合

```python
def rrf_mutate_run(base_run_id: str, mutate_delta: MutateDelta) -> FusionResult:
    """
    Re-fuse with mutated parameters (cheap path)
    """
    # 1. Load base fusion result
    base_result = load_fusion_result(base_run_id)

    # 2. Load lane results (from base_result)
    lane_results = base_result.lane_results

    # 3. Merge parameters
    new_params = base_result.params.copy()
    if mutate_delta.weights:
        new_params.weights.update(mutate_delta.weights)
    if mutate_delta.lane_weights:
        new_params.lane_weights.update(mutate_delta.lane_weights)
    if mutate_delta.pi_weights:
        new_params.pi_weights.update(mutate_delta.pi_weights)
    if mutate_delta.rrf_k is not None:
        new_params.rrf_k = mutate_delta.rrf_k
    if mutate_delta.beta_fuse is not None:
        new_params.beta_fuse = mutate_delta.beta_fuse

    # 4. Re-fuse with new parameters
    return rrf_blend_frontier(
        runs=lane_results,
        target_profile=base_result.target_profile,
        weights=new_params.weights,
        lane_weights=new_params.lane_weights,
        pi_weights=new_params.pi_weights,
        facet_terms=base_result.facet_terms,
        facet_weights=base_result.facet_weights,
        rrf_k=new_params.rrf_k,
        beta_fuse=new_params.beta_fuse
    )
```

## まとめ

融合エンジンの核心:

**RRF基本式:**
```
RRF_score(d) = Σ [ w_lane_i / (k + rank_i(d)) ]
```

**π(d)ブースト:**
```
π(d) = w_code × π_code(d) + w_facet × π_facet(d) + w_lane × π_lane(d)
```

**最終スコア:**
```
final_score(d) = RRF_score(d) × (1 + β × π(d))
```

**2段階ブースト:**
- Primary: fi_norm（target_profile）
- Secondary: fi_full（弱いヒント）

**構造メトリクス:**
- LAS, CCW, S_shape, F_struct, Fproxy

**cheap_path:**
- rrf_mutate_runで既存レーン結果を再利用
- パラメータのみ変更して再融合

次章では、各コンポーネント仕様を学びます。
