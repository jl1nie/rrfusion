# Fusion Algorithm Skill

## Purpose
Guide implementation and debugging of RRF fusion and code-aware algorithms.

## Core Algorithm: Weighted RRF

### Basic RRF Formula
```python
def rrf_score(doc, lanes, k=60):
    """
    RRF(d) = Σ(w_lane / (k + rank_lane(d)))

    Args:
        doc: Document ID
        lanes: List of lane results
        k: RRF constant (default 60, range 60-120)
    """
    score = 0.0
    for lane in lanes:
        rank = lane.get_rank(doc)  # 1-based
        if rank:
            score += lane.weight / (k + rank)
    return score
```

### Lane Score Storage
```python
# On search_fulltext/semantic:
# Store RRF-ready score in Redis ZSET
lane_score = w_lane / (rrf_k + rank)
redis.zadd(f"z:{snapshot}:{query_hash}:{lane}", {doc_id: lane_score})
```

### Fusion via ZUNIONSTORE
```python
# Combine lanes into fusion ZSET
redis.zunionstore(
    dest=f"z:rrf:{run_id}",
    keys=[lane_key1, lane_key2, ...],
    weights=[1.0, 1.0, ...]  # Already encoded in lane scores
)
```

## Code-Aware Adjustments

### A) Per-Doc Code Overlap Boost
```python
def compute_code_overlap(doc, target_profile):
    """
    g(d) = normalized overlap score

    Returns:
        float in [0, 1]
    """
    score = 0.0

    # FI subgroup overlap (primary)
    if "fi_norm" in target_profile:
        for code in doc.fi_norm:
            if code in target_profile["fi_norm"]:
                score += target_profile["fi_norm"][code]

    # IPC/CPC overlap
    if "ipc" in target_profile:
        for code in doc.ipc:
            if code in target_profile["ipc"]:
                score += target_profile["ipc"][code]

    # FT overlap (secondary)
    if "ft" in target_profile:
        for code in doc.ft:
            if code in target_profile["ft"]:
                score += target_profile["ft"][code] * 0.5  # Weaker

    # Normalize to [0, 1]
    return min(1.0, score / max_possible_score)

def apply_code_boost(lane_score, g_d, alpha=0.3):
    """
    ŝ(d) = s(d) * (1 + α * g(d))

    Args:
        lane_score: Original RRF score
        g_d: Code overlap score [0, 1]
        alpha: Boost strength (default 0.3)
    """
    return lane_score * (1.0 + alpha * g_d)
```

### B) Lane Modulation
```python
def lane_code_similarity(lane_freqs, target_profile):
    """
    Compare lane code distribution to target_profile.

    Uses cosine similarity or weighted overlap.
    """
    # Extract fi_norm frequencies
    lane_fi = lane_freqs.get("fi_norm", {})
    target_fi = target_profile.get("fi_norm", {})

    # Compute cosine similarity
    from numpy import dot
    from numpy.linalg import norm

    all_codes = set(lane_fi.keys()) | set(target_fi.keys())
    v1 = [lane_fi.get(c, 0) for c in all_codes]
    v2 = [target_fi.get(c, 0) for c in all_codes]

    if norm(v1) == 0 or norm(v2) == 0:
        return 0.0

    return dot(v1, v2) / (norm(v1) * norm(v2))

def apply_lane_modulation(w_lane, similarity, beta=0.2):
    """
    w'_lane = w_lane * (1 + β * sim(F_lane, T))

    Args:
        w_lane: Original lane weight
        similarity: Code similarity [0, 1]
        beta: Modulation strength (default 0.2)
    """
    return w_lane * (1.0 + beta * similarity)
```

### C) Code-Only Lane (Optional)
```python
def create_code_lane(docs, target_profile, w_code=0.5):
    """
    Create ranking based purely on code overlap.

    Returns:
        Redis ZSET with scores = g(d)
    """
    code_scores = {}
    for doc in docs:
        g_d = compute_code_overlap(doc, target_profile)
        if g_d > 0:
            code_scores[doc.id] = g_d * w_code

    redis.zadd(f"z:code:{run_id}", code_scores)
    return f"z:code:{run_id}"
```

## Frontier Estimation

### Relevance Proxy π'(d)
```python
def compute_relevance_proxy(doc, score, g_d, a=1.0, b=0.0, gamma=0.5):
    """
    π'(d) = σ(a * ŝ(d) + b + γ * z(g(d)))

    Where:
        σ = sigmoid function
        z(g) = normalized code score
        ŝ(d) = code-boosted RRF score

    Returns:
        float in [0, 1]
    """
    import numpy as np

    z_g = (g_d - 0.5) / 0.2  # Normalize around 0.5
    logit = a * score + b + gamma * z_g

    # Sigmoid
    return 1.0 / (1.0 + np.exp(-logit))
```

### Precision at k: P*(k)
```python
def precision_star(docs_at_k):
    """
    P*(k) = average π'(d) for top-k docs
    """
    return sum(d.relevance_proxy for d in docs_at_k) / len(docs_at_k)
```

### Recall proxy R*(k)
```python
def recall_star(docs_at_k, target_profile, rho=0.6):
    """
    R*(k) = ρ * coverage(k) + (1-ρ) * CDF_score(k)

    Where:
        coverage(k) = code diversity vs target_profile
        CDF_score(k) = cumulative score distribution
    """
    # Code coverage
    seen_codes = set()
    target_codes = set(target_profile.get("fi_norm", {}).keys())

    for doc in docs_at_k:
        seen_codes.update(doc.fi_norm)

    coverage = len(seen_codes & target_codes) / max(1, len(target_codes))

    # Score CDF
    total_score = sum(d.score for d in docs_at_k)
    max_score = total_score * 2  # Assume diminishing returns
    cdf_score = total_score / max_score

    return rho * coverage + (1 - rho) * cdf_score
```

### F-beta frontier
```python
def f_beta_star(P_k, R_k, beta=1.5):
    """
    F_β*(k) = (1 + β²) * (P*(k) * R*(k)) / (β² * P*(k) + R*(k))

    Args:
        beta: Recall weight (>1 favors recall)
    """
    if P_k == 0 and R_k == 0:
        return 0.0

    return (1 + beta**2) * (P_k * R_k) / (beta**2 * P_k + R_k)

def estimate_frontier(run_id, k_grid=[10,20,30,50,80,100,150,200]):
    """
    Compute frontier metrics for multiple k values.

    Returns:
        list[FrontierPoint]
    """
    frontier = []

    for k in k_grid:
        docs_at_k = get_top_k_docs(run_id, k)

        P_k = precision_star(docs_at_k)
        R_k = recall_star(docs_at_k, target_profile)
        F_k = f_beta_star(P_k, R_k, beta=1.5)

        frontier.append(FrontierPoint(
            k=k,
            P_star=P_k,
            R_star=R_k,
            F_beta_star=F_k
        ))

    return frontier
```

## Contribution Tracking

```python
def compute_contributions(docs, lanes):
    """
    Track which lanes contributed each doc.

    Returns:
        dict[lane_name, float]  # Percentage contribution
    """
    lane_counts = {lane.name: 0 for lane in lanes}

    for doc in docs:
        # Which lanes ranked this doc?
        for lane in lanes:
            if lane.contains(doc):
                lane_counts[lane.name] += 1

    # Normalize to percentages
    total = sum(lane_counts.values())
    return {
        lane: (count / total * 100) if total > 0 else 0
        for lane, count in lane_counts.items()
    }
```

## Structural Metrics

### LAS (Lane Agreement Score)
```python
def compute_las(lanes, k=50):
    """
    Measure top-k overlap between lanes.

    High LAS = lanes agree, likely in-domain
    Low LAS = lanes diverge, possible off-domain lane
    """
    top_k_sets = []
    for lane in lanes:
        top_k = set(lane.get_top_k_docs(k))
        top_k_sets.append(top_k)

    # Jaccard similarity between all pairs
    n = len(top_k_sets)
    similarities = []
    for i in range(n):
        for j in range(i+1, n):
            intersection = len(top_k_sets[i] & top_k_sets[j])
            union = len(top_k_sets[i] | top_k_sets[j])
            similarities.append(intersection / union if union > 0 else 0)

    return sum(similarities) / len(similarities) if similarities else 0
```

### CCW (Class Consistency Weight)
```python
def compute_ccw(docs, k=50):
    """
    Measure FI/IPC concentration in top-k.

    High CCW = focused technical field
    Low CCW = scattered codes
    """
    from collections import Counter

    # Count fi_norm in top-k
    code_counts = Counter()
    for doc in docs[:k]:
        code_counts.update(doc.fi_norm)

    # Compute Herfindahl index (concentration)
    total = sum(code_counts.values())
    if total == 0:
        return 0.0

    hhi = sum((count / total) ** 2 for count in code_counts.values())

    # Normalize to [0, 1]
    n_codes = len(code_counts)
    hhi_min = 1 / n_codes if n_codes > 0 else 0
    hhi_max = 1.0

    return (hhi - hhi_min) / (hhi_max - hhi_min) if hhi_max > hhi_min else 0
```

### S-shape (Score Distribution)
```python
def compute_s_shape(scores):
    """
    Measure top-heaviness of score distribution.

    High S-shape = overly concentrated at top (semantic dominant)
    Low S-shape = smooth decay (balanced)
    """
    if len(scores) < 2:
        return 0.0

    # Gini coefficient
    sorted_scores = sorted(scores, reverse=True)
    n = len(sorted_scores)

    cumsum = 0
    for i, score in enumerate(sorted_scores):
        cumsum += (n - i) * score

    total = sum(sorted_scores)
    if total == 0:
        return 0.0

    gini = (2 * cumsum) / (n * total) - (n + 1) / n

    return gini
```

### Fproxy (Overall Health)
```python
def compute_fproxy(las, ccw, s_shape):
    """
    F_struct = F1(LAS, CCW)
    Fproxy = F_struct * (1 - α_shape * S_shape)

    Rule of thumb:
        Fproxy >= 0.5: Structurally healthy
        Fproxy < 0.5: Consider adjustments
    """
    # F1 of LAS and CCW
    if las + ccw == 0:
        f_struct = 0
    else:
        f_struct = 2 * las * ccw / (las + ccw)

    # Penalize high S-shape
    alpha_shape = 0.3
    fproxy = f_struct * (1 - alpha_shape * s_shape)

    return fproxy
```

## Tuning Recipes

### Scenario: Low LAS (lanes disagree)
```python
# Diagnosis: Semantic lane off-domain
# Solution 1: Reduce semantic weight
delta = MutateDelta(weights={"semantic": 0.5})

# Solution 2: Tighten semantic filters
# Re-run semantic with stricter FI codes

# Solution 3: Remove semantic entirely
# Fusion without semantic lane
```

### Scenario: Low CCW (scattered codes)
```python
# Diagnosis: Wide search too broad
# Solution 1: Tighten FI/FT filters in fulltext_recall
filters = [
    {"field": "fi_norm", "op": "in", "value": top_10_fi_codes}
]

# Solution 2: Increase code lane weight
delta = MutateDelta(weights={"code": 1.0})

# Solution 3: Strengthen target_profile
target_profile = {
    "fi_norm": {code: 2.0 for code in core_codes}
}
```

### Scenario: High S-shape (top-heavy)
```python
# Diagnosis: Semantic too dominant
# Solution 1: Reduce semantic weight
delta = MutateDelta(weights={"semantic": 0.6})

# Solution 2: Reduce beta_fuse
delta = MutateDelta(beta_fuse=1.0)

# Solution 3: Increase fulltext_recall weight
delta = MutateDelta(weights={"fulltext": 1.5, "semantic": 0.7})
```

## Implementation Checklist

### fusion.py
- [ ] RRF scoring with weighted lanes
- [ ] Code overlap computation (fi_norm primary)
- [ ] Per-doc code boost
- [ ] Lane modulation
- [ ] Frontier estimation (P*/R*/F*)
- [ ] Contribution tracking
- [ ] Structural metrics (LAS/CCW/S-shape/Fproxy)

### storage.py
- [ ] Lane ZSET storage with RRF scores
- [ ] ZUNIONSTORE for fusion
- [ ] Code freq hash (fi_norm + fi_full + ft)
- [ ] Recipe storage in h:run:{run_id}
- [ ] Lineage tracking

### mcp/service.py
- [ ] rrf_blend_frontier implementation
- [ ] rrf_mutate_run implementation
- [ ] get_provenance with metrics

## Testing

```python
# tests/unit/test_fusion.py
def test_rrf_score():
    lanes = [
        MockLane("fulltext", ranks={123: 1, 456: 3}, weight=1.0),
        MockLane("semantic", ranks={123: 2, 456: 1}, weight=0.8)
    ]

    score_123 = rrf_score(123, lanes, k=60)
    # 1.0/(60+1) + 0.8/(60+2) ≈ 0.0164 + 0.0129 = 0.0293
    assert abs(score_123 - 0.0293) < 0.001

def test_code_overlap():
    doc = MockDoc(fi_norm=["G06V10/82", "H04L9/32"])
    profile = {"fi_norm": {"G06V10/82": 1.0, "G06T7/00": 0.5}}

    g_d = compute_code_overlap(doc, profile)
    assert g_d > 0

def test_frontier_estimation():
    frontier = estimate_frontier("run123")
    assert len(frontier) > 0
    assert all(0 <= f.P_star <= 1 for f in frontier)
```

## References
- [fusion.py implementation](../../src/rrfusion/fusion.py)
- [docs/searcher/01_concept.md Chapter 1](../../docs/searcher/01_concept.md#L134-L234)
- [AGENT.md Algorithm section](../../AGENT.md#L358-L379)
- [prompts/SystemPrompt_v1_5.yaml fusion config](../../prompts/SystemPrompt_v1_5.yaml#L399-L418)
