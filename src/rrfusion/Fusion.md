# 📘 Fusion.md — Multi-Lane Fusion Specification (v1.0)
RRFusion MCP — Fusion Algorithm & Structural Metrics Specification
(Codex Implementation Guide)

---

## 1. Purpose & Philosophy

Fusion は複数検索レーン（fulltext / semantic / code-aware / その他）を統合し、
Top-K 文献集合の「構造的な品質」を最大化するための中核アルゴリズムです。

Fusion の目的:

- 各レーンが持つ異なる検索視点を統合する
- semantic の暴走（off-domain drift）を抑制する
- FI/IPC に基づく技術領域としての純度を評価する
- Top-K の顔ぶれが技術的に自然かどうかを判定する
- ラベル無しの環境で、F1 に近い最適化を実現する

このために、Fusion は単なる数値スコアだけでなく、以下の構造指標を使います:

- LAS: Lane Agreement Score（レーン間の顔ぶれ一致度）
- CCW: Class Consistency Weight（FI/IPC 分布の凝集度）
- S_shape: Score-Shape Index（スコア分布の「尖り度」）
- Fproxy: 上記を統合した構造的 F 値（最終目的関数）

---

## 2. Inputs & Outputs

### 2.1 Inputs

Multi-lane search の結果として、各 lane ℓ は以下のようなリストを持つ:

```python
lane_results[ℓ]: List[ScoredDoc]

class ScoredDoc(TypedDict):
    doc_id: str
    score: float      # lane 内の生スコア
    rank: int        # lane 内順位 (1-based)
    metadata: dict   # 少なくとも main FI などを含む
```

lane_results は Redis か in-memory 経由で fusion 層に渡される。

### 2.2 Outputs

```python
class BlendItem(TypedDict):
    doc_id: str
    score: float      # fusion 最終スコア
    rank: int

class FusionMetrics(TypedDict):
    LAS: float
    CCW: float
    S_shape: float
    Fproxy: float
    F_struct: float
    beta_struct: float  # F_struct に使った beta (通常 1.0)

class BlendResponse(TypedDict):
    run_id: str
    items: List[BlendItem]
    metrics: FusionMetrics
```

- `items` は fusion 後の最終ランキング
- `metrics` は fusion 品質の診断用メトリクス

---

## 3. Fusion Core Algorithm

Fusion の基本スコアは「RRF + lane weights + beta_fuse + code-aware boost」で定義する。

### 3.1 Lane Score (RRF with weights and beta_fuse)

各 lane ℓ に対し、順位 r_ℓ(d) に基づく RRF スコアを:

\[
s_\ell(d) = w_\ell \cdot rac{1}{k + eta_\ell \cdot r_\ell(d)}
\]

- `w_ℓ` : lane 重み（semantic / fulltext / code lane 等の相対的寄与度）
- `β_ℓ (beta_fuse)` : lane 内ランキングの勾配
  - β が大きい → 上位少数に集中（precision 寄り）
  - β が小さい → 長いテールを許容（recall 寄り）
- `k` は通常 60〜100 程度の定数（RRF の平滑化用）

### 3.2 Code-Aware Boost

FI / IPC コードに基づき、target_profile とのマッチ度で boost を掛ける:

\[
s'_\ell(d) = s_\ell(d) \cdot (1 + \gamma \cdot 	ext{code\_match}(d))
\]

- `code_match(d)` は target_profile に対する FI/IPC のマッチ度 (0〜1)
- `γ` は boost 強度

実装は既存の `fusion.py` の `apply_code_boosts()` パターンを踏襲してよい。

### 3.3 Final Fusion Score

全レーンを集約して最終スコア S(d) を定義:

\[
S(d) = \sum_{\ell} s'_\ell(d)
\]

- S(d) に基づきソートし、上位 K 件を BlendResponse.items として返す。

---

## 4. Structural Metrics

Fusion の品質を評価するために、以下の 3 つの構造指標を計算する。

### 4.1 Lane Agreement Score (LAS)

各 lane ℓ について、上位 K_eval 件の doc_id 集合を:

\[
S_\ell = \{ d \mid d 	ext{ is in Top-}K_	ext{eval} 	ext{ of lane } \ell \}
\]

と定義する。LAS は全レーンペアの平均 Jaccard 類似度:

\[
LAS = 
rac{1}{inom{L}{2}}
\sum_{\ell_i < \ell_j}
rac{|S_{\ell_i} \cap S_{\ell_j}|}
     {|S_{\ell_i} \cup S_{\ell_j}|}
\]

- semantic lane が別世界に飛んでいると LAS は低くなる
- fulltext narrow が異常挙動している場合も LAS が低下する
- 計算量: O(L^2 · K_eval) （通常 L は小さいので実用上 O(K_eval)）

実装メモ:

```python
def compute_las(lane_topk: dict[str, list[str]]) -> float:
    lanes = list(lane_topk.keys())
    m = len(lanes)
    if m <= 1:
        return 0.0
    import itertools
    scores = []
    for a, b in itertools.combinations(lanes, 2):
        sa, sb = set(lane_topk[a]), set(lane_topk[b])
        inter = len(sa & sb)
        union = len(sa | sb) or 1
        scores.append(inter / union)
    return sum(scores) / len(scores)
```

### 4.2 Class Consistency Weight (CCW)

fusion 後の Top-K_eval 文献集合 C を考える。各文献 d の主 FI コードを FI(d) とする。

1. FI コード分布の頻度を数える:
   \[
   n_f = |\{ d \in C \mid FI(d) = f \}|
   \]

2. 確率分布:
   \[
   p_f = rac{n_f}{\sum_g n_g}
   \]

3. エントロピー:
   \[
   H = -\sum_f p_f \log p_f
   \]

4. 正規化エントロピー:
   \[
   H_	ext{norm} = 
   egin{cases}
   rac{H}{\log |\mathcal{F}|} & (|\mathcal{F}| > 1) \
   0 & (|\mathcal{F}| = 1)
   \end{cases}
   \]

5. CCW を「凝集度」として:
   \[
   CCW = 1 - H_	ext{norm}
   \]

- 1.0 に近い → ほとんど同じ FI に凝集
- 0.0 に近い → FI がバラバラ

実装メモ:

```python
import math
from collections import Counter

def compute_ccw(docs: list[str], fi_lookup: dict[str, str]) -> float:
    codes = [fi_lookup[d] for d in docs if d in fi_lookup]
    if not codes:
        return 0.0
    freq = Counter(codes)
    total = sum(freq.values())
    probs = [c / total for c in freq.values()]
    H = -sum(p * math.log(p) for p in probs)
    if len(freq) <= 1:
        return 1.0
    H_norm = H / math.log(len(freq))
    return 1.0 - H_norm
```

分類コードでハードに絞っているレーンばかりの場合、CCW は常に高く（≒固定値）になりうる。その場合でも特に問題はなく、「そのステップでは CCW が情報を持たない」と解釈すればよい。

### 4.3 Score-Shape Index (S_shape)

Top-K_eval 文献の fusion スコア S(d) の「尖り度」を測る。

具体的には、Top-3 のスコアが Top-50 の総和に対してどれだけ大きいかを見る:

\[
S_{	ext{shape}} 
= 
rac{\sum_{i=1}^{3} S_i}
     {\sum_{i=1}^{50} S_i}
\]

- S_i は最終 fusion スコアでソートした i 位の score
- 文献数が 50 未満のときは存在する分だけで計算する

解釈:

- 0.2〜0.3 程度: 正常（上位数件にやや集中しているが許容範囲）
- 0.6 以上: 異常（semantic lane などが上位 1〜3 件だけに極端な重みを与えている）

S_shape は旧来の Fβ における「スコア幾何」の役割だけを抽出した軽量指標であり、
LAS / CCW と独立に「semantic top-heavy 異常」を検知する。

---

## 5. Fproxy（最終目的関数）

### 5.1 Structural F (F_struct)

LAS と CCW のバランスを classical Fβ 形式で統合した構造的 F 値を定義する:

\[
F_{	ext{struct}} =
(1+eta^2)
\cdot
rac{LAS \cdot CCW}
     {eta^2 \cdot LAS + CCW}
\]

- β = 1.0（F1 相当）を推奨
- LAS / CCW のどちらかが低いと F_struct も低くなる
- LAS が高く CCW も高い時に最大化される

### 5.2 Final Fproxy（score-shape ペナルティ付き）

Score-Shape の異常をペナルティとして掛けた最終 F 値を:

\[
F_{	ext{proxy}}
=
F_{	ext{struct}}
	imes
(1 - \lambda \cdot S_{	ext{shape}})
\]

- λ の初期値として 0.5 を推奨
- S_shape が小さい（正常） → (1 - λ·S_shape) ≒ 1.0
- S_shape が大きい（異常） → Fproxy が減衰する

これにより:

- LAS / CCW が高くても、semantic の top-heavy 異常があると Fproxy が低下する
- LAS / CCW / S_shape を単純加重平均するより解釈が明確

---

## 6. Optimization Loop（Fusion → Evaluate → Mutate → Re-search）

Fusion は単発の rank-fusion ではなく、Fproxy を目的関数とする反復最適化ループの中で使う。

### 6.1 高レベルフロー

1. LLM が multi-lane の検索計画を立てる
2. 各レーンで search_fulltext / search_semantic を実行
3. blend_frontier_codeaware で fusion を実行 → BlendResponse
4. get_provenance(run_id) で FusionMetrics (LAS/CCW/S_shape/Fproxy) を取得
5. Fproxy が閾値以上なら採用、閾値未満なら mutate_run でパラメータや検索式を調整し再検索

### 6.2 閾値の例

- Fproxy >= 0.5: 「構造的に十分よい集合」と判断してよい
- Fproxy < 0.5: 「検索式やレーン構成を見直すべき」

### 6.3 メトリクスに応じたアクション指針（LLM 用）

- LAS が低い:
  - レーン間の顔ぶれが噛み合っていない
  - 対応:
    - semantic lane の weight を下げる
    - beta_fuse を調整（上位数件だけに寄りすぎていないか）
    - 明らかに off-domain な lane を一時的に無効化

- CCW が低い:
  - FI 分布が技術的にバラバラ
  - 対応:
    - fulltext の検索式に技術領域を明示する語を追加
    - code lane のフィルタを強める（target_profile ベース）
    - semantic lane に FI フィルタを掛ける（FI が支配的クラスタと一致するものに限定して再検索）

- S_shape が高い:
  - fusion スコアが Top-1〜3 に極端に集中
  - 対応:
    - semantic lane の weight を下げる
    - semantic lane の beta_fuse を小さくして、tail も評価に入れる
    - fulltext broad lane の weight を少し上げてバランスを取る

LLM は上記のヒントを使って mutate_run / 再検索を設計する。

---

## 7. MCP Integration

### 7.1 ProvenanceResponse への metrics 追加

ProvenanceResponse は以下の構造を持つものとする（既存構造に metrics を追加）:

```python
class ProvenanceResponse(TypedDict):
    run_id: str
    items: list[dict]  # 既存の per-doc 情報
    metrics: FusionMetrics
```

FusionMetrics は前述の通り:

```python
class FusionMetrics(TypedDict):
    LAS: float
    CCW: float
    S_shape: float
    Fproxy: float
    F_struct: float
    beta_struct: float  # 通常 1.0
```

### 7.2 mutate_run の利用想定

mutate_run は少なくとも以下の制御をサポートする:

- lane weights の調整
- lane ごとの beta_fuse の調整
- lane ON/OFF（例: semantic lane を一時的に無効化）
- target_profile の微調整
- 再検索のための search_fulltext / search_semantic 設定変更

LLM は get_provenance → metrics を見た上で mutate_run を設計し、必要なレーンだけ再実行させる。

---

## 8. Implementation Notes

- fusion.py:
  - 既存の RRF / code-aware boost を維持する
  - compute_las / compute_ccw / compute_s_shape / compute_fproxy を追加する
  - BlendResponse.metrics に FusionMetrics を詰める

- Redis オフロード案:
  - Top-K doc_id: ZSET
  - LAS: ZINTER/ZUNION ベースで計算可能
  - CCW: doc_id→FI の hash を引いて Python 側でカウント
  - S_shape: ZRANGE で Top50 スコアを取得して計算
  - 初期実装は Python 内で完結させてよい

- テスト観点:
  - semantic がスマホ認証に飛ぶケース（ゲートクエリで G06F21 が混入）
  - fulltext narrow が極端に尖るケース
  - FI が一つのクラスタに凝集する正常ケース
  - 全レーンが同じ顔ぶれを返す trivial ケース

---

## 9. System Prompt 修正案（SystemPrompt.yaml への追記）

以下は、現在の SystemPrompt.yaml に対して **「fusion metrics をどう解釈し、どう使うか」** を LLM に教えるための追記案です。

英語ベースで記載しているので、そのまま SystemPrompt にコピペしてもよいし、既存のセクション構造に合わせて統合しても構いません。

### 9.1 追加セクション例: `### Using fusion metrics (LAS / CCW / S_shape / Fproxy)`

```text
### Using fusion metrics (LAS / CCW / S_shape / Fproxy)

After you run `blend_frontier_codeaware`, you MUST call `get_provenance(run_id)`
to inspect the fusion metrics before deciding whether the current search plan is
good enough or needs refinement.

The MCP backend exposes the following metrics in `ProvenanceResponse.metrics`:

- `LAS` (Lane Agreement Score):
  - Measures how similar the Top-K candidate sets are across lanes.
  - Low LAS means that at least one lane (often the semantic lane) is "seeing a different world".
- `CCW` (Class Consistency Weight):
  - Measures how concentrated the FI/IPC distribution is in a coherent technical cluster.
  - Low CCW means the result set mixes multiple technical domains (e.g., gate control + smartphone unlock).
- `S_shape` (Score-Shape Index):
  - Measures how top-heavy the final fusion scores are.
  - High S_shape means that only the top 1–3 documents dominate the fusion score,
    which often indicates an unstable or over-confident lane (typically semantic).
- `Fproxy`:
  - Final structural F-like score combining LAS, CCW, and S_shape.
  - This is the main objective: higher is better.

#### Basic decision rule

- If `Fproxy >= 0.5`:
  - Treat the current fusion result as structurally acceptable.
  - You may still refine the search if the user explicitly asks,
    but you do NOT need to redesign the whole search plan.
- If `Fproxy < 0.5`:
  - The result set is structurally weak.
  - You MUST consider adjusting lane weights, beta_fuse, code filters,
    or even the fulltext queries and then re-run the search.

#### How to react to each metric

- When `LAS` is low:
  - Interpretation: Lanes do not agree on the candidate set.
    A common pattern is that the semantic lane has jumped to a different domain.
  - Actions:
    - Down-weigh the semantic lane in the next fusion, or temporarily disable it.
    - Increase or decrease `beta_fuse` of the problematic lane to avoid overly sharp ranks.
    - Prefer the lanes that are consistent with the dominant FI/IPC cluster.

- When `CCW` is low:
  - Interpretation: FI/IPC codes of Top-K candidates are scattered across domains.
  - Actions:
    - Strengthen code filters in fulltext queries (e.g., enforce G06V/G07C for gate-control tasks).
    - Narrow the semantic search to documents whose FI/IPC matches the dominant cluster.
    - Add domain-specific keywords to fulltext queries to focus on the right technical field.

- When `S_shape` is high:
  - Interpretation: Fusion scores are dominated by the top 1–3 documents (top-heavy).
  - Actions:
    - Down-weigh the lane that causes the top-heavy behavior (often semantic).
    - Reduce `beta_fuse` for that lane so that more tail documents are considered.
    - Slightly increase the weight of robust fulltext lanes to stabilize the ranking.

#### Loop behavior

- After each `blend_frontier_codeaware`:
  1. Call `get_provenance(run_id)` and read `metrics`.
  2. Decide whether to accept the current result (`Fproxy >= threshold`) or to refine it.
  3. If refinement is needed, design a `mutate_run` that:
     - Adjusts lane weights and/or beta_fuse,
     - Tightens or relaxes code filters,
     - Rewrites fulltext queries where necessary,
     - Re-runs the affected lanes only (to respect cost and rate limits).
  4. Repeat until `Fproxy` is acceptable OR the user’s time/step budget is reached.

Always explain to the user (in Japanese) why you think the current fusion is good or bad,
using LAS/CCW/S_shape in natural language (do NOT expose raw numbers unless helpful),
and what changes you will try next.
```

### 9.2 統合のポイント

- SystemPrompt.yaml 内の「ツールの使い方」や「検索計画の立て方」を説明しているセクションの末尾に、このセクションを追加するとよい。
- 既存の `get_provenance` / `mutate_run` に関する説明がある場合は、その直後にこのセクションを置き、「メトリクスを見てから mutate_run を設計する」という流れが明確になるようにする。
- ユーザーへの説明は日本語で行い、内部ロジックの思考には LAS / CCW / S_shape / Fproxy を使う、という前提を SystemPrompt に明示する。

---

以上が、Codex 実装向けの Fusion 仕様および SystemPrompt 修正案です。
