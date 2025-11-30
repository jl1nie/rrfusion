# Fusion メトリクス トラブルシューティング

## 問題: F_struct や Fproxy が常に 0.0 または 1.0 になる

## 原因と対策

### 🔴 原因 1: 単一レーンでの融合 → LAS = 0.0

**症状:**
```json
{
  "LAS": 0.0,
  "CCW": 0.5,
  "F_struct": 0.0,
  "Fproxy": 0.0
}
```

**発生条件:**
- `rrf_blend_frontier` に渡した `runs` が 1 つだけ
- 例: fulltext レーンのみ、または semantic レーンのみ

**根本原因:**
[fusion.py:253-254](../src/rrfusion/fusion.py#L253-L254)
```python
def compute_las(lane_docs: dict[str, Sequence[tuple[str, float]]], k_eval: int = METRICS_TOP_K) -> float:
    trimmed: list[set[str]] = []
    for docs in lane_docs.values():
        trimmed.append({doc_id for doc_id, _ in docs[:k_eval]})
    if len(trimmed) <= 1:
        return 0.0  # ← 1レーン以下なら常に 0.0
```

LAS (Lane Agreement Score) は**レーン間の合意度**を測るため、1レーンしかない場合は定義上 0.0 になります。

**F_struct への影響:**
```python
# β_struct = 1.0 の場合
denom = 1.0² × LAS + CCW = LAS + CCW

# LAS = 0.0 なら
denom = 0.0 + CCW = CCW

# CCW が小さい（< 0.1）と denom が小さくなり、F_struct も低下
# 極端な場合 CCW = 0.0 なら denom = 0.0 → F_struct = 0.0
```

**対策:**
✅ **複数レーンを使用する**
```yaml
runs:
  - lane: "fulltext"
    run_id_lane: "fulltext-abc123"
    weight: 1.0
  - lane: "semantic"
    run_id_lane: "semantic-def456"
    weight: 1.2
```

最低でも **fulltext + semantic の 2 レーン** を使用してください。

---

### 🔴 原因 2: FI コードがない → CCW = 0.0

**症状:**
```json
{
  "LAS": 0.3,
  "CCW": 0.0,
  "F_struct": 0.0,
  "Fproxy": 0.0
}
```

**発生条件:**
- 上位文献に `fi_norm` メタデータが存在しない
- バックエンドが FI コードを返さない（Stub backend 等）
- フィルタで FI を絞りすぎてヒットなし

**根本原因:**
[fusion.py:279-280](../src/rrfusion/fusion.py#L279-L280)
```python
def compute_ccw(doc_ids: Sequence[str], doc_meta: dict[str, dict[str, Any]]) -> float:
    codes: list[str] = []
    for doc_id in doc_ids:
        meta = doc_meta.get(doc_id)
        if not meta:
            continue
        norm_codes = _get_doc_fi_norm_codes(meta)
        if norm_codes:
            codes.append(norm_codes[0])
    if not codes:
        return 0.0  # ← FI コードが 1 つもない場合
```

CCW (Code Coverage Weight) は **FI コードの多様性** を測るため、FI コードが存在しない場合は計算不能で 0.0 になります。

**F_struct への影響:**
```python
# β_struct = 1.0 の場合
denom = LAS + CCW

# CCW = 0.0 かつ LAS が小さい（< 0.2）と denom が小さくなる
# LAS = 0.0 かつ CCW = 0.0 なら denom = 0.0 → F_struct = 0.0
```

**対策:**
✅ **Patentfield バックエンドを使用する**（FI コードを返す）

✅ **target_profile に FI コードを含める**
```yaml
target_profile:
  fi:
    "G06V10/82": 1.0
    "G06V40/16": 0.95
    "G06T7/00": 0.8
  ft: {}
```

✅ **フィルタを緩める**（上位文献に FI が必ず含まれるようにする）

---

### 🟡 原因 3: 全文献が同一 FI → CCW = 1.0

**症状:**
```json
{
  "LAS": 0.4,
  "CCW": 1.0,
  "F_struct": 0.57,  // 低め
  "Fproxy": 0.48
}
```

**発生条件:**
- 上位 k_eval 件（デフォルト 50 件）が**全て同じ FI コード**
- 例: 全て `G06V10/82`

**根本原因:**
[fusion.py:288-291](../src/rrfusion/fusion.py#L288-L291)
```python
def compute_ccw(doc_ids: Sequence[str], doc_meta: dict[str, dict[str, Any]]) -> float:
    # ... codes を収集
    freq = Counter(codes)
    total = sum(freq.values())
    if total == 0:
        return 0.0
    probs = [value / total for value in freq.values()]
    H = -sum(p * math.log(p) for p in probs if p > 0)
    if len(freq) <= 1:
        return 1.0  # ← FI コードの種類が 1 つだけ
    H_norm = H / math.log(len(freq))
    return 1.0 - H_norm  # エントロピー正規化（多様性が低いほど高い）
```

CCW は **1.0 - 正規化エントロピー** で計算されるため:
- エントロピー = 0（全て同じ）→ CCW = 1.0
- エントロピー = max（完全に多様）→ CCW = 0.0

**注意:** CCW = 1.0 自体は問題ではありませんが、**多様性の欠如** を示します。

**F_struct への影響:**
```python
# β_struct = 1.0, LAS = 0.4, CCW = 1.0 の場合
denom = 1.0 × 0.4 + 1.0 = 1.4
F_struct = (1 + 1.0) × 0.4 × 1.0 / 1.4 = 0.8 / 1.4 = 0.57

# LAS が低い（< 0.3）と F_struct も低下
# 例: LAS = 0.1, CCW = 1.0
denom = 0.1 + 1.0 = 1.1
F_struct = 2.0 × 0.1 × 1.0 / 1.1 = 0.2 / 1.1 = 0.18
```

**対策:**
✅ **target_profile に複数の FI コードを含める**（多様性を確保）

✅ **フィルタを緩める**（単一 FI に絞り込みすぎない）

✅ **fulltext レーンで field_boosts を調整**（claim/desc の重みを上げて diversity を増やす）

---

### 🔴 原因 4: 複合条件（LAS = 0.0 かつ CCW = 0.0）

**症状:**
```json
{
  "LAS": 0.0,
  "CCW": 0.0,
  "F_struct": 0.0,
  "Fproxy": 0.0
}
```

**発生条件:**
- 単一レーン（LAS = 0.0）
- **かつ** FI コードなし（CCW = 0.0）

**根本原因:**
```python
denom = 1.0² × LAS + CCW = 0.0 + 0.0 = 0.0

if denom <= 0:
    f_struct = 0.0  # ← ゼロ除算回避
```

**対策:**
✅ **原因 1 と原因 2 の両方を解決**
- 複数レーンを使用
- FI コードを含む文献を確保

---

## 診断手順

### 1. デバッグスクリプトを実行

```bash
# 既存の fusion run ID を指定
python scripts/debug_metrics.py fusion-abc123def4
```

出力例:
```
✅ Run type: fusion

📊 Stored Metrics:
{
  "LAS": 0.0,
  "CCW": 0.52,
  "S_shape": 0.68,
  "F_struct": 0.0,
  "beta_struct": 1.0,
  "Fproxy": 0.0
}

🔍 Analysis:
⚠️  LAS = 0.0 - Possible causes:
   - Only 1 lane was used
   - No overlap between lanes
   - Actual lanes used: 1
     * fulltext (weight=1.0)

📐 F_struct calculation:
   β² = 1.0
   denominator = β² × LAS + CCW = 1.0 × 0.0 + 0.52 = 0.52
   F_struct = (1 + β²) × LAS × CCW / denom
            = 2.0 × 0.0 × 0.52 / 0.52
            = 0.0
   ✅ Calculation matches: 0.0

🎯 Target Profile:
   FI codes: 3 (['G06V10/82', 'G06V40/16', 'G06T7/00']...)
```

### 2. 原因を特定

| LAS | CCW | F_struct | 原因 | 対策 |
|-----|-----|----------|------|------|
| 0.0 | 任意 | 0.0 | 単一レーン | 複数レーン使用 |
| 任意 | 0.0 | 0.0 | FI なし | Patentfield 使用 / フィルタ緩和 |
| 任意 | 1.0 | 低め | 単一 FI | target_profile 多様化 |
| 0.0 | 0.0 | 0.0 | 複合 | 上記すべて |

### 3. SystemPrompt でのガイドライン

LLM エージェントに以下を指示する（[prompts/SystemPrompt_v1_5.yaml](../prompts/SystemPrompt_v1_5.yaml)）:

```yaml
fusion_quality_policy:
  description: "Ensure healthy fusion metrics"
  guidelines:
    - "Always use multiple lanes (fulltext + semantic minimum)"
    - "Include diverse FI codes in target_profile (3-5 codes)"
    - "Check F_proxy after fusion: ≥ 0.5 indicates healthy frontier"
    - "If F_proxy < 0.3, review LAS and CCW:"
      - "LAS = 0.0 → Add more lanes"
      - "CCW = 0.0 → Ensure FI codes exist"
      - "CCW = 1.0 → Diversify target_profile"
```

---

## 推奨される融合パターン

### ✅ 良い例（健全なメトリクス）

```yaml
# Phase1: 2 レーン + 多様な FI
runs:
  - lane: "fulltext"
    run_id_lane: "fulltext-abc123"
    weight: 1.0
  - lane: "semantic"
    run_id_lane: "semantic-def456"
    weight: 1.2

target_profile:
  fi:
    "G06V10/82": 1.0   # 特徴抽出
    "G06V40/16": 0.95  # 顔認証
    "G06T7/00": 0.8    # 画像処理
    "H04N5/225": 0.7   # カメラ
  ft: {}

# 期待されるメトリクス:
# LAS: 0.3-0.6（レーン間の適度な合意）
# CCW: 0.4-0.8（適度な多様性）
# F_struct: 0.4-0.7
# Fproxy: 0.5-0.8
```

### ❌ 悪い例 1（単一レーン）

```yaml
# 単一レーンのみ
runs:
  - lane: "fulltext"
    run_id_lane: "fulltext-abc123"
    weight: 1.0

# メトリクス:
# LAS: 0.0（レーン不足）
# F_struct: 0.0
# Fproxy: 0.0
```

### ❌ 悪い例 2（FI なし）

```yaml
# FI コードを含まない target_profile
target_profile:
  fi: {}  # 空
  ft:
    "5B050AA01": 1.0
    "5B050BA13": 0.9

# メトリクス:
# CCW: 0.0（FI なし）
# F_struct: 0.0（LAS が低い場合）
# Fproxy: 0.0
```

### ❌ 悪い例 3（単一 FI）

```yaml
# 単一 FI のみ
target_profile:
  fi:
    "G06V10/82": 1.0
  ft: {}

filters:
  - field: "fi"
    op: "in"
    value: ["G06V10/82"]  # 厳しすぎる

# メトリクス:
# CCW: 1.0（多様性なし）
# F_struct: 低め（0.2-0.4）
# Fproxy: 低め
```

---

## 参考資料

- **[fusion.py:309-339](../src/rrfusion/fusion.py#L309-L339)**: `compute_fusion_metrics` 実装
- **[fusion.py:246-264](../src/rrfusion/fusion.py#L246-L264)**: `compute_las` 実装
- **[fusion.py:267-291](../src/rrfusion/fusion.py#L267-L291)**: `compute_ccw` 実装
- **[docs/searcher/01_concept.md](searcher/01_concept.md)**: Fusion メトリクスの理論的背景
- **[AGENT.md](../AGENT.md)**: MCP API 仕様

---

**作成日**: 2025-11-30
**対象バージョン**: RRFusion v1.4+
**関連スキル**: [fusion-algorithm.md](../.claude/skills/fusion-algorithm.md), [redis-debug.md](../.claude/skills/redis-debug.md)
